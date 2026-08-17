import axios from "axios";
import { BACKEND_URL } from "../config";
import type { Job } from "../types/job";

export async function fetchJobs(): Promise<Job[]> {
  const response = await axios.get<Job[]>(`${BACKEND_URL}/api/jobs`);
  return response.data;
}

export async function importJobs(): Promise<Job[]> {
  const response = await axios.post<Job[]>(`${BACKEND_URL}/api/jobs/import`);
  return response.data;
}

export async function extractSkills(description: string, prompt: string): Promise<string> {
  const response = await axios.post<{ skills: string }>(`${BACKEND_URL}/api/jobs/extract-skills`, {
    description,
    prompt,
  });
  return response.data.skills;
}
