/** Sign-in card for a browser-session AI provider — DeepSeek, ChatGPT or
 *  Jobright, parameterised so the three share one implementation.
 *
 *  Clicking "Sign in" opens a tab for this provider in the one shared,
 *  visible browser window every provider's sign-in uses (see
 *  api/browser.ts) — the same window if one is already open, a new one on
 *  the first click of a session. This card then polls the status endpoint
 *  until it reports connected.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { openSignInTab, type SignInProvider } from "../api/browser";
import type { SessionStatus } from "../api/deepseek";

// Deliberately slower than a normal status poll: while the shared window is
// open, each check reads its live page directly, but once it closes a check
// is a genuine ~5-8s browser launch, and polling faster than that just queues
// requests behind each other for no benefit.
const POLL_INTERVAL_MS = 3000;
// Give up waiting after this long — the tab is still open and usable, this
// only stops the polling loop so it does not run forever if the user walks
// away mid sign-in.
const POLL_TIMEOUT_MS = 10 * 60 * 1000;

/** Why the status call failed, in terms the reader can act on.
 *
 *  A 404 is the opposite of unreachable: the backend answered, it just does not
 *  have this route yet — which is what a server started before the feature was
 *  added looks like. Reporting that as "could not reach the backend" sends
 *  people to check the wrong thing.
 */
function describeReachError(err: unknown, label: string): string {
  const status = (err as { response?: { status?: number } }).response?.status;
  if (status === 404) {
    return `This backend has no ${label} routes — restart it to pick up the latest code.`;
  }
  if (status !== undefined) {
    return `The backend answered ${status} when checking ${label}.`;
  }
  return "Could not reach the backend. Is it running?";
}

interface ProviderConnectProps {
  provider: SignInProvider;
  label: string;
  description: string;
  fetchSession: () => Promise<SessionStatus>;
  onConnectedChange?: (connected: boolean) => void;
  /** Fires once, the moment a poll first sees connected: true — not on every
   *  refresh — so a sibling like the sidebar dots can react to a fresh
   *  sign-in without re-checking on every routine poll. */
  onSignedIn?: () => void;
  /** When supplied, a connected card offers Sign out. Forgets the stored
   *  session on this machine; the provider account is untouched. */
  signOut?: () => Promise<SessionStatus>;
  /** Told when a sign-out lands, so the rest of the app can re-check. */
  onSignedOut?: () => void;
}

export function ProviderConnect({
  provider,
  label,
  description,
  fetchSession,
  onConnectedChange,
  onSignedIn,
  signOut,
  onSignedOut,
}: ProviderConnectProps) {
  const [signingOut, setSigningOut] = useState(false);
  const [session, setSession] = useState<SessionStatus | null>(null);
  const [checking, setChecking] = useState(true);
  const [opening, setOpening] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);
  const wasConnected = useRef(false);

  const refresh = useCallback(async () => {
    // Verification loads the provider in a headless browser, so this takes a
    // few seconds — surface it instead of showing a stale "Not connected".
    setChecking(true);
    try {
      const status = await fetchSession();
      setSession(status);
      onConnectedChange?.(status.connected);
      if (status.connected && !wasConnected.current) onSignedIn?.();
      wasConnected.current = status.connected;
      return status;
    } catch (err) {
      setError(describeReachError(err, label));
      return null;
    } finally {
      setChecking(false);
    }
  }, [fetchSession, onConnectedChange, onSignedIn, label]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    setWaiting(false);
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const handleConnect = async () => {
    setError(null);
    setOpening(true);
    try {
      await openSignInTab(provider);
    } catch (err) {
      setError(describeReachError(err, label));
      setOpening(false);
      return;
    }
    setOpening(false);

    stopPolling();
    setWaiting(true);
    const deadline = Date.now() + POLL_TIMEOUT_MS;
    pollRef.current = window.setInterval(async () => {
      if (Date.now() > deadline) {
        stopPolling();
        return;
      }
      const status = await refresh();
      if (status?.connected) stopPolling();
    }, POLL_INTERVAL_MS);
  };

  const handleSignOut = async () => {
    if (!signOut) return;
    setError(null);
    setSigningOut(true);
    try {
      setSession(await signOut());
      onConnectedChange?.(false);
      onSignedOut?.();
    } catch (err) {
      // The backend explains why — usually the shared window still holding
      // the browser profile, which the user can act on.
      const detail = (err as { response?: { data?: { detail?: { message?: string } } } }).response
        ?.data?.detail?.message;
      setError(detail ?? `Could not sign out of ${label}.`);
    } finally {
      setSigningOut(false);
    }
  };

  const busy = opening || waiting;
  const connected = session?.connected ?? false;
  const ok = connected && !busy && !checking;

  const stateLabel = checking
    ? "Checking…"
    : opening
      ? "Opening…"
      : waiting
        ? "Waiting for you to sign in…"
        : connected
          ? "Connected"
          : "Not connected";

  // When not connected the backend's reason (expired, Cloudflare, no token) is
  // far more useful than the generic description.
  const detail = busy
    ? (session?.detail ?? "A browser tab just opened — sign in there.")
    : checking
      ? "Verifying the saved session…"
      : connected
        ? description
        : (session?.detail ?? description);

  return (
    <div className={`provider-card ${ok ? "provider-card--ok" : "provider-card--warn"}`}>
      <div className="provider-head">
        <span
          className={`deepseek-dot ${ok ? "deepseek-dot--ok" : "deepseek-dot--warn"}`}
          aria-hidden="true"
        />
        <strong>{label}</strong>
        {/* Status is text, not colour alone (9.4). */}
        <span className="provider-state">
          {(checking || busy) && <span className="spinner" aria-hidden="true" />}
          {stateLabel}
        </span>
      </div>
      <p className="deepseek-detail">{detail}</p>
      {error && <p className="error">{error}</p>}
      {/* Connected offers Sign out and nothing else — there is no reconnecting
          to do. */}
      {ok
        ? signOut && (
            <button
              type="button"
              className="danger-quiet"
              onClick={handleSignOut}
              disabled={signingOut}
            >
              {signingOut && <span className="spinner" aria-hidden="true" />}
              {signingOut ? "Signing out…" : "Sign out"}
            </button>
          )
        : (
            <button type="button" onClick={() => void handleConnect()} disabled={busy || checking}>
              {busy && <span className="spinner" aria-hidden="true" />}
              {waiting ? "Waiting…" : opening ? "Opening…" : `Sign in to ${label}`}
            </button>
          )}
    </div>
  );
}
