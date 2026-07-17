#!/usr/bin/env python3
"""Classify template fields into policy classes that gate how they may be filled.

  compliance        -> safety/legal/regulatory; NEVER inferred. No firm source =>
                       needs_user_input, cell left blank.
  seller_owned      -> decided by the seller (price, SKU, condition, fulfillment,
                       warranty…); only filled from user intake, never the web.
  product_attribute -> everything else; web/Keepa fill + inference allowed.

The pattern lists live in ../field_policy.json (editable). Used both as a CLI
(annotate a fields.json) and as a library (write_values / validate_output import
`classify`).

CLI:
  python3 field_policy.py fields.json [--out fields_policy.json]
"""
import argparse
import json
import os

_POLICY_PATH = os.path.join(os.path.dirname(__file__), "..", "field_policy.json")


def _load_policy():
    with open(_POLICY_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return (
        [p.lower() for p in data.get("compliance", {}).get("patterns", [])],
        [p.lower() for p in data.get("seller_owned", {}).get("patterns", [])],
    )


_COMPLIANCE, _SELLER = _load_policy()


def base_name(attribute):
    """The token before the first '[' or '#', lowercased."""
    a = str(attribute or "").strip().lower()
    return a.split("[", 1)[0].split("#", 1)[0]


def classify(attribute):
    """Return 'compliance' | 'seller_owned' | 'product_attribute'."""
    base = base_name(attribute)
    if any(p in base for p in _COMPLIANCE):
        return "compliance"
    if any(p in base for p in _SELLER):
        return "seller_owned"
    return "product_attribute"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fields", help="fields.json from parse_template.py")
    ap.add_argument("--out", default="fields_policy.json")
    args = ap.parse_args()

    with open(args.fields, encoding="utf-8") as fh:
        manifest = json.load(fh)
    counts = {"compliance": 0, "seller_owned": 0, "product_attribute": 0}
    for f in manifest.get("fields", []):
        f["policy"] = classify(f["attribute"])
        counts[f["policy"]] += 1
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    print(f"Classified {len(manifest.get('fields', []))} fields -> {args.out}")
    print("By policy:", counts)
    print("\nCompliance fields (never inferred):")
    for f in manifest["fields"]:
        if f["policy"] == "compliance":
            print(f"  {f['label']}  <- {f['attribute'][:48]}")
    print("\nSeller-owned fields (from user intake only):")
    for f in manifest["fields"]:
        if f["policy"] == "seller_owned":
            print(f"  {f['label']}  <- {f['attribute'][:48]}")


if __name__ == "__main__":
    main()
