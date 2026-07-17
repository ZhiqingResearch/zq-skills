#!/usr/bin/env python3
"""Value-level rule checks derived from Data Definitions + known Amazon limits.

The template's `accepted_values` column is mostly descriptive prose, but it
sometimes carries machine-readable constraints (max length, numeric range). This
module:

  1. parses those constraints out of `accepted_values` when present (authoritative
     for that template -> ERROR on violation), and
  2. falls back to common Amazon field limits from ../field_rules.json (heuristic
     -> WARN on violation).

`check(attribute, accepted_values, value)` returns a list of (severity, message).
Used by validate_output.py. Enum/dropdown legality is handled separately by
resolve_valid_values.py + write_values.py (the authoritative, template-enforced
constraint); this module covers length / numeric / range.
"""
import json
import os
import re

from field_policy import base_name

_RULES_PATH = os.path.join(os.path.dirname(__file__), "..", "field_rules.json")


def _load():
    with open(_RULES_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return (
        {k.lower(): int(v) for k, v in data.get("max_length", {}).items()},
        [s.lower() for s in data.get("numeric_base_names", [])],
    )


_MAX_LEN, _NUMERIC_BASES = _load()


def parse_accepted(accepted):
    """Pull constraints stated in the accepted_values prose. All fields optional."""
    text = str(accepted or "")
    out = {}
    m = (re.search(r"max(?:imum)?\s+(?:of\s+)?(\d{2,5})\s+char", text, re.I)
         or re.search(r"up\s+to\s+(\d{2,5})\s+char", text, re.I)
         or re.search(r"(\d{2,5})\s+char(?:acter)?s?\s+max", text, re.I))
    if m:
        out["max_length"] = int(m.group(1))
    m = re.search(r"between\s+(\d+)\s+and\s+(\d+)", text, re.I)
    if m:
        out["range"] = (float(m.group(1)), float(m.group(2)))
    if re.search(r"\b(numeric|must be a number|enter a number|integer|decimal value)\b", text, re.I):
        out["numeric"] = True
    return out


def length_limit(attribute, accepted):
    """Return (limit, source): 'template' (authoritative) or 'default' (heuristic)."""
    parsed = parse_accepted(accepted)
    if "max_length" in parsed:
        return parsed["max_length"], "template"
    base = base_name(attribute)
    for pat, lim in _MAX_LEN.items():
        if pat in base:
            return lim, "default"
    return None, None


def _as_number(value):
    try:
        return float(re.sub(r"[, ]", "", str(value)))
    except (ValueError, TypeError):
        return None


def check(attribute, accepted, value):
    """Return [(severity, message), ...] for a single written value."""
    issues = []
    if value in (None, ""):
        return issues
    sval = str(value)
    parsed = parse_accepted(accepted)

    limit, source = length_limit(attribute, accepted)
    if limit and len(sval) > limit:
        sev = "ERROR" if source == "template" else "WARN"
        issues.append((sev, f"length {len(sval)} exceeds {limit} ({source})"))

    numeric_expected = parsed.get("numeric") or any(b in base_name(attribute) for b in _NUMERIC_BASES)
    num = _as_number(value)
    if numeric_expected and num is None:
        issues.append(("WARN", f"expected a numeric value, got {sval!r}"))

    if "range" in parsed and num is not None:
        lo, hi = parsed["range"]
        if not (lo <= num <= hi):
            issues.append(("ERROR", f"value {num} out of stated range [{lo}, {hi}]"))

    return issues


if __name__ == "__main__":
    # Tiny self-check when run directly.
    print(check("item_name[x]#1.value", "Provide a title", "x" * 250))
    print(check("number_of_items#1.value", "numeric", "two"))
    print(check("x", "Values between 1 and 10", "42"))
