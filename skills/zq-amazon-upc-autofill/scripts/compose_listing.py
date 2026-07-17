#!/usr/bin/env python3
"""Compose a values.json (v2) for a listing from operator input + org rules.

This is the heart of the listing-CREATION flow (see org_rules.json, the authoritative
rule source). It turns a small operator input into the full parent+child variant
rows, applying:
  - org fixed defaults (Country of Origin=United States, Dangerous Goods=Not
    Applicable, all battery fields blank, FBM, Free Shipping, Modified Product,
    Number of Items, Target Region, Skip Offer, Are batteries required=No, Item
    Condition/Quantity operator defaults),
  - SKU generation (3-group) and UPC generation (brand prefix + check digit; brand
    not in brand_prefixes.json -> no UPC + highlight),
  - parent/child variant logic (parent: no price/inventory/UPC; children: unique
    SKU + UPC + price + the varying attribute).

The emitted values.json is fed to write_values.py --valid-values (which enforces
enum legality and preserves the template). Field data the operator supplies (title,
description, bullets, images, specs) is passed through; sourcing those from the
purchase link/manual is the agent's job before calling this.

Usage:
  python3 compose_listing.py operator_input.json --template TEMPLATE.xlsm --out values.json
"""
import argparse
import json
import os

from parse_template import build_manifest

_ORG_PATH = os.path.join(os.path.dirname(__file__), "..", "org_rules.json")


def load_org():
    with open(_ORG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def build_label_index(fields):
    """label(lower) -> first field; label(lower) -> all fields (repeated columns);
    attribute -> field."""
    by_label, by_label_all, by_attr = {}, {}, {}
    for f in fields:
        lab = str(f.get("label") or "").strip().lower()
        if lab:
            by_label.setdefault(lab, f)
            by_label_all.setdefault(lab, []).append(f)
        by_attr[f["attribute"]] = f
    for lab in by_label_all:
        by_label_all[lab].sort(key=lambda x: x["column"])
    return by_label, by_label_all, by_attr


def resolve_field(key, by_label, by_attr):
    """Resolve an operator/org key (label or attribute) to a field, or None.

    Order: exact attribute -> exact label -> label startswith -> label substring.
    startswith is preferred over substring so org 'Quantity' hits 'Quantity (US)',
    not 'Package Contains SKU Quantity'.
    """
    if key in by_attr:
        return by_attr[key]
    k = str(key).strip().lower()
    if not k:
        return None
    if k in by_label:
        return by_label[k]
    for lab, f in by_label.items():
        if lab.startswith(k):
            return f
    for lab, f in by_label.items():
        if k in lab:
            return f
    return None


def is_battery_field(attr):
    a = attr.lower()
    return any(t in a for t in ("battery", "lithium", "cell_composition", "un_number")) \
        and "are_batteries_required" not in a and "batteries_required" not in a


def set_cell(row_values, field, value, source, evidence, inferred=False):
    if field is None or value in (None, ""):
        return
    row_values[field["attribute"]] = {
        "value": str(value), "source": source, "evidence": evidence,
        "inferred": inferred, "status": "filled",
    }


def set_repeated(row_values, key, values, by_label_all, by_attr, source, evidence):
    """Spread a list across the repeated columns of a label (Bullet Point #1..#5, …)."""
    k = str(key).strip().lower()
    fields = by_label_all.get(k)
    if not fields:
        for lab, fl in by_label_all.items():
            if lab.startswith(k):
                fields = fl
                break
    if not fields and key in by_attr:
        fields = [by_attr[key]]
    for f, v in zip(fields or [], values):
        set_cell(row_values, f, v, source, evidence)


def apply_org_fixed(row_values, by_label, by_attr, org, *, is_parent):
    """Apply org fixed + operator defaults to a row (skip parent-excluded fields)."""
    for item in org["fixed_defaults"]:
        f = resolve_field(item["label"], by_label, by_attr)
        # Parent rows don't carry Product Id Type (children only).
        if is_parent and "product id type" in item["label"].lower():
            continue
        set_cell(row_values, f, item["value"], "org_rule", f"org fixed: {item['label']}")
    for item in org["operator_defaults"]:
        if is_parent:  # defaults like Condition/Quantity are child (offer) fields
            continue
        f = resolve_field(item["label"], by_label, by_attr)
        set_cell(row_values, f, item["value"], "org_rule", f"org default: {item['label']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("operator_input")
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", default="values.json")
    args = ap.parse_args()

    with open(args.operator_input, encoding="utf-8") as fh:
        op = json.load(fh)
    manifest = build_manifest(args.template)
    by_label, by_label_all, by_attr = build_label_index(manifest["fields"])
    org = load_org()

    # Deferred import so a missing brand table surfaces clearly.
    import generators
    prefixes = generators._load_prefixes()

    product_type = manifest.get("product_type")
    theme = op.get("variation_theme")
    multi = bool(op.get("multi_variant"))
    brand = op.get("brand")
    used_skus, used_upcs, highlights = set(), set(), []

    def base_row(is_parent):
        rv = {}
        # product type + action + brand on every row
        set_cell(rv, resolve_field("Product Type", by_label, by_attr), product_type, "template", "product_type")
        set_cell(rv, resolve_field("Listing Action", by_label, by_attr),
                 "Create or Replace (Full Update)", "org_rule", "listing action")
        set_cell(rv, resolve_field("Brand Name", by_label, by_attr), brand, "operator", "operator brand")
        # shared operator content (title/desc/bullets/images/specs)
        for key, val in (op.get("shared") or {}).items():
            if isinstance(val, list):
                # repeated fields (bullets #1..#5, special features, …) spread across columns
                set_repeated(rv, key, val, by_label_all, by_attr, "operator", f"operator {key}")
            else:
                set_cell(rv, resolve_field(key, by_label, by_attr), val, "operator", f"operator {key}")
        apply_org_fixed(rv, by_label, by_attr, org, is_parent=is_parent)
        # battery fields explicitly blanked (org rule) -> simply never set them
        return rv

    rows = []
    if multi:
        parent_sku = generators.gen_sku(used_skus)
        # Parent
        prow = base_row(is_parent=True)
        set_cell(prow, resolve_field("SKU", by_label, by_attr), parent_sku, "generated", "SKU 3-group")
        set_cell(prow, resolve_field("Parentage Level", by_label, by_attr), "Parent", "org_rule", "variant: parent")
        set_cell(prow, resolve_field("Variation Theme Name", by_label, by_attr), theme, "operator", "variation theme")
        set_cell(prow, resolve_field("Skip Offer", by_label, by_attr), "Yes", "org_rule", "parent not offered")
        rows.append({"upc": f"PARENT:{parent_sku}", "identity_confidence": "high",
                     "identity_evidence": ["org-composed parent"], "values": prow})
        # Children
        for v in op.get("variants", []):
            crow = base_row(is_parent=False)
            csku = generators.gen_sku(used_skus)
            set_cell(crow, resolve_field("SKU", by_label, by_attr), csku, "generated", "SKU 3-group")
            set_cell(crow, resolve_field("Parentage Level", by_label, by_attr), "Child", "org_rule", "variant: child")
            set_cell(crow, resolve_field("Parent SKU", by_label, by_attr), parent_sku, "org_rule", "link to parent")
            set_cell(crow, resolve_field("Variation Theme Name", by_label, by_attr), theme, "operator", "variation theme")
            # UPC (brand prefix) — brand not in table => no UPC + highlight
            upc, reason = generators.gen_upc(brand, prefixes, used_upcs)
            if upc:
                set_cell(crow, resolve_field("Product Id", by_label, by_attr), upc, "generated", reason)
            else:
                highlights.append(f"child {csku}: {reason}")
            # variant-specific fields (the varying attribute + price + quantity + specs)
            for key, val in (v.get("fields") or {}).items():
                set_cell(crow, resolve_field(key, by_label, by_attr), val, "operator", f"variant {key}")
            rows.append({"upc": upc or f"CHILD:{csku}", "identity_confidence": "high",
                         "identity_evidence": ["org-composed child"], "values": crow})
    else:
        row = base_row(is_parent=False)
        sku = generators.gen_sku(used_skus)
        set_cell(row, resolve_field("SKU", by_label, by_attr), sku, "generated", "SKU 3-group")
        upc, reason = generators.gen_upc(brand, prefixes, used_upcs)
        if upc:
            set_cell(row, resolve_field("Product Id", by_label, by_attr), upc, "generated", reason)
        else:
            highlights.append(f"{sku}: {reason}")
        for key, val in (op.get("fields") or {}).items():
            set_cell(row, resolve_field(key, by_label, by_attr), val, "operator", f"field {key}")
        rows.append({"upc": upc or f"SINGLE:{sku}", "identity_confidence": "high",
                     "identity_evidence": ["org-composed"], "values": row})

    out = {"template": args.template, "clear_examples": True, "rows": rows}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"Composed {len(rows)} row(s) ({'multi-variant' if multi else 'single'}) -> {args.out}")
    if highlights:
        print("HIGHLIGHT (no UPC — brand not in prefix table):")
        for h in highlights:
            print("  - " + h)


if __name__ == "__main__":
    main()
