# zq-amazon-listing-fill — Optimization Plan

A staged plan to move the skill from "fill everything, guess if needed" to a
**confidence-gated, evidence-based, validated** pipeline that refuses to emit a
file Amazon would reject. Every point from the review is mapped to a phase below.

## The core architectural shift

Three ideas underpin most of the fixes:

1. **A field-policy layer.** Not all fields are equal. Classify every field into
   `compliance` (never infer), `seller_owned` (never web-fill), or
   `product_attribute` (web/Keepa fill allowed). Behavior branches on the class.
2. **An evidence-bearing value record.** Replace `{value, inferred, source}` with a
   record carrying `source_url`, `evidence`, and `confidence`, plus a per-item
   `identity_confidence`. This makes gating and auditing possible.
3. **A hard validation gate.** A dedicated `validate_output.py` decides whether the
   file is emittable; the writer enforces enum/identity rules and can fail rather
   than produce a rejectable file.

### New `values.json` schema (v2)

```json
{
  "template": "NOTEBOOK_COMPUTER.xlsm",
  "clear_examples": true,
  "rows": [
    {
      "upc": "889842188837",
      "identity_confidence": "high",
      "identity_evidence": ["UPC exact match on brand site", "MPN matches Keepa"],
      "values": {
        "<attribute>": {
          "value": "16",
          "source": "keepa",
          "source_url": "https://...",
          "evidence": "16GB DDR5 RAM",
          "confidence": "high",
          "inferred": false,
          "status": "filled"        // filled | inferred | needs_user_input | blocked
        }
      }
    }
  ]
}
```

`status` is the single source of truth the writer and validator act on.

---

## Phase 0 — Correctness fixes (fast, low risk) — items 11–14

Do these first; they are unambiguous and unblock trust in the rest.

- **[11] Preserve output extension.** `.xlsx` in → `.xlsx` out, `.xlsm` → `.xlsm`.
  Fix the `re.sub(r"\.xls[mx]$", ".filled.xlsm", ...)` default to keep the suffix.
- **[12] Strict required matching.** Replace the substring test with an exact set
  `{"Required", "Conditionally Required"}` so nothing is mis-bucketed.
- **[13] Resolve the credentials contradiction in `SKILL.md`.** The Rules section
  still says keys come from "env/`.env` only" — update it to match the real
  resolver (env → `.env` → `~/.config/zq-skills/credentials.json`).
- **[14] Hide unimplemented SIF config.** Drop `SIF_API_KEY` from `config.py`'s
  known keys (or mark it `planned` and refuse to use it) until SIF is wired in.

---

## Phase 1 — Reliability core (the five criticals) — items 1, 2, 3, 4, 5/6

**Status: DONE.** Shipped `field_policy.{py,json}` (compliance no-infer + seller
separation), `resolve_valid_values.py` (287/288 enum columns resolved on the sample
template; unresolved flagged `enum_unresolved`), `validate_output.py` (policy-aware
required checks, GTIN check digit, enum re-check, value/unit pairing, residual-
example scan, structure preservation, re-open), writer v2 (evidence schema +
identity gate + enum hard-fail + policy enforcement), and `parse_template`
data-region reporting. All verified end-to-end against `NOTEBOOK_COMPUTER.xlsm`.

These decide whether the file is trustworthy and upload-safe.

### 1.1 Field policy: forbid inference on compliance/safety fields — items 1, 7

New `field_policy.py` + editable `field_policy.json` classifying by attribute-name
pattern:

- **`compliance` (never infer — must have a firm source or `needs_user_input`):**
  `country_of_origin`, `dangerous_goods*`, `is_battery*`/`battery*`, `un*`/`hazmat`,
  `ghs*`, `fcc*`, `california_proposition_65*`/`prop_65`, `supplier_declared_*`,
  `*regulation*`, `pesticide*`, `safety_*warning`.
- **`seller_owned` (never web-fill — comes from the user):** `sku`,
  `*price`/`*quantity`, `condition*`, `fulfillment*` (FBA/FBM), `merchant_shipping_group`
  (shipping template), `warranty*`, `list_price`, `max_order_quantity`.
- **`product_attribute` (default; web/Keepa fill + inference allowed):** everything
  else.

Behavior:

- Compliance field with no firm source → **do not write a guess**; set
  `status: needs_user_input`, leave the cell blank, list it in the report.
- `Dangerous Goods Regulations = Transportation` style guesses are now impossible;
  they surface as `needs_user_input`.
- The list lives in JSON so it is auditable and extensible per category.

### 1.2 Real dropdown / enum validation — item 2

New `resolve_valid_values.py` producing `valid_values.json` (`column → allowed[]`),
resolving Amazon's actual validation, not the prose in `accepted_values`:

- Read `Template` sheet `data_validations.dataValidation` (each has `type`, `sqref`,
  `formula1`).
- Resolve `formula1`:
  - literal list `"A,B,C"` → allowed values;
  - range / **Named Range** → look up `wb.defined_names`, read the target range on
    `Valid Values` / `Dropdown Lists`;
  - **`INDIRECT(...)`** (product-type-dependent dependent dropdowns) → resolve the
    referenced name/cell to the concrete range, then read it. Best-effort; when a
    formula can't be resolved, mark the field `enum_unresolved` and warn rather
    than silently allowing anything.
- `write_values.py` enforces membership (case/trim-insensitive) for resolved enums
  and **fails on an illegal value** instead of writing a rejectable file.
- The agent also reads `valid_values.json` so it *chooses* legal values up front.

> Honest scope note: full `INDIRECT` coverage across every Amazon category is hard;
> the plan is correct resolution for named-range and literal enums, best-effort for
> `INDIRECT`, and an explicit `enum_unresolved` flag when we can't be sure.

### 1.3 Automatic output validation — item 3

New `validate_output.py` run after writing; exits non-zero on hard failures:

- every strictly-Required field has a value (or an explicit `needs_user_input`);
- UPC format + **GTIN check-digit** validation;
- enum membership (reuses `valid_values.json`);
- unit / numeric format sanity;
- **paired fields complete** (e.g. capacity value ⇔ unit, RAM size ⇔ unit);
- **no residual foreign data** — scan data cells for brand/model/CPU that don't
  match the target item (catches leftover ASUS ROG values);
- macros, data-validation count, and sheet set preserved vs the original;
- output re-opens cleanly (round-trip load).

Report is machine-readable (JSON) + human summary, with per-issue severity.

### 1.4 Example-data handling, completed — item 4

- **Parse phase reports** how many values already sit in the data region and a
  sample, and *classifies* them: `example` (matches Amazon's Example column /
  known markers like SKU `ABC123` / the "✅ pre-filled" note row) vs `user_data`
  (anything else) — so we never silently wipe a seller's own in-progress row.
- Writer default: **clear example values, preserve styles, data validation, and any
  needed formulas** (detect formula cells and keep them). `--keep-examples` opts out.
- Surface `clear_examples` in `SKILL.md` and the `values.json` example.

### 1.5 Identity confidence + evidence — items 5, 6

- New identity-resolution step per UPC yields `identity_confidence` from:
  - the **full UPC appears verbatim** on a source page;
  - **brand + model + MPN agree across ≥2 sources**;
  - **no config mixing** (RAM/SSD/color consistent across sources).
- Every field carries `source_url` + `evidence` + `confidence` (schema v2 above),
  enabling an auditable report (which fields came from brand site vs retailer vs
  snippet).
- **Gate:** `identity_confidence: low` → the writer refuses the row (unless
  `--force`) and the agent pauses to ask the user.

---

## Phase 2 — Robustness & correctness of the data path — items 8, 9, 10, 7

**Status: DONE.** Keepa client hardened (distinct 400/401/402/429/no-product errors,
retry+backoff, gzip, UPC-match verification, best-of-multiple, token accounting);
config safety (`validate` live check, `unset`, stdin input, wrong-type rejection);
batch row style fidelity; seller intake + `validate_output` UPLOAD-READINESS verdict.
Verified live against the saved Keepa key and end-to-end on `NOTEBOOK_COMPUTER.xlsm`.

### 2.1 Harden the Keepa client — item 8

- **Key precheck** via a cheap `/token` call; clear messages for 401 / 400 /
  insufficient tokens / no product (distinct, not one generic error).
- **Timeout + retry with backoff**, and 429 rate-limit handling.
- When querying by code, **verify the returned product's `upcList` contains the
  target UPC**; if not, treat as a mismatch.
- **Multi-result:** don't blindly take `products[0]`; pick the best match (UPC
  match → most complete) and report ambiguity.
- Record **token consumption** per run.

### 2.2 Config safety — item 9

- `config.py validate KEEPA_API_KEY` (live check) and optional validate-before-save.
- `unset` / `delete` commands.
- Read secrets from **stdin** (never argv → keeps keys out of shell history and
  process listings).
- Reject obvious wrong-type keys (e.g. a `sifapi...`-prefixed value saved as
  `KEEPA_API_KEY`).

### 2.3 Batch row fidelity — item 10

- When writing the 2nd+ data row, **copy the first data row's style, number format,
  and formulas**, and **extend each data-validation `sqref`** to cover the new rows,
  so dropdowns/format apply to the whole batch.

### 2.4 Seller-data intake / output framing — item 7

- At the start, collect seller-owned inputs once: **SKU rule, New/Used, price,
  quantity, FBA/FBM, shipping template, warranty**.
- If not provided, output is labeled **"product attributes filled — NOT
  upload-ready"** rather than implying it can be uploaded as-is.

---

## Decisions (locked)

1. **Seller-owned fields:** support both — optional up-front intake; otherwise
   leave blank + flag and label the file "attributes-only, not upload-ready".
2. **Enum enforcement:** hard-fail on resolvable illegal values; `enum_unresolved`
   + warn where `INDIRECT` can't be resolved.
3. **Identity gate:** pause on `low` only.
4. **Build order:** Phase 0 first (done), then stop for Phase 1 sign-off.

## Open decisions (resolved above; kept for context)

1. **Seller-owned fields:** collect them up front via an intake prompt, or leave
   blank + flag and label the file "attributes-only, not upload-ready"? (Recommend:
   support both — intake if the user offers, otherwise flag.)
2. **Compliance field list:** confirm the set in 1.1 (add/remove any category-
   specific ones you care about, e.g. energy labels).
3. **Enum enforcement strictness:** hard-fail on resolvable illegal enum values
   (recommended), and `enum_unresolved` + warn where `INDIRECT` can't be resolved —
   OK?
4. **Identity gate threshold:** pause on `low` only, or also on `medium`?

## Suggested build order

Phase 0 (all four, immediately) → Phase 1.1 + 1.4 (policy + example handling, they
share the writer) → 1.2 (enum resolver) → 1.3 (output validator, depends on 1.2) →
1.5 (identity/evidence schema) → Phase 2. Ship and re-test against a real batch
after Phase 1.
