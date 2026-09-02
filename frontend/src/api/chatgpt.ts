import axios from "axios";
import { BACKEND_URL } from "../config";
import { settled, type SessionStatus } from "./providerSession";

/** Whether the stored ChatGPT session for `worker` still works.
 *
 *  A live check: it loads ChatGPT in that worker's saved profile rather than
 *  inspecting a file, so this takes a few seconds on a cold cache. `worker`
 *  is 1-based, matching the "Worker N" label on Settings — see chatgpt_pool.py.
 */
export async function fetchChatGptSession(force = false, worker = 1): Promise<SessionStatus> {
  const response = await axios.get<SessionStatus>(`${BACKEND_URL}/api/chatgpt/session`, {
    params: { worker, ...(force ? { force: true } : {}) },
    timeout: 60000,
  });
  return response.data;
}

export function fetchSettledChatGptSession(force = false, worker = 1): Promise<SessionStatus> {
  return settled(() => fetchChatGptSession(force, worker));
}

/** Forgets the stored session for `worker` on this machine. Signs out of the
 *  app, not of ChatGPT — the account is untouched. */
export async function signOutChatGpt(worker = 1): Promise<SessionStatus> {
  const response = await axios.post<SessionStatus>(`${BACKEND_URL}/api/chatgpt/sign-out`, null, {
    params: { worker },
  });
  return response.data;
}

/** Every currently configured worker index (1-based). */
export async function fetchChatGptWorkers(): Promise<{ index: number }[]> {
  const response = await axios.get<{ index: number }[]>(`${BACKEND_URL}/api/chatgpt/workers`);
  return response.data;
}
