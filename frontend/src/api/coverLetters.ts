import axios from "axios";
import { BACKEND_URL } from "../config";
import type {
  CoverLetterStyle,
  CoverLetterTemplateDefinition,
  ProfileCoverLetterTemplateSettings,
} from "../resume/coverLetterTypes";

export interface CoverLetterTemplateCatalog {
  templates: CoverLetterTemplateDefinition[];
  /** System-default style layer, so the client merges exactly like the server. */
  systemDefaultStyle: CoverLetterStyle;
}

export async function fetchCoverLetterTemplates(): Promise<CoverLetterTemplateCatalog> {
  const response = await axios.get<CoverLetterTemplateCatalog>(
    `${BACKEND_URL}/api/cover-letter-templates`,
  );
  return response.data;
}

export async function fetchCoverLetterTemplateSettings(
  profileId: string,
): Promise<ProfileCoverLetterTemplateSettings> {
  const response = await axios.get<ProfileCoverLetterTemplateSettings>(
    `${BACKEND_URL}/api/profiles/${profileId}/cover-letter-template`,
  );
  return response.data;
}

export async function saveCoverLetterTemplateSettings(
  profileId: string,
  templateId: string,
  styleOverrides: Partial<CoverLetterStyle>,
): Promise<ProfileCoverLetterTemplateSettings> {
  const response = await axios.put<ProfileCoverLetterTemplateSettings>(
    `${BACKEND_URL}/api/profiles/${profileId}/cover-letter-template`,
    { templateId, styleOverrides },
  );
  return response.data;
}

export async function resetCoverLetterTemplateSettings(
  profileId: string,
): Promise<ProfileCoverLetterTemplateSettings> {
  const response = await axios.delete<ProfileCoverLetterTemplateSettings>(
    `${BACKEND_URL}/api/profiles/${profileId}/cover-letter-template`,
  );
  return response.data;
}

// -- tailored cover letters, saved into the output folder alongside the resume --

/** A tailored cover letter PDF that has been written to the output folder. */
export interface TailoredCoverLetter {
  jobId: string;
  profileId: string | null;
  profileName: string;
  templateId: string;
  folder: string;
  fileName: string;
  filePath: string;
  pageCount: number;
  byteSize: number;
  generatedAt: string;
  exists: boolean;
}

export async function generateTailoredCoverLetter(payload: {
  jobId: string;
  company?: string;
  jobTitle?: string;
  profileId?: string;
}): Promise<TailoredCoverLetter> {
  const response = await axios.post<TailoredCoverLetter>(
    `${BACKEND_URL}/api/cover-letters/tailored`,
    payload,
  );
  return response.data;
}

/** Every saved cover letter, so badges survive a page refresh. */
export async function fetchAllTailoredCoverLetters(): Promise<Record<string, TailoredCoverLetter>> {
  const response = await axios.get<Record<string, TailoredCoverLetter>>(
    `${BACKEND_URL}/api/cover-letters/tailored`,
  );
  return response.data;
}

/** Served from disk, so this opens the same bytes that were saved. */
export function tailoredCoverLetterUrl(jobId: string): string {
  return `${BACKEND_URL}/api/cover-letters/tailored/${encodeURIComponent(jobId)}/file`;
}

/** Opens the saved PDF's folder in Explorer on the machine running the backend. */
export async function openTailoredCoverLetterFolder(jobId: string): Promise<void> {
  await axios.post(
    `${BACKEND_URL}/api/cover-letters/tailored/${encodeURIComponent(jobId)}/open-folder`,
  );
}
