import axios from "axios";
import { BACKEND_URL } from "../config";
import type {
  Profile,
  ProfileTemplateSettings,
  ResumeData,
  ResumeStyle,
  TemplateDefinition,
} from "../resume/types";


export interface TemplateCatalog {
  templates: TemplateDefinition[];
  /** System-default style layer, so the client merges exactly like the server. */
  systemDefaultStyle: ResumeStyle;
}

export async function fetchTemplates(): Promise<TemplateCatalog> {
  const response = await axios.get<TemplateCatalog>(`${BACKEND_URL}/api/templates`);
  return response.data;
}

export async function fetchProfiles(): Promise<Profile[]> {
  const response = await axios.get<Profile[]>(`${BACKEND_URL}/api/profiles`);
  return response.data;
}

export async function createProfile(name: string): Promise<Profile> {
  const response = await axios.post<Profile>(`${BACKEND_URL}/api/profiles`, { name });
  return response.data;
}

export async function updateProfile(
  profileId: string,
  patch: { name?: string; data?: ResumeData },
): Promise<Profile> {
  const response = await axios.put<Profile>(`${BACKEND_URL}/api/profiles/${profileId}`, patch);
  return response.data;
}

export async function deleteProfile(profileId: string): Promise<void> {
  await axios.delete(`${BACKEND_URL}/api/profiles/${profileId}`);
}

export async function fetchTemplateSettings(profileId: string): Promise<ProfileTemplateSettings> {
  const response = await axios.get<ProfileTemplateSettings>(
    `${BACKEND_URL}/api/profiles/${profileId}/template`,
  );
  return response.data;
}

export async function saveTemplateSettings(
  profileId: string,
  templateId: string,
  styleOverrides: Partial<ResumeStyle>,
): Promise<ProfileTemplateSettings> {
  const response = await axios.put<ProfileTemplateSettings>(
    `${BACKEND_URL}/api/profiles/${profileId}/template`,
    { templateId, styleOverrides },
  );
  return response.data;
}

/** Generate a PDF and hand it to the browser as a download. */
export async function downloadResumePdf(
  profileId: string,
  templateId: string,
  styleOverrides: Partial<ResumeStyle>,
): Promise<void> {
  const response = await axios.post(
    `${BACKEND_URL}/api/resumes/generate`,
    { profileId, templateId, styleOverrides },
    { responseType: "blob" },
  );

  // Filename comes from the server so sanitisation lives in one place.
  const disposition = String(response.headers["content-disposition"] ?? "");
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const filename = match?.[1] ?? "resume.pdf";

  const url = URL.createObjectURL(response.data as Blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export async function resetTemplateSettings(profileId: string): Promise<ProfileTemplateSettings> {
  const response = await axios.delete<ProfileTemplateSettings>(
    `${BACKEND_URL}/api/profiles/${profileId}/template`,
  );
  return response.data;
}
