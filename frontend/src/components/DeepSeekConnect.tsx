import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchLoginStatus,
  fetchSessionStatus,
  startLogin,
  type LoginState,
  type SessionStatus,
} from "../api/deepseek";

const POLL_INTERVAL_MS = 1500;

/** States where the sign-in window is open and we should keep polling. */
const IN_PROGRESS: LoginState[] = ["opening", "waiting"];

interface DeepSeekConnectProps {
  /** Lets the parent disable Extract until a session exists. */
  onConnectedChange?: (connected: boolean) => void;
}

export function DeepSeekConnect({ onConnectedChange }: DeepSeekConnectProps) {
  const [session, setSession] = useState<SessionStatus | null>(null);
  const [loginState, setLoginState] = useState<LoginState>("idle");
  const [loginDetail, setLoginDetail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const refreshSession = useCallback(async () => {
    try {
      const status = await fetchSessionStatus();
      setSession(status);
      onConnectedChange?.(status.connected);
      return status;
    } catch {
      setError("Could not reach the backend. Is it running on port 8000?");
      return null;
    }
  }, [onConnectedChange]);

  useEffect(() => {
    void refreshSession();
  }, [refreshSession]);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Always clear the interval on unmount.
  useEffect(() => stopPolling, [stopPolling]);

  const handleConnect = async () => {
    setError(null);
    try {
      const initial = await startLogin();
      setLoginState(initial.status);
      setLoginDetail(initial.detail);
    } catch {
      setError("Could not start sign-in. Is the backend running on port 8000?");
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
          if (status.status === "success") await refreshSession();
        }
      } catch {
        stopPolling();
        setError("Lost contact with the backend while signing in.");
      }
    }, POLL_INTERVAL_MS);
  };

  const busy = IN_PROGRESS.includes(loginState);
  const connected = session?.connected ?? false;

  if (connected && !busy) {
    return (
      <div className="deepseek-status deepseek-status--ok">
        <span className="deepseek-dot deepseek-dot--ok" aria-hidden="true" />
        <span>DeepSeek connected</span>
        <button type="button" className="deepseek-relink" onClick={handleConnect}>
          Sign in again
        </button>
      </div>
    );
  }

  return (
    <div className="deepseek-status deepseek-status--warn">
      <span className="deepseek-dot deepseek-dot--warn" aria-hidden="true" />
      <div className="deepseek-status-body">
        <strong>
          {busy ? "Waiting for DeepSeek sign-in…" : "Not connected to DeepSeek"}
        </strong>
        <p className="deepseek-detail">
          {busy
            ? loginDetail
            : loginState === "failed" || loginState === "cancelled"
              ? loginDetail
              : "Skill extraction needs a signed-in DeepSeek session. Connecting opens a browser window for you to sign in — it closes itself when done."}
        </p>
        {error && <p className="error">{error}</p>}
      </div>
      <button type="button" onClick={handleConnect} disabled={busy}>
        {busy && <span className="spinner" aria-hidden="true" />}
        {busy ? "Signing in…" : "Connect DeepSeek"}
      </button>
    </div>
  );
}
