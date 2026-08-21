import axios from "axios";
import { BACKEND_URL } from "../config";

export type SignInProvider = "deepseek" | "chatgpt" | "jobright";

/** Opens (launching the shared sign-in window on the first call) a new tab
 *  for this provider — the same window every other provider's sign-in shares,
 *  so it opens as an additional tab there rather than a separate window. */
export async function openSignInTab(provider: SignInProvider): Promise<void> {
  await axios.post(
    `${BACKEND_URL}/api/browser/open-tab`,
    { provider },
    // Covers a cold launch of the window plus its first navigation.
    { timeout: 30000 },
  );
}
