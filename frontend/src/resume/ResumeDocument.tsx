/** Shared rendering engine for every template.
 *
 *  Each of the ten templates is its own registered renderer, but they all
 *  delegate here so that section ordering, visibility, empty-section removal,
 *  page-break handling and safe text rendering behave identically. A template
 *  differentiates itself through `chrome` (header/section presentation), not by
 *  reimplementing resume semantics.
 *
 *  Page geometry matches the PDF spec exactly (section 6.1) so preview and PDF
 *  stay in parity: US Letter, margins 0.7 / 0.5 / 0.65 / 0.65 in.
 */

import type { CSSProperties, ReactNode } from "react";
import {
  bulletLimit,
  dateRange,
  displayUrl,
  groupSkills,
  isEmptyExperience,
  joinParts,
  parseBold,
  safeUrl,
  toBullets,
  yearRange,
} from "./format";
import type { ResumeData, ResumeStyle, SectionId } from "./types";

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

/** Per-template presentation knobs. */
export interface TemplateChrome {
  /** Section heading treatment. */
  headingStyle?: "underline" | "rule" | "plain" | "boxed";
  headingTransform?: "uppercase" | "none";
  headingLetterSpacing?: string;
  /** Extra styling applied to the header block. */
  headerAccentBar?: boolean;
  /** Render skills as "Category: a, b" lines vs. a single inline list. */
  skillLayout?: "grouped" | "inline";
}

interface ResumeDocumentProps {
  data: ResumeData;
  style: ResumeStyle;
  chrome?: TemplateChrome;
}

function fontStack(fontFamily: string): string {
  switch (fontFamily) {
    case "Georgia":
      return 'Georgia, "Times New Roman", serif';
    case "Times New Roman":
      return '"Times New Roman", Times, serif';
    case "Helvetica":
      return 'Helvetica, Arial, sans-serif';
    case "System UI":
      return 'system-ui, "Segoe UI", Roboto, sans-serif';
    default:
      // "Template default"
      return 'Georgia, "Times New Roman", serif';
  }
}

/** Renders **bold** segments without any HTML injection. */
function RichText({ text }: { text: string }) {
  return (
    <>
      {parseBold(text).map((segment, index) =>
        segment.bold ? <strong key={index}>{segment.text}</strong> : <span key={index}>{segment.text}</span>,
      )}
    </>
  );
}

export function ResumeDocument({ data, style, chrome = {} }: ResumeDocumentProps) {
  const { profile, experience, education, skills } = data;
  const family = fontStack(style.fontFamily);

  const headingStyle: CSSProperties = {
    fontSize: `${style.sectionSize}pt`,
    color: style.sectionColor,
    fontWeight: 700,
    textTransform: chrome.headingTransform === "uppercase" ? "uppercase" : "none",
    letterSpacing: chrome.headingLetterSpacing ?? "normal",
    marginTop: `${style.sectionTopInches}in`,
    marginBottom: `${style.sectionBottomInches}in`,
    paddingBottom: chrome.headingStyle === "underline" ? "2px" : undefined,
    borderBottom:
      chrome.headingStyle === "underline" || chrome.headingStyle === "rule"
        ? `1px solid ${style.sectionColor}`
        : undefined,
    background: chrome.headingStyle === "boxed" ? `${style.sectionColor}14` : undefined,
    padding: chrome.headingStyle === "boxed" ? "2px 6px" : undefined,
  };

  const bodyStyle: CSSProperties = {
    fontSize: `${style.bodySize}pt`,
    lineHeight: style.bodyLineHeight,
    color: style.bodyColor,
  };

  // ---- contact line -----------------------------------------------------
  const addressText = joinParts(
    [
      style.showStreet ? profile.street : "",
      style.showCity ? profile.city : "",
      style.showState ? profile.state : "",
      style.showPostal ? profile.postal : "",
    ],
    ", ",
  );

  const contactValues: Record<string, string> = {
    address: addressText,
    phone: style.showPhone ? profile.phone : "",
    email: style.showEmail ? profile.email : "",
    birthday: style.showBirthday ? profile.birthday : "",
  };
  // Empty values are dropped before joining, so hidden fields never leave
  // dangling separators (RG-FR-008).
  const contactParts = style.personalOrder
    .map((field) => (contactValues[field] ?? "").trim())
    .filter(Boolean);

  const linkedin = safeUrl(profile.linkedin);
  const website = safeUrl(profile.website);

  // ---- sections ---------------------------------------------------------
  const visibleExperience = experience.filter((e) => !isEmptyExperience(e));
  const visibleEducation = education.filter((e) => (e.university || e.degree || "").trim());
  const skillGroups = groupSkills(skills);
  const summaryText = (profile.summary ?? "").trim();

  const pageBreakBefore = (id: SectionId): CSSProperties =>
    style.forcePageBreakBeforeSections.includes(id) ? { breakBefore: "page" } : {};

  function Section({ id, title, children }: { id: SectionId; title: string; children: ReactNode }) {
    return (
      <section style={pageBreakBefore(id)}>
        <div style={headingStyle}>{title}</div>
        {children}
      </section>
    );
  }

  const sections: Record<SectionId, ReactNode> = {
    // Summary can be hidden explicitly, and is auto-hidden when empty.
    summary:
      style.showSummary && summaryText ? (
        <Section id="summary" title="Summary">
          <div style={bodyStyle}>
            <RichText text={summaryText} />
          </div>
        </Section>
      ) : null,

    experience: visibleExperience.length ? (
      <Section id="experience" title="Experience">
        {visibleExperience.map((entry) => {
          const limit = bulletLimit(style, entry.id);
          const allBullets = toBullets(entry.description);
          const bullets = limit === null ? allBullets : allBullets.slice(0, limit);
          const dates = dateRange(entry.startDate, entry.endDate, entry.current);
          const breakBefore = style.forcePageBreakBeforeExperienceIds.includes(entry.id);

          return (
            <div
              key={entry.id}
              style={{
                ...bodyStyle,
                marginBottom: `${style.sectionBottomInches}in`,
                ...(breakBefore ? { breakBefore: "page" } : {}),
                // Keep a role heading with at least some of its content.
                breakInside: "avoid",
              }}
            >
              {/* wrap + minWidth:0 so long titles reflow instead of pushing
                  the nowrap date range out of the page (US-TM-02). */}
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: "0.2in",
                  flexWrap: "wrap",
                  minWidth: 0,
                }}
              >
                <strong>{joinParts([entry.title, entry.company], " · ")}</strong>
                {dates && <span style={{ whiteSpace: "nowrap" }}>{dates}</span>}
              </div>
              {entry.location && <div style={{ fontStyle: "italic" }}>{entry.location}</div>}
              {bullets.length > 0 && (
                <ul
                  style={{
                    margin: `${style.bulletGapInches}in 0 0 0`,
                    paddingLeft: `${style.bulletIndentInches}in`,
                    listStyle: "none",
                  }}
                >
                  {bullets.map((bullet, index) => (
                    <li
                      key={index}
                      style={{ marginBottom: `${style.bulletGapInches}in`, display: "flex", gap: "0.06in" }}
                    >
                      <span aria-hidden="true">{style.bulletChar}</span>
                      <span>
                        <RichText text={bullet} />
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </Section>
    ) : null,

    skills: skillGroups.length ? (
      <Section id="skills" title="Skills">
        <div style={bodyStyle}>
          {chrome.skillLayout === "inline" ? (
            <div>{skillGroups.flatMap((g) => g.names).join(" · ")}</div>
          ) : (
            skillGroups.map((group) => (
              <div key={group.category} style={{ marginBottom: `${style.bulletGapInches}in` }}>
                <strong>{group.category}:</strong> {group.names.join(", ")}
              </div>
            ))
          )}
        </div>
      </Section>
    ) : null,

    education: visibleEducation.length ? (
      <Section id="education" title="Education">
        {visibleEducation.map((entry) => {
          const years = yearRange(entry.startYear, entry.endYear);
          const breakBefore = style.forcePageBreakBeforeEducationIds.includes(entry.id);
          return (
            <div
              key={entry.id}
              style={{
                ...bodyStyle,
                marginBottom: `${style.bulletGapInches}in`,
                ...(breakBefore ? { breakBefore: "page" } : {}),
                breakInside: "avoid",
              }}
            >
              {/* wrap + minWidth:0 so long titles reflow instead of pushing
                  the nowrap date range out of the page (US-TM-02). */}
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: "0.2in",
                  flexWrap: "wrap",
                  minWidth: 0,
                }}
              >
                <strong>{joinParts([entry.degree, entry.university], ", ")}</strong>
                {years && <span style={{ whiteSpace: "nowrap" }}>{years}</span>}
              </div>
              {entry.location && <div style={{ fontStyle: "italic" }}>{entry.location}</div>}
            </div>
          );
        })}
      </Section>
    ) : null,
  };

  return (
    /* Content only — no page geometry.
     *
     * Page size and margins are supplied by whoever renders this: the preview
     * wraps it in page frames, and the PDF lets Playwright apply the margin
     * box. Previously the document carried its own padding while the print
     * route stripped it, so preview and PDF applied margins by two different
     * mechanisms and drifted apart (RG-FR-015). */
    <div
      className="resume-document"
      style={{
        fontFamily: family,
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
        {profile.fullName && (
          <div
            style={{
              fontSize: `${style.nameSize}pt`,
              color: style.nameColor,
              fontWeight: style.nameBold ? 700 : 400,
              fontStyle: style.nameItalic ? "italic" : "normal",
              textAlign: style.nameTextAlign,
              lineHeight: 1.15,
            }}
          >
            {profile.fullName}
          </div>
        )}
        {profile.professionalTitle && (
          <div
            style={{
              fontSize: `${style.titleSize}pt`,
              color: style.titleColor,
              fontWeight: style.titleBold ? 700 : 400,
              fontStyle: style.titleItalic ? "italic" : "normal",
              textAlign: style.titleTextAlign,
            }}
          >
            {profile.professionalTitle}
          </div>
        )}
        {(contactParts.length > 0 || linkedin || website) && (
          <div
            style={{
              fontSize: `${style.contactSize}pt`,
              color: style.contactColor,
              fontWeight: style.contactBold ? 700 : 400,
              fontStyle: style.contactItalic ? "italic" : "normal",
              textAlign: style.contactTextAlign,
              marginTop: "0.04in",
            }}
          >
            {contactParts.join("  •  ")}
            {(linkedin || website) && contactParts.length > 0 && "  •  "}
            {linkedin && (
              <a href={linkedin} target="_blank" rel="noopener noreferrer" style={{ color: "inherit" }}>
                {displayUrl(profile.linkedin)}
              </a>
            )}
            {linkedin && website && "  •  "}
            {website && (
              <a href={website} target="_blank" rel="noopener noreferrer" style={{ color: "inherit" }}>
                {displayUrl(profile.website)}
              </a>
            )}
          </div>
        )}
      </header>

      {/* Order comes entirely from style; nulls (empty sections) drop out. */}
      {style.sectionOrder.map((id) => (
        <div key={id}>{sections[id]}</div>
      ))}
    </div>
  );
}
