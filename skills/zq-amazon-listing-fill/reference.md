# zq-amazon-listing-fill — reference

Load this when you need the template mechanics, the Keepa→field mapping, source
priority, or the plan for adding SIF. The main workflow is in `SKILL.md`.

## How Amazon flat-file templates are structured

Every Amazon category template follows the same shape, so the scripts are generic:

- The **`Template`** sheet holds the data. Its `A1` cell contains a settings string
  encoding the layout — `parse_template.py` reads `labelRow`, `attributeRow`, and
  `dataRow` from it (commonly 4 / 5 / 8):
  - **label row** — human-readable field labels
  - **attribute row** — technical attribute names (the keys `write_values.py` uses)
  - **data row** — first row of actual product data; one product per row below it
- The **`Data Definitions`** sheet documents every field. Its header row has:
  `Group Name | Field Name | Local Label Name | Accepted Values | Example | Required?`
  - **Field Name** matches the attribute row in `Template`.
  - **Accepted Values** is the filling rule (format, units, allowed values).
  - **Required?** is one of `Required`, `Conditionally Required`, `Recommended`,
    `Optional`.
- **`Valid Values`** / **`Dropdown Lists`** back the in-cell dropdowns. When a field
  is enumerated, the value you write **must** be one of these exact strings.

For the sample `NOTEBOOK_COMPUTER.xlsm`: 513 columns, **9 Required** + **131
Conditionally Required** fields.

## The 9 strictly-Required fields (sample template)

| Field | Typical source |
| ----- | -------------- |
| SKU | user-provided / generated |
| Product Type | from the template itself |
| Item Name (title) | Keepa `title` → web search to refine |
| Brand Name | Keepa `brand` |
| Product Id Type | `UPC` (constant) |
| Product Description | Keepa/web; follow length + HTML rules |
| Bullet Point | Keepa `bullet_points` / web |
| Country of Origin | **compliance — never inferred**; user-confirmed source only |
| Dangerous Goods Regulations | **compliance — never inferred**; `needs_user_input` if unconfirmed |

Conditionally-Required spec fields (screen size, RAM, CPU, storage, weight, …)
are filled when Keepa/web provide them.

## Keepa → template field mapping

`keepa_lookup.py` normalizes Keepa into these keys; map them onto the field whose
`accepted_values` fits:

| Keepa key | Fills (examples) |
| --------- | ---------------- |
| `asin` | UPC→ASIN bridge (needed for SIF later); not a template field |
| `brand` | Brand Name |
| `manufacturer` | Manufacturer |
| `title` | Item Name (refine to the rule's length/format) |
| `model` / `part_number` | Model Number / Model Name |
| `category_tree` | Item Type Keyword / browse hints |
| `bullet_points` | Bullet Point (one per bullet field) |
| `description` | Product Description |
| `color` / `size` | Color / Size |
| `package_dimensions_cm` + `package_weight_g` | package length/width/height/weight (convert to the unit the rule wants) |
| `item_dimensions_cm` + `item_weight_g` | item dimensions/weight |
| `images` | Main / Other Image URL |

Keepa dimensions are normalized to **cm** (from mm) and weight stays in **grams** —
convert to whatever unit the field's `accepted_values` specifies.

## Source priority

Per-field, the **filling rule wins**: pick whatever source produces a value that
matches `accepted_values`. When more than one source fits, prefer:

1. **Keepa** — structured catalog data, and the only UPC-native source.
2. **web search** — gap-fill, verification, enumerated values (e.g. Country of
   Origin), and anything Keepa lacks.

(When SIF is added it becomes the preferred source for keyword/copy fields — see
below.)

## Inferred values

A value is **inferred** when it isn't confirmed by any source (an educated guess
to satisfy a Required field). `write_values.py` fills those cells with a
background color (default `FFE0B2`, light orange). This is cosmetic — it does not
affect Amazon's server-side validation on upload — but lets the user review every
guess at a glance. Always also list inferred fields in the report.

## Adding SIF later

SIF (sif.com) is an **advertising / traffic keyword reverse-lookup** tool. It
queries by **ASIN** (not UPC) and returns keyword/traffic data, not product specs.
Planned role:

- Bridge UPC→ASIN via Keepa (already produced by `keepa_lookup.py`).
- Query SIF by ASIN for high-traffic ad/search keywords.
- Feed those into **copy/keyword fields**: Item Name, Bullet Point, Product
  Description, and backend Search Terms — making SIF the preferred source there.
- Add a `scripts/sif_lookup.py` mirroring `keepa_lookup.py` (env `SIF_API_KEY`,
  POST JSON with `authorization` header), plus a step in the workflow.
