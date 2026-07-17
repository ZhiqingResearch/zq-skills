#!/usr/bin/env python3
"""SKU and UPC generators for the org listing-creation rules (see org_rules.json).

Rules come from the Feishu doc '亚马逊批量上传表格字段规则':
  - SKU: 3 groups of uppercase alphanumeric (2-4 chars each) joined by '-', unique.
  - UPC: brand's 6-digit prefix (brand_prefixes.json) + item digits + check digit
    (12-digit UPC-A). Brand not in the table -> no UPC (caller must highlight).
    Uniqueness ('no Google results') is verified by the agent, not here — this
    module only produces candidates and avoids in-batch collisions.

CLI (for quick checks / agent use):
  python3 generators.py sku [--count N] [--used A,B]
  python3 generators.py upc --brand HP [--count N]
"""
import argparse
import json
import os
import random
import string
import sys

_PREFIX_PATH = os.path.join(os.path.dirname(__file__), "..", "brand_prefixes.json")
_ALNUM = string.ascii_uppercase + string.digits


def _load_prefixes():
    with open(_PREFIX_PATH, encoding="utf-8") as fh:
        return json.load(fh).get("prefixes", {})


def _brand_key(prefixes, brand):
    """Case-insensitive brand match against the prefix table. Returns the table key or None."""
    b = str(brand or "").strip().lower()
    for k in prefixes:
        if k.lower() == b:
            return k
    return None


def gen_sku(used=None, rng=random):
    """One SKU: 3 groups of 2-4 uppercase alnum joined by '-', not in `used`."""
    used = used or set()
    for _ in range(10000):
        groups = ["".join(rng.choice(_ALNUM) for _ in range(rng.randint(2, 4))) for _ in range(3)]
        sku = "-".join(groups)
        if sku not in used:
            used.add(sku)
            return sku
    raise RuntimeError("could not generate a unique SKU")


def upc_check_digit(d11):
    """UPC-A check digit for the first 11 digits (string of 11 digits)."""
    digits = [int(c) for c in d11]
    odd = sum(digits[0::2])   # positions 1,3,5,7,9,11 (0-indexed 0,2,4,...)
    even = sum(digits[1::2])
    return (10 - (odd * 3 + even) % 10) % 10


def gen_upc(brand, prefixes=None, used=None, rng=random):
    """Return (upc | None, reason). None means brand not in the prefix table."""
    prefixes = prefixes if prefixes is not None else _load_prefixes()
    used = used or set()
    key = _brand_key(prefixes, brand)
    if not key or not prefixes.get(key):
        return None, f"brand '{brand}' not in prefix table — no UPC generated (highlight this row)"
    for _ in range(10000):
        prefix = rng.choice(prefixes[key])            # 6 digits
        body = "".join(rng.choice(string.digits) for _ in range(5))
        d11 = (prefix + body)[:11]
        upc = d11 + str(upc_check_digit(d11))
        if upc not in used:
            used.add(upc)
            return upc, f"prefix {prefix} (brand {key})"
    raise RuntimeError("could not generate a unique UPC")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["sku", "upc"])
    ap.add_argument("--brand", help="brand (required for upc)")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--used", default="", help="comma-separated already-used values")
    args = ap.parse_args()

    used = set(x for x in args.used.split(",") if x)
    if args.kind == "sku":
        for _ in range(args.count):
            print(gen_sku(used))
    else:
        if not args.brand:
            sys.exit("--brand is required for upc")
        prefixes = _load_prefixes()
        for _ in range(args.count):
            upc, reason = gen_upc(args.brand, prefixes, used)
            print(f"{upc if upc else '(none)'}\t{reason}")


if __name__ == "__main__":
    main()
