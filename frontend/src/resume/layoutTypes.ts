/** Versioned template-layout contracts shared by the builder and renderer. */

import type { ResumeStyle } from "./types";

// ---------------------------------------------------------------------------
// Layout v1 — retained so every existing saved template renders unchanged.
// ---------------------------------------------------------------------------

export type LayoutBlockType =
  | "name"
  | "title"
  | "contact"
  | "summary"
  | "experience"
  | "education"
  | "skills"
  | "customText"
  | "divider"
  | "spacer";

export interface LayoutDivider {
  kind: "none" | "line" | "character";
  character?: string;
  /** Overrides the effective section color for this divider only. */
  color?: string;
  /** Vertical space on the previous-element side of this boundary. */
  spaceBeforeIn?: number;
  /** Vertical space between a visible divider and the following element. */
  spaceAfterIn?: number;
}

export interface LayoutColumn {
  id: string;
  widthPct: number;
  /** A vertical divider between this and the preceding visible column. */
  dividerBefore?: LayoutDivider;
}

export interface LayoutRegion {
  id: string;
  columns: LayoutColumn[];
  keepTogether?: boolean;
  /** A horizontal divider between this and the preceding visible region. */
  dividerBefore?: LayoutDivider;
}

export interface LayoutBlock {
  id: string;
  type: LayoutBlockType;
  columnId: string;
  order: number;
  style?: Partial<ResumeStyle>;
  props?: Record<string, unknown>;
}

export interface TemplateLayoutV1 {
  version: 1;
  page: { regions: LayoutRegion[] };
  blocks: LayoutBlock[];
}

// ---------------------------------------------------------------------------
// Layout v2 — five semantic blocks with constrained, nested section flows.
// ---------------------------------------------------------------------------

export type SemanticBlockType = "header" | "summary" | "skills" | "experience" | "education";

export type FlowItemRef =
  | "name"
  | "title"
  | "contactInfo"
  | "blockTitle"
  | "summaryContent"
  | "skills"
  | "groups"
  | "companyName"
  | "roleTitle"
  | "period"
  | "location"
  | "companySummary"
  | "bullets"
  | "universityName"
  | "degree"
  | "date";

export interface FlowItem {
  id: string;
  ref: FlowItemRef;
  hidden?: boolean;
  style?: Partial<ResumeStyle>;
  props?: Record<string, unknown>;
  /** A horizontal divider between this and the preceding visible item. */
  dividerBefore?: LayoutDivider;
}

export interface FlowColumn {
  id: string;
  widthPct: number;
  items: FlowItem[];
  /** Stack sections vertically, or merge them into one inline group. */
  mode?: "stack" | "inline";
  /** Position this cell/group within its share of the row. */
  align?: "left" | "center" | "right";
  /** A vertical divider between this and the preceding visible column. */
  dividerBefore?: LayoutDivider;
}

export interface FlowRow {
  id: string;
  columns: FlowColumn[];
  /** A horizontal divider between this and the preceding visible row. */
  dividerBefore?: LayoutDivider;
}

export interface Flow {
  rows: FlowRow[];
}

export interface SemanticBlock {
  id: string;
  type: SemanticBlockType;
  columnId: string;
  order: number;
  style?: Partial<ResumeStyle>;
  /** A horizontal divider between this and the preceding visible block. */
  dividerBefore?: LayoutDivider;
  contentFlow: Flow;
  /** Repeated once per Experience/Education record. */
  itemFlow?: Flow;
  /** A horizontal divider between consecutive repeated records. */
  itemDivider?: LayoutDivider;
}

export interface TemplateLayoutV2 {
  version: 2;
  dividerDefaults: { character: string };
  page: {
    size?: PaperSize;
    marginTopIn?: number;
    marginBottomIn?: number;
    marginLeftIn?: number;
    marginRightIn?: number;
    regions: LayoutRegion[];
  };
  blocks: SemanticBlock[];
}

export type PaperSize =
  | "letter"
  | "tabloid"
  | "legal"
  | "statement"
  | "executive"
  | "folio"
  | "a3"
  | "a4"
  | "a5"
  | "b4"
  | "b5";

export type TemplateLayout = TemplateLayoutV1 | TemplateLayoutV2;

/** Older validators accepted any integer version for the flat v1 shape, so
 * some persisted flat documents may say `version: 2`. Detect the structured
 * contract by its required shape as well as its version before dispatching. */
export function isTemplateLayoutV2(layout: TemplateLayout | unknown): layout is TemplateLayoutV2 {
  if (!layout || typeof layout !== "object") return false;
  const candidate = layout as Record<string, unknown>;
  if (candidate.version !== 2) return false;

  const defaults = candidate.dividerDefaults;
  if (
    !defaults ||
    typeof defaults !== "object" ||
    typeof (defaults as Record<string, unknown>).character !== "string"
  ) {
    return false;
  }

  const page = candidate.page;
  if (
    !page ||
    typeof page !== "object" ||
    !Array.isArray((page as Record<string, unknown>).regions)
  ) {
    return false;
  }

  return (
    Array.isArray(candidate.blocks) &&
    candidate.blocks.every((block) => {
      if (!block || typeof block !== "object") return false;
      const contentFlow = (block as Record<string, unknown>).contentFlow;
      return (
        Boolean(contentFlow) &&
        typeof contentFlow === "object" &&
        Array.isArray((contentFlow as Record<string, unknown>).rows)
      );
    })
  );
}
