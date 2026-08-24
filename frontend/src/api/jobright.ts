import axios from "axios";
import { BACKEND_URL } from "../config";
import { settled, type SessionStatus } from "./providerSession";

/** Whether the stored Jobright cookie still works.
 *
 *  Much quicker than DeepSeek's check — one request to the feed rather than a
 *  browser launch — so this needs no extended timeout.
 */
export async function fetchJobrightSession(force = false): Promise<SessionStatus> {
  const response = await axios.get<SessionStatus>(`${BACKEND_URL}/api/jobright/session`, {
    params: force ? { force: true } : undefined,
    timeout: 30000,
  });
  return response.data;
}

export function fetchSettledJobrightSession(force = false): Promise<SessionStatus> {
  return settled(() => fetchJobrightSession(force));
}

/** Forgets the harvested cookie and the browser profile on this machine.
 *
 *  Signs out of the app, not out of Jobright — the account is untouched.
 */
export async function signOutJobright(): Promise<SessionStatus> {
  const response = await axios.post<SessionStatus>(`${BACKEND_URL}/api/jobright/sign-out`);
  return response.data;
}
