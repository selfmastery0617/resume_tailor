import axios from "axios";
import { BACKEND_URL } from "../config";

export interface ExperienceJob {
  company: string;
  product: string;
  timeline: string;
  companySummary: string;
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
  /** Resume headline finalized by ChatGPT from a DeepSeek draft; "" when unavailable. */
  title: string;
  titleSource: "chatgpt" | "none";
  /** Resume skill set written for this job, last in the DeepSeek chat;
   *  [] when unavailable (the profile's own skills are used instead). */
  skillSet: string[];
  skillSetSource: "deepseek" | "none";
  /** ChatGPT's categorization of skillSet, from the same revision pass that
   *  handles bullets/summaries; [] when it never ran or didn't parse, in
   *  which case skillSet renders as one uncategorized group instead. */
  skillGroups: { category: string; skills: string[] }[];
  /** Prompts that shared this job's single DeepSeek chat; 0 = never connected. */
  deepseekTurns: number;
  search: { mode: "semantic" | "lexical"; model: string | null; detail: string | null };
  /** "fallback" means the AI provider was unavailable and bullets were composed
   *  directly from database.json rather than generated. "chatgpt" means
   *  DeepSeek generated the bullets and summary, and a final ChatGPT pass
   *  then revised them — that revised text is what's actually on the resume. */
  generator: "deepseek" | "chatgpt" | "fallback";
  extractedAt: string;
}

/** One profile's career corpus. Each profile has its own database.json. */
export interface DatabaseInfo {
  text: string;
  companies: string[];
  path: string;
  profileId: string;
  /** False when this profile has no corpus yet — a normal state, not an error. */
  exists: boolean;
  valid: boolean;
  detail: string | null;
}

export async function fetchExperienceDatabase(profileId?: string): Promise<DatabaseInfo> {
  const response = await axios.get<DatabaseInfo>(`${BACKEND_URL}/api/experience/database`, {
    params: profileId ? { profileId } : undefined,
  });
  return response.data;
}

export async function saveExperienceDatabase(
  text: string,
  profileId?: string,
): Promise<{ companies: string[]; profileId: string }> {
  const response = await axios.put<{ companies: string[]; profileId: string }>(
    `${BACKEND_URL}/api/experience/database`,
    { text },
    { params: profileId ? { profileId } : undefined },
  );
  return response.data;
}

/** The expected shape, for a profile starting from nothing. */
export async function fetchDatabaseExample(): Promise<string> {
  const response = await axios.get<{ text: string }>(
    `${BACKEND_URL}/api/experience/database/example`,
  );
  return response.data.text;
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
