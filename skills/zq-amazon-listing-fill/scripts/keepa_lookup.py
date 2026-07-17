#!/usr/bin/env python3
"""Look up Amazon product data via the Keepa API — by UPC or by ASIN.

Keepa is the only source that accepts a UPC directly; it returns the matching
ASIN plus catalog attributes. When a UPC has no Keepa match, the agent can find
an ASIN via web search and re-query here with --asin.

  by UPC:  python3 keepa_lookup.py 889842188837 [more...] --domain 1 --out keepa.json
  by ASIN: python3 keepa_lookup.py B01NBNDC1T   [more...] --asin --out keepa_asin.json

API key resolution (via credentials.resolve_secret, first hit wins):
  1. env var KEEPA_API_KEY
  2. KEEPA_API_KEY=... in ./.env
  3. ~/.config/zq-skills/credentials.json  (set once via config.py — recommended)
Never hardcode keys — this repo is public.

--domain: Keepa marketplace id (1=US .com, 2=UK, 3=DE, 4=FR, 5=JP, 6=CA ...).
Output: JSON list; each entry {query, query_type, found, asin, ...fields..., [raw]}.
"""
import argparse
import gzip
import json
import sys
import urllib.parse
import urllib.request
import zlib

from credentials import resolve_secret


def resolve_key():
    key = resolve_secret("KEEPA_API_KEY")
    if key:
        return key
    sys.exit("KEEPA_API_KEY not configured. Run: "
             "python3 config.py set KEEPA_API_KEY <your-key>  "
             "(or set the env var / add it to ./.env)")


def _read_body(resp):
    """Read an HTTP response and transparently decompress gzip/deflate.

    Keepa returns gzip-compressed JSON, so a plain .decode('utf-8') on the raw
    bytes fails. Detect by Content-Encoding *and* by the gzip magic bytes, since
    some responses arrive gzipped without an explicit header.
    """
    raw = resp.read()
    enc = (resp.headers.get("Content-Encoding") or "").lower()
    if raw[:2] == b"\x1f\x8b" or "gzip" in enc:
        raw = gzip.decompress(raw)
    elif "deflate" in enc:
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw.decode("utf-8")


def call_keepa(key, domain, *, code=None, asin=None, timeout=60):
    params = {"key": key, "domain": domain}
    if code is not None:
        params["code"] = code
    if asin is not None:
        params["asin"] = asin
    url = "https://api.keepa.com/product?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(_read_body(resp))


def normalize(p):
    """Pull the fields useful for a listing template out of a Keepa product object."""
    def dim(mm):
        return round(mm / 10.0, 2) if isinstance(mm, (int, float)) and mm > 0 else None
    def grams(g):
        return g if isinstance(g, (int, float)) and g > 0 else None
    images = []
    if p.get("imagesCSV"):
        images = [f"https://m.media-amazon.com/images/I/{n}" for n in p["imagesCSV"].split(",") if n]
    return {
        "asin": p.get("asin"),
        "title": p.get("title"),
        "brand": p.get("brand"),
        "manufacturer": p.get("manufacturer"),
        "model": p.get("model") or p.get("partNumber"),
        "part_number": p.get("partNumber"),
        "color": p.get("color"),
        "size": p.get("size"),
        "product_group": p.get("productGroup"),
        "category_tree": [c.get("name") for c in (p.get("categoryTree") or []) if c.get("name")],
        "bullet_points": p.get("features") or [],
        "description": p.get("description"),
        "upc_list": p.get("upcList") or [],
        "ean_list": p.get("eanList") or [],
        "package_dimensions_cm": {
            "length": dim(p.get("packageLength")),
            "width": dim(p.get("packageWidth")),
            "height": dim(p.get("packageHeight")),
        },
        "package_weight_g": grams(p.get("packageWeight")),
        "item_dimensions_cm": {
            "length": dim(p.get("itemLength")),
            "width": dim(p.get("itemWidth")),
            "height": dim(p.get("itemHeight")),
        },
        "item_weight_g": grams(p.get("itemWeight")),
        "images": images,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="+", help="UPCs (default) or ASINs (with --asin)")
    ap.add_argument("--asin", action="store_true", help="treat inputs as ASINs, not UPCs")
    ap.add_argument("--domain", type=int, default=1)
    ap.add_argument("--out", default="keepa.json")
    ap.add_argument("--raw", action="store_true", help="include Keepa's raw product object")
    args = ap.parse_args()

    key = resolve_key()
    qtype = "asin" if args.asin else "upc"
    results = []
    for q in args.queries:
        try:
            data = call_keepa(key, args.domain, **({"asin": q} if args.asin else {"code": q}))
        except Exception as e:  # noqa: BLE001 - surface any network/API error per-query
            results.append({"query": q, "query_type": qtype, "found": False, "error": str(e)})
            print(f"  {q}: ERROR {e}", file=sys.stderr)
            continue
        products = data.get("products") or []
        # A product object with no asin means Keepa knows the code but has no listing.
        products = [p for p in products if p.get("asin")]
        if not products:
            results.append({"query": q, "query_type": qtype, "found": False,
                            "tokens_left": data.get("tokensLeft")})
            print(f"  {q}: not found (tokensLeft={data.get('tokensLeft')})", file=sys.stderr)
            continue
        entry = {"query": q, "query_type": qtype, "found": True,
                 "tokens_left": data.get("tokensLeft")}
        entry.update(normalize(products[0]))
        if args.raw:
            entry["raw"] = products[0]
        results.append(entry)
        print(f"  {q}: {entry.get('asin')}  {str(entry.get('title'))[:60]}", file=sys.stderr)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    found = sum(1 for r in results if r.get("found"))
    print(f"\n{found}/{len(results)} {qtype.upper()} matched -> {args.out}")
    if found < len(results) and qtype == "upc":
        print("Tip: for unmatched UPCs, find the ASIN via web search, then re-run with --asin.")


if __name__ == "__main__":
    main()
