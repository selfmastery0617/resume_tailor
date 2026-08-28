/** Live progress console.
 *
 *  Extraction takes tens of seconds and makes decisions that are otherwise
 *  invisible — which product won, which two projects were picked, what the
 *  similarity scores were. This streams the backend's event log so a surprising
 *  result can be explained rather than just observed.
 *
 *  Polled by sequence number, so reconnecting resumes instead of replaying.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { BACKEND_URL } from "../config";

const POLL_MS = 600;

type Level = "info" | "step" | "result" | "warn" | "error";

interface ProgressEvent {
  seq: number;
  ts: number;
  level: Level;
  stage: string;
  message: string;
  data: Record<string, unknown>;
}

const LEVEL_MARK: Record<Level, string> = {
  info: "·",
  step: "▸",
  result: "✓",
  warn: "!",
  error: "✕",
};

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString(undefined, { hour12: false });
}

/** Renders the structured payload that accompanies some events. */
function EventData({ data }: { data: Record<string, unknown> }) {
  const rows: React.ReactNode[] = [];

  const matches = data.matches as
    | { score: number; company: string; product: string; project: string; text: string }[]
    | undefined;
  if (matches?.length) {
    rows.push(
      <table key="matches" className="console-table">
        <tbody>
          {matches.map((m, i) => (
            <tr key={i}>
              <td className="console-score">{m.score.toFixed(3)}</td>
              <td>
                <span className="console-dim">{m.product} · {m.project}</span>
                <br />
                {m.text}
              </td>
            </tr>
          ))}
        </tbody>
      </table>,
    );
  }

  const documents = data.documents as
    | { id: string; company: string; product: string; project: string; text: string }[]
    | undefined;
  if (documents?.length) {
    rows.push(
      <table key="documents" className="console-table">
        <tbody>
          {documents.map((d) => (
            <tr key={d.id}>
              <td>
                <span className="console-dim">{d.company} · {d.product} · {d.project}</span>
                <br />
                {d.text}
              </td>
            </tr>
          ))}
        </tbody>
      </table>,
    );
  }

  const tally = data.tally as { product: string; score: number }[] | undefined;
  if (tally?.length) {
    const max = Math.max(...tally.map((t) => t.score));
    rows.push(
      <div key="tally" className="console-bars">
        {tally.map((t) => (
          <div key={t.product} className="console-bar-row">
            <span className="console-bar-label">{t.product}</span>
            <span className="console-bar" style={{ width: `${(t.score / max) * 100}%` }} />
            <span className="console-score">{t.score.toFixed(3)}</span>
          </div>
        ))}
      </div>,
    );
  }

  const projects = data.projects as { project: string; totalScore: number }[] | undefined;
  if (projects?.length) {
    const chosen = new Set((data.chosen as string[] | undefined) ?? []);
    rows.push(
      <ul key="projects" className="console-list">
        {projects.map((p) => (
          <li key={p.project} className={chosen.has(p.project) ? "console-chosen" : undefined}>
            {chosen.has(p.project) ? "✓ " : "· "}
            {p.project} <span className="console-score">{p.totalScore.toFixed(3)}</span>
          </li>
        ))}
      </ul>,
    );
  }

  // The finished extraction. Shown in full because the Jobs table no longer
  // carries an Experience column — this is where the bullets are read.
  const extracted = data.extracted as
    | {
        summary: string;
        roles: {
          label: string;
          company: string;
          product: string;
          timeline: string;
          projects: string[];
          bullets: string[];
        }[];
      }
    | undefined;
  if (extracted) {
    rows.push(
      <div key="extracted" className="console-result">
        {extracted.summary && (
          <div className="console-result-block">
            <div className="console-result-head">Summary</div>
            <p className="console-summary">{extracted.summary}</p>
          </div>
        )}
        {extracted.roles.map((role) => (
          <div key={role.label} className="console-result-block">
            <div className="console-result-head">
              {role.label}
              <span className="console-dim">
                {" "}
                — {role.company}
                {role.product ? ` · ${role.product}` : ""}
                {role.timeline ? ` · ${role.timeline}` : ""}
              </span>
            </div>
            {role.projects.length > 0 && (
              <div className="console-dim console-result-projects">
                Projects: {role.projects.join(", ")}
              </div>
            )}
            <ul className="console-bullets">
              {role.bullets.map((bullet, index) => (
                <li key={index}>{bullet}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>,
    );
  }

  if (typeof data.query === "string") {
    rows.push(
      <div key="query" className="console-quote">
        {data.query}
      </div>,
    );
  }
  if (typeof data.preview === "string") {
    rows.push(
      <div key="preview" className="console-quote">
        {data.preview}
      </div>,
    );
  }

  return rows.length ? <div className="console-data">{rows}</div> : null;
}

export function ProgressConsole({ onClose }: { onClose: () => void }) {
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const sinceRef = useRef(0);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    // A slow poll must not overlap the next one: both would send the same
    // `since` and append the same events twice (duplicate React keys).
    let inFlight = false;

    const id = window.setInterval(async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const { data } = await axios.get<{ events: ProgressEvent[]; latest: number }>(
          `${BACKEND_URL}/api/experience/progress`,
          { params: { since: sinceRef.current } },
        );
        if (cancelled || !data.events.length) return;

        // Advance from the highest seq actually received, not the server's
        // global latest — those differ if events arrive between calls.
        sinceRef.current = Math.max(
          sinceRef.current,
          ...data.events.map((e) => e.seq),
        );

        setEvents((prev) => {
          // Belt and braces: drop anything already shown.
          const seen = new Set(prev.map((e) => e.seq));
          const fresh = data.events.filter((e) => !seen.has(e.seq));
          if (!fresh.length) return prev;
          // Cap client-side too; a long session should not grow the DOM forever.
          return [...prev, ...fresh].slice(-400);
        });
      } catch {
        /* backend may be restarting */
      } finally {
        inFlight = false;
      }
    }, POLL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (autoScroll && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [events, autoScroll]);

  const clear = useCallback(async () => {
    setEvents([]);
    try {
      const { data } = await axios.post<{ latest: number }>(
        `${BACKEND_URL}/api/experience/progress/clear`,
      );
      // Resume from the server's current sequence, not 0, or the cleared
      // events would stream straight back in.
      sinceRef.current = data.latest;
    } catch {
      /* clearing locally is enough */
    }
  }, []);

  return (
    <aside className="console-dock" aria-label="Progress console">
      <div className="console-head">
        <strong>Console</strong>
        <span className="console-dim">{events.length} events</span>
        <label className="console-auto">
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
          />
          follow
        </label>
        <button type="button" onClick={clear}>
          Clear
        </button>
        <button type="button" onClick={onClose} aria-label="Close console">
          &times;
        </button>
      </div>

      <div className="console-body" ref={bodyRef}>
        {events.length === 0 && (
          <p className="console-dim console-empty">
            Waiting for activity… Run Extract on a job to see skill extraction,
            company selection and similarity scores here.
          </p>
        )}
        {events.map((event) => (
          <div key={event.seq} className={`console-line console-${event.level}`}>
            <span className="console-time">{formatTime(event.ts)}</span>
            <span className="console-mark">{LEVEL_MARK[event.level]}</span>
            <span className="console-stage">{event.stage}</span>
            <span className="console-msg">
              {event.message}
              <EventData data={event.data} />
            </span>
          </div>
        ))}
      </div>
    </aside>
  );
}
