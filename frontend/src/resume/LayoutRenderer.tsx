/** Renderer for user-built templates (template-builder step 2).
 *
 *  Walks regions -> columns -> blocks from a layout document and renders each
 *  block with the shared components in blocks.tsx, so a user template gets the
 *  same bullet parsing, empty-section removal, safe links and page-break rules
 *  as the built-in ten.
 *
 *  Registered as rendererKey "layout-v1", so the preview and the PDF print
 *  route pick it up through the existing getRenderer() lookup with no changes.
 */

import type { CSSProperties } from "react";
import {
  ContactBlock,
  CustomTextBlock,
  DividerBlock,
  EducationSection,
  ExperienceSection,
  NameBlock,
  SkillsSection,
  SpacerBlock,
  SummarySection,
  TitleBlock,
  fontStack,
  type TemplateChrome,
} from "./blocks";
import type { ResumeData, ResumeStyle } from "./types";

// Mirrors backend app/schemas/layout.py. Kept structural rather than importing
// a generated type so the two can be validated independently.
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

export interface LayoutColumn {
  id: string;
  widthPct: number;
}

export interface LayoutRegion {
  id: string;
  columns: LayoutColumn[];
  keepTogether?: boolean;
}

export interface LayoutBlock {
  id: string;
  type: LayoutBlockType;
  columnId: string;
  order: number;
  style?: Partial<ResumeStyle>;
  props?: Record<string, unknown>;
}

export interface TemplateLayout {
  version: number;
  page: { regions: LayoutRegion[] };
  blocks: LayoutBlock[];
}

interface LayoutRendererProps {
  data: ResumeData;
  style: ResumeStyle;
  layout: TemplateLayout;
  chrome?: TemplateChrome;
}

function renderBlock(
  block: LayoutBlock,
  data: ResumeData,
  baseStyle: ResumeStyle,
  chrome: TemplateChrome,
) {
  // Per-block overrides sit on top of the effective document style, so a block
  // can restyle itself without affecting its neighbours.
  const style: ResumeStyle = block.style
    ? ({ ...baseStyle, ...block.style } as ResumeStyle)
    : baseStyle;

  switch (block.type) {
    case "name":
      return <NameBlock data={data} style={style} />;
    case "title":
      return <TitleBlock data={data} style={style} />;
    case "contact":
      return <ContactBlock data={data} style={style} />;
    case "summary":
      return <SummarySection data={data} style={style} chrome={chrome} />;
    case "experience":
      return <ExperienceSection data={data} style={style} chrome={chrome} />;
    case "skills":
      return <SkillsSection data={data} style={style} chrome={chrome} />;
    case "education":
      return <EducationSection data={data} style={style} chrome={chrome} />;
    case "customText":
      return (
        <CustomTextBlock
          heading={String(block.props?.heading ?? "")}
          body={String(block.props?.body ?? "")}
          style={style}
          chrome={chrome}
        />
      );
    case "divider":
      return <DividerBlock style={style} />;
    case "spacer":
      return <SpacerBlock heightInches={Number(block.props?.heightInches ?? 0.1)} />;
    default:
      // Unknown types are skipped rather than thrown: a template saved by a
      // newer build must not break rendering of an older one.
      return null;
  }
}

export function LayoutRenderer({ data, style, layout, chrome = {} }: LayoutRendererProps) {
  const blocksByColumn = new Map<string, LayoutBlock[]>();
  for (const block of layout.blocks) {
    const list = blocksByColumn.get(block.columnId);
    if (list) list.push(block);
    else blocksByColumn.set(block.columnId, [block]);
  }
  for (const list of blocksByColumn.values()) list.sort((a, b) => a.order - b.order);

  return (
    <div
      className="resume-document"
      style={{
        fontFamily: fontStack(style.fontFamily),
        width: "100%",
        boxSizing: "border-box",
        background: "#ffffff",
        color: style.bodyColor,
      }}
    >
      {layout.page.regions.map((region) => {
        const multiColumn = region.columns.length > 1;
        // v1: multi-column regions do not split across pages. Independent
        // column flow across a page boundary is unreliable in CSS, so the
        // region is kept whole instead of breaking mid-column.
        const regionStyle: CSSProperties = {
          display: multiColumn ? "flex" : "block",
          gap: multiColumn ? "0.25in" : undefined,
          alignItems: "flex-start",
          breakInside: multiColumn || region.keepTogether ? "avoid" : "auto",
        };

        return (
          <div key={region.id} style={regionStyle}>
            {region.columns.map((column) => {
              const blocks = blocksByColumn.get(column.id) ?? [];
              if (blocks.length === 0) return null;
              return (
                <div
                  key={column.id}
                  style={{
                    // flexBasis carries the width in multi-column regions;
                    // minWidth:0 lets long content wrap instead of overflowing.
                    flexBasis: multiColumn ? `${column.widthPct}%` : undefined,
                    flexGrow: 0,
                    flexShrink: 1,
                    minWidth: 0,
                    width: multiColumn ? undefined : "100%",
                  }}
                >
                  {blocks.map((block) => (
                    <div key={block.id}>{renderBlock(block, data, style, chrome)}</div>
                  ))}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
