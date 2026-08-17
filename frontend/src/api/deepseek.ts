import axios from "axios";

const BACKEND_URL = "http://localhost:8000";

export interface SessionStatus {
  connected: boolean;
  detail: string;
}

/** Mirrors the backend's LoginStatus literal. */
export type LoginState = "idle" | "opening" | "waiting" | "success" | "failed" | "cancelled";

export interface LoginStatus {
  status: LoginState;
  detail: string;
  elapsed_seconds: number;
}

export async function fetchSessionStatus(): Promise<SessionStatus> {
  const response = await axios.get<SessionStatus>(`${BACKEND_URL}/api/deepseek/session`);
  return response.data;
}

/** Opens the sign-in window. Returns immediately — poll fetchLoginStatus(). */
export async function startLogin(): Promise<LoginStatus> {
  const response = await axios.post<LoginStatus>(`${BACKEND_URL}/api/deepseek/login`);
  return response.data;
}

export async function fetchLoginStatus(): Promise<LoginStatus> {
  const response = await axios.get<LoginStatus>(`${BACKEND_URL}/api/deepseek/login/status`);
  return response.data;
}
