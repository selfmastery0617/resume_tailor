/** Shared shape and retry logic for the browser-session providers.
 *
 *  DeepSeek and Jobright both sign in through the docked browser panel and both
 *  report their status the same way, so the pieces that are easy to get subtly
 *  wrong live here once.
 */

export interface SessionStatus {
  connected: boolean;
  detail: string;
  /** True when the backend actually checked, rather than only inspecting the
   *  stored session file. */
  verified?: boolean;
  cached?: boolean;
  /** A sign-in holds the browser profile, so this is "cannot tell yet" rather
   *  than a verdict — ask again once the panel is done. */
  signingIn?: boolean;
}

/** Verification that waits out a sign-in holding the browser profile.
 *
 *  Closing a sign-in dock stops the remote session asynchronously, so a check
 *  fired straight afterwards can still land while it is shutting down. The
 *  backend answers "signing in" rather than guessing, and without this retry a
 *  perfectly good session would sit there showing as disconnected.
 */
export async function settled(
  fetch: () => Promise<SessionStatus>,
): Promise<SessionStatus> {
  let status = await fetch();
  for (let attempt = 0; attempt < 4 && status.signingIn; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 900));
    status = await fetch();
  }
  return status;
}
