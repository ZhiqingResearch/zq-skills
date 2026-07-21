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
  - parent/child variant logic (parent: clear offer fields + Skip Offer=Yes, no
    UPC; children: unique SKU + UPC + price + the varying attribute).

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
import re
from collections import Counter

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
    a = str(attr or "").lower()
    return any(t in a for t in ("battery", "lithium", "cell_composition", "un_number")) \
        and "are_batteries_required" not in a and "batteries_required" not in a


def set_cell(row_values, field, value, source, evidence, inferred=False):
    if field is None or value in (None, ""):
        return
    # Org rule (all categories): every battery-related field stays blank, no matter
    # what the operator/web supplies. 'Are batteries required?' is excluded above and
    # still handled by fixed_defaults. This is the single write chokepoint, so the
    # rule holds regardless of caller.
    if is_battery_field(field["attribute"]):
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


def _parent_clear_match(label, clear_substrings):
    lab = (label or "").lower()
    return any(s.lower() in lab for s in clear_substrings)


def apply_org_fixed(row_values, by_label, by_attr, org, *, is_parent):
    """Apply org fixed + operator defaults to a row (skip parent-excluded fields)."""
    parent_clear = org.get("parent_offer_clear") or {}
    clear_subs = parent_clear.get("clear_label_substrings") or []
    for item in org["fixed_defaults"]:
        f = resolve_field(item["label"], by_label, by_attr)
        # Parent rows don't carry Product Id Type (children only).
        if is_parent and "product id type" in item["label"].lower():
            continue
        # 0720: parent clears fulfillment / price / quantity / inventory / shipping.
        if is_parent and _parent_clear_match(item["label"], clear_subs):
            continue
        if is_parent and "skip offer" in item["label"].lower():
            continue  # set explicitly in apply_parent_offer_clear
        set_cell(row_values, f, item["value"], "org_rule", f"org fixed: {item['label']}")
    for item in org["operator_defaults"]:
        if is_parent:  # defaults like Condition/Quantity are child (offer) fields
            continue
        f = resolve_field(item["label"], by_label, by_attr)
        set_cell(row_values, f, item["value"], "org_rule", f"org default: {item['label']}")


def apply_parent_offer_clear(row_values, by_label, by_attr, by_label_all, org):
    """0720: strip offer fields from the parent row; Skip Offer = Yes."""
    parent_clear = org.get("parent_offer_clear") or {}
    clear_subs = parent_clear.get("clear_label_substrings") or []
    skip_val = parent_clear.get("skip_offer") or "Yes"
    set_cell(row_values, resolve_field("Skip Offer", by_label, by_attr),
             skip_val, "org_rule", "parent not offered (0720)")
    # Drop any offer cells that slipped in via shared operator content.
    drop_attrs = set()
    for lab, fields in by_label_all.items():
        if _parent_clear_match(lab, clear_subs):
            for f in fields:
                drop_attrs.add(f["attribute"])
    for attr in drop_attrs:
        row_values.pop(attr, None)


def _num(v):
    m = re.search(r"-?\d+(?:\.\d+)?", str(v or ""))
    return float(m.group()) if m else None


def apply_item_type_keyword(rows, field, allowed):
    """Auto-fill / canonicalize Item Type Keyword against the template's valid values."""
    if not field or not allowed:
        return
    attr = field["attribute"]
    canon = {a.lower(): a for a in allowed}
    for row in rows:
        cur = row["values"].get(attr, {}).get("value") if attr in row["values"] else None
        if cur:
            if cur.lower() in canon:
                continue
            match = next((a for a in allowed if cur.lower() in a.lower()), None)  # partial -> full path
            if match:
                row["values"][attr] = {"value": match, "source": "operator",
                                       "evidence": "canonicalized item type keyword",
                                       "inferred": False, "status": "filled"}
        elif len(allowed) == 1:  # unambiguous -> auto-fill
            row["values"][attr] = {"value": allowed[0], "source": "org_rule",
                                   "evidence": "only valid item type keyword",
                                   "inferred": False, "status": "filled"}


def _cat_match(rule_cat, product_type):
    rc = str(rule_cat or "").strip().lower()
    if rc in ("", "*"):
        return True
    pt = str(product_type or "").strip().lower()
    return bool(pt) and rc == pt


def _row_is_parent(row, by_label, by_attr):
    f = resolve_field("Parentage Level", by_label, by_attr)
    if not f:
        return False
    cell = row["values"].get(f["attribute"])
    return bool(cell) and str(cell.get("value", "")).strip().lower() == "parent"


def _label_fields(label, by_label, by_label_all, by_attr):
    """All template columns for a label (repeated cells first), else single/attr."""
    k = str(label).strip().lower()
    fields = by_label_all.get(k)
    if not fields:
        for lab, fl in by_label_all.items():
            if lab.startswith(k):
                fields = fl
                break
    if not fields:
        one = resolve_field(label, by_label, by_attr)
        fields = [one] if one else []
    return fields


def _row_label_value(row, label, by_label, by_label_all, by_attr):
    """First non-empty value currently set for `label` in this row (or None)."""
    for f in _label_fields(label, by_label, by_label_all, by_attr):
        if not f:
            continue
        cell = row["values"].get(f["attribute"])
        if cell and cell.get("value") not in (None, ""):
            return cell.get("value")
    return None


def _condition_met(row, when, by_label, by_label_all, by_attr):
    """Evaluate an infer_default `when` clause against a row's current values.

    Supported keys: label + one of {contains, equals, empty, not_empty}. No `when`
    (or no label) => always true.
    """
    if not when:
        return True
    lab = when.get("label")
    if not lab:
        return True
    cur = _row_label_value(row, lab, by_label, by_label_all, by_attr)
    cur_s = "" if cur is None else str(cur).strip()
    if when.get("empty"):
        return cur_s == ""
    if when.get("not_empty"):
        return cur_s != ""
    if "equals" in when:
        return cur_s.lower() == str(when["equals"]).strip().lower()
    if "contains" in when:
        return str(when["contains"]).strip().lower() in cur_s.lower()
    return cur_s != ""


def _set_unit(row, label, unit_label, unit_value, by_label, by_label_all, by_attr, applied):
    """Fill a value field's sibling unit (explicit unit_label, else '<label> Unit')."""
    if unit_value in (None, ""):
        return
    ulabel = unit_label or f"{label} Unit"
    ufields = _label_fields(ulabel, by_label, by_label_all, by_attr)
    if ufields and ufields[0]:
        cell = row["values"].get(ufields[0]["attribute"])
        if not cell or cell.get("value") in (None, ""):
            set_cell(row["values"], ufields[0], unit_value, "org_rule",
                     f"autofill unit: {ulabel}", inferred=True)


def apply_autofill_rules(rows, by_label, by_label_all, by_attr, org, product_type):
    """Apply the deterministic subset of org rules (those carrying an `action`).

    Reads both `autofill_rules` and `inferable_rules` (SKILL.md documents this) —
    only entries WITH an `action` are applied here. Rules WITHOUT an `action` stay
    agent-owned (need product judgment / generation) per the SKILL.md checklist.
    Values the operator/web already supplied are never overwritten: every fill is
    guarded on the target cell(s) being empty.
    """
    applied = []
    tr_field = resolve_field("Target Region", by_label, by_attr)
    # inferable_rules run first so derived rules (e.g. sum of USB ports) see them.
    all_rules = list(org.get("inferable_rules", [])) + list(org.get("autofill_rules", []))
    # Two passes: fills first, then aggregations (sum_labels) that read those fills.
    sum_rules = []
    for rule in all_rules:
        action = rule.get("action")
        if not action or not _cat_match(rule.get("category"), product_type):
            continue
        label = rule.get("label")
        atype = action.get("type")
        if atype == "sum_labels":
            sum_rules.append(rule)
            continue
        fields = _label_fields(label, by_label, by_label_all, by_attr)
        if not fields:
            continue

        if atype in ("infer_default", "conditional_fill"):
            value = action.get("value")
            when = action.get("when")
            for row in rows:
                if any(row["values"].get(f["attribute"], {}).get("value") not in (None, "")
                       for f in fields if f):
                    continue  # operator/web already filled it
                if not _condition_met(row, when, by_label, by_label_all, by_attr):
                    continue
                set_cell(row["values"], fields[0], value, "org_rule",
                         f"autofill inferred default: {label}", inferred=True)
                _set_unit(row, label, action.get("unit_label"), action.get("unit"),
                          by_label, by_label_all, by_attr, applied)
                applied.append(f"infer {label} = {value}")

        elif atype == "normalize":
            amap = {str(k).strip().lower(): v for k, v in (action.get("map") or {}).items()}
            for row in rows:
                for f in fields:
                    cell = row["values"].get(f["attribute"])
                    if not cell:
                        continue
                    mapped = amap.get(str(cell.get("value", "")).strip().lower())
                    if mapped is not None and mapped != cell.get("value"):
                        cell["value"] = str(mapped)
                        cell["evidence"] = f"autofill normalize: {label}"
                        applied.append(f"normalize {label} -> {mapped}")

        elif atype == "default_when_empty":
            values = action.get("values") or []
            for row in rows:
                already = any(f["attribute"] in row["values"] for f in fields)
                if already:
                    continue
                for f, v in zip(fields, values):
                    set_cell(row["values"], f, v, "org_rule",
                             f"autofill default: {label}", inferred=True)
                if fields and values:
                    applied.append(f"default {label} ({len(values)} cell(s))")

        elif atype == "clear_when_global":
            for row in rows:
                is_global = True
                if tr_field:
                    tr = row["values"].get(tr_field["attribute"])
                    is_global = bool(tr) and str(tr.get("value", "")).strip().lower() == "global"
                if not is_global:
                    continue
                for f in fields:
                    if row["values"].pop(f["attribute"], None) is not None:
                        applied.append(f"clear-on-global {label}")

    # Second pass: aggregations that depend on the fills above (e.g. Total USB Ports
    # = USB 2.0 + USB 3.0). Only fills when the target is empty and every source has
    # a numeric value.
    for rule in sum_rules:
        label = rule.get("label")
        action = rule["action"]
        fields = _label_fields(label, by_label, by_label_all, by_attr)
        if not fields:
            continue
        src_labels = action.get("labels") or []
        for row in rows:
            if any(row["values"].get(f["attribute"], {}).get("value") not in (None, "")
                   for f in fields if f):
                continue
            parts = [_num(_row_label_value(row, sl, by_label, by_label_all, by_attr))
                     for sl in src_labels]
            if not parts or any(p is None for p in parts):
                continue
            total = sum(parts)
            total = int(total) if total == int(total) else total
            set_cell(row["values"], fields[0], total, "org_rule",
                     f"autofill sum: {label} = {' + '.join(src_labels)}", inferred=True)
            applied.append(f"sum {label} = {total}")
    return applied


def apply_unit_backfill(rows, by_attr, allowed_by_col):
    """Deterministic unit backfill: when a `<x>.value` cell is filled but its sibling
    `<x>.unit` is empty AND that unit column has exactly one allowed value, fill it.

    Only the single-allowed-value case is safe to automate (no ambiguity between,
    e.g., GB vs TB). Ambiguous units stay for the agent / validator to flag.
    """
    applied = []
    for row in rows:
        for attr in list(row["values"].keys()):
            if not attr.endswith(".value"):
                continue
            val = row["values"][attr].get("value")
            if val in (None, ""):
                continue
            unit_attr = attr[:-6] + ".unit"
            uf = by_attr.get(unit_attr)
            if not uf:
                continue
            if unit_attr in row["values"] and row["values"][unit_attr].get("value") not in (None, ""):
                continue
            allowed = allowed_by_col.get(uf["column"]) or []
            if len(allowed) == 1:
                set_cell(row["values"], uf, allowed[0], "org_rule",
                         "autofill unit: only allowed unit")
                applied.append(f"unit {unit_attr} = {allowed[0]}")
    return applied


def apply_ram_max(rows, field):
    """Org rule: RAM Memory Maximum Size = the largest value among rows (with its unit)."""
    if not field:
        return
    attr = field["attribute"]
    vals = [(row["values"][attr]["value"]) for row in rows if attr in row["values"]]
    nums = [(_num(v), v) for v in vals if _num(v) is not None]
    if len(nums) < 2:
        return
    _, maxv = max(nums, key=lambda x: x[0])
    for row in rows:
        if attr in row["values"]:
            row["values"][attr]["value"] = str(maxv)
            row["values"][attr]["evidence"] = "org rule: max RAM among variants"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("operator_input")
    ap.add_argument("--template", required=True)
    ap.add_argument("--valid-values", help="valid_values.json (auto-fill Item Type Keyword)")
    ap.add_argument("--exclude-upcs", default="",
                    help="comma-separated UPCs already used/found — regenerate around them")
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
    used_skus = set()
    used_upcs = set(u.strip() for u in args.exclude_upcs.split(",") if u.strip())
    highlights = []

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
        apply_parent_offer_clear(prow, by_label, by_attr, by_label_all, org)
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

    # Post-processing rules (Item Type Keyword auto-fill, RAM max, autofill engine)
    allowed_by_col = {}
    if args.valid_values:
        with open(args.valid_values, encoding="utf-8") as fh:
            vv = json.load(fh)
        allowed_by_col = {int(c["column"]): c.get("allowed") or []
                          for c in (vv.get("columns") or {}).values() if c.get("resolved")}
        itk = resolve_field("Item Type Keyword", by_label, by_attr)
        if itk:
            apply_item_type_keyword(rows, itk, allowed_by_col.get(itk["column"], []))
    apply_ram_max(rows, resolve_field("RAM Memory Maximum Size", by_label, by_attr))

    # Deterministic org autofill_rules (normalize / default_when_empty / clear_when_global)
    autofilled = apply_autofill_rules(rows, by_label, by_label_all, by_attr, org, product_type)
    if allowed_by_col:
        autofilled += apply_unit_backfill(rows, by_attr, allowed_by_col)

    out = {"template": args.template, "clear_examples": True, "rows": rows}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"Composed {len(rows)} row(s) ({'multi-variant' if multi else 'single'}) -> {args.out}")
    if autofilled:
        print(f"Autofill rules applied ({len(autofilled)}):")
        for msg, n in Counter(autofilled).most_common():
            print(f"  - {msg}" + (f"  x{n}" if n > 1 else ""))
    if highlights:
        print("HIGHLIGHT (no UPC — brand not in prefix table):")
        for h in highlights:
            print("  - " + h)


if __name__ == "__main__":
    main()
