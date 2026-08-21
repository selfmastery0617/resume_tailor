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
import type {
  Education,
  Experience,
  ResumeData,
  ResumeStyle,
  SectionId,
} from "./types";

/** Per-template presentation knobs. */
export interface TemplateChrome {
  headingStyle?: "underline" | "rule" | "plain" | "boxed";
  headingTransform?: "uppercase" | "none";
  headingLetterSpacing?: string;
  headerAccentBar?: boolean;
  skillLayout?: "grouped" | "inline";
}

export { fontStack } from "./fonts";

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

/** Atomic heading used by layout-v2 semantic blocks. */
export function BlockTitleSection({
  title,
  style,
  chrome,
}: {
  title: string;
  style: ResumeStyle;
  chrome: TemplateChrome;
}) {
  const text = title.trim();
  if (!text) return null;
  return (
    <SectionHeading style={style} chrome={chrome}>
      {text}
    </SectionHeading>
  );
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

/** Mirrors ContactBlock's empty-content decision for visibility-aware layouts. */
export function hasContactContent(data: ResumeData, style: ResumeStyle): boolean {
  const { profile } = data;
  const address = joinParts(
    [
      style.showStreet ? profile.street : "",
      style.showCity ? profile.city : "",
      style.showState ? profile.state : "",
      style.showPostal ? profile.postal : "",
    ],
    ", ",
  );
  const values: Record<string, string> = {
    address,
    phone: style.showPhone ? profile.phone : "",
    email: style.showEmail ? profile.email : "",
    birthday: style.showBirthday ? profile.birthday : "",
  };
  const hasPersonalValue = style.personalOrder.some((field) => (values[field] ?? "").trim());
  return Boolean(hasPersonalValue || safeUrl(profile.linkedin) || safeUrl(profile.website));
}

export function ContactBlock({
  data,
  style,
  separator = "•",
}: {
  data: ResumeData;
  style: ResumeStyle;
  separator?: string;
}) {
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

  const separatorText = Array.from(separator.trim()).slice(0, 3).join("") || "•";
  const contactItems: ReactNode[] = [...parts];
  if (linkedin) {
    contactItems.push(
      <a href={linkedin} target="_blank" rel="noopener noreferrer" style={{ color: "inherit" }}>
        {displayUrl(profile.linkedin)}
      </a>,
    );
  }
  if (website) {
    contactItems.push(
      <a href={website} target="_blank" rel="noopener noreferrer" style={{ color: "inherit" }}>
        {displayUrl(profile.website)}
      </a>,
    );
  }

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
      {contactItems.map((contactItem, index) => (
        <span key={index}>
          {index > 0 && `  ${separatorText}  `}
          {contactItem}
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Atomic content pieces used by layout-v2. The legacy aggregate sections below
// remain intact so v1 layouts and built-in renderers keep their exact DOM.
// ---------------------------------------------------------------------------

export function SummaryContentBlock({ data, style }: { data: ResumeData; style: ResumeStyle }) {
  const text = (data.profile.summary ?? "").trim();
  // In layout-v2 the Summary block's presence owns visibility. The legacy
  // SummarySection below continues to honour style.showSummary for built-ins.
  if (!text) return null;
  return (
    <div style={bodyStyleFor(style)}>
      <RichText text={text} />
    </div>
  );
}

export function SkillsContentBlock({
  data,
  style,
  chrome,
  separator = "·",
}: {
  data: ResumeData;
  style: ResumeStyle;
  chrome: TemplateChrome;
  separator?: string;
}) {
  const groups = groupSkills(data.skills);
  if (!groups.length) return null;
  return (
    <div style={bodyStyleFor(style)}>
      {chrome.skillLayout === "inline" ? (
        <div>{groups.flatMap((group) => group.names).join(` ${separator} `)}</div>
      ) : (
        groups.map((group) => (
          <div key={group.category} style={{ marginBottom: `${style.bulletGapInches}in` }}>
            <strong>{group.category}:</strong> {group.names.join(", ")}
          </div>
        ))
      )}
    </div>
  );
}

interface ExperienceItemProps {
  entry: Experience;
  style: ResumeStyle;
}

export function ExperienceCompanyName({ entry, style }: ExperienceItemProps) {
  const text = entry.company.trim();
  if (!text) return null;
  return <strong style={bodyStyleFor(style)}>{text}</strong>;
}

export function ExperienceRoleTitle({ entry, style }: ExperienceItemProps) {
  const text = entry.title.trim();
  if (!text) return null;
  return <strong style={bodyStyleFor(style)}>{text}</strong>;
}

export function ExperiencePeriod({ entry, style }: ExperienceItemProps) {
  const text = dateRange(entry.startDate, entry.endDate, entry.current);
  if (!text) return null;
  return (
    <span style={{ ...bodyStyleFor(style), whiteSpace: "nowrap" }}>
      {text}
    </span>
  );
}

export function ExperienceLocation({ entry, style }: ExperienceItemProps) {
  const text = entry.location.trim();
  if (!text) return null;
  return <div style={{ ...bodyStyleFor(style), fontStyle: "italic" }}>{text}</div>;
}

export function ExperienceCompanySummary({ entry, style }: ExperienceItemProps) {
  const text = (entry.companySummary ?? "").trim();
  if (!text) return null;
  return (
    <div style={bodyStyleFor(style)}>
      <RichText text={text} />
    </div>
  );
}

export function experienceBullets(entry: Experience, style: ResumeStyle): string[] {
  const all = toBullets(entry.description);
  const limit = bulletLimit(style, entry.id);
  return limit === null ? all : all.slice(0, limit);
}

export function ExperienceBullets({ entry, style }: ExperienceItemProps) {
  const bullets = experienceBullets(entry, style);
  if (!bullets.length) return null;
  return (
    <ul
      style={{
        ...bodyStyleFor(style),
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
            paddingLeft: "0.16in",
            textIndent: "-0.16in",
          }}
        >
          <span
            aria-hidden="true"
            style={{ display: "inline-block", width: "0.16in", textIndent: 0 }}
          >
            {style.bulletChar}
          </span>
          <RichText text={bullet} />
        </li>
      ))}
    </ul>
  );
}

interface EducationItemProps {
  entry: Education;
  style: ResumeStyle;
}

export function EducationUniversityName({ entry, style }: EducationItemProps) {
  const text = entry.university.trim();
  if (!text) return null;
  return <strong style={bodyStyleFor(style)}>{text}</strong>;
}

export function EducationDegree({ entry, style }: EducationItemProps) {
  const text = entry.degree.trim();
  if (!text) return null;
  return <strong style={bodyStyleFor(style)}>{text}</strong>;
}

export function EducationDate({ entry, style }: EducationItemProps) {
  const text = yearRange(entry.startYear, entry.endYear);
  if (!text) return null;
  return (
    <span style={{ ...bodyStyleFor(style), whiteSpace: "nowrap" }}>
      {text}
    </span>
  );
}

export function EducationLocation({ entry, style }: EducationItemProps) {
  const text = entry.location.trim();
  if (!text) return null;
  return <div style={{ ...bodyStyleFor(style), fontStyle: "italic" }}>{text}</div>;
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
    <section
      style={pageBreakBefore(style, "summary")}
      data-break-before={style.forcePageBreakBeforeSections.includes("summary") ? "page" : undefined}
    >
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
    <section
      style={pageBreakBefore(style, "experience")}
      data-break-before={style.forcePageBreakBeforeSections.includes("experience") ? "page" : undefined}
    >
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
            data-break-before={breakBefore ? "page" : undefined}
            style={{
              ...bodyStyleFor(style),
              marginBottom: `${style.sectionBottomInches}in`,
              ...(breakBefore ? { breakBefore: "page" } : {}),
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
                      paddingLeft: "0.16in",
                      textIndent: "-0.16in",
                    }}
                  >
                    <span
                      aria-hidden="true"
                      style={{ display: "inline-block", width: "0.16in", textIndent: 0 }}
                    >
                      {style.bulletChar}
                    </span>
                    <RichText text={bullet} />
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
    <section
      style={pageBreakBefore(style, "skills")}
      data-break-before={style.forcePageBreakBeforeSections.includes("skills") ? "page" : undefined}
    >
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
    <section
      style={pageBreakBefore(style, "education")}
      data-break-before={style.forcePageBreakBeforeSections.includes("education") ? "page" : undefined}
    >
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
            data-break-before={breakBefore ? "page" : undefined}
            style={{
              ...bodyStyleFor(style),
              marginBottom: `${style.bulletGapInches}in`,
              ...(breakBefore ? { breakBefore: "page" } : {}),
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
