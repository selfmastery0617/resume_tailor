import axios from "axios";
import { BACKEND_URL } from "../config";
import type { Job } from "../types/job";

export async function fetchJobs(): Promise<Job[]> {
  const response = await axios.get<Job[]>(`${BACKEND_URL}/api/jobs`);
  return response.data;
}

/** Imports from the source and returns everything stored, not just the new rows. */
export async function importJobs(): Promise<Job[]> {
  const response = await axios.post<Job[]>(`${BACKEND_URL}/api/jobs/import`);
  return response.data;
}

/** A row typed or pasted into the empty row at the bottom of the table. */
export async function createJob(fields: Record<string, string>): Promise<Job> {
  const response = await axios.post<Job>(`${BACKEND_URL}/api/jobs`, fields);
  return response.data;
}

/** One cell edit. Only the fields sent are changed. */
export async function updateJob(jobId: string, patch: Record<string, string>): Promise<Job> {
  const response = await axios.patch<Job>(
    `${BACKEND_URL}/api/jobs/${encodeURIComponent(jobId)}`,
    patch,
  );
  return response.data;
}

/** Whole rows — Ctrl+Delete, not clearing their cells. */
export async function deleteJobRows(jobIds: string[]): Promise<{ count: number }> {
  const response = await axios.post<{ count: number }>(
    `${BACKEND_URL}/api/jobs/delete-rows`,
    { jobIds },
  );
  return response.data;
}

/** Records that this job was applied to. The row is read-only afterwards. */
export async function markJobApplied(jobId: string): Promise<Job> {
  const response = await axios.post<Job>(
    `${BACKEND_URL}/api/jobs/${encodeURIComponent(jobId)}/apply`,
  );
  return response.data;
}

export interface DeleteJobResult {
  deleted: string;
  title: string;
  company: string;
  /** A PDF left in the output folder, if one had been generated. */
  orphanedFile: string | null;
}

export async function deleteJob(jobId: string): Promise<DeleteJobResult> {
  const response = await axios.delete<DeleteJobResult>(
    `${BACKEND_URL}/api/jobs/${encodeURIComponent(jobId)}`,
  );
  return response.data;
}

export async function extractSkills(description: string, prompt: string): Promise<string> {
  const response = await axios.post<{ skills: string }>(`${BACKEND_URL}/api/jobs/extract-skills`, {
    description,
    prompt,
  });
  return response.data.skills;
}
