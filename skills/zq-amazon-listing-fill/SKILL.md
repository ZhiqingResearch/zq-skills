---
name: zq-amazon-listing-fill
description: Fill an Amazon flat-file listing template (.xlsm/.xlsx) for one or more UPCs by looking up product data via Keepa and web search, then writing the required fields back into the sheet. Use when the user provides an Amazon listing/category template plus UPC codes and asks to auto-fill the required fields and get the completed file back.
---

# zq-amazon-listing-fill

Fill the **required** fields of an Amazon flat-file listing template for a batch of
UPCs, using **Keepa** (product attributes + UPC→ASIN) and **web search** (gap-fill
and verification), then hand back the completed `.xlsm`. Values that had to be
inferred are highlighted so the user can review them.

> SIF (ad/keyword reverse-lookup) is **not** wired in yet — it will later supply
> keyword/copy fields (title, bullets, search terms). See `reference.md`.

## Inputs

- An Amazon template file (`.xlsm`/`.xlsx`) — standard multi-sheet flat file.
- One or more **UPC** codes (12-digit).

## Prerequisites — API key (one-time, no env setup needed)

The skill needs a Keepa API key. **Do not make the user configure environment
variables.** On the first run, resolve the key like this:

```bash
python3 scripts/config.py check      # is KEEPA_API_KEY already available?
```

- If it reports `OK`, proceed — a key is already saved (env, `.env`, or the
  user-level config from a previous run).
- If it reports `missing`, ask the user in chat to paste their Keepa key once,
  then save it for them:

  ```bash
  python3 scripts/config.py set KEEPA_API_KEY <pasted-key>
  ```

  It is stored at `~/.config/zq-skills/credentials.json` (perms 0600, outside this
  repo, never committed) and reused automatically on every future run — the user
  never has to configure it again.

## Workflow

Run the scripts in `scripts/` (they need only Python 3 + `openpyxl`). The pipeline
enforces safety: compliance fields are never guessed, dropdown values are validated
against the template's real allowed values, and the output is checked before you
hand it over.

### 1. Read fields, policy, and real dropdown values

```bash
python3 scripts/parse_template.py <template> --required-only --out fields.json
python3 scripts/field_policy.py fields.json --out fields_policy.json
python3 scripts/resolve_valid_values.py <template> --out valid_values.json
```

- `fields_policy.json` = every Required/Conditionally-Required field with its
  `accepted_values` rule, 1-based `column`, the template `product_type`, **and a
  `policy` class** (`compliance` / `seller_owned` / `product_attribute`).
- `valid_values.json` = the **actual allowed values** for each dropdown column
  (resolved from the template's data validations, not the prose rule). Choose enum
  values from here; anything marked `resolved: false` is `enum_unresolved`.
- `parse_template` also reports the **data region** — how many existing values sit
  in the sheet and whether they look like the built-in example vs real user data.

### 2. Look up product data (Keepa), with an ASIN fallback

```bash
python3 scripts/keepa_lookup.py <UPC> [<UPC> ...] --domain 1 --out keepa.json
```

Per query: `found`, `asin`, `brand`, `title`, `model`, `category_tree`,
dimensions/weight, `images`, `bullet_points`, etc. `--domain 1` = US.

**For any UPC where `found: false`:** web-search the UPC to find its Amazon **ASIN**
(confirm it's the same item), then re-query Keepa by ASIN:

```bash
python3 scripts/keepa_lookup.py <ASIN> [<ASIN> ...] --asin --domain 1 --out keepa_asin.json
```

If still nothing, fill from web-search info alone. Never fabricate an ASIN/UPC.

### 3. Establish product identity (confidence gate)

Before trusting any data for a UPC, confirm you have the **right product**. Set
`identity_confidence` per UPC:

- `high` — the full UPC appears verbatim on a source page, **and** brand + model +
  MPN agree across ≥2 sources, with no config mixing (RAM/SSD/color consistent).
- `medium` — mostly consistent but one leg is weak.
- `low` — can't confirm the item. **The writer will refuse a `low` row** — pause
  and ask the user rather than fill the wrong product.

### 4. Resolve each field (your judgment, gated by policy)

For every field in `fields_policy.json`, branch on `policy`:

- **`product_attribute`** — fill from Keepa/web following `accepted_values`. For
  dropdown columns, pick a value from `valid_values.json`. If no data is found for a
  `Required` field, you may infer — set `inferred: true` (it will be highlighted).
- **`compliance`** (country of origin, battery, dangerous goods, FCC, Prop 65, …) —
  **never infer.** Only fill with a firm source (`inferred: false` + a `source_url`
  or `evidence`). Otherwise set `status: "needs_user_input"` and leave it for the
  user. The writer enforces this.
- **`seller_owned`** (SKU, price, condition, fulfillment, shipping template,
  warranty) — do **not** web-fill. If the user supplied them (intake), write with
  `source: "user"`; otherwise leave blank. The writer rejects web-sourced values here.

  **Optional intake** — offer to collect these once up front so the file can be
  upload-ready: SKU (or a naming rule), condition (New/Used), price, quantity,
  fulfillment (FBA/FBM), shipping template, warranty. If the user declines, that's
  fine — the file is then "attributes-only" (see step 7).

Record evidence per field so the report is auditable (see the v2 schema below).

### 5. Write values back (enforced)

Build `values.json` (v2 schema — see `scripts/write_values.py`) and run with enum
enforcement:

```bash
python3 scripts/write_values.py values.json --valid-values valid_values.json
```

The writer: enforces the policy gates above; **hard-fails (no file written) on any
illegal dropdown value**; auto-corrects enum casing; skips `low`-identity rows
(unless `--force`); highlights inferred cells; clears the template's example data
(unless `--keep-examples`); preserves macros, sheets, and dropdown validation; and
keeps the original extension (`.xlsx`→`.xlsx`, `.xlsm`→`.xlsm`).

v2 `values.json` (per field: value + evidence + status):

```json
{
  "template": "<template path>",
  "rows": [
    {
      "upc": "889842188837",
      "identity_confidence": "high",
      "identity_evidence": ["UPC exact match on brand site", "MPN matches Keepa"],
      "values": {
        "<attribute>": {
          "value": "16", "source": "keepa", "source_url": "https://…",
          "evidence": "16GB DDR5 RAM", "confidence": "high",
          "inferred": false, "status": "filled"
        }
      }
    }
  ]
}
```

### 6. Validate the output

```bash
python3 scripts/validate_output.py <template>.filled.xlsm --template <template> \
    --fields fields.json --valid-values valid_values.json --json validation_report.json
```

Exits non-zero on hard errors (illegal enum, lost dropdowns/macros/sheets, file
won't open). Fix and re-run before handing the file over.

### 7. Report back to the user

Give the file path + a report: which fields were filled, which were **inferred
(highlighted)**, which need user input (`compliance` / `seller_owned` blanks), any
UPC that needed the ASIN fallback or is UPC-unverified in Keepa, and the
`validate_output` verdict — including its **UPLOAD READINESS** line. If that line
says "attributes-only", label the file **"product attributes filled — NOT
upload-ready"** rather than implying it can be uploaded as-is.

## Rules

- **Compliance fields are never guessed.** No firm source → `needs_user_input`.
- **Seller fields never come from the web** — only user intake, else blank.
- **Enum values must be legal** (from `valid_values.json`); the writer/validator
  hard-fail otherwise.
- **Confirm identity first**; a `low`-confidence product is not written.
- Inferred = highlighted; never silently guess a Required field without the mark.
- Follow each field's `accepted_values` exactly (format, units, valid values).
- Keys resolve via env → `./.env` → `~/.config/zq-skills/credentials.json`; never
  hardcode or commit a key.
- Output a new file; never overwrite the user's original template.

See [reference.md](reference.md) for template mechanics, the Keepa→field mapping,
and how SIF will slot in later. See [OPTIMIZATION_PLAN.md](OPTIMIZATION_PLAN.md) for
the roadmap (Phase 2: Keepa hardening, config safety, batch row fidelity).
