import axios from "axios";
import { BACKEND_URL } from "../config";

export type GenerationModel = "deepseek" | "chatgpt";

export interface AppSettings {
  skillsPrompt: string;
  tailoringPrompt: string;
  /** Writes the resume summary from the bullets, in the same ChatGPT chat
   *  every prompt for this job runs in. */
  summaryPrompt: string;
  /** Writes the resume headline and each company's own title together, in
   *  one turn, once the summary exists. */
  titlePrompt: string;
  /** Writes one summary per role (Job 1, Job 2), right after that role's own
   *  bullets, in the same chat. */
  companySummaryPrompt: string;
  /** Writes the resume's skill set in the same chat, before the whole
   *  resume is assembled. Positioned on the resume wherever the
   *  template's own "skills" block is placed (right after Summary by default). */
  skillSetPrompt: string;
  /** Runs in the same chat: assembles the complete resume from everything
   *  already written, before the revision prompt below revises it. */
  wholeResumePrompt: string;
  /** Runs last, still in the same chat: revises the resume it just assembled. */
  revisionPrompt: string;
  /** One further message in that same chat, marking main keywords by
   *  wrapping them in [square brackets] -- the PDF renders those bold. */
  keywordsPrompt: string;
  /** Drafts a profile's database.json from its experience. Not part of
   *  extraction — run on demand from the Profile tab. */
  corpusPrompt: string;
  outputFolder: string;
  generationModel: GenerationModel;
  /** Company used as Job 1 (the earlier role) in experience extraction. */
  firstCompany: string;
  /** The first company's years. Job 1 runs start->end and Job 2 runs
   *  end->present, so these two numbers date every tailored resume. */
  firstCompanyStartYear: string;
  firstCompanyEndYear: string;
  /** How much a challenge's industry-similarity score counts toward its
   *  ranking score during Job 1/Job 2 selection -- a number from 0 to 1,
   *  as a string (settings are stored as text). Profile-scoped, like
   *  firstCompany. */
  industryWeight: string;
  /** Profile used for tailored resume PDFs; its name becomes the file name.
   *  Empty means "use the first profile". */
  resumeProfile: string;
}

export interface FolderCheck {
  valid: boolean;
  detail: string;
  resolved?: string;
}

export interface FolderSelection extends FolderCheck {
  cancelled: boolean;
}

export async function fetchSettings(): Promise<AppSettings> {
  const response = await axios.get<AppSettings>(`${BACKEND_URL}/api/settings`);
  return response.data;
}

export async function saveSettings(patch: Partial<AppSettings>): Promise<AppSettings> {
  const response = await axios.put<AppSettings>(`${BACKEND_URL}/api/settings`, patch);
  return response.data;
}

export async function checkFolder(path: string): Promise<FolderCheck> {
  const response = await axios.post<FolderCheck>(`${BACKEND_URL}/api/settings/check-folder`, {
    path,
  });
  return response.data;
}

export async function selectFolder(initialPath?: string): Promise<FolderSelection> {
  const response = await axios.post<FolderSelection>(
    `${BACKEND_URL}/api/settings/select-folder`,
    { initialPath: initialPath || null },
  );
  return response.data;
}

// -- ChatGPT session (mirrors the DeepSeek client) ------------------------

