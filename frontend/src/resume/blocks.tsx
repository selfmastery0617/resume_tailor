/** Reusable resume building blocks.
 *
 *  Extracted so ResumeDocument (the ten built-in templates) and LayoutRenderer
 *  (user-built templates) render identical content. Bullet parsing, date
 *  handling, empty-section removal, safe links and page-break rules live here
 *  once — a layout template cannot drift from a built-in one.
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

/** Per-template presentation knobs. */
export interface TemplateChrome {
  headingStyle?: "underline" | "rule" | "plain" | "boxed";
  headingTransform?: "uppercase" | "none";
  headingLetterSpacing?: string;
  headerAccentBar?: boolean;
  skillLayout?: "grouped" | "inline";
}

export function fontStack(fontFamily: string): string {
  switch (fontFamily) {
    case "Georgia":
      return 'Georgia, "Times New Roman", serif';
    case "Times New Roman":
      return '"Times New Roman", Times, serif';
    case "Helvetica":
      return "Helvetica, Arial, sans-serif";
    case "System UI":
      return 'system-ui, "Segoe UI", Roboto, sans-serif';
    default:
      return 'Georgia, "Times New Roman", serif';
  }
}

/** Renders **bold** segments without any HTML injection (RG-FR-003/004). */
export function RichText({ text }: { text: string }) {
  return (
    <>
      {parseBold(text).map((segment, index) =>
        segment.bold ? (
          <strong key={index}>{segment.text}</strong>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </>
  );
}

export function headingStyleFor(style: ResumeStyle, chrome: TemplateChrome): CSSProperties {
  return {
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
}

export function bodyStyleFor(style: ResumeStyle): CSSProperties {
  return {
    fontSize: `${style.bodySize}pt`,
    lineHeight: style.bodyLineHeight,
    color: style.bodyColor,
  };
}

export function pageBreakBefore(style: ResumeStyle, id: SectionId): CSSProperties {
  return style.forcePageBreakBeforeSections.includes(id) ? { breakBefore: "page" } : {};
}

export function SectionHeading({
  style,
  chrome,
  children,
}: {
  style: ResumeStyle;
  chrome: TemplateChrome;
  children: ReactNode;
}) {
  return <div style={headingStyleFor(style, chrome)}>{children}</div>;
}

// ---------------------------------------------------------------------------
// Header pieces — individually placeable by the layout builder.
// ---------------------------------------------------------------------------

export function NameBlock({ data, style }: { data: ResumeData; style: ResumeStyle }) {
  const name = data.profile.fullName?.trim();
  if (!name) return null;
  return (
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
      {name}
    </div>
  );
}

export function TitleBlock({ data, style }: { data: ResumeData; style: ResumeStyle }) {
  const title = data.profile.professionalTitle?.trim();
  if (!title) return null;
  return (
    <div
      style={{
        fontSize: `${style.titleSize}pt`,
        color: style.titleColor,
        fontWeight: style.titleBold ? 700 : 400,
        fontStyle: style.titleItalic ? "italic" : "normal",
        textAlign: style.titleTextAlign,
      }}
    >
      {title}
    </div>
  );
}

export function ContactBlock({ data, style }: { data: ResumeData; style: ResumeStyle }) {
  const { profile } = data;

  const addressText = joinParts(
    [
      style.showStreet ? profile.street : "",
      style.showCity ? profile.city : "",
      style.showState ? profile.state : "",
      style.showPostal ? profile.postal : "",
    ],
    ", ",
  );

  const values: Record<string, string> = {
    address: addressText,
    phone: style.showPhone ? profile.phone : "",
    email: style.showEmail ? profile.email : "",
    birthday: style.showBirthday ? profile.birthday : "",
  };
  // Empty values are dropped before joining, so hidden fields never leave
  // dangling separators (RG-FR-008).
  const parts = style.personalOrder.map((f) => (values[f] ?? "").trim()).filter(Boolean);

  const linkedin = safeUrl(profile.linkedin);
  const website = safeUrl(profile.website);
  if (parts.length === 0 && !linkedin && !website) return null;

  return (
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
      {parts.join("  •  ")}
      {(linkedin || website) && parts.length > 0 && "  •  "}
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
  );
}

// ---------------------------------------------------------------------------
// Body sections. Each returns null when empty (RG-FR-008).
// ---------------------------------------------------------------------------

interface SectionProps {
  data: ResumeData;
  style: ResumeStyle;
  chrome: TemplateChrome;
  /** Omit the heading — useful for layouts that supply their own. */
  showHeading?: boolean;
}

export function SummarySection({ data, style, chrome, showHeading = true }: SectionProps) {
  const text = (data.profile.summary ?? "").trim();
  if (!style.showSummary || !text) return null;
  return (
    <section style={pageBreakBefore(style, "summary")}>
      {showHeading && (
        <SectionHeading style={style} chrome={chrome}>
          Summary
        </SectionHeading>
      )}
      <div style={bodyStyleFor(style)}>
        <RichText text={text} />
      </div>
    </section>
  );
}

export function ExperienceSection({ data, style, chrome, showHeading = true }: SectionProps) {
  const entries = data.experience.filter((e) => !isEmptyExperience(e));
  if (!entries.length) return null;

  return (
    <section style={pageBreakBefore(style, "experience")}>
      {showHeading && (
        <SectionHeading style={style} chrome={chrome}>
          Experience
        </SectionHeading>
      )}
      {entries.map((entry) => {
        const limit = bulletLimit(style, entry.id);
        const all = toBullets(entry.description);
        const bullets = limit === null ? all : all.slice(0, limit);
        const dates = dateRange(entry.startDate, entry.endDate, entry.current);
        const breakBefore = style.forcePageBreakBeforeExperienceIds.includes(entry.id);

        return (
          <div
            key={entry.id}
            style={{
              ...bodyStyleFor(style),
              marginBottom: `${style.sectionBottomInches}in`,
              ...(breakBefore ? { breakBefore: "page" } : {}),
              breakInside: "avoid",
            }}
          >
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
                    style={{
                      marginBottom: `${style.bulletGapInches}in`,
                      display: "flex",
                      gap: "0.06in",
                    }}
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
    </section>
  );
}

export function SkillsSection({ data, style, chrome, showHeading = true }: SectionProps) {
  const groups = groupSkills(data.skills);
  if (!groups.length) return null;

  return (
    <section style={pageBreakBefore(style, "skills")}>
      {showHeading && (
        <SectionHeading style={style} chrome={chrome}>
          Skills
        </SectionHeading>
      )}
      <div style={bodyStyleFor(style)}>
        {chrome.skillLayout === "inline" ? (
          <div>{groups.flatMap((g) => g.names).join(" · ")}</div>
        ) : (
          groups.map((group) => (
            <div key={group.category} style={{ marginBottom: `${style.bulletGapInches}in` }}>
              <strong>{group.category}:</strong> {group.names.join(", ")}
            </div>
          ))
        )}
      </div>
    </section>
  );
}

export function EducationSection({ data, style, chrome, showHeading = true }: SectionProps) {
  const entries = data.education.filter((e) => (e.university || e.degree || "").trim());
  if (!entries.length) return null;

  return (
    <section style={pageBreakBefore(style, "education")}>
      {showHeading && (
        <SectionHeading style={style} chrome={chrome}>
          Education
        </SectionHeading>
      )}
      {entries.map((entry) => {
        const years = yearRange(entry.startYear, entry.endYear);
        const breakBefore = style.forcePageBreakBeforeEducationIds.includes(entry.id);
        return (
          <div
            key={entry.id}
            style={{
              ...bodyStyleFor(style),
              marginBottom: `${style.bulletGapInches}in`,
              ...(breakBefore ? { breakBefore: "page" } : {}),
              breakInside: "avoid",
            }}
          >
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
    </section>
  );
}

/** Template-authored text (not profile data). Rendered as text, never HTML. */
export function CustomTextBlock({
  heading,
  body,
  style,
  chrome,
}: {
  heading: string;
  body: string;
  style: ResumeStyle;
  chrome: TemplateChrome;
}) {
  if (!heading.trim() && !body.trim()) return null;
  return (
    <section>
      {heading.trim() && (
        <SectionHeading style={style} chrome={chrome}>
          {heading}
        </SectionHeading>
      )}
      {body.trim() && (
        <div style={{ ...bodyStyleFor(style), whiteSpace: "pre-wrap" }}>
          <RichText text={body} />
        </div>
      )}
    </section>
  );
}

export function DividerBlock({ style }: { style: ResumeStyle }) {
  return (
    <hr
      style={{
        border: "none",
        borderTop: `1px solid ${style.sectionColor}`,
        margin: `${style.sectionTopInches}in 0`,
      }}
    />
  );
}

export function SpacerBlock({ heightInches }: { heightInches: number }) {
  return <div style={{ height: `${heightInches}in` }} aria-hidden="true" />;
}
