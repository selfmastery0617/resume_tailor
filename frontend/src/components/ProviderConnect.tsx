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
}

export function ProviderConnect({
  label,
  description,
  fetchSession,
  startLogin,
  fetchLoginStatus,
  onConnectedChange,
}: ProviderConnectProps) {
  const [session, setSession] = useState<SessionStatus | null>(null);
  const [loginState, setLoginState] = useState<LoginState>("idle");
  const [loginDetail, setLoginDetail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const status = await fetchSession();
      setSession(status);
      onConnectedChange?.(status.connected);
    } catch {
      setError("Could not reach the backend on port 8000.");
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

  return (
    <div
      className={`provider-card ${connected && !busy ? "provider-card--ok" : "provider-card--warn"}`}
    >
      <div className="provider-head">
        <span
          className={`deepseek-dot ${connected && !busy ? "deepseek-dot--ok" : "deepseek-dot--warn"}`}
          aria-hidden="true"
        />
        <strong>{label}</strong>
        {/* Status is text, not colour alone (9.4). */}
        <span className="provider-state">
          {busy ? "Signing in…" : connected ? "Connected" : "Not connected"}
        </span>
      </div>
      <p className="deepseek-detail">
        {busy ? loginDetail : connected ? description : (session?.detail ?? description)}
      </p>
      {error && <p className="error">{error}</p>}
      <button type="button" onClick={handleConnect} disabled={busy}>
        {busy && <span className="spinner" aria-hidden="true" />}
        {connected ? `Sign in to ${label} again` : `Connect ${label}`}
      </button>
    </div>
  );
}
