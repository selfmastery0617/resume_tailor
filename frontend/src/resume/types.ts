/** Mirrors backend app/schemas/resume.py and style.py. */

export type SectionId = "summary" | "experience" | "skills" | "education";
export type PersonalField = "address" | "phone" | "email" | "birthday";
export type TextAlign = "left" | "center" | "right";

export interface ProfileInfo {
  fullName: string;
  professionalTitle: string;
  email: string;
  phone: string;
  street: string;
  city: string;
  state: string;
  postal: string;
  birthday: string;
  linkedin: string;
  website: string;
  summary: string;
}

export interface Experience {
  id: string;
  company: string;
  title: string;
  location: string;
  startDate: string;
  endDate: string;
  current: boolean;
  description: string;
}

export interface Education {
  id: string;
  university: string;
  degree: string;
  startYear: string;
  endYear: string;
  location: string;
}

export interface Skill {
  id: string;
  name: string;
  category: string;
}

export interface ResumeData {
  profile: ProfileInfo;
  experience: Experience[];
  education: Education[];
  skills: Skill[];
}

export interface Profile {
  id: string;
  name: string;
  data: ResumeData;
  createdAt: string;
  updatedAt: string;
}

export interface ResumeStyle {
  fontFamily: string;
  nameSize: number;
  titleSize: number;
  contactSize: number;
  sectionSize: number;
  bodySize: number;
  bodyLineHeight: number;
  nameBold: boolean;
  nameItalic: boolean;
  titleBold: boolean;
  titleItalic: boolean;
  contactBold: boolean;
  contactItalic: boolean;

  nameColor: string;
  titleColor: string;
  contactColor: string;
  sectionColor: string;
  bodyColor: string;

  nameTextAlign: TextAlign;
  titleTextAlign: TextAlign;
  contactTextAlign: TextAlign;

  sectionOrder: SectionId[];
  showSummary: boolean;
  showHeaderDivider: boolean;

  personalOrder: PersonalField[];
  showEmail: boolean;
  showPhone: boolean;
  showStreet: boolean;
  showCity: boolean;
  showState: boolean;
  showPostal: boolean;
  showBirthday: boolean;

  sectionTopInches: number;
  sectionBottomInches: number;
  bulletIndentInches: number;
  bulletGapInches: number;

  bulletChar: string;
  bulletCount: number | null;
  bulletLines: number | null;
  perExperienceBulletCount: Record<string, number>;

  forcePageBreakBeforeSections: SectionId[];
  forcePageBreakBeforeExperienceIds: string[];
  forcePageBreakBeforeEducationIds: string[];
}

export interface TemplateDefinition {
  id: string;
  name: string;
  description: string;
  version: number;
  active: boolean;
  rendererKey: string;
  defaultStyle: Partial<ResumeStyle>;
  supportedStyleFields: string[];
  /** 'builtin' templates are source-controlled and read-only in the builder. */
  source: "builtin" | "user";
  /** Layout document; present only for user templates. */
  layout?: unknown;
  ownerProfileId?: string | null;
}

export interface ProfileTemplateSettings {
  profileId: string;
  templateId: string;
  templateVersion: number;
  styleOverrides: Partial<ResumeStyle>;
  effectiveStyle: ResumeStyle;
  updatedAt: string;
}

/** The contract every template renderer implements (TM-FR-003).
 *
 *  `layout` is only supplied for user-built templates (rendererKey
 *  "layout-v1"); the ten built-in renderers ignore it. Keeping it optional
 *  means the contract stays uniform and callers need no branching.
 */
export interface TemplateRendererProps {
  data: ResumeData;
  style: ResumeStyle;
  layout?: unknown;
}
