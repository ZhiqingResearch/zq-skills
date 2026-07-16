#!/usr/bin/env python3
"""Look up Amazon product data by UPC via the Keepa API.

Keepa is the only one of our sources that accepts a UPC directly; it returns the
matching ASIN plus catalog attributes. Use it as the primary spec source AND as
the UPC -> ASIN bridge.

API key resolution (first hit wins):
  1. env var KEEPA_API_KEY
  2. KEEPA_API_KEY=... line in a .env file in the current directory
  3. error (never hardcode keys — this repo is public)

Usage:
  python3 keepa_lookup.py UPC [UPC ...] [--domain 1] [--out keepa.json]

--domain: Keepa marketplace id (1=US .com, 2=UK, 3=DE, 4=FR, 5=JP, 6=CA ...).
Outputs a JSON list; each entry is {upc, found, asin, ...normalized fields..., raw}.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request


def resolve_key():
    key = os.environ.get("KEEPA_API_KEY")
    if key:
        return key.strip()
    try:
        with open(".env", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("KEEPA_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    sys.exit("KEEPA_API_KEY not set. `export KEEPA_API_KEY=...` or add it to ./.env")


def call_keepa(key, upc, domain):
    q = urllib.parse.urlencode({"key": key, "domain": domain, "code": upc})
    url = f"https://api.keepa.com/product?{q}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
    ap.add_argument("upcs", nargs="+")
    ap.add_argument("--domain", type=int, default=1)
    ap.add_argument("--out", default="keepa.json")
    ap.add_argument("--raw", action="store_true", help="include Keepa's raw product object")
    args = ap.parse_args()

    key = resolve_key()
    results = []
    for upc in args.upcs:
        try:
            data = call_keepa(key, upc, args.domain)
        except Exception as e:  # noqa: BLE001 - surface any network/API error per-UPC
            results.append({"upc": upc, "found": False, "error": str(e)})
            print(f"  {upc}: ERROR {e}", file=sys.stderr)
            continue
        products = data.get("products") or []
        if not products:
            results.append({"upc": upc, "found": False,
                            "tokens_left": data.get("tokensLeft")})
            print(f"  {upc}: not found (tokensLeft={data.get('tokensLeft')})", file=sys.stderr)
            continue
        entry = {"upc": upc, "found": True, "tokens_left": data.get("tokensLeft")}
        entry.update(normalize(products[0]))
        if args.raw:
            entry["raw"] = products[0]
        results.append(entry)
        print(f"  {upc}: {entry.get('asin')}  {str(entry.get('title'))[:60]}", file=sys.stderr)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    found = sum(1 for r in results if r.get("found"))
    print(f"\n{found}/{len(results)} UPCs matched -> {args.out}")


if __name__ == "__main__":
    main()
