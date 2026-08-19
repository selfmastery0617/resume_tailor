import axios from "axios";
import { BACKEND_URL } from "../config";
import type { LoginStatus, SessionStatus } from "./deepseek";

export type GenerationModel = "deepseek" | "chatgpt";

export interface AppSettings {
  skillsPrompt: string;
  tailoringPrompt: string;
  /** Writes the resume summary from the bullets, in the same DeepSeek chat. */
  summaryPrompt: string;
  /** Writes the resume headline, once the summary exists. */
  titlePrompt: string;
  /** Drafts a profile's database.json from its experience. Not part of
   *  extraction — run on demand from the Profile tab. */
  corpusPrompt: string;
  outputFolder: string;
  generationModel: GenerationModel;
  /** Company used as Job 1 (the earlier role) in experience extraction. */
  firstCompany: string;
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

export async function fetchChatGptSession(): Promise<SessionStatus> {
  const response = await axios.get<SessionStatus>(`${BACKEND_URL}/api/chatgpt/session`);
  return response.data;
}

export async function startChatGptLogin(): Promise<LoginStatus> {
  const response = await axios.post<LoginStatus>(`${BACKEND_URL}/api/chatgpt/login`);
  return response.data;
}

export async function fetchChatGptLoginStatus(): Promise<LoginStatus> {
  const response = await axios.get<LoginStatus>(`${BACKEND_URL}/api/chatgpt/login/status`);
  return response.data;
}
