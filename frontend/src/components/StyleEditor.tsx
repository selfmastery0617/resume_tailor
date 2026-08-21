/** Live style editor (US-TM-03, US-TM-04).
 *
 *  Edits go into a local draft and update the preview with no server round
 *  trip; nothing is persisted until Save (TM-FR-013). Clearing a field removes
 *  the override rather than freezing today's default into the profile (§4.5),
 *  so future template-default changes still reach this profile.
 */

import type { ReactNode } from "react";
import { APPROVED_FONTS } from "../resume/fonts";
import type { PersonalField, ResumeStyle, SectionId, TextAlign } from "../resume/types";

export const BULLET_CHARS = ["●", "•", "◦", "-", "*", "▪", "▸"] as const;

const SECTION_LABELS: Record<SectionId, string> = {
  summary: "Summary",
  experience: "Experience",
  skills: "Skills",
  education: "Education",
};

const PERSONAL_LABELS: Record<PersonalField, string> = {
  address: "Address",
  phone: "Phone",
  email: "Email",
  birthday: "Birthday",
};

/** Numeric limits mirror the backend validators exactly, so the UI cannot
 *  offer a value the server would reject. */
export const FIELD_LIMITS: Record<string, { min: number; max: number; step: number }> = {
  nameSize: { min: 8, max: 32, step: 0.5 },
  titleSize: { min: 8, max: 32, step: 0.5 },
  contactSize: { min: 8, max: 32, step: 0.5 },
  sectionSize: { min: 8, max: 32, step: 0.5 },
  bodySize: { min: 8, max: 32, step: 0.5 },
  bodyLineHeight: { min: 1, max: 2, step: 0.05 },
  sectionTopInches: { min: 0, max: 1, step: 0.01 },
  sectionBottomInches: { min: 0, max: 1, step: 0.01 },
  bulletIndentInches: { min: 0, max: 1, step: 0.01 },
  bulletGapInches: { min: 0, max: 0.5, step: 0.01 },
  bulletCount: { min: 0, max: 20, step: 1 },
};

/** Field membership per group — drives both rendering and per-section reset. */
export const STYLE_GROUPS: { id: string; label: string; fields: (keyof ResumeStyle)[] }[] = [
  {
    id: "typography",
    label: "Typography",
    fields: [
      "fontFamily", "nameSize", "titleSize", "contactSize", "sectionSize",
      "bodySize", "bodyLineHeight", "nameBold", "nameItalic", "titleBold",
      "titleItalic", "contactBold", "contactItalic",
    ],
  },
  {
    id: "colors",
    label: "Colors",
    fields: ["nameColor", "titleColor", "contactColor", "sectionColor", "bodyColor"],
  },
  {
    id: "alignment",
    label: "Alignment",
    fields: ["nameTextAlign", "titleTextAlign", "contactTextAlign"],
  },
  {
    id: "sections",
    label: "Sections",
    fields: ["sectionOrder", "showSummary", "showHeaderDivider"],
  },
  {
    id: "contact",
    label: "Contact details",
    fields: [
      "personalOrder", "showEmail", "showPhone", "showStreet",
      "showCity", "showState", "showPostal", "showBirthday",
    ],
  },
  {
    id: "spacing",
    label: "Spacing",
    fields: ["sectionTopInches", "sectionBottomInches", "bulletIndentInches", "bulletGapInches"],
  },
  { id: "bullets", label: "Bullets", fields: ["bulletChar", "bulletCount"] },
];

interface StyleEditorProps {
  /** Fully merged style currently being previewed. */
  effective: ResumeStyle;
  /** Only the profile's own overrides — used to show what's customised. */
  overrides: Partial<ResumeStyle>;
  /** Fields the selected template actually honours (RG-FR-011). */
  supportedFields: string[];
  onChange: (field: keyof ResumeStyle, value: unknown) => void;
  onResetField: (field: keyof ResumeStyle) => void;
  onResetGroup: (fields: (keyof ResumeStyle)[]) => void;
}

export function StyleEditor({
  effective,
  overrides,
  supportedFields,
  onChange,
  onResetField,
  onResetGroup,
}: StyleEditorProps) {
  const supports = (field: keyof ResumeStyle) =>
    supportedFields.length === 0 || supportedFields.includes(field as string);

  const isOverridden = (field: keyof ResumeStyle) =>
    Object.prototype.hasOwnProperty.call(overrides, field);

  function Row({ field, label, children }: { field: keyof ResumeStyle; label: string; children: ReactNode }) {
    const disabled = !supports(field);
    return (
      <div className={`style-row${disabled ? " style-row--disabled" : ""}`}>
        <label htmlFor={`style-${field}`} className="style-label">
          {label}
          {isOverridden(field) && (
            <span className="override-dot" title="Customised for this profile">
              ●
            </span>
          )}
        </label>
        <div className="style-control">{children}</div>
        <button
          type="button"
          className="style-reset"
          onClick={() => onResetField(field)}
          disabled={!isOverridden(field)}
          title="Reset this field to the template default"
          aria-label={`Reset ${label}`}
        >
          ↺
        </button>
      </div>
    );
  }

  const numberInput = (field: keyof ResumeStyle) => {
    const limits = FIELD_LIMITS[field as string];
    const value = effective[field] as number | null;
    return (
      <input
        id={`style-${field}`}
        type="number"
        disabled={!supports(field)}
        min={limits?.min}
        max={limits?.max}
        step={limits?.step}
        value={value ?? ""}
        onChange={(event) => {
          const raw = event.target.value;
          if (raw === "") return onResetField(field);
          const next = Number(raw);
          if (Number.isNaN(next)) return;
          // Clamp so an out-of-range value can never reach Save.
          if (limits) onChange(field, Math.min(limits.max, Math.max(limits.min, next)));
          else onChange(field, next);
        }}
      />
    );
  };

  const checkbox = (field: keyof ResumeStyle) => (
    <input
      id={`style-${field}`}
      type="checkbox"
      disabled={!supports(field)}
      checked={Boolean(effective[field])}
      onChange={(event) => onChange(field, event.target.checked)}
    />
  );

  const color = (field: keyof ResumeStyle) => (
    <input
      id={`style-${field}`}
      type="color"
      disabled={!supports(field)}
      value={String(effective[field] ?? "#000000")}
      onChange={(event) => onChange(field, event.target.value)}
    />
  );

  const align = (field: keyof ResumeStyle) => (
    <select
      id={`style-${field}`}
      disabled={!supports(field)}
      value={String(effective[field])}
      onChange={(event) => onChange(field, event.target.value as TextAlign)}
    >
      <option value="left">Left</option>
      <option value="center">Center</option>
      <option value="right">Right</option>
    </select>
  );

  /** Move an item within an ordered list (keyboard-accessible, no drag-drop). */
  const move = <T,>(list: T[], index: number, delta: number): T[] => {
    const next = [...list];
    const target = index + delta;
    if (target < 0 || target >= next.length) return next;
    [next[index], next[target]] = [next[target], next[index]];
    return next;
  };

  return (
    <div className="style-editor">
      {STYLE_GROUPS.map((group) => (
        <details key={group.id} className="style-group" open={group.id === "typography"}>
          <summary>
            {group.label}
            <button
              type="button"
              className="group-reset"
              onClick={(event) => {
                event.preventDefault();
                onResetGroup(group.fields);
              }}
              title={`Reset all ${group.label} settings`}
            >
              Reset section
            </button>
          </summary>

          {group.id === "typography" && (
            <>
              <Row field="fontFamily" label="Font">
                <select
                  id="style-fontFamily"
                  disabled={!supports("fontFamily")}
                  value={effective.fontFamily}
                  onChange={(event) => onChange("fontFamily", event.target.value)}
                >
                  {APPROVED_FONTS.map((font) => (
                    <option key={font} value={font}>
                      {font}
                    </option>
                  ))}
                </select>
              </Row>
              <Row field="nameSize" label="Name size (pt)">{numberInput("nameSize")}</Row>
              <Row field="titleSize" label="Title size (pt)">{numberInput("titleSize")}</Row>
              <Row field="contactSize" label="Contact size (pt)">{numberInput("contactSize")}</Row>
              <Row field="sectionSize" label="Heading size (pt)">{numberInput("sectionSize")}</Row>
              <Row field="bodySize" label="Body size (pt)">{numberInput("bodySize")}</Row>
              <Row field="bodyLineHeight" label="Line height">{numberInput("bodyLineHeight")}</Row>
              <Row field="nameBold" label="Name bold">{checkbox("nameBold")}</Row>
              <Row field="nameItalic" label="Name italic">{checkbox("nameItalic")}</Row>
              <Row field="titleBold" label="Title bold">{checkbox("titleBold")}</Row>
              <Row field="titleItalic" label="Title italic">{checkbox("titleItalic")}</Row>
              <Row field="contactBold" label="Contact bold">{checkbox("contactBold")}</Row>
              <Row field="contactItalic" label="Contact italic">{checkbox("contactItalic")}</Row>
            </>
          )}

          {group.id === "colors" && (
            <>
              <Row field="nameColor" label="Name">{color("nameColor")}</Row>
              <Row field="titleColor" label="Title">{color("titleColor")}</Row>
              <Row field="contactColor" label="Contact">{color("contactColor")}</Row>
              <Row field="sectionColor" label="Headings">{color("sectionColor")}</Row>
              <Row field="bodyColor" label="Body">{color("bodyColor")}</Row>
            </>
          )}

          {group.id === "alignment" && (
            <>
              <Row field="nameTextAlign" label="Name">{align("nameTextAlign")}</Row>
              <Row field="titleTextAlign" label="Title">{align("titleTextAlign")}</Row>
              <Row field="contactTextAlign" label="Contact">{align("contactTextAlign")}</Row>
            </>
          )}

          {group.id === "sections" && (
            <>
              <Row field="sectionOrder" label="Order">
                <ul className="order-list">
                  {effective.sectionOrder.map((id, index) => (
                    <li key={id}>
                      <span>{SECTION_LABELS[id]}</span>
                      <button
                        type="button"
                        aria-label={`Move ${SECTION_LABELS[id]} up`}
                        disabled={index === 0}
                        onClick={() => onChange("sectionOrder", move(effective.sectionOrder, index, -1))}
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        aria-label={`Move ${SECTION_LABELS[id]} down`}
                        disabled={index === effective.sectionOrder.length - 1}
                        onClick={() => onChange("sectionOrder", move(effective.sectionOrder, index, 1))}
                      >
                        ↓
                      </button>
                    </li>
                  ))}
                </ul>
              </Row>
              <Row field="showSummary" label="Show summary">{checkbox("showSummary")}</Row>
              <Row field="showHeaderDivider" label="Header divider">{checkbox("showHeaderDivider")}</Row>
            </>
          )}

          {group.id === "contact" && (
            <>
              <Row field="personalOrder" label="Order">
                <ul className="order-list">
                  {effective.personalOrder.map((id, index) => (
                    <li key={id}>
                      <span>{PERSONAL_LABELS[id]}</span>
                      <button
                        type="button"
                        aria-label={`Move ${PERSONAL_LABELS[id]} up`}
                        disabled={index === 0}
                        onClick={() => onChange("personalOrder", move(effective.personalOrder, index, -1))}
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        aria-label={`Move ${PERSONAL_LABELS[id]} down`}
                        disabled={index === effective.personalOrder.length - 1}
                        onClick={() => onChange("personalOrder", move(effective.personalOrder, index, 1))}
                      >
                        ↓
                      </button>
                    </li>
                  ))}
                </ul>
              </Row>
              <Row field="showEmail" label="Email">{checkbox("showEmail")}</Row>
              <Row field="showPhone" label="Phone">{checkbox("showPhone")}</Row>
              <Row field="showStreet" label="Street">{checkbox("showStreet")}</Row>
              <Row field="showCity" label="City">{checkbox("showCity")}</Row>
              <Row field="showState" label="State">{checkbox("showState")}</Row>
              <Row field="showPostal" label="Postal code">{checkbox("showPostal")}</Row>
              <Row field="showBirthday" label="Birthday">{checkbox("showBirthday")}</Row>
            </>
          )}

          {group.id === "spacing" && (
            <>
              <Row field="sectionTopInches" label="Section top (in)">{numberInput("sectionTopInches")}</Row>
              <Row field="sectionBottomInches" label="Section bottom (in)">{numberInput("sectionBottomInches")}</Row>
              <Row field="bulletIndentInches" label="Bullet indent (in)">{numberInput("bulletIndentInches")}</Row>
              <Row field="bulletGapInches" label="Bullet gap (in)">{numberInput("bulletGapInches")}</Row>
            </>
          )}

          {group.id === "bullets" && (
            <>
              <Row field="bulletChar" label="Bullet">
                <select
                  id="style-bulletChar"
                  disabled={!supports("bulletChar")}
                  value={effective.bulletChar}
                  onChange={(event) => onChange("bulletChar", event.target.value)}
                >
                  {BULLET_CHARS.map((char) => (
                    <option key={char} value={char}>
                      {char}
                    </option>
                  ))}
                </select>
              </Row>
              <Row field="bulletCount" label="Max bullets">{numberInput("bulletCount")}</Row>
            </>
          )}
        </details>
      ))}
    </div>
  );
}
