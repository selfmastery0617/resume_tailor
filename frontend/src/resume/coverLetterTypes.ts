/** Mirrors backend app/schemas/cover_letter.py, cover_letter_style.py and
 *  cover_letter_template.py. */

import type { PaperSize } from "./layoutTypes";

export interface CoverLetterStyle {
  pageSize: PaperSize;
  marginTopIn: number;
  marginBottomIn: number;
  marginLeftIn: number;
  marginRightIn: number;
  fontFamily: string;
  fontSize: number;
  lineHeight: number;
  paragraphSpacingIn: number;
}

/** Every field optional -- a partial style layer (template default, saved
 *  profile override, or a one-time generation override). */
export type CoverLetterStyleOverrides = Partial<CoverLetterStyle>;

export interface CoverLetterData {
  jobTitle: string;
  companyName: string;
  candidateName: string;
  phone: string;
  email: string;
  linkedin: string;
  greeting: string;
  paragraphs: string[];
  closing: string;
}

export interface CoverLetterTemplateDefinition {
  id: string;
  name: string;
  description: string;
  defaultStyle: CoverLetterStyleOverrides;
}

export interface CoverLetterTemplateCatalog {
  templates: CoverLetterTemplateDefinition[];
  systemDefaultStyle: CoverLetterStyle;
}

export interface ProfileCoverLetterTemplateSettings {
  profileId: string;
  templateId: string;
  styleOverrides: CoverLetterStyleOverrides;
  effectiveStyle: CoverLetterStyle;
  updatedAt: string;
}
