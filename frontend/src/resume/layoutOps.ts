/** Pure operations on a layout document.
 *
 *  Kept separate from the builder UI so each edit is a testable function, and
 *  so every mutation goes through `normalise()` — the backend rejects duplicate
 *  orders and orphaned columns, and it is far easier to keep the document valid
 *  by construction than to repair it at save time.
 */

import type { LayoutBlock, LayoutBlockType, TemplateLayout } from "./LayoutRenderer";

/** Block types bound to profile data — at most one of each per template. */
export const SINGLETON_BLOCKS: LayoutBlockType[] = [
  "name",
  "title",
  "contact",
  "summary",
  "experience",
  "education",
  "skills",
];

export const BLOCK_LABELS: Record<LayoutBlockType, string> = {
  name: "Name",
  title: "Professional title",
  contact: "Contact details",
  summary: "Summary",
  experience: "Experience",
  education: "Education",
  skills: "Skills",
  customText: "Custom text",
  divider: "Divider",
  spacer: "Spacer",
};

const newId = (prefix: string) => `${prefix}-${Math.random().toString(36).slice(2, 10)}`;

function clone(layout: TemplateLayout): TemplateLayout {
  return JSON.parse(JSON.stringify(layout)) as TemplateLayout;
}

/** Renumber `order` to 0..n-1 within every column. */
export function normalise(layout: TemplateLayout): TemplateLayout {
  const next = clone(layout);
  const known = new Set(allColumnIds(next));

  // Drop blocks whose column disappeared (e.g. after collapsing to one column)
  // rather than leaving a reference the validator will reject.
  next.blocks = next.blocks.filter((b) => known.has(b.columnId));

  const byColumn = new Map<string, LayoutBlock[]>();
  for (const block of next.blocks) {
    const list = byColumn.get(block.columnId);
    if (list) list.push(block);
    else byColumn.set(block.columnId, [block]);
  }
  for (const list of byColumn.values()) {
    list.sort((a, b) => a.order - b.order);
    list.forEach((block, index) => {
      block.order = index;
    });
  }
  return next;
}

export function allColumnIds(layout: TemplateLayout): string[] {
  return layout.page.regions.flatMap((r) => r.columns.map((c) => c.id));
}

export function blocksInColumn(layout: TemplateLayout, columnId: string): LayoutBlock[] {
  return layout.blocks
    .filter((b) => b.columnId === columnId)
    .sort((a, b) => a.order - b.order);
}

export function usedSingletons(layout: TemplateLayout): Set<LayoutBlockType> {
  return new Set(
    layout.blocks
      .map((b) => b.type)
      .filter((t): t is LayoutBlockType => SINGLETON_BLOCKS.includes(t)),
  );
}

export function addBlock(
  layout: TemplateLayout,
  type: LayoutBlockType,
  columnId: string,
): { layout: TemplateLayout; blockId: string } {
  const next = clone(layout);
  const blockId = newId("blk");
  const order = blocksInColumn(next, columnId).length;

  const block: LayoutBlock = { id: blockId, type, columnId, order, style: {} };
  if (type === "customText") {
    block.props = { heading: "New section", body: "" };
  } else if (type === "spacer") {
    block.props = { heightInches: 0.2 };
  }

  next.blocks.push(block);
  return { layout: normalise(next), blockId };
}

export function removeBlock(layout: TemplateLayout, blockId: string): TemplateLayout {
  const next = clone(layout);
  next.blocks = next.blocks.filter((b) => b.id !== blockId);
  return normalise(next);
}

/** Move a block up or down within its own column. */
export function moveBlock(
  layout: TemplateLayout,
  blockId: string,
  delta: -1 | 1,
): TemplateLayout {
  const next = clone(layout);
  const block = next.blocks.find((b) => b.id === blockId);
  if (!block) return layout;

  const siblings = blocksInColumn(next, block.columnId);
  const index = siblings.findIndex((b) => b.id === blockId);
  const target = index + delta;
  if (target < 0 || target >= siblings.length) return layout;

  const swapWith = next.blocks.find((b) => b.id === siblings[target].id)!;
  const tmp = block.order;
  block.order = swapWith.order;
  swapWith.order = tmp;
  return normalise(next);
}

/** Move a block into a different column, appended at the end. */
export function moveBlockToColumn(
  layout: TemplateLayout,
  blockId: string,
  columnId: string,
): TemplateLayout {
  const next = clone(layout);
  const block = next.blocks.find((b) => b.id === blockId);
  if (!block || block.columnId === columnId) return layout;
  block.columnId = columnId;
  block.order = Number.MAX_SAFE_INTEGER; // normalise() puts it last
  return normalise(next);
}

/** Place a block at a specific index in a column (used by drag-and-drop). */
export function placeBlock(
  layout: TemplateLayout,
  blockId: string,
  columnId: string,
  index: number,
): TemplateLayout {
  const next = clone(layout);
  const block = next.blocks.find((b) => b.id === blockId);
  if (!block) return layout;

  block.columnId = columnId;
  // Half-steps slot the block between two neighbours; normalise() renumbers.
  block.order = index - 0.5;
  return normalise(next);
}

export function updateBlock(
  layout: TemplateLayout,
  blockId: string,
  patch: Partial<LayoutBlock>,
): TemplateLayout {
  const next = clone(layout);
  const block = next.blocks.find((b) => b.id === blockId);
  if (!block) return layout;
  Object.assign(block, patch);
  return normalise(next);
}

/** Switch a region between one and two columns.
 *
 *  Collapsing merges the second column's blocks into the first rather than
 *  discarding them — losing content on a layout change would be surprising.
 */
export function setRegionColumnCount(
  layout: TemplateLayout,
  regionId: string,
  count: 1 | 2,
  splitPct = 65,
): TemplateLayout {
  const next = clone(layout);
  const region = next.page.regions.find((r) => r.id === regionId);
  if (!region || region.columns.length === count) return layout;

  if (count === 2) {
    const first = region.columns[0];
    first.widthPct = splitPct;
    region.columns.push({ id: `${regionId}-side`, widthPct: 100 - splitPct });
  } else {
    const [keep, ...dropped] = region.columns;
    keep.widthPct = 100;
    const droppedIds = new Set(dropped.map((c) => c.id));
    for (const block of next.blocks) {
      if (droppedIds.has(block.columnId)) {
        block.columnId = keep.id;
        block.order = Number.MAX_SAFE_INTEGER;
      }
    }
    region.columns = [keep];
  }
  return normalise(next);
}

export function setRegionSplit(
  layout: TemplateLayout,
  regionId: string,
  firstPct: number,
): TemplateLayout {
  const next = clone(layout);
  const region = next.page.regions.find((r) => r.id === regionId);
  if (!region || region.columns.length !== 2) return layout;
  const clamped = Math.min(85, Math.max(15, Math.round(firstPct)));
  region.columns[0].widthPct = clamped;
  region.columns[1].widthPct = 100 - clamped;
  return next;
}
