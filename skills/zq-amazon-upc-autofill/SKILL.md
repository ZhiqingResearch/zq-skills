---
name: zq-amazon-upc-autofill
description: Fill an Amazon flat-file listing template (.xlsm/.xlsx) for bulk operations (listing creation) by gathering product info from a UPC (web/Keepa search) plus operator-supplied fields, applying the organization's field rules, and writing a complete parent/child listing back into the sheet. Use when someone provides an Amazon category template plus UPC(s) and asks to fill it for bulk upload.
---

# zq-amazon-upc-autofill

Fill an Amazon flat-file template for **bulk listing operations** (上架). For each
UPC it gathers product info (web/Keepa search is **one data source**), asks the
operator to supply what search can't find, applies the **organization's field
rules**, and writes a complete listing — including parent/child variants — ready
for bulk upload.

> **Authoritative rule source:** `org_rules.json` (transcribed from the ops doc
> '亚马逊批量上传表格字段规则'). Its fixed defaults and generation rules **override**
> any web/Keepa value. Keep it in sync with that doc.

## The two UPCs (don't confuse them)

- **Input UPC** — provided by the operator, used only as a **search key** to gather
  product info. It is NOT written into the listing.
- **Product Id (UPC)** — the listing's barcode, **generated** per org rules (brand
  prefix + check digit). Brand not in `brand_prefixes.json` → no Product Id +
  highlight the row.

## Inputs (operator provides)

- The category template (`.xlsm`) — matched to the product's **大类** (category).
- One or more **input UPCs**, plus **brand** and (if known) product details.
- Whether it's **multi-variant**; if so the **Variation Theme** + each variant's
  distinguishing attribute + **price**; the **store**; optional overrides for the
  modifiable defaults (Item Condition, Quantity).

## Prerequisites

- Keepa key (optional but recommended) for the UPC search — one-time setup:
  `python3 scripts/config.py check`; if missing, ask the operator to paste it once
  and `python3 scripts/config.py set KEEPA_API_KEY <key>` (stored in
  `~/.config/zq-skills/`, never committed). Web search works without it.
- Python 3 + `openpyxl`.

## Workflow

### 1. Read the template (fields, policy, dropdown values)

```bash
python3 scripts/parse_template.py <template> --required-only --out fields.json
python3 scripts/field_policy.py <template> --required-only --out fields_policy.json
python3 scripts/resolve_valid_values.py <template> --out valid_values.json
```

All three read only the template — run in any order / parallel.

### 2. Gather product info from the input UPC (one source)

```bash
python3 scripts/keepa_lookup.py <input-UPC> [...] --domain 1 --out keepa.json
```

In parallel, **web-search the UPC** (and brand + model) for specs, title,
description, images. Combine both; keep each fact's `source_url` + `evidence`.
Cross-source agreement raises confidence.

### 3. Fill gaps from the operator (per the ops doc)

For any UPC that **search can't resolve** (`found:false`, or missing specs), guide
the operator to supply the fields the ops doc lists them as owning: category,
brand, product info (purchase link / manual / notes — **operator notes win
conflicts**), variant attributes, price, store. Never fabricate specs — **except**
item/package dimensions & weights (see Rules / `dimension_weight_guess`): those
are required and **may be guess-filled from similar products** (mark `inferred`).

### 4. Build the operator_input

Assemble everything you gathered + the operator supplied into an `operator_input`
JSON (schema documented in `scripts/compose_listing.py`): `category`, `brand`,
`store`, `multi_variant`, `variation_theme`, `shared` (title / description /
bullet points [list] / special features [list] / images / specs common to all
variants), and `variants[]` (each variant's distinguishing attribute + `List
Price` / `Your Price USD ...` / `Quantity (US)`). Map values to template **labels**
(e.g. "Item Name", "Hard Disk Size").

### 5. Compose the listing (org rules + generation + variants)

```bash
python3 scripts/compose_listing.py operator_input.json --template <template> --out values.json
```

This produces the full parent+child rows and applies `org_rules.json`:

- **Fixed org defaults** on every row (Country of Origin = United States, Dangerous
  Goods = Not Applicable, **all battery fields blank** + Are batteries required =
  No, Fulfillment = FBM, Free Shipping, Target Region = Global, Modified Product,
  Number of Items = 1, …) and operator defaults (Item Condition = New, Quantity =
  10 unless overridden).
- **SKU** generated (3 groups of 2-4 alphanumerics, unique).
- **Product Id (UPC)** generated from the brand prefix (valid check digit). Brand
  not in `brand_prefixes.json` → no Product Id, row highlighted in the output.
- **Parent/child**: parent clears fulfillment/price/quantity/inventory/shipping,
  sets **Skip Offer = Yes**, no Product Id; each child gets a unique SKU +
  generated UPC + price + the varying attribute; all variants share
  title/description/bullets/images.
- **Deterministic rules** are applied automatically by compose from BOTH
  `autofill_rules` and `inferable_rules` in `org_rules.json` (any entry carrying an
  `action`). Every fill is guarded on the target being empty, so operator/web values
  always win. Action types: `normalize` (e.g. `802.11be` → `802.11.be`),
  `default_when_empty` lists (Specific Uses, Included Components), `clear_when_global`
  (Notebook compliance fields), `infer_default` (single-value fallback with optional
  `unit` + optional `when` gate — e.g. **Total USB 2.0 = 0**, **USB 3.0 = 1**,
  SSD → **Hard Disk Rotational Speed = 0 RPM** (when Hard Disk Description contains
  SSD), integrated graphics → **Graphics Card Interface = Integrated / Graphics Ram
  = Shared / Graphics Ram Size = 0 GB** (when Graphics Coprocessor is empty)),
  `sum_labels` (**Total USB Ports = USB 2.0 + USB 3.0**), plus **unit backfill** when
  a `.value` is set and its `.unit` column has exactly one allowed value. The compose
  output prints an "Autofill rules applied" summary.

#### Agent-owned rules (compose can't do these — do them while building `operator_input`)

These `inferable_rules` / `autofill_rules` need product judgment, source reading, or
generation, so they have **no `action`** and are your responsibility. Work through
this checklist for the product's category before composing:

- **Dimensions/weights** (all categories): if sources lack item/package L·W·H·weight,
  guess from similar products and mark `inferred` — they are **required**.
- **Computer categories** (`PERSONAL_COMPUTER` / `NOTEBOOK_COMPUTER`):
  - RAM Memory Technology (DDR4/DDR5/LPDDR), CPU Base Speed, SSD Interface / Form Factor.
  - CPU Socket (AIO/mobile → BGA, else Integrated); Human Interface Input
    (touch → Touchscreen; AIO adds Keyboard/Mouse).
  - *Already automated by compose (you only override when research gives a better
    value): USB 2.0 / 3.0 port counts (fallback 0 / 1), Total USB Ports (sum),
    SSD → Hard Disk Rotational Speed 0 RPM, integrated graphics → Graphics Card
    Interface = Integrated / Graphics Ram = Shared / Graphics Ram Size 0 GB. To get
    the correct SSD / integrated-graphics behavior, put the drive type in **Hard Disk
    Description** ("SSD") and leave **Graphics Coprocessor** empty for integrated (or
    fill it with the discrete GPU name to suppress the integrated defaults).*
- **SPEAKERS**: Speaker Maximum Output Power (extract if present); its unit → Watts.
- **All categories**: Model Year (current year only when source lacks one);
  **Special Features ×5** (generate product-relevant phrases).

`compose_listing.py` reads these entries too, so keep `org_rules.json` the single
source; the `rule` text marks each agent-owned item with `(agent: …)`.

**Verify each generated Product Id is unique** — web-search it; if it returns
results, regenerate (re-run) until it's unused (per the ops doc).

### 6. Write and validate

```bash
python3 scripts/write_values.py values.json --valid-values valid_values.json
python3 scripts/validate_output.py <template>.filled.xlsm --template <template> \
    --fields fields.json --valid-values valid_values.json --json validation_report.json
```

`write_values` fills the sheet, clears the template's example data, preserves
macros/sheets/dropdowns, keeps the original extension, and **warns (not fails) on
out-of-list dropdown values** (Amazon accepts them for open fields like brand and
price). `validate_output` checks required presence, UPC check digits, length/rules,
structure, and the UPLOAD-READINESS verdict.

### 7. Report

Give the file path + a report: rows with **no Product Id** (brand not in the prefix
table — need attention), any field left blank that needs operator input,
out-of-list enum warnings, and the validation verdict.

## Rules

- **`org_rules.json` is authoritative** — its fixed defaults, generation rules,
  `inferable_rules`, and `autofill_rules` override web/Keepa values.
- **Batteries: always blank** — in every category, leave all battery-related fields
  empty (Are batteries required = No).
- **Dimensions/weights (0720):** item + package L/W/H/weight are **required**. If
  purchase/reference info lacks them, search similar products and **guess-fill**
  (`inferred: true`). See `dimension_weight_guess` in `org_rules.json`.
- **Product Id is generated, never the input UPC.** Brand not in the prefix table →
  no Product Id + highlight. Verify uniqueness by web search.
- **SKU is generated** (3 groups, 2-4 alnum, unique).
- **Parent Skip Offer = Yes**; clear parent fulfillment/price/quantity/inventory.
- **Enum values are advisory** — write the operator/org value even if it isn't in
  the dropdown (proven acceptable by real uploads); the validator warns.
- Follow the template's `accepted_values` and length limits; the validator flags
  violations (template-stated → error, common defaults → warn).
- Output a new file; never overwrite the operator's original template.

## Data files (edit to keep in sync with the ops doc)

- `org_rules.json` — fixed defaults, generation rules, variant logic (SSOT).
- `brand_prefixes.json` — brand → UPC 6-digit prefix (from the doc's table).
- `field_policy.json` — compliance / seller / product classification.
- `field_rules.json` — length / numeric limits.

See [reference.md](reference.md) for template mechanics and the Keepa→field
mapping; [OPTIMIZATION_PLAN.md](OPTIMIZATION_PLAN.md) for the roadmap.
