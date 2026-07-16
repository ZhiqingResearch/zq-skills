#!/usr/bin/env python3
"""Write resolved field values back into an Amazon flat-file template.

Reads a values.json prepared by the agent and writes each value into the
`Template` sheet starting at the template's data row. Cells whose value was
*inferred* (not confirmed from a data source) get a background fill so the user
can eyeball them. Macros and all other sheets are preserved (keep_vba=True), and
the result is saved as a new file — the original template is never overwritten.

values.json shape:
{
  "template": "NOTEBOOK_COMPUTER.xlsm",
  "output":   "NOTEBOOK_COMPUTER.filled.xlsm",       # optional; default *.filled.xlsm
  "rows": [
    {
      "upc": "889842188837",
      "values": {
        "brand[marketplace_id=ATVPDKIKX0DER][language_tag=en_US]#1.value": {
          "value": "Dell", "inferred": false, "source": "keepa"
        },
        "item_name[...]#1.value": { "value": "...", "inferred": true, "source": "web_search" }
      }
    }
  ]
}

Usage:
  python3 write_values.py values.json [--color FFE0B2]
"""
import argparse
import json
import os
import re
import sys

import openpyxl
from openpyxl.styles import PatternFill


def load_settings(ws):
    raw = str(ws.cell(row=1, column=1).value or "")
    def grab(name, default):
        m = re.search(rf"{name}=(\d+)", raw)
        return int(m.group(1)) if m else default
    return grab("attributeRow", 5), grab("dataRow", 8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("values")
    ap.add_argument("--color", default="FFE0B2",
                    help="ARGB/RGB hex fill for inferred cells (default light orange)")
    args = ap.parse_args()

    with open(args.values, encoding="utf-8") as fh:
        spec = json.load(fh)

    template = spec["template"]
    output = spec.get("output") or re.sub(r"\.xls[mx]$", ".filled.xlsm", template)
    is_macro = template.lower().endswith(".xlsm")

    wb = openpyxl.load_workbook(template, keep_vba=is_macro, data_only=False)
    ws = wb["Template"]
    attr_row, data_row = load_settings(ws)

    # attribute name -> 1-based column index
    col_of = {}
    for cell in next(ws.iter_rows(min_row=attr_row, max_row=attr_row)):
        if cell.value is not None:
            col_of[str(cell.value).strip()] = cell.column

    fill = PatternFill(start_color=args.color, end_color=args.color, fill_type="solid")
    stats = {"written": 0, "inferred": 0, "unmatched": set()}

    for i, row in enumerate(spec.get("rows", [])):
        r = data_row + i
        for attr, info in (row.get("values") or {}).items():
            col = col_of.get(attr.strip())
            if not col:
                stats["unmatched"].add(attr)
                continue
            value = info.get("value") if isinstance(info, dict) else info
            if value in (None, ""):
                continue
            cell = ws.cell(row=r, column=col, value=value)
            stats["written"] += 1
            if isinstance(info, dict) and info.get("inferred"):
                cell.fill = fill
                stats["inferred"] += 1

    wb.save(output)

    print(f"Saved: {output}")
    print(f"Cells written: {stats['written']}  (inferred/colored: {stats['inferred']})")
    print(f"Rows: {len(spec.get('rows', []))}   data starts at Template row {data_row}")
    if stats["unmatched"]:
        print(f"\nWARNING: {len(stats['unmatched'])} attribute name(s) not found in template "
              f"(skipped). First few:", file=sys.stderr)
        for a in list(stats["unmatched"])[:5]:
            print(f"  - {a}", file=sys.stderr)


if __name__ == "__main__":
    main()
