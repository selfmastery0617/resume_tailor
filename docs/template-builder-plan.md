# Plan: user-created, manually edited templates

## What changes conceptually

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

## Layout schema

One JSON document per template, validated server-side.

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

## Rendering

Add one renderer, `LayoutRenderer`, registered as `rendererKey: "layout-v1"`:

```
getRenderer(rendererKey)
  ├── "renderer-1..10"  → existing chrome-based components   (unchanged)
  └── "layout-v1"       → LayoutRenderer(layout, data, style)
```

It walks regions → columns → blocks and reuses the existing section renderers
for `experience` / `education` / `skills`, so bullet parsing, date handling,
empty-section removal, and page-break rules are not reimplemented.

Preview and PDF need **no changes**: both already call `getRenderer()`, so a
layout template flows through the existing paginated preview and print route
automatically. That is the payoff of the content-only refactor already done.

---

## Editor UI

New tab or a mode on Templates: **Template Builder**.

```
┌──────────┬────────────────────────┬──────────────┐
│ Blocks   │  Canvas (live preview) │ Properties   │
│ palette  │  drag to reorder/move  │ of selection │
└──────────┴────────────────────────┴──────────────┘
```

- **Library:** `@dnd-kit/core` + `@dnd-kit/sortable`. Keyboard-accessible out of
  the box, which matters because §9.4 requires keyboard operation and HTML5
  drag-and-drop is notoriously bad at it. Every drag action also needs a
  non-drag equivalent (↑/↓ buttons, a column dropdown) — the existing section
  reorder already works this way.
- **Canvas:** the real `ResumePreview` with a selection overlay, so what you drag
  is what prints. No separate "design mode" rendering — that is how editors
  drift from their output.
- **Properties panel:** reuses `StyleEditor` controls, scoped to the selected
  block instead of the whole document.
- Save / Cancel / Reset and the unsaved-changes guard already exist and carry
  over.

---

## Build order

| Step | Deliverable | Why this order |
|---|---|---|
| 1 | Layout schema + server-side validator + unit tests | Everything else depends on the contract; cheapest place to get it wrong |
| 2 | `LayoutRenderer` + express one built-in as layout JSON | Proves the schema can express a real template before any UI exists |
| 3 | DB migration, `source`/`layout_json`, snapshot columns | Persistence before editing, so nothing is lost |
| 4 | CRUD API: duplicate, create, save, delete user templates | Testable via API alone |
| 5 | Builder UI: selection + properties panel, no drag yet | Reorder via buttons; already accessible |
| 6 | Drag-and-drop layer on top | Purely additive |
| 7 | PDF verification across user templates | Confirm parity holds for layouts |

Steps 1–4 are backend-only and independently verifiable; the UI cannot go wrong
in ways the API hasn't already caught.

---

## Risks

**Two-column pagination.** Columns that flow independently across pages are
genuinely hard — CSS multi-column breaks awkwardly and the slice-based preview
assumes a single flow. Simplest sound approach: treat a two-column region as
non-breaking (fits on one page) in v1, and only allow the single-column body
region to span pages.

**Preview/PDF drift.** Mitigated by rendering the canvas with the real preview
component, but user layouts widen the space of possible content enormously.
Worth a visual-regression pass over a few generated layouts.

**Scope.** This is comparable in size to Phases 1–3 combined. Steps 1–4 alone are
a solid increment and leave the app fully working without any UI change.
