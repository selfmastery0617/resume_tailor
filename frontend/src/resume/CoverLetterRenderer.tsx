/** Renders a cover letter: a name + contact header, greeting, 3-4 body
 *  paragraphs, closing + candidate name. Standard business letter -- no
 *  date, no "Re:" line, no sender/recipient address blocks, per the fixed
 *  structure every cover letter template shares (only page size, font,
 *  spacing, and margins vary -- see CoverLetterStyle).
 */

import { safeUrl } from "./format";
import type { CoverLetterData, CoverLetterStyle } from "./coverLetterTypes";

export function CoverLetterRenderer({
  data,
  style,
}: {
  data: CoverLetterData;
  style: CoverLetterStyle;
}) {
  const paragraphStyle: React.CSSProperties = {
    margin: `0 0 ${style.paragraphSpacingIn}in 0`,
  };

  // Each shown only when the profile actually has it. LinkedIn links to the
  // real URL but displays as a plain label, same as the resume's own
  // contact line (blocks.tsx) -- not the raw URL text.
  const linkedin = safeUrl(data.linkedin);
  const contactParts: React.ReactNode[] = [data.phone, data.email].filter(Boolean);
  if (linkedin) {
    contactParts.push(
      <a key="linkedin" href={linkedin} target="_blank" rel="noopener noreferrer" style={{ color: "inherit" }}>
        LinkedIn
      </a>,
    );
  }
  const contactLine =
    contactParts.length > 0
      ? contactParts.reduce<React.ReactNode[]>((acc, part, index) => {
          if (index > 0) acc.push("  ·  ");
          acc.push(part);
          return acc;
        }, [])
      : null;

  return (
    <div
      className="cover-letter-document"
      style={{
        fontFamily: style.fontFamily === "Template default" ? undefined : style.fontFamily,
        fontSize: `${style.fontSize}pt`,
        lineHeight: style.lineHeight,
        color: "#222222",
      }}
    >
      {(data.candidateName || contactLine) && (
        <div style={{ margin: `0 0 ${style.paragraphSpacingIn * 2}in 0` }}>
          {data.candidateName && <p style={{ margin: 0, fontWeight: "bold" }}>{data.candidateName}</p>}
          {contactLine && <p style={{ margin: 0 }}>{contactLine}</p>}
        </div>
      )}
      <p style={paragraphStyle}>{data.greeting || "Dear Hiring Manager,"}</p>
      {data.paragraphs.map((paragraph, index) => (
        <p key={index} style={paragraphStyle}>
          {paragraph}
        </p>
      ))}
      <p style={{ margin: `${style.paragraphSpacingIn}in 0 0 0` }}>{data.closing || "Sincerely,"}</p>
      {data.candidateName && <p style={{ margin: 0 }}>{data.candidateName}</p>}
    </div>
  );
}
