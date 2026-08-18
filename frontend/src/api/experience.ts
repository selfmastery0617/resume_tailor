import axios from "axios";
import { BACKEND_URL } from "../config";

export interface ExperienceJob {
  company: string;
  product: string;
  timeline: string;
  projects: string[];
  bullets: string[];
  source_challenge_ids: string[];
}

export interface ExperienceResult {
  job1: ExperienceJob;
  job2: ExperienceJob;
  /** Resume summary written from the bullets above; "" when unavailable. */
  summary: string;
  summarySource: "deepseek" | "none";
  /** Prompts that shared this job's single DeepSeek chat; 0 = never connected. */
  deepseekTurns: number;
  search: { mode: "semantic" | "lexical"; model: string | null; detail: string | null };
  /** "fallback" means the AI provider was unavailable and bullets were composed
   *  directly from database.json rather than generated. */
  generator: "deepseek" | "fallback";
  extractedAt: string;
}

export interface DatabaseInfo {
  text: string;
  companies: string[];
  path: string;
  valid: boolean;
  detail: string | null;
}

export async function fetchExperienceDatabase(): Promise<DatabaseInfo> {
  const response = await axios.get<DatabaseInfo>(`${BACKEND_URL}/api/experience/database`);
  return response.data;
}

export async function saveExperienceDatabase(text: string): Promise<{ companies: string[] }> {
  const response = await axios.put<{ companies: string[] }>(
    `${BACKEND_URL}/api/experience/database`,
    { text },
  );
  return response.data;
}

export async function extractExperience(payload: {
  jobId: string;
  jobDescription: string;
  jobTitle?: string;
  jobMission?: string;
  techSkills?: string[];
}): Promise<ExperienceResult> {
  const response = await axios.post<ExperienceResult>(
    `${BACKEND_URL}/api/experience/extract`,
    payload,
  );
  return response.data;
}

/** Every stored extraction, so badges survive a page refresh. */
export async function fetchAllExperience(): Promise<Record<string, ExperienceResult>> {
  const response = await axios.get<Record<string, ExperienceResult>>(
    `${BACKEND_URL}/api/experience/all`,
  );
  return response.data;
}
