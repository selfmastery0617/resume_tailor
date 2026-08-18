/** Embedded DeepSeek sign-in.
 *
 *  Shows a live view of the backend's browser and forwards clicks and typing
 *  back to it. Not a real <iframe>: a login completed in a frame would store
 *  cookies in *this* browser, where the backend cannot read them, so the status
 *  would never flip and extraction would still fail.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { BACKEND_URL } from "../config";

const FRAME_INTERVAL_MS = 500;
const STATUS_INTERVAL_MS = 1000;

interface EmbeddedStatus {
  sessionId: number;
  status: "idle" | "starting" | "waiting" | "success" | "failed" | "cancelled";
  detail: string;
  url: string;
  hasFrame: boolean;
  width: number;
  height: number;
  elapsedSeconds: number;
}

interface DeepSeekLoginPanelProps {
  onSignedIn: () => void;
  onClose: () => void;
}

export function DeepSeekLoginPanel({ onSignedIn, onClose }: DeepSeekLoginPanelProps) {
  const [status, setStatus] = useState<EmbeddedStatus | null>(null);
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const objectUrlRef = useRef<string | null>(null);
  const signalledRef = useRef(false);
  const sessionIdRef = useRef<number | null>(null);

  // ---- start the session on mount ---------------------------------------
  useEffect(() => {
    let startedId: number | null = null;
    (async () => {
      try {
        const { data } = await axios.post<EmbeddedStatus>(
          `${BACKEND_URL}/api/deepseek/embedded-login/start`,
        );
        startedId = data.sessionId;
      } catch {
        setError("Could not start the sign-in session.");
      }
    })();
    return () => {
      // Pass the id we started: under React StrictMode this effect runs twice,
      // and an unqualified stop from the first (discarded) mount would kill the
      // session the second mount just created.
      void axios
        .post(`${BACKEND_URL}/api/deepseek/embedded-login/stop`, null, {
          params: startedId === null ? undefined : { sessionId: startedId },
        })
        .catch(() => {});
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    };
  }, []);

  // ---- poll status -------------------------------------------------------
  useEffect(() => {
    const id = window.setInterval(async () => {
      try {
        const { data } = await axios.get<EmbeddedStatus>(
          `${BACKEND_URL}/api/deepseek/embedded-login/status`,
        );
        setStatus(data);
        sessionIdRef.current = data.sessionId;
        if (data.status === "success" && !signalledRef.current) {
          signalledRef.current = true;
          onSignedIn();
        }
      } catch {
        /* transient */
      }
    }, STATUS_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [onSignedIn]);

  // ---- poll frames -------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    const id = window.setInterval(async () => {
      try {
        const response = await axios.get(`${BACKEND_URL}/api/deepseek/embedded-login/frame`, {
          responseType: "blob",
        });
        if (cancelled || response.status === 204) return;
        const next = URL.createObjectURL(response.data as Blob);
        // Revoke the previous object URL or the tab leaks a blob per frame.
        if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = next;
        setFrameUrl(next);
      } catch {
        /* transient */
      }
    }, FRAME_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const send = useCallback(async (event: Record<string, unknown>) => {
    try {
      await axios.post(`${BACKEND_URL}/api/deepseek/embedded-login/input`, event);
    } catch {
      /* dropped events are not worth surfacing */
    }
  }, []);

  /** Map a click on the scaled image back to page coordinates. */
  const toPageCoords = (clientX: number, clientY: number) => {
    const img = imgRef.current;
    if (!img || !status) return null;
    const rect = img.getBoundingClientRect();
    return {
      x: ((clientX - rect.left) / rect.width) * status.width,
      y: ((clientY - rect.top) / rect.height) * status.height,
    };
  };

  const live = status?.status === "waiting" || status?.status === "starting";

  return (
    <div className="login-panel">
      <div className="login-panel-head">
        <strong>Sign in to DeepSeek</strong>
        <span className="provider-state">
          {status?.status === "success"
            ? "Signed in ✓"
            : status?.status === "starting"
              ? "Opening…"
              : status?.status === "waiting"
                ? "Waiting for sign-in"
                : (status?.status ?? "…")}
        </span>
        <button type="button" onClick={onClose} aria-label="Close sign-in">
          &times;
        </button>
      </div>

      <p className="notice">
        {status?.detail ?? "Starting…"}{" "}
        {live && <span className="login-url">{status?.url}</span>}
      </p>
      {error && <p className="error">{error}</p>}

      <div
        className="login-viewport"
        // The image is not focusable by default, but typing has to reach the
        // remote page, so the wrapper takes focus and forwards keystrokes.
        tabIndex={0}
        onKeyDown={(event) => {
          if (!live) return;
          event.preventDefault();
          if (event.key.length === 1) {
            void send({ type: "type", text: event.key });
          } else {
            const named: Record<string, string> = {
              Backspace: "Backspace",
              Enter: "Enter",
              Tab: "Tab",
              Escape: "Escape",
              ArrowUp: "ArrowUp",
              ArrowDown: "ArrowDown",
              ArrowLeft: "ArrowLeft",
              ArrowRight: "ArrowRight",
              Delete: "Delete",
            };
            const key = named[event.key];
            if (key) void send({ type: "key", key });
          }
        }}
        onWheel={(event) => {
          if (live) void send({ type: "scroll", dy: event.deltaY });
        }}
      >
        {frameUrl ? (
          <img
            ref={imgRef}
            src={frameUrl}
            alt="DeepSeek sign-in"
            draggable={false}
            onClick={(event) => {
              if (!live) return;
              const point = toPageCoords(event.clientX, event.clientY);
              if (point) void send({ type: "click", ...point });
              (event.currentTarget.parentElement as HTMLElement)?.focus();
            }}
          />
        ) : (
          <div className="login-placeholder">
            <span className="spinner" aria-hidden="true" /> Loading DeepSeek…
          </div>
        )}
      </div>

      <p className="notice login-hint">
        Click the panel, then type as usual. Your credentials go to DeepSeek
        through this app's backend — only use this on a machine you trust.
      </p>
    </div>
  );
}
