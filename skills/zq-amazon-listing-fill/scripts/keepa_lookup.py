#!/usr/bin/env python3
"""Look up Amazon product data via the Keepa API — by UPC or by ASIN.

Keepa is the only source that accepts a UPC directly; it returns the matching
ASIN plus catalog attributes. When a UPC has no Keepa match, the agent can find an
ASIN via web search and re-query here with --asin.

  by UPC:  python3 keepa_lookup.py 889842188837 [more...] --domain 1 --out keepa.json
  by ASIN: python3 keepa_lookup.py B01NBNDC1T   [more...] --asin --out keepa_asin.json

Hardened client: distinct errors (invalid key / rate limit / out of tokens / no
product), retry with backoff on 429 + transient failures, gzip/deflate decoding,
UPC-match verification, best-of multiple results, and token accounting.

API key resolution (via credentials.resolve_secret, first hit wins):
  env KEEPA_API_KEY -> ./.env -> ~/.config/zq-skills/credentials.json
Never hardcode keys — this repo is public.

--domain: Keepa marketplace id (1=US .com, 2=UK, 3=DE, 4=FR, 5=JP, 6=CA ...).
Output: JSON list; each entry {query, query_type, found, asin, upc_verified,
ambiguous, candidates, ...fields..., [raw]}.
"""
import argparse
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

from credentials import resolve_secret

API = "https://api.keepa.com/product"


class KeepaError(Exception):
    """Carries a human-readable, category-specific message."""


def resolve_key():
    key = resolve_secret("KEEPA_API_KEY")
    if key:
        return key
    sys.exit("KEEPA_API_KEY not configured. Run: "
             "python3 config.py set KEEPA_API_KEY <your-key>  "
             "(or set the env var / add it to ./.env)")


def _read_body(resp_bytes, encoding_header):
    if resp_bytes[:2] == b"\x1f\x8b" or "gzip" in (encoding_header or "").lower():
        return gzip.decompress(resp_bytes).decode("utf-8")
    if "deflate" in (encoding_header or "").lower():
        try:
            return zlib.decompress(resp_bytes).decode("utf-8")
        except zlib.error:
            return zlib.decompress(resp_bytes, -zlib.MAX_WBITS).decode("utf-8")
    return resp_bytes.decode("utf-8")


def _classify_http(code, body_text):
    detail = ""
    try:
        j = json.loads(body_text)
        detail = (j.get("error") or {}).get("message") or j.get("error") or ""
    except Exception:  # noqa: BLE001
        detail = body_text[:120]
    if code in (401, 403):
        return f"invalid or unauthorized Keepa API key ({code}). {detail}"
    if code == 402:
        return f"Keepa subscription/payment issue ({code}). {detail}"
    if code == 400:
        return f"bad request — check the key or parameters ({code}). {detail}"
    if code == 429:
        return f"rate limited / out of tokens ({code}). {detail}"
    if 500 <= code < 600:
        return f"Keepa server error ({code}). {detail}"
    return f"HTTP {code}. {detail}"


def keepa_request(key, domain, *, code=None, asin=None, timeout=60, retries=3):
    params = {"key": key, "domain": domain}
    if code is not None:
        params["code"] = code
    if asin is not None:
        params["asin"] = asin
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip, deflate"})

    attempt = 0
    while True:
        attempt += 1
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(_read_body(resp.read(), resp.headers.get("Content-Encoding")))
            # Out-of-tokens can arrive as HTTP 200 with tokensLeft <= 0.
            if isinstance(data.get("tokensLeft"), int) and data["tokensLeft"] < 0:
                wait = (data.get("refillIn") or 0) / 1000.0
                if attempt <= retries and wait > 0 and wait <= 60:
                    time.sleep(wait)
                    continue
                raise KeepaError(f"out of Keepa tokens (tokensLeft={data['tokensLeft']}); "
                                 f"refill in ~{int(wait)}s")
            return data
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = _read_body(e.read(), e.headers.get("Content-Encoding"))
            except Exception:  # noqa: BLE001
                pass
            if e.code == 429 and attempt <= retries:
                time.sleep(min(2 ** attempt, 30))
                continue
            if 500 <= e.code < 600 and attempt <= retries:
                time.sleep(min(2 ** attempt, 30))
                continue
            raise KeepaError(_classify_http(e.code, body))
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt <= retries:
                time.sleep(min(2 ** attempt, 30))
                continue
            raise KeepaError(f"network error contacting Keepa: {e}")


def validate_key(key, domain=1):
    """Live-check a key with one request. Returns tokensLeft. Raises KeepaError."""
    data = keepa_request(key, domain, asin="B0000000000", retries=1)
    return data.get("tokensLeft")


def _digits(x):
    return re.sub(r"\D", "", str(x)) if x is not None else ""


def pick_product(products, target_code):
    """Choose the best product and report ambiguity + UPC verification."""
    real = [p for p in products if p.get("asin")]
    if not real:
        return None, False, 0
    verified = None
    if target_code:
        tgt = _digits(target_code)
        for p in real:
            codes = {_digits(c) for c in (p.get("upcList") or []) + (p.get("eanList") or [])}
            if tgt in codes:
                verified = p
                break
    chosen = verified or max(real, key=lambda p: (
        bool(p.get("title")), bool(p.get("brand")), len(p.get("features") or [])))
    return chosen, (verified is not None), len(real)


def normalize(p):
    def dim(mm):
        return round(mm / 10.0, 2) if isinstance(mm, (int, float)) and mm > 0 else None
    def grams(g):
        return g if isinstance(g, (int, float)) and g > 0 else None
    images = []
    if p.get("imagesCSV"):
        images = [f"https://m.media-amazon.com/images/I/{n}" for n in p["imagesCSV"].split(",") if n]
    return {
        "asin": p.get("asin"), "title": p.get("title"), "brand": p.get("brand"),
        "manufacturer": p.get("manufacturer"),
        "model": p.get("model") or p.get("partNumber"), "part_number": p.get("partNumber"),
        "color": p.get("color"), "size": p.get("size"),
        "product_group": p.get("productGroup"),
        "category_tree": [c.get("name") for c in (p.get("categoryTree") or []) if c.get("name")],
        "bullet_points": p.get("features") or [], "description": p.get("description"),
        "upc_list": p.get("upcList") or [], "ean_list": p.get("eanList") or [],
        "package_dimensions_cm": {"length": dim(p.get("packageLength")),
                                  "width": dim(p.get("packageWidth")),
                                  "height": dim(p.get("packageHeight"))},
        "package_weight_g": grams(p.get("packageWeight")),
        "item_dimensions_cm": {"length": dim(p.get("itemLength")),
                               "width": dim(p.get("itemWidth")),
                               "height": dim(p.get("itemHeight"))},
        "item_weight_g": grams(p.get("itemWeight")), "images": images,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="+", help="UPCs (default) or ASINs (with --asin)")
    ap.add_argument("--asin", action="store_true", help="treat inputs as ASINs, not UPCs")
    ap.add_argument("--domain", type=int, default=1)
    ap.add_argument("--out", default="keepa.json")
    ap.add_argument("--raw", action="store_true")
    args = ap.parse_args()

    key = resolve_key()
    qtype = "asin" if args.asin else "upc"
    results = []
    tokens_start = None
    for q in args.queries:
        try:
            data = keepa_request(key, args.domain, **({"asin": q} if args.asin else {"code": q}))
        except KeepaError as e:
            results.append({"query": q, "query_type": qtype, "found": False, "error": str(e)})
            print(f"  {q}: ERROR {e}", file=sys.stderr)
            continue
        if tokens_start is None:
            tokens_start = data.get("tokensLeft")
        chosen, verified, n = pick_product(data.get("products") or [], None if args.asin else q)
        if not chosen:
            results.append({"query": q, "query_type": qtype, "found": False,
                            "tokens_left": data.get("tokensLeft")})
            print(f"  {q}: not found (tokensLeft={data.get('tokensLeft')})", file=sys.stderr)
            continue
        entry = {"query": q, "query_type": qtype, "found": True,
                 "upc_verified": verified if not args.asin else None,
                 "ambiguous": n > 1, "candidates": n,
                 "tokens_left": data.get("tokensLeft"),
                 "tokens_consumed": data.get("tokensConsumed")}
        entry.update(normalize(chosen))
        if args.raw:
            entry["raw"] = chosen
        results.append(entry)
        flags = []
        if not args.asin and not verified:
            flags.append("UPC-UNVERIFIED")
        if n > 1:
            flags.append(f"{n} candidates")
        print(f"  {q}: {entry['asin']} {str(entry.get('title'))[:48]}"
              + (f"  [{', '.join(flags)}]" if flags else ""), file=sys.stderr)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    found = sum(1 for r in results if r.get("found"))
    tokens_end = next((r.get("tokens_left") for r in reversed(results) if r.get("tokens_left") is not None), None)
    print(f"\n{found}/{len(results)} {qtype.upper()} matched -> {args.out}")
    if tokens_start is not None and tokens_end is not None:
        print(f"Keepa tokens: {tokens_start} -> {tokens_end} (used ~{tokens_start - tokens_end})")
    unverified = [r["query"] for r in results if r.get("found") and r.get("upc_verified") is False]
    if unverified:
        print(f"UPC NOT verified in Keepa for: {', '.join(unverified)} "
              f"— confirm identity via web search before trusting.")
    if found < len(results) and qtype == "upc":
        print("Tip: for unmatched UPCs, find the ASIN via web search, then re-run with --asin.")


if __name__ == "__main__":
    main()
