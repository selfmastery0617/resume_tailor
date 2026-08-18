import axios from "axios";
import { BACKEND_URL } from "../config";

export interface SessionStatus {
  connected: boolean;
  detail: string;
  /** True when the backend actually loaded the provider to check, rather than
   *  only inspecting the stored session file. */
  verified?: boolean;
  cached?: boolean;
}

/** Mirrors the backend's LoginStatus literal. */
export type LoginState = "idle" | "opening" | "waiting" | "success" | "failed" | "cancelled";

export interface LoginStatus {
  status: LoginState;
  detail: string;
  elapsed_seconds: number;
}

export async function fetchSessionStatus(force = false): Promise<SessionStatus> {
  const response = await axios.get<SessionStatus>(`${BACKEND_URL}/api/deepseek/session`, {
    params: force ? { force: true } : undefined,
    // A live probe launches a browser; allow well beyond the usual timeout.
    timeout: 60000,
  });
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
