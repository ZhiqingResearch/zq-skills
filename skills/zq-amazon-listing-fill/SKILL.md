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

Run the scripts in `scripts/` (they need only Python 3 + `openpyxl`).

### 1. Read the template's fields and rules

```bash
python3 scripts/parse_template.py <template> --required-only --out fields.json
```

`fields.json` lists every Required / Conditionally Required field with its
**`accepted_values`** (the filling rule), `label`, `group`, and 1-based `column`.
It also reports the template's **`product_type`** (e.g. `NOTEBOOK_COMPUTER`) — use
that as the value for the `Product Type` field. The script auto-detects the sheet
layout (label/attribute/data rows) from the template — it works for any Amazon
category, not just this one.

### 2. Look up product data (Keepa), with an ASIN fallback

```bash
python3 scripts/keepa_lookup.py <UPC> [<UPC> ...] --domain 1 --out keepa.json
```

`keepa.json` gives, per query: `found`, `asin`, `brand`, `title`, `model`,
`category_tree`, dimensions/weight, `images`, `bullet_points`, etc.
`--domain 1` = US marketplace.

**For any UPC where `found: false`, do the fallback before giving up:**

1. **Web-search the UPC** to find the product's Amazon **ASIN** (search the UPC,
   brand+model, or the product name; confirm the ASIN belongs to the same item).
2. If you find an ASIN, **re-query Keepa by ASIN** to recover structured data:
   ```bash
   python3 scripts/keepa_lookup.py <ASIN> [<ASIN> ...] --asin --domain 1 --out keepa_asin.json
   ```
3. If still nothing (no ASIN, or Keepa has no data for it), **fill from web-search
   information alone** — and mark those values `inferred: true` where they aren't
   firmly confirmed.

Never fabricate an ASIN or UPC. Note in the report which UPCs needed the fallback.

### 3. Resolve each field (your judgment goes here)

For every UPC and every field in `fields.json`, decide the value:

1. **Follow the field's `accepted_values` rule** — it dictates the allowed format,
   units, and valid values. Match it exactly (e.g. enumerated valid values,
   number+unit format). The source you pick per field is whatever the rule fits.
2. Prefer confirmed data: **Keepa first**, then **web search** to fill gaps or
   verify (search by UPC, ASIN, brand+model). Cross-check when they disagree.
3. **Scope:**
   - `Required` fields → always fill. If no data is found, infer a reasonable
     value and mark it `inferred: true`.
   - `Conditionally Required` → fill when you have data; otherwise leave blank
     (do **not** fabricate).
   - Everything else → leave blank.
4. Never invent an ASIN or a UPC. If Keepa returns `found: false`, note it and
   rely on web search; flag the row in the report.

### 4. Write values back

Build `values.json` (shape documented in `scripts/write_values.py`) mapping each
UPC row to `{attribute: {value, inferred, source}}`, then:

```bash
python3 scripts/write_values.py values.json
```

This writes into the `Template` sheet from its data row down, **highlights every
inferred cell** with a background color, and saves a new `*.filled.xlsm` (the
original is untouched). By default it also **clears the template's built-in
example/sample data** (the `ABC123`/`Sony…` example row and any leftover sample
values) so it can't be mistaken for real data — header rows and all other sheets
and dropdown validations are preserved. Pass `--keep-examples` to leave the
sample data in place.

### 5. Report back to the user

Give the user the filled file path plus a short report: per UPC, which fields were
filled, which were **inferred (highlighted)**, and any UPC that Keepa couldn't
match. State that highlighted cells are inferred and worth reviewing.

## Rules

- Follow each field's `accepted_values` exactly — wrong enum/format/units get the
  listing rejected on upload.
- Only touch Required (always) and Conditionally Required (when data exists) fields.
- Inferred = highlighted. Never silently guess a Required field without the mark.
- Keys come from env/`.env` only — never hardcode or commit them.
- Output a new file; never overwrite the user's original template.

See [reference.md](reference.md) for template mechanics, the Keepa→field mapping,
source priority, and how SIF will slot in later.
