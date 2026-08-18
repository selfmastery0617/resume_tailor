/** Generic sign-in card for a browser-session AI provider.
 *
 *  Same flow as the DeepSeek banner, parameterised so DeepSeek and ChatGPT
 *  share one implementation on the Settings page. The existing Jobs-tab
 *  DeepSeek banner is untouched and keeps its own component.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { LoginState, LoginStatus, SessionStatus } from "../api/deepseek";

const POLL_INTERVAL_MS = 1500;
const IN_PROGRESS: LoginState[] = ["opening", "waiting"];

interface ProviderConnectProps {
  label: string;
  description: string;
  fetchSession: () => Promise<SessionStatus>;
  startLogin: () => Promise<LoginStatus>;
  fetchLoginStatus: () => Promise<LoginStatus>;
  onConnectedChange?: (connected: boolean) => void;
  /** When supplied, Connect defers to the caller (e.g. an in-page sign-in
   *  panel) instead of opening a separate browser window. */
  onConnectClick?: () => void;
}

export function ProviderConnect({
  label,
  description,
  fetchSession,
  startLogin,
  fetchLoginStatus,
  onConnectedChange,
  onConnectClick,
}: ProviderConnectProps) {
  const [session, setSession] = useState<SessionStatus | null>(null);
  const [checking, setChecking] = useState(true);
  const [loginState, setLoginState] = useState<LoginState>("idle");
  const [loginDetail, setLoginDetail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    // Verification loads the provider in a headless browser, so this takes a
    // few seconds — surface it instead of showing a stale "Not connected".
    setChecking(true);
    try {
      const status = await fetchSession();
      setSession(status);
      onConnectedChange?.(status.connected);
    } catch {
      setError("Could not reach the backend on port 8000.");
    } finally {
      setChecking(false);
    }
  }, [fetchSession, onConnectedChange]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const handleConnect = async () => {
    setError(null);
    if (onConnectClick) {
      onConnectClick();
      return;
    }
    try {
      const initial = await startLogin();
      setLoginState(initial.status);
      setLoginDetail(initial.detail);
    } catch {
      setError("Could not start sign-in. Is the backend running?");
      return;
    }

    stopPolling();
    pollRef.current = window.setInterval(async () => {
      try {
        const status = await fetchLoginStatus();
        setLoginState(status.status);
        setLoginDetail(status.detail);
        if (!IN_PROGRESS.includes(status.status)) {
          stopPolling();
          if (status.status === "success") await refresh();
        }
      } catch {
        stopPolling();
        setError("Lost contact with the backend while signing in.");
      }
    }, POLL_INTERVAL_MS);
  };

  const busy = IN_PROGRESS.includes(loginState);
  const connected = session?.connected ?? false;
  const ok = connected && !busy && !checking;

  const stateLabel = checking
    ? "Checking…"
    : busy
      ? "Signing in…"
      : connected
        ? "Connected"
        : "Not connected";

  // When not connected the backend's reason (expired, Cloudflare, no token) is
  // far more useful than the generic description.
  const detail = busy
    ? loginDetail
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
      <button type="button" onClick={handleConnect} disabled={busy || checking}>
        {busy && <span className="spinner" aria-hidden="true" />}
        {connected ? `Sign in to ${label} again` : `Connect ${label}`}
      </button>
    </div>
  );
}
