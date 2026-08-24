import axios from "axios";
import { BACKEND_URL } from "../config";
import { settled, type SessionStatus } from "./providerSession";

/** Whether the stored ChatGPT session still works.
 *
 *  A live check: it loads ChatGPT in the saved profile rather than inspecting a
 *  file, so this takes a few seconds on a cold cache.
 */
export async function fetchChatGptSession(force = false): Promise<SessionStatus> {
  const response = await axios.get<SessionStatus>(`${BACKEND_URL}/api/chatgpt/session`, {
    params: force ? { force: true } : undefined,
    timeout: 60000,
  });
  return response.data;
}

export function fetchSettledChatGptSession(force = false): Promise<SessionStatus> {
  return settled(() => fetchChatGptSession(force));
}

/** Forgets the stored session on this machine. Signs out of the app, not of
 *  ChatGPT — the account is untouched. */
export async function signOutChatGpt(): Promise<SessionStatus> {
  const response = await axios.post<SessionStatus>(`${BACKEND_URL}/api/chatgpt/sign-out`);
  return response.data;
}
