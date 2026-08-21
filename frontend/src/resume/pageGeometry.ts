import { isTemplateLayoutV2, type PaperSize } from "./layoutTypes";

export const PAPER_OPTIONS: ReadonlyArray<{
  id: PaperSize;
  label: string;
  widthIn: number;
  heightIn: number;
}> = [
  { id: "letter", label: "Letter (8.5 × 11 in)", widthIn: 8.5, heightIn: 11 },
  { id: "tabloid", label: "Tabloid (11 × 17 in)", widthIn: 11, heightIn: 17 },
  { id: "legal", label: "Legal (8.5 × 14 in)", widthIn: 8.5, heightIn: 14 },
  { id: "statement", label: "Statement (5.5 × 8.5 in)", widthIn: 5.5, heightIn: 8.5 },
  { id: "executive", label: "Executive (7.25 × 10.5 in)", widthIn: 7.25, heightIn: 10.5 },
  { id: "folio", label: "Folio (8.5 × 13 in)", widthIn: 8.5, heightIn: 13 },
  { id: "a3", label: "A3 (11.69 × 16.54 in)", widthIn: 11.69, heightIn: 16.54 },
  { id: "a4", label: "A4 (8.27 × 11.69 in)", widthIn: 8.27, heightIn: 11.69 },
  { id: "a5", label: "A5 (5.83 × 8.27 in)", widthIn: 5.83, heightIn: 8.27 },
  { id: "b4", label: "B4 (9.84 × 13.9 in)", widthIn: 9.84, heightIn: 13.9 },
  { id: "b5", label: "B5 (6.93 × 9.84 in)", widthIn: 6.93, heightIn: 9.84 },
];

export const DEFAULT_PAGE_GEOMETRY = {
  size: "letter" as PaperSize,
  widthIn: 8.5,
  heightIn: 11,
  marginTopIn: 0.7,
  marginBottomIn: 0.5,
  marginLeftIn: 0.65,
  marginRightIn: 0.65,
};

export interface PageGeometry {
  size: PaperSize;
  widthIn: number;
  heightIn: number;
  marginTopIn: number;
  marginBottomIn: number;
  marginLeftIn: number;
  marginRightIn: number;
  contentWidthIn: number;
  contentHeightIn: number;
}

function finiteOr(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export function pageGeometry(layout: unknown): PageGeometry {
  const page = isTemplateLayoutV2(layout) ? layout.page : undefined;
  const requestedSize = page?.size ?? DEFAULT_PAGE_GEOMETRY.size;
  const paper = PAPER_OPTIONS.find((candidate) => candidate.id === requestedSize) ?? PAPER_OPTIONS[0];
  const marginTopIn = finiteOr(page?.marginTopIn, DEFAULT_PAGE_GEOMETRY.marginTopIn);
  const marginBottomIn = finiteOr(page?.marginBottomIn, DEFAULT_PAGE_GEOMETRY.marginBottomIn);
  const marginLeftIn = finiteOr(page?.marginLeftIn, DEFAULT_PAGE_GEOMETRY.marginLeftIn);
  const marginRightIn = finiteOr(page?.marginRightIn, DEFAULT_PAGE_GEOMETRY.marginRightIn);

  return {
    size: paper.id,
    widthIn: paper.widthIn,
    heightIn: paper.heightIn,
    marginTopIn,
    marginBottomIn,
    marginLeftIn,
    marginRightIn,
    contentWidthIn: Math.max(0.5, paper.widthIn - marginLeftIn - marginRightIn),
    contentHeightIn: Math.max(0.5, paper.heightIn - marginTopIn - marginBottomIn),
  };
}
