/** Shared rendering engine for the ten built-in templates.
 *
 *  Each built-in is its own registered renderer, but they all delegate here so
 *  section ordering, visibility, empty-section removal, page-break handling and
 *  safe text rendering behave identically. A template differentiates itself
 *  through `chrome` (header/section presentation), not by reimplementing resume
 *  semantics.
 *
 *  The individual sections live in blocks.tsx and are shared with
 *  LayoutRenderer, so user-built templates render the same content.
 *
 *  Content only — no page geometry. Page size and margins are supplied by
 *  whoever renders this: the preview wraps it in page frames, and the PDF lets
 *  Playwright apply the margin box. Previously the document carried its own
 *  padding while the print route stripped it, so preview and PDF applied
 *  margins by two different mechanisms and drifted apart (RG-FR-015).
 */

import {
  ContactBlock,
  EducationSection,
  ExperienceSection,
  NameBlock,
  SkillsSection,
  SummarySection,
  TitleBlock,
  fontStack,
  type TemplateChrome,
} from "./blocks";
import type { ResumeData, ResumeStyle, SectionId } from "./types";

export type { TemplateChrome };

export const PAGE = {
  widthIn: 8.5,
  heightIn: 11,
  marginTopIn: 0.7,
  marginBottomIn: 0.5,
  marginLeftIn: 0.65,
  marginRightIn: 0.65,
};

export const CONTENT_WIDTH_IN = PAGE.widthIn - PAGE.marginLeftIn - PAGE.marginRightIn;
export const CONTENT_HEIGHT_IN = PAGE.heightIn - PAGE.marginTopIn - PAGE.marginBottomIn;

interface ResumeDocumentProps {
  data: ResumeData;
  style: ResumeStyle;
  chrome?: TemplateChrome;
}

export function ResumeDocument({ data, style, chrome = {} }: ResumeDocumentProps) {
  const sections: Record<SectionId, React.ReactNode> = {
    summary: <SummarySection data={data} style={style} chrome={chrome} />,
    experience: <ExperienceSection data={data} style={style} chrome={chrome} />,
    skills: <SkillsSection data={data} style={style} chrome={chrome} />,
    education: <EducationSection data={data} style={style} chrome={chrome} />,
  };

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
      <header
        style={{
          borderBottom: style.showHeaderDivider ? `1px solid ${style.sectionColor}` : undefined,
          borderLeft: chrome.headerAccentBar ? `3px solid ${style.sectionColor}` : undefined,
          paddingLeft: chrome.headerAccentBar ? "0.12in" : undefined,
          paddingBottom: style.showHeaderDivider ? "0.08in" : undefined,
          marginBottom: `${style.sectionTopInches}in`,
        }}
      >
        <NameBlock data={data} style={style} />
        <TitleBlock data={data} style={style} />
        <ContactBlock data={data} style={style} />
      </header>

      {/* Order comes entirely from style; empty sections render null. */}
      {style.sectionOrder.map((id) => (
        <div key={id}>{sections[id]}</div>
      ))}
    </div>
  );
}
