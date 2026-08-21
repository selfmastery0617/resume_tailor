import axios from "axios";
import { BACKEND_URL } from "../config";
import { settled, type SessionStatus } from "./providerSession";

export type { SessionStatus };

export async function fetchSessionStatus(force = false): Promise<SessionStatus> {
  const response = await axios.get<SessionStatus>(`${BACKEND_URL}/api/deepseek/session`, {
    params: force ? { force: true } : undefined,
    // A live probe launches a browser; allow well beyond the usual timeout.
    timeout: 60000,
  });
  return response.data;
}

/** Verification that waits out a sign-in holding the browser profile.
 *
 *  Closing the sign-in dock stops the remote session asynchronously, so a check
 *  fired straight afterwards can still land while it is shutting down. The
 *  backend answers "signing in" rather than guessing, and without this retry a
 *  perfectly good session would sit there showing as disconnected.
 */
export function fetchSettledSessionStatus(force = false): Promise<SessionStatus> {
  return settled(() => fetchSessionStatus(force));
}

/** Forgets the stored session on this machine.
 *
 *  Signs out of the app, not out of DeepSeek — the account is untouched and any
 *  session in your own browser keeps working.
 */
export async function signOutDeepSeek(): Promise<SessionStatus> {
  const response = await axios.post<SessionStatus>(`${BACKEND_URL}/api/deepseek/sign-out`);
  return response.data;
}
