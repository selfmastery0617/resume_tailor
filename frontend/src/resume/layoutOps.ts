/** Pure, typed operations for the constrained five-block layout editor.
 *
 * Layout v2 deliberately has no free x/y positioning. Resume blocks flow in
 * page columns, and their owned sections flow through rows and columns inside
 * the block. Keeping every mutation here makes the UI keyboard-operable and
 * prevents a Header section from accidentally being placed in Experience.
 */

import {
  isTemplateLayoutV2,
  type Flow,
  type FlowColumn,
  type FlowItem,
  type FlowItemRef,
  type FlowRow,
  type LayoutDivider,
  type PaperSize,
  type SemanticBlock,
  type SemanticBlockType,
  type TemplateLayoutV1,
  type TemplateLayoutV2,
} from "./layoutTypes";
import { PAPER_OPTIONS, pageGeometry } from "./pageGeometry";
import type { ResumeStyle } from "./types";

export { isTemplateLayoutV2 };
export type { FlowItemRef, LayoutDivider, SemanticBlock, SemanticBlockType };

export type FlowScope = "content" | "item";

export type SectionColorField =
  | "nameColor"
  | "titleColor"
  | "contactColor"
  | "sectionColor"
  | "bodyColor";

/** ResumeStyle uses specialized header/heading colors and a common body color.
 * Map each semantic section to the field its atomic renderer actually reads. */
export function sectionColorField(ref: FlowItemRef): SectionColorField {
  if (ref === "name") return "nameColor";
  if (ref === "title") return "titleColor";
  if (ref === "contactInfo") return "contactColor";
  if (ref === "blockTitle") return "sectionColor";
  return "bodyColor";
}

export const BLOCK_LABELS: Record<SemanticBlockType, string> = {
  header: "Header",
  summary: "Summary",
  skills: "Skills",
  experience: "Experience",
  education: "Education",
};

export const SECTION_LABELS: Record<FlowItemRef, string> = {
  name: "Name",
  title: "Professional title",
  contactInfo: "Contact info",
  blockTitle: "Block title",
  summaryContent: "Summary content",
  skills: "Skills",
  groups: "Groups",
  companyName: "Company name",
  roleTitle: "Role title",
  period: "Period",
  location: "Location",
  companySummary: "Company summary",
  bullets: "Bullets",
  universityName: "University name",
  degree: "Degree",
  date: "Date",
};

export const REQUIRED_BLOCK_TYPES: readonly SemanticBlockType[] = [
  "header",
  "skills",
  "experience",
  "education",
];

const newId = (prefix: string) => `${prefix}-${Math.random().toString(36).slice(2, 10)}`;

function clone<T>(value: T): T {
  return structuredClone(value);
}

function item(ref: FlowItemRef, label?: string): FlowItem {
  return {
    id: newId(`section-${ref}`),
    ref,
    ...(label ? { props: { label } } : {}),
  };
}

function row(...columnItems: FlowItem[][]): FlowRow {
  const widthPct = 100 / columnItems.length;
  return {
    id: newId("row"),
    columns: columnItems.map((items) => ({
      id: newId("flow-column"),
      widthPct,
      items,
    })),
  };
}

function inlineItems(refs: FlowItemRef[]): FlowItem[] {
  return refs.map((ref, index) => ({
    ...item(ref),
    ...(index > 0 ? { dividerBefore: { kind: "character" as const } } : {}),
  }));
}

function metadataRow(left: FlowItemRef[], right: FlowItemRef[]): FlowRow {
  const currentRow = row(inlineItems(left), inlineItems(right));
  currentRow.columns[0].widthPct = 65;
  currentRow.columns[0].mode = "inline";
  currentRow.columns[0].align = "left";
  currentRow.columns[1].widthPct = 35;
  currentRow.columns[1].mode = "inline";
  currentRow.columns[1].align = "right";
  return currentRow;
}

function setConventionalAlignments(columns: FlowColumn[]): void {
  columns.forEach((column, index) => {
    column.align =
      index === 0 ? "left" : index === columns.length - 1 ? "right" : "center";
  });
}

function flow(...rows: FlowRow[]): Flow {
  return { rows };
}

function createSemanticBlock(
  type: SemanticBlockType,
  columnId: string,
  order: number,
): SemanticBlock {
  const base = {
    id: `block-${type}-${Math.random().toString(36).slice(2, 8)}`,
    type,
    columnId,
    order,
  };

  switch (type) {
    case "header":
      return {
        ...base,
        contentFlow: flow(row([item("name")]), row([item("title")]), row([item("contactInfo")])),
      };
    case "summary":
      return {
        ...base,
        contentFlow: flow(
          row([item("blockTitle", "Summary")]),
          row([item("summaryContent")]),
        ),
      };
    case "skills":
      return {
        ...base,
        contentFlow: flow(row([item("blockTitle", "Skills")]), row([item("skills")])),
      };
    case "experience":
      return {
        ...base,
        contentFlow: flow(row([item("blockTitle", "Experience")]), row([item("groups")])),
        // roleTitle gets its own row, right below the company/period heading
        // row, rather than sharing it -- company name on line one, title on
        // line two. Matches default_layout() in backend/app/schemas/layout.py.
        itemFlow: flow(
          metadataRow(["companyName"], ["period", "location"]),
          row([item("roleTitle")]),
          row([item("companySummary")]),
          row([item("bullets")]),
        ),
      };
    case "education":
      return {
        ...base,
        contentFlow: flow(row([item("blockTitle", "Education")]), row([item("groups")])),
        itemFlow: flow(
          metadataRow(["universityName", "degree"], ["date", "location"]),
        ),
      };
  }
}

export function allPageColumnIds(layout: TemplateLayoutV2): string[] {
  return layout.page.regions.flatMap((region) => region.columns.map((column) => column.id));
}

export function blocksInColumn(layout: TemplateLayoutV2, columnId: string): SemanticBlock[] {
  return layout.blocks
    .filter((block) => block.columnId === columnId)
    .sort((a, b) => a.order - b.order);
}

export function flowFor(block: SemanticBlock, scope: FlowScope): Flow | undefined {
  return scope === "content" ? block.contentFlow : block.itemFlow;
}

function normaliseFlow(target: Flow): void {
  target.rows = target.rows
    .map((currentRow) => {
      currentRow.columns = currentRow.columns.filter((column) => column.items.length > 0);
      if (currentRow.columns.length === 0) return currentRow;

      const requested = currentRow.columns.map((column) => Math.max(1, column.widthPct));
      const total = requested.reduce((sum, value) => sum + value, 0);
      currentRow.columns.forEach((column, index) => {
        column.widthPct = (requested[index] / total) * 100;
        if (index === 0) delete column.dividerBefore;
        column.items.forEach((currentItem, itemIndex) => {
          if (itemIndex === 0) delete currentItem.dividerBefore;
          else if (
            column.mode === "inline" &&
            (!currentItem.dividerBefore || currentItem.dividerBefore.kind === "none")
          ) {
            currentItem.dividerBefore = { kind: "character" };
          }
        });
      });
      return currentRow;
    })
    .filter((currentRow) => currentRow.columns.some((column) => column.items.length > 0));

  target.rows.forEach((currentRow, index) => {
    if (index === 0) delete currentRow.dividerBefore;
  });
}

/** Renumber page-block order and remove dividers that no longer have a leading sibling. */
export function normalise(layout: TemplateLayoutV2): TemplateLayoutV2 {
  const next = clone(layout);
  const knownColumns = new Set(allPageColumnIds(next));
  const fallbackColumn = allPageColumnIds(next)[0];

  for (const block of next.blocks) {
    if (!knownColumns.has(block.columnId) && fallbackColumn) block.columnId = fallbackColumn;
    normaliseFlow(block.contentFlow);
    if (block.itemFlow) normaliseFlow(block.itemFlow);
  }

  for (const columnId of knownColumns) {
    blocksInColumn(next, columnId).forEach((block, index) => {
      block.order = index;
      if (index === 0) delete block.dividerBefore;
    });
  }

  next.page.regions.forEach((region, regionIndex) => {
    if (regionIndex === 0) delete region.dividerBefore;
    region.columns.forEach((column, columnIndex) => {
      if (columnIndex === 0) delete column.dividerBefore;
    });
  });
  return next;
}

export function moveBlock(
  layout: TemplateLayoutV2,
  blockId: string,
  delta: -1 | 1,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  if (!block) return layout;
  const siblings = blocksInColumn(next, block.columnId);
  const index = siblings.findIndex((candidate) => candidate.id === blockId);
  const target = index + delta;
  if (target < 0 || target >= siblings.length) return layout;
  const other = next.blocks.find((candidate) => candidate.id === siblings[target].id)!;
  [block.order, other.order] = [other.order, block.order];
  return normalise(next);
}

export function moveBlockToColumn(
  layout: TemplateLayoutV2,
  blockId: string,
  columnId: string,
): TemplateLayoutV2 {
  if (!allPageColumnIds(layout).includes(columnId)) return layout;
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  if (!block || block.columnId === columnId) return layout;
  block.columnId = columnId;
  block.order = blocksInColumn(next, columnId).length;
  delete block.dividerBefore;
  return normalise(next);
}

export function setRegionColumnCount(
  layout: TemplateLayoutV2,
  regionId: string,
  count: 1 | 2,
  splitPct = 65,
): TemplateLayoutV2 {
  const next = clone(layout);
  const region = next.page.regions.find((candidate) => candidate.id === regionId);
  if (!region || region.columns.length === count) return layout;
  if (count === 2) {
    const first = region.columns[0];
    first.widthPct = splitPct;
    region.columns.push({
      id: newId(`${regionId}-column`),
      widthPct: 100 - splitPct,
    });
  } else {
    const [keep, ...removed] = region.columns;
    const removedIds = new Set(removed.map((column) => column.id));
    for (const block of next.blocks) {
      if (removedIds.has(block.columnId)) {
        block.columnId = keep.id;
        block.order = Number.MAX_SAFE_INTEGER;
      }
    }
    keep.widthPct = 100;
    region.columns = [keep];
  }
  return normalise(next);
}

export function setRegionSplit(
  layout: TemplateLayoutV2,
  regionId: string,
  firstPct: number,
): TemplateLayoutV2 {
  const next = clone(layout);
  const region = next.page.regions.find((candidate) => candidate.id === regionId);
  if (!region || region.columns.length !== 2) return layout;
  const clamped = Math.min(85, Math.max(15, Math.round(firstPct)));
  region.columns[0].widthPct = clamped;
  region.columns[1].widthPct = 100 - clamped;
  return next;
}

export function addSummary(layout: TemplateLayoutV2, columnId?: string): TemplateLayoutV2 {
  if (layout.blocks.some((block) => block.type === "summary")) return layout;
  const target = columnId && allPageColumnIds(layout).includes(columnId)
    ? columnId
    : allPageColumnIds(layout).find((id) => id.includes("body")) ?? allPageColumnIds(layout)[0];
  if (!target) return layout;
  const next = clone(layout);
  next.blocks.push(createSemanticBlock("summary", target, blocksInColumn(next, target).length));
  return normalise(next);
}

export function removeSummary(layout: TemplateLayoutV2): TemplateLayoutV2 {
  const next = clone(layout);
  next.blocks = next.blocks.filter((block) => block.type !== "summary");
  return normalise(next);
}

export function setOptionalLocation(
  layout: TemplateLayoutV2,
  blockId: string,
  enabled: boolean,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  if (!block || !["experience", "education"].includes(block.type) || !block.itemFlow) {
    return layout;
  }
  const present = block.itemFlow.rows.some((currentRow) =>
    currentRow.columns.some((column) => column.items.some((currentItem) => currentItem.ref === "location")),
  );
  if (present === enabled) return layout;
  if (enabled) block.itemFlow.rows.push(row([item("location")]));
  else {
    for (const currentRow of block.itemFlow.rows) {
      for (const column of currentRow.columns) {
        column.items = column.items.filter((currentItem) => currentItem.ref !== "location");
      }
    }
  }
  return normalise(next);
}

export function hasSection(block: SemanticBlock, scope: FlowScope, ref: FlowItemRef): boolean {
  const target = flowFor(block, scope);
  return Boolean(target?.rows.some((currentRow) =>
    currentRow.columns.some((column) => column.items.some((currentItem) => currentItem.ref === ref)),
  ));
}

function findItem(target: Flow, itemId: string) {
  for (const currentRow of target.rows) {
    for (const column of currentRow.columns) {
      const index = column.items.findIndex((currentItem) => currentItem.id === itemId);
      if (index >= 0) return { row: currentRow, column, index, item: column.items[index] };
    }
  }
  return null;
}

const COMPACT_ENTRY_REFS: Record<"experience" | "education", ReadonlySet<FlowItemRef>> = {
  experience: new Set(["companyName", "roleTitle", "period", "location"]),
  education: new Set(["universityName", "degree", "date", "location"]),
};

export function isCompactEntryColumn(block: SemanticBlock, column: FlowColumn): boolean {
  if (block.type !== "experience" && block.type !== "education") return false;
  const allowed = COMPACT_ENTRY_REFS[block.type];
  return column.items.every((currentItem) => allowed.has(currentItem.ref));
}

export function moveSection(
  layout: TemplateLayoutV2,
  blockId: string,
  scope: FlowScope,
  itemId: string,
  targetRowId: string,
  targetColumnId: string,
  targetIndex: number,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  const target = block && flowFor(block, scope);
  if (!target) return layout;
  const source = findItem(target, itemId);
  const rowTarget = target.rows.find((candidate) => candidate.id === targetRowId);
  const columnTarget = rowTarget?.columns.find((candidate) => candidate.id === targetColumnId);
  if (!source || !columnTarget) return layout;
  const [moving] = source.column.items.splice(source.index, 1);
  columnTarget.items.splice(Math.max(0, Math.min(targetIndex, columnTarget.items.length)), 0, moving);
  if (
    scope === "item" &&
    isCompactEntryColumn(block, columnTarget) &&
    columnTarget.items.length > 1
  ) {
    columnTarget.mode = "inline";
  }
  return normalise(next);
}

export function moveSectionBy(
  layout: TemplateLayoutV2,
  blockId: string,
  scope: FlowScope,
  itemId: string,
  delta: -1 | 1,
): TemplateLayoutV2 {
  const block = layout.blocks.find((candidate) => candidate.id === blockId);
  const target = block && flowFor(block, scope);
  const source = target && findItem(target, itemId);
  if (!source) return layout;
  const targetIndex = source.index + delta;
  if (targetIndex < 0 || targetIndex >= source.column.items.length) return layout;
  return moveSection(layout, blockId, scope, itemId, source.row.id, source.column.id, targetIndex);
}

export function moveSectionToNewRow(
  layout: TemplateLayoutV2,
  blockId: string,
  scope: FlowScope,
  itemId: string,
  afterRowId: string,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  const target = block && flowFor(block, scope);
  if (!target) return layout;
  const source = findItem(target, itemId);
  const afterIndex = target.rows.findIndex((candidate) => candidate.id === afterRowId);
  if (!source || afterIndex < 0) return layout;
  const [moving] = source.column.items.splice(source.index, 1);
  target.rows.splice(afterIndex + 1, 0, row([moving]));
  return normalise(next);
}

/** Split the last section from a multi-section column into a new row. */
export function addFlowRow(
  layout: TemplateLayoutV2,
  blockId: string,
  scope: FlowScope,
): TemplateLayoutV2 {
  const block = layout.blocks.find((candidate) => candidate.id === blockId);
  const target = block && flowFor(block, scope);
  if (!target) return layout;
  const source = [...target.rows].reverse().flatMap((currentRow) =>
    [...currentRow.columns].reverse().map((column) => ({ row: currentRow, column })),
  ).find(({ column }) => column.items.length > 1);
  const moving = source?.column.items.at(-1);
  const lastRow = target.rows.at(-1);
  if (!moving || !lastRow) return layout;
  return moveSectionToNewRow(layout, blockId, scope, moving.id, lastRow.id);
}

/** Remove a row without deleting content, preserving order in an adjacent row. */
export function removeFlowRow(
  layout: TemplateLayoutV2,
  blockId: string,
  scope: FlowScope,
  rowId: string,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  const target = block && flowFor(block, scope);
  if (!target || target.rows.length <= 1) return layout;
  const index = target.rows.findIndex((candidate) => candidate.id === rowId);
  if (index < 0) return layout;
  const [removed] = target.rows.splice(index, 1);
  const destination = target.rows[Math.max(0, index - 1)].columns[0];
  const removedItems = removed.columns.flatMap((column) => column.items);
  if (index === 0) destination.items.unshift(...removedItems);
  else destination.items.push(...removedItems);
  return normalise(next);
}

export function setFlowRowColumnCount(
  layout: TemplateLayoutV2,
  blockId: string,
  scope: FlowScope,
  rowId: string,
  count: 1 | 2 | 3 | 4,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  const target = block && flowFor(block, scope);
  const targetRow = target?.rows.find((candidate) => candidate.id === rowId);
  if (!block || !targetRow || targetRow.columns.length === count) return layout;
  const maxColumns =
    scope === "item" && targetRow.columns.every((column) => isCompactEntryColumn(block, column))
      ? 4
      : 2;
  if (count > maxColumns) return layout;

  while (targetRow.columns.length > count) {
    const removed = targetRow.columns.pop();
    const destination = targetRow.columns.at(-1);
    if (!removed || !destination) break;
    destination.items.push(...removed.items);
    if (scope === "item" && isCompactEntryColumn(block, destination)) {
      destination.mode = "inline";
    }
  }

  while (targetRow.columns.length < count) {
    let sourceIndex = -1;
    for (let index = targetRow.columns.length - 1; index >= 0; index -= 1) {
      if (targetRow.columns[index].items.length > 1) {
        sourceIndex = index;
        break;
      }
    }
    if (sourceIndex < 0) break;
    const source = targetRow.columns[sourceIndex];
    const moving = source.items.pop();
    if (!moving) break;
    delete moving.dividerBefore;
    targetRow.columns.splice(sourceIndex + 1, 0, {
      id: newId("flow-column"),
      widthPct: 1,
      items: [moving],
      mode: "stack",
      align: sourceIndex + 1 === count - 1 ? "right" : "center",
    });
  }

  const equalWidth = 100 / targetRow.columns.length;
  targetRow.columns.forEach((column) => {
    column.widthPct = equalWidth;
  });
  setConventionalAlignments(targetRow.columns);
  return normalise(next);
}

export function setFlowRowSplit(
  layout: TemplateLayoutV2,
  blockId: string,
  scope: FlowScope,
  rowId: string,
  firstPct: number,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  const target = block && flowFor(block, scope);
  const targetRow = target?.rows.find((candidate) => candidate.id === rowId);
  if (!targetRow || targetRow.columns.length !== 2) return layout;
  const clamped = Math.min(85, Math.max(15, Math.round(firstPct)));
  targetRow.columns[0].widthPct = clamped;
  targetRow.columns[1].widthPct = 100 - clamped;
  return next;
}

export function setFlowColumnMode(
  layout: TemplateLayoutV2,
  blockId: string,
  scope: FlowScope,
  rowId: string,
  columnId: string,
  mode: "stack" | "inline",
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  const target = block && flowFor(block, scope);
  const column = target?.rows.find((candidate) => candidate.id === rowId)?.columns
    .find((candidate) => candidate.id === columnId);
  if (!block || !column || (mode === "inline" && !isCompactEntryColumn(block, column))) {
    return layout;
  }
  column.mode = mode;
  return normalise(next);
}

export function setFlowColumnAlign(
  layout: TemplateLayoutV2,
  blockId: string,
  scope: FlowScope,
  rowId: string,
  columnId: string,
  align: "left" | "center" | "right",
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  const target = block && flowFor(block, scope);
  const column = target?.rows.find((candidate) => candidate.id === rowId)?.columns
    .find((candidate) => candidate.id === columnId);
  if (!column) return layout;
  column.align = align;
  return next;
}

export function setFlowItemHidden(
  layout: TemplateLayoutV2,
  blockId: string,
  scope: FlowScope,
  itemId: string,
  hidden: boolean,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  const target = block && flowFor(block, scope);
  const found = target && findItem(target, itemId);
  if (!found) return layout;
  found.item.hidden = hidden;
  return next;
}

export function setFlowItemColor(
  layout: TemplateLayoutV2,
  blockId: string,
  scope: FlowScope,
  itemId: string,
  color: string | null,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  const target = block && flowFor(block, scope);
  const found = target && findItem(target, itemId);
  if (!found) return layout;

  const field = sectionColorField(found.item.ref);
  const style = { ...(found.item.style ?? {}) };
  if (color === null) delete style[field];
  else if (/^#[0-9a-fA-F]{6}$/.test(color)) style[field] = color;
  else return layout;
  found.item.style = Object.keys(style).length ? style : undefined;
  return next;
}

export function setPaperSize(
  layout: TemplateLayoutV2,
  size: PaperSize,
): TemplateLayoutV2 {
  if (!PAPER_OPTIONS.some((paper) => paper.id === size)) return layout;
  const next = clone(layout);
  next.page.size = size;
  const geometry = pageGeometry(next);
  const maxHorizontalMargin = Math.max(0, (geometry.widthIn - 2) / 2);
  const maxVerticalMargin = Math.max(0, (geometry.heightIn - 2) / 2);
  next.page.marginLeftIn = Math.min(geometry.marginLeftIn, maxHorizontalMargin);
  next.page.marginRightIn = Math.min(geometry.marginRightIn, maxHorizontalMargin);
  next.page.marginTopIn = Math.min(geometry.marginTopIn, maxVerticalMargin);
  next.page.marginBottomIn = Math.min(geometry.marginBottomIn, maxVerticalMargin);
  return next;
}

export function setPageMargin(
  layout: TemplateLayoutV2,
  side: "top" | "bottom" | "left" | "right",
  inches: number,
): TemplateLayoutV2 {
  if (!Number.isFinite(inches)) return layout;
  const next = clone(layout);
  const paper = PAPER_OPTIONS.find((candidate) => candidate.id === (next.page.size ?? "letter"))
    ?? PAPER_OPTIONS[0];
  const clamped = Math.max(0, Math.min(2, inches));
  if (side === "top") {
    next.page.marginTopIn = Math.min(clamped, paper.heightIn - (next.page.marginBottomIn ?? 0.5) - 2);
  } else if (side === "bottom") {
    next.page.marginBottomIn = Math.min(clamped, paper.heightIn - (next.page.marginTopIn ?? 0.7) - 2);
  } else if (side === "left") {
    next.page.marginLeftIn = Math.min(clamped, paper.widthIn - (next.page.marginRightIn ?? 0.65) - 2);
  } else {
    next.page.marginRightIn = Math.min(clamped, paper.widthIn - (next.page.marginLeftIn ?? 0.65) - 2);
  }
  return next;
}

export function mergeSectionIntoPreviousColumn(
  layout: TemplateLayoutV2,
  blockId: string,
  itemId: string,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  if (!block?.itemFlow) return layout;
  const source = findItem(block.itemFlow, itemId);
  if (!source) return layout;
  const sourceRow = block.itemFlow.rows.find((candidate) => candidate.id === source.row.id);
  const sourceColumnIndex = sourceRow?.columns.findIndex(
    (candidate) => candidate.id === source.column.id,
  ) ?? -1;
  if (!sourceRow || sourceColumnIndex <= 0) return layout;
  const destination = sourceRow.columns[sourceColumnIndex - 1];
  if (!isCompactEntryColumn(block, destination)) return layout;
  const [moving] = source.column.items.splice(source.index, 1);
  destination.items.push(moving);
  if (!isCompactEntryColumn(block, destination)) return layout;
  destination.mode = "inline";
  sourceRow.columns = sourceRow.columns.filter((column) => column.items.length > 0);
  setConventionalAlignments(sourceRow.columns);
  return normalise(next);
}

export function splitSectionToNewColumn(
  layout: TemplateLayoutV2,
  blockId: string,
  itemId: string,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  if (!block?.itemFlow) return layout;
  const source = findItem(block.itemFlow, itemId);
  if (!source || source.column.items.length <= 1 || source.row.columns.length >= 4) return layout;
  const columnIndex = source.row.columns.findIndex((column) => column.id === source.column.id);
  const [moving] = source.column.items.splice(source.index, 1);
  delete moving.dividerBefore;
  source.row.columns.splice(columnIndex + 1, 0, {
    id: newId("flow-column"),
    widthPct: 1,
    items: [moving],
    mode: "stack",
    align: columnIndex + 1 === source.row.columns.length ? "right" : "center",
  });
  const equalWidth = 100 / source.row.columns.length;
  source.row.columns.forEach((column) => {
    column.widthPct = equalWidth;
  });
  setConventionalAlignments(source.row.columns);
  return normalise(next);
}

export function setBlockLabel(
  layout: TemplateLayoutV2,
  blockId: string,
  label: string,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  const heading = block && block.contentFlow.rows
    .flatMap((currentRow) => currentRow.columns)
    .flatMap((column) => column.items)
    .find((currentItem) => currentItem.ref === "blockTitle");
  if (!heading) return layout;
  heading.props = { ...heading.props, label: label.slice(0, 120) };
  return next;
}

function cleanDivider(value: LayoutDivider | null): LayoutDivider | undefined {
  if (!value) return undefined;
  const cleanSpace = (space: number | undefined) =>
    typeof space === "number" && Number.isFinite(space)
      ? Math.max(0, Math.min(1, space))
      : undefined;
  const spaceBeforeIn = cleanSpace(value.spaceBeforeIn);
  const spaceAfterIn = cleanSpace(value.spaceAfterIn);
  const spacing = {
    ...(spaceBeforeIn !== undefined ? { spaceBeforeIn } : {}),
    ...(spaceAfterIn !== undefined ? { spaceAfterIn } : {}),
  };
  const color =
    typeof value.color === "string" && /^#[0-9a-fA-F]{6}$/.test(value.color)
      ? value.color
      : undefined;
  const appearance = color ? { color } : {};
  if (value.kind === "none") {
    return Object.keys(spacing).length ? { kind: "none", ...spacing } : undefined;
  }
  if (value.kind === "line") return { kind: "line", ...appearance, ...spacing };
  const characters = Array.from((value.character ?? "").trim());
  const character = characters.slice(0, 3).join("");
  return {
    kind: "character",
    ...(character ? { character } : {}),
    ...appearance,
    ...spacing,
  };
}

export function setDividerDefaultCharacter(
  layout: TemplateLayoutV2,
  character: string,
): TemplateLayoutV2 {
  const next = clone(layout);
  next.dividerDefaults.character = Array.from(character.trim()).slice(0, 3).join("") || "·";
  return next;
}

export function setBlockDivider(
  layout: TemplateLayoutV2,
  blockId: string,
  value: LayoutDivider | null,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  if (!block) return layout;
  block.dividerBefore = cleanDivider(value);
  return normalise(next);
}

export function setRegionDivider(
  layout: TemplateLayoutV2,
  regionId: string,
  value: LayoutDivider | null,
): TemplateLayoutV2 {
  const next = clone(layout);
  const region = next.page.regions.find((candidate) => candidate.id === regionId);
  if (!region) return layout;
  region.dividerBefore = cleanDivider(value);
  return normalise(next);
}

export function setPageColumnDivider(
  layout: TemplateLayoutV2,
  regionId: string,
  columnId: string,
  value: LayoutDivider | null,
): TemplateLayoutV2 {
  const next = clone(layout);
  const column = next.page.regions
    .find((region) => region.id === regionId)?.columns
    .find((candidate) => candidate.id === columnId);
  if (!column) return layout;
  column.dividerBefore = cleanDivider(value);
  return normalise(next);
}

export function setFlowRowDivider(
  layout: TemplateLayoutV2,
  blockId: string,
  scope: FlowScope,
  rowId: string,
  value: LayoutDivider | null,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  const target = block && flowFor(block, scope);
  const targetRow = target?.rows.find((candidate) => candidate.id === rowId);
  if (!targetRow) return layout;
  targetRow.dividerBefore = cleanDivider(value);
  return normalise(next);
}

export function setFlowColumnDivider(
  layout: TemplateLayoutV2,
  blockId: string,
  scope: FlowScope,
  rowId: string,
  columnId: string,
  value: LayoutDivider | null,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  const target = block && flowFor(block, scope);
  const column = target?.rows.find((candidate) => candidate.id === rowId)?.columns
    .find((candidate) => candidate.id === columnId);
  if (!column) return layout;
  column.dividerBefore = cleanDivider(value);
  return normalise(next);
}

export function setFlowItemDivider(
  layout: TemplateLayoutV2,
  blockId: string,
  scope: FlowScope,
  itemId: string,
  value: LayoutDivider | null,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  const target = block && flowFor(block, scope);
  const found = target && findItem(target, itemId);
  if (!found) return layout;
  found.item.dividerBefore = cleanDivider(value);
  return normalise(next);
}

export function setItemDivider(
  layout: TemplateLayoutV2,
  blockId: string,
  value: LayoutDivider | null,
): TemplateLayoutV2 {
  const next = clone(layout);
  const block = next.blocks.find((candidate) => candidate.id === blockId);
  if (!block?.itemFlow) return layout;
  block.itemDivider = cleanDivider(value);
  return next;
}

/**
 * Best-effort, explicit conversion for the old free-form layout.
 *
 * It keeps up to two columns per old region (collapsing additional columns),
 * preserves explicit keep-together and style choices, groups
 * Name/Title/Contact into Header, inserts missing mandatory blocks, and
 * intentionally drops legacy custom text/spacer/divider nodes. Callers must
 * present this as a copy because that regrouping cannot be lossless.
 */
export function upgradeLegacyLayout(
  legacy: TemplateLayoutV1,
  legacyStyle: Partial<ResumeStyle> = {},
): TemplateLayoutV2 {
  const legacyRegions = legacy.page.regions.filter((region) => region.columns.length > 0);
  const legacyColumnTargets = new Map<string, string>();
  const regions = legacyRegions.length
    ? legacyRegions.map((region, regionIndex) => {
      const kept = region.columns.slice(0, 2);
      const rawWidths = kept.map((column, columnIndex) =>
        columnIndex === 1
          ? region.columns.slice(1).reduce((sum, candidate) => sum + candidate.widthPct, 0)
          : column.widthPct,
      );
      const total = rawWidths.reduce((sum, width) => sum + width, 0) || 100;
      const columns = kept.map((column, columnIndex) => {
        const id = `upgrade-page-${regionIndex + 1}-column-${columnIndex + 1}`;
        if (!legacyColumnTargets.has(column.id)) legacyColumnTargets.set(column.id, id);
        if (columnIndex === 1) {
          for (const collapsed of region.columns.slice(2)) {
            if (!legacyColumnTargets.has(collapsed.id)) {
              legacyColumnTargets.set(collapsed.id, id);
            }
          }
        }
        return {
          id,
          widthPct: kept.length === 1 ? 100 : (rawWidths[columnIndex] / total) * 100,
        };
      });
      return {
        id: `upgrade-page-region-${regionIndex + 1}`,
        columns,
        ...(region.keepTogether ? { keepTogether: true } : {}),
      };
    })
    : [
      { id: "header", columns: [{ id: "header-main", widthPct: 100 }] },
      { id: "body", columns: [{ id: "body-main", widthPct: 100 }] },
    ];
  const columns = regions.flatMap((region) => region.columns.map((column) => column.id));
  const firstColumn = columns[0] ?? "body-main";
  const legacyBodyColumn = legacyRegions
    .flatMap((region) => region.columns)
    .find((column) => column.id.includes("body"));
  const bodyColumn = (legacyBodyColumn && legacyColumnTargets.get(legacyBodyColumn.id)) ?? firstColumn;
  const oldByType = new Map(legacy.blocks.map((block) => [block.type, block]));
  const headerPieces = ["name", "title", "contact"]
    .map((type) => oldByType.get(type as "name" | "title" | "contact"))
    .filter((value): value is NonNullable<typeof value> => Boolean(value));
  const headerAnchor = headerPieces.sort((a, b) => a.order - b.order)[0];

  const make = (type: SemanticBlockType, fallback: string, fallbackOrder: number) => {
    const old = oldByType.get(type as "summary" | "skills" | "experience" | "education");
    const target = (old && legacyColumnTargets.get(old.columnId)) ?? fallback;
    const upgraded = createSemanticBlock(type, target, old?.order ?? fallbackOrder);
    if (old?.style) upgraded.style = clone(old.style);
    return upgraded;
  };

  const header = createSemanticBlock(
    "header",
    (headerAnchor && legacyColumnTargets.get(headerAnchor.columnId)) ?? firstColumn,
    headerAnchor?.order ?? 0,
  );
  const headerStyleSources = {
    name: oldByType.get("name"),
    title: oldByType.get("title"),
    contactInfo: oldByType.get("contact"),
  } as const;
  for (const headerItem of header.contentFlow.rows.flatMap((currentRow) =>
    currentRow.columns.flatMap((column) => column.items),
  )) {
    const source = headerStyleSources[headerItem.ref as keyof typeof headerStyleSources];
    if (source?.style) headerItem.style = clone(source.style);
  }

  const blocks: SemanticBlock[] = [header];
  const oldSummary = oldByType.get("summary");
  const summaryWasVisible = oldSummary?.style?.showSummary ?? legacyStyle.showSummary ?? true;
  if (oldSummary && summaryWasVisible) {
    blocks.push(make("summary", bodyColumn, 0));
  }
  blocks.push(make("experience", bodyColumn, 1));
  blocks.push(make("skills", bodyColumn, 2));
  blocks.push(make("education", bodyColumn, 3));

  return normalise({
    version: 2,
    dividerDefaults: { character: "·" },
    page: { regions },
    blocks,
  });
}
