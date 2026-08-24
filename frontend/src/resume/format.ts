/** Formatting helpers shared by every template renderer.
 *
 *  Resume content is always treated as text (RG-FR-003) — nothing here ever
 *  produces raw HTML, so a profile containing markup cannot inject into the
 *  rendered document or the generated PDF.
 */

import type { Experience, ResumeStyle, Skill } from "./types";

/** Split **bold** and [bold] spans into React-safe segments (RG-FR-004).
 *
 *  Two markers, one meaning: **double asterisks** is legacy markdown-style
 *  bold; [square brackets] is what ChatGPT's keyword-marking pass now writes
 *  (see experience_service._revise_with_chatgpt's step 6b) to bold a
 *  resume's main keywords. The double-asterisk alternative is tried first at
 *  each position so the two never interfere with each other.
 *
 *  Returns plain segments rather than HTML so there is no injection path.
 */
export function parseBold(text: string): { text: string; bold: boolean }[] {
  if (!text) return [];
  const segments: { text: string; bold: boolean }[] = [];
  const pattern = /\*\*(.+?)\*\*|\[(.+?)\]/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ text: text.slice(lastIndex, match.index), bold: false });
    }
    segments.push({ text: match[1] ?? match[2], bold: true });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    segments.push({ text: text.slice(lastIndex), bold: false });
  }
  return segments;
}

/** Newline-separated description -> individual bullets (RG-FR-005).
 *
 *  Blank lines are dropped so a stray newline never renders an empty bullet.
 */
export function toBullets(description: string): string[] {
  if (!description) return [];
  return description
    .split(/\r?\n/)
    // \s+ (not \s*) after the marker, so a stray leading "*" that isn't
    // actually a bullet marker (e.g. sitting right against the first word)
    // is left alone rather than stripped -- a real "- "/"* " marker always
    // has a space after it. Keyword markers are [brackets] (see parseBold
    // above), which this never touches at all since "[" was never one of
    // the marker characters here.
    .map((line) => line.replace(/^\s*[-•●◦*▪▸]\s+/, "").trim())
    .filter((line) => line.length > 0);
}

/** How many bullets to show for one experience, honouring per-entry limits. */
export function bulletLimit(style: ResumeStyle, experienceId: string): number | null {
  const perEntry = style.perExperienceBulletCount?.[experienceId];
  if (typeof perEntry === "number") return perEntry;
  return style.bulletCount ?? null;
}

const UNSAFE_PROTOCOL = /^\s*(javascript|data|vbscript):/i;

/** Make a user-supplied link safe to render (RG-FR-009).
 *
 *  Adds https:// when no protocol is given, and refuses unsafe schemes.
 */
export function safeUrl(value: string): string | null {
  const raw = (value ?? "").trim();
  if (!raw) return null;
  if (UNSAFE_PROTOCOL.test(raw)) return null;
  const withProtocol = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
  try {
    const url = new URL(withProtocol);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return url.toString();
  } catch {
    return null;
  }
}

/** Strip the protocol for display while linking to the full URL. */
export function displayUrl(value: string): string {
  return (value ?? "").trim().replace(/^https?:\/\//i, "").replace(/\/$/, "");
}

/** "Jan 2020 – Present" (RG-FR-007). Missing halves never leave a dangling dash. */
export function dateRange(start: string, end: string, current: boolean): string {
  const from = (start ?? "").trim();
  const to = current ? "Present" : (end ?? "").trim();
  if (from && to) return `${from} – ${to}`;
  return from || to;
}

export function yearRange(start: string, end: string): string {
  const from = (start ?? "").trim();
  const to = (end ?? "").trim();
  if (from && to) return `${from}–${to}`;
  return from || to;
}

/** Join non-empty parts so missing values never create stray separators. */
export function joinParts(parts: (string | null | undefined)[], separator: string): string {
  return parts.map((p) => (p ?? "").trim()).filter(Boolean).join(separator);
}

/** Group skills by category, falling back to "Other" (RG-FR-006). */
export function groupSkills(skills: Skill[]): { category: string; names: string[] }[] {
  const groups = new Map<string, string[]>();
  for (const skill of skills) {
    const name = (skill.name ?? "").trim();
    if (!name) continue;
    const category = (skill.category ?? "").trim() || "Other";
    const bucket = groups.get(category);
    if (bucket) bucket.push(name);
    else groups.set(category, [name]);
  }
  return [...groups.entries()].map(([category, names]) => ({ category, names }));
}

/** True when the entry has nothing worth rendering. */
export function isEmptyExperience(entry: Experience): boolean {
  return !joinParts(
    [entry.company, entry.title, entry.description, entry.startDate, entry.endDate],
    "",
  );
}
