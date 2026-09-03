import axios from "axios";
import { BACKEND_URL } from "../config";

/** A tailored resume PDF that has been written to the output folder. */
export interface TailoredResume {
  jobId: string;
  profileId: string | null;
  profileName: string;
  templateId: string;
  /** Absolute path of the `[Profile Name]/[mm-dd-yy-HHMM]_[Company]_[Job Title]` folder. */
  folder: string;
  fileName: string;
  filePath: string;
  pageCount: number;
  byteSize: number;
  generatedAt: string;
  /** False once the file is moved or deleted outside the app. */
  exists: boolean;
}

export async function generateTailoredResume(payload: {
  jobId: string;
  company?: string;
  jobTitle?: string;
  profileId?: string;
}): Promise<TailoredResume> {
  const response = await axios.post<TailoredResume>(
    `${BACKEND_URL}/api/resumes/tailored`,
    payload,
  );
  return response.data;
}

/** Every saved resume, so badges survive a page refresh. */
export async function fetchAllTailoredResumes(): Promise<Record<string, TailoredResume>> {
  const response = await axios.get<Record<string, TailoredResume>>(
    `${BACKEND_URL}/api/resumes/tailored`,
  );
  return response.data;
}

/** Served from disk, so this opens the same bytes that were saved. */
export function tailoredResumeUrl(jobId: string): string {
  return `${BACKEND_URL}/api/resumes/tailored/${encodeURIComponent(jobId)}/file`;
}

/** Opens the saved PDF's folder in Explorer on the machine running the backend. */
export async function openTailoredResumeFolder(jobId: string): Promise<void> {
  await axios.post(
    `${BACKEND_URL}/api/resumes/tailored/${encodeURIComponent(jobId)}/open-folder`,
  );
}
