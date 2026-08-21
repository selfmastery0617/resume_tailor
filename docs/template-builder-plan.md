# Plan: user-created, manually edited templates

> Status (layout v2): implemented. The flat v1 format remains renderable and
> read-only; new templates use the constrained five-block format below.

## Current v2 contract

A user template has exactly these semantic blocks:

| Block | Presence | Sections |
|---|---|---|
| Header | required | Name, Professional title, Contact info |
| Summary | optional | Block title, Summary content |
| Skills | required | Block title, Skills |
| Experience | required | Block title, repeating groups |
| Education | required | Block title, repeating groups |

The Experience group blueprint contains Company name, Role title, Period,
Company summary, Bullets, and optional Location. The Education blueprint
contains University name, Degree, Date, and optional Location. A blueprint is
stored once and repeated for the profile's current entries; templates never
serialize one layout group per company or school.

Sections can move only inside their owning block. Each block has a `contentFlow`
of rows, one or two columns per row, and ordered section references. Experience
and Education also have an `itemFlow` for their repeating group. Their compact
metadata (company/university, role/degree, period/date, and location) can use up
to four cells in one row. A cell can stack its sections or merge them inline,
and can align its content left, center, or right. Long summaries and bullets
remain in one/two-column stacked flow so they paginate safely. Blocks can move
between declared page columns, but the editor has no arbitrary x/y coordinates.
Every section remains structurally present and has an independent `hidden`
flag, allowing authors to show or hide it without weakening block cardinality.
Each section can also override the specific text-color field used by its
renderer, while retaining a one-click path back to its inherited template or
block color.

The page contract stores paper size plus top, bottom, left, and right margins.
Supported sizes are Letter, Tabloid, Legal, Statement, Executive, Folio, A3,
A4, A5, B4, and B5. Preview pagination and Playwright PDF generation consume
the same dimensions. Template defaults also store the selected font family;
the editor exposes a broad document-font catalog with category-safe fallbacks.

Dividers belong to the gap before the following visible item:

- gaps between stacked rows, sections, blocks, and regions are horizontal;
- gaps between adjacent columns are vertical;
- gaps between sections merged into one inline cell are character separators
  or inline rules;
- a gap can contain a line or one character;
- character gaps inherit `dividerDefaults.character` unless explicitly
  overridden, including Contact info and inline Skills; and
- every visible horizontal, vertical, or inline divider can override its color
  independently, falling back to the effective section color; and
- every horizontal boundary can override space before and after its divider;
  a boundary with no visible divider can still carry vertical spacing; and
- hidden or empty content removes its adjacent divider, so no orphan rule
  prints.

Backend validation enforces exact block and section cardinality, owning-block
scope, global ID uniqueness, one/two-column general limits and four-cell entry
metadata limits, widths totalling 100%, valid gap ownership, bounded labels and
divider characters, and normalized style values. The canonical TypeScript contract lives in
`frontend/src/resume/layoutTypes.ts`; the authoritative validator is
`backend/app/schemas/layout.py`.

`companySummary` is a real Experience field. It is editable on a profile and is
also carried from corpus product summaries through extraction persistence into
tailored resumes. The guarded Alembic revision adds it to both profile and
extracted experience rows.

### Compatibility

- `layout-v1` remains the generic renderer key and dispatches by document
  shape, so existing flat layouts still render.
- Historical flat layouts that happened to store `version: 2` are detected by
  shape and stay on the legacy path.
- Legacy layouts are read-only in the new builder. **Upgrade as five-block
  copy** performs an explicit best-effort conversion, preserves supported
  styles and keep-together choices, collapses extra columns to the v2 maximum,
  and never rewrites the original template.
- Generated-document layout snapshots remain immutable.

## Original design background

Today a template is **code**: `rendererKey` → a React component, ten of them, with
a fixed single-column structure. `ResumeDocument` decides that the header comes
first, then sections in `sectionOrder`. The user can restyle that structure but
not change it.

Letting users build templates makes a template **data**: a layout document the
renderer interprets. That is the whole change; everything below follows from it.

---

## The decision that shapes everything: how elements are positioned

### Option A — absolute positioning (drag anywhere, x/y/width/height)

Feels like Canva or Figma. Each element gets coordinates.

It breaks badly on this product, because resume content is variable-length:

- A profile with 3 experience entries and one with 12 need different heights.
  An absolutely-placed block either overlaps its neighbour or leaves a gap.
- Multi-page stops working. Pagination assumes content *flows*; absolute blocks
  have no natural break points. The paginated preview and PDF parity just
  achieved would have to be rebuilt on a different model.
- Every profile would need per-profile position tweaking, defeating the point of
  a reusable template.

Absolute positioning works for fixed-content design (posters, business cards).
Resumes are the opposite case.

### Option B — structured blocks in a flow (recommended)

The user arranges **blocks** into **regions**; content still flows and paginates.
Concretely they can:

- reorder blocks by dragging,
- move a block between columns (e.g. Skills into a right sidebar),
- switch a region between one and two columns and set the split (e.g. 65/35),
- resize, show/hide, and restyle each block,
- insert custom text, dividers, and spacers.

This is what Rezi, Novoresume, and Teal actually do, for the reasons above. It
keeps pagination, break-inside rules, and preview/PDF parity intact.

### Option C — hybrid

Option B everywhere, plus free positioning **inside the header band only**, where
content length is bounded (name, title, contact, photo). Gives most of the
"design freedom" feel without breaking flow.

**Recommendation: build B, leave the door open to C.** The layout schema below
supports adding a positioned header later without a migration.

---

## Legacy v1 layout schema (read-only)

This was the first builder wire format. It remains available for rendering and
explicit upgrade only; new templates do not use it.

```jsonc
{
  "version": 1,
  "page": {
    "regions": [
      { "id": "header", "columns": [{ "id": "h1", "widthPct": 100 }] },
      { "id": "body",   "columns": [
          { "id": "main", "widthPct": 65 },
          { "id": "side", "widthPct": 35 }
      ]}
    ]
  },
  "blocks": [
    { "id": "b1", "type": "name",       "columnId": "h1",   "order": 0, "style": {} },
    { "id": "b2", "type": "contact",    "columnId": "h1",   "order": 1, "style": {} },
    { "id": "b3", "type": "experience", "columnId": "main", "order": 0, "style": {} },
    { "id": "b4", "type": "skills",     "columnId": "side", "order": 0, "style": {} },
    { "id": "b5", "type": "customText", "columnId": "side", "order": 1,
      "props": { "heading": "Certifications", "body": "AWS SA\nCKA" } }
  ]
}
```

### Block types

| Type | Bound to | Notes |
|---|---|---|
| `name`, `title`, `contact` | profile fields | header pieces, individually movable |
| `summary` | `profile.summary` | |
| `experience`, `education`, `skills` | repeatable lists | keep existing bullet/date logic |
| `customText` | literal text in the template | **template-level, not profile data** |
| `divider`, `spacer` | — | pure layout |

### Rules the validator must enforce

- `columnId` must reference a declared column.
- A profile-bound block type may appear **at most once** (two Experience blocks
  would render duplicates).
- `widthPct` per region must total 100.
- `order` unique within a column.
- `customText` is stored as **text**, never HTML — same rule as RG-FR-003.
  This is the main new injection surface, since it is the first place template
  content is user-authored rather than code.

---

## Data model

The existing `template_definitions` shape mostly works; it needs three additions:

```sql
ALTER TABLE template_definitions ADD COLUMN source TEXT NOT NULL DEFAULT 'builtin'
    CHECK (source IN ('builtin', 'user'));
ALTER TABLE template_definitions ADD COLUMN layout_json TEXT;   -- NULL for code renderers
ALTER TABLE template_definitions ADD COLUMN owner_profile_id TEXT;  -- NULL = shared
```

- **Built-ins stay source-controlled.** They keep `rendererKey` and a NULL
  layout, so TM-FR-005 ("user edits do not rewrite source-controlled template
  files") still holds. "Duplicate to edit" produces a `user` row.
- **User templates get `layout_json`** and a NULL/shared `rendererKey` pointing at
  the generic layout renderer.

### The immutability problem this creates

`generated_resumes` currently stores `template_id` + `template_version` and
assumes the definition is stable — safe when templates are code. A user template
is mutable, so editing it would retroactively change what a past PDF claims to
have been rendered with.

**Fix: snapshot the layout too.** Add `layout_snapshot_json` to
`generated_resumes`, and bump `template_version` on every save of a user
template. Without this, US-RG-02 ("later changes must not modify previous PDFs")
silently breaks the moment templates become editable.

---

## Rendering architecture

`LayoutRenderer`, registered as `rendererKey: "layout-v1"`, now dispatches the
legacy flat document and the structured v2 document by validated shape:

```
getRenderer(rendererKey)
  ├── "renderer-1..10"  → existing chrome-based components   (unchanged)
  └── "layout-v1"       → LayoutRenderer(layout, data, style)
```

The v1 path reuses the aggregate section renderers unchanged. The v2 path uses
the same atomic content components through visibility-aware flows and repeating
group blueprints, so bullet parsing, dates, empty-content removal, and page
breaks stay consistent.

Preview and PDF need **no changes**: both already call `getRenderer()`, so a
layout template flows through the existing paginated preview and print route
automatically. That is the payoff of the content-only refactor already done.

---

## Editor UI

The **Template Builder** tab now combines a structure editor, live preview, and
template settings panel.

```
┌──────────────────┬────────────────────────┬──────────────────┐
│ Blocks/sections  │  Canvas (live preview) │ Template settings│
│ rows and columns │  paginated output      │ divider defaults │
└──────────────────┴────────────────────────┴──────────────────┘
```

- **Controls:** Every placement is keyboard-operable through move buttons,
  destination selectors, row/column controls, and split sliders. Invalid
  cross-block destinations do not exist.
- **Canvas:** the real `ResumePreview` renders the current draft. There is no
  separate design-mode renderer that can drift from printed output.
- **Settings panel:** controls the inherited divider character and optional
  Summary; block cards own headings, optional locations, flows, and gap rules.
- Save / Cancel and the unsaved-changes guard share the existing template CRUD
  workflow.

---

## Original build order (completed)

| Step | Deliverable | Why this order |
|---|---|---|
| 1 | Versioned schema, strict validator, and unit tests | Establish one shared contract |
| 2 | Atomic v2 renderer and repeat-group flows | Prove every semantic section renders |
| 3 | Company-summary persistence and guarded migration | Make the new section real data |
| 4 | Constrained builder operations and UI | Expose only schema-valid placements |
| 5 | Explicit legacy upgrade-as-copy | Preserve history without silent rewrites |
| 6 | Browser save/upgrade checks and multipage PDF verification | Confirm UI/API/renderer parity |


---

## Risks

**Two-column pagination.** Natural overflow is allowed to fragment a two-column
region so both columns can use the remainder of the current page. The
slice-based preview still assumes one shared vertical flow, so an explicit page
break inside only one column cannot exactly mirror Chromium's independent
column fragmentation. Avoid that combination until the preview has per-column
pagination; ordinary two-column overflow remains supported.

**Preview/PDF drift.** Mitigated by rendering the canvas with the real preview
component, but user layouts widen the space of possible content enormously.
Worth a visual-regression pass over a few generated layouts.

**Scope boundary.** The builder intentionally stops at structured flow. Free
absolute positioning would require a different pagination model and is not a
compatible extension of v2.
