import axios from "axios";
import { BACKEND_URL } from "../config";

export interface Health {
  status: string;
  startedAt: number;
  newestSourceAt: number;
  /** The backend is serving code older than the files on disk. */
  stale: boolean;
}

export async function fetchHealth(): Promise<Health> {
  const response = await axios.get<Health>(`${BACKEND_URL}/health`, { timeout: 8000 });
  return response.data;
}
