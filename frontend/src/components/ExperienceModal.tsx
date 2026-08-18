import { useEffect, useState } from "react";
import type { ExperienceResult } from "../api/experience";

interface ExperienceModalProps {
  result: ExperienceResult | null;
  jobLabel: string;
  onClose: () => void;
}

export function ExperienceModal({ result, jobLabel, onClose }: ExperienceModalProps) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!result) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [result, onClose]);

  useEffect(() => setCopied(false), [result]);

  if (!result) return null;

  const { job1, job2 } = result;
  const allBullets = [...job1.bullets, ...job2.bullets];

  const copyAll = async () => {
    const text = [
      ...(result.summary ? ["SUMMARY", result.summary, ""] : []),
      `${job1.company} — ${job1.product}${job1.timeline ? ` (${job1.timeline})` : ""}`,
      ...job1.bullets.map((b) => `• ${b}`),
      "",
      `${job2.company} — ${job2.product}${job2.timeline ? ` (${job2.timeline})` : ""}`,
      ...job2.bullets.map((b) => `• ${b}`),
    ].join("\n");

    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard API needs a secure context; fall back to a temp selection so
      // Copy All still works over plain http.
      const area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    setCopied(true);
  };

  const Section = ({ label, job }: { label: string; job: typeof job1 }) => (
    <section className="exp-section">
      <h3>
        {label}: {job.company}
        <span className="exp-meta">
          {job.product}
          {job.timeline ? ` · ${job.timeline}` : ""} · {job.bullets.length} bullets
        </span>
      </h3>
      {job.projects.length > 0 && (
        <p className="exp-projects">Projects: {job.projects.join(", ")}</p>
      )}
      <ul className="exp-bullets">
        {job.bullets.map((bullet, index) => (
          <li key={index}>{bullet}</li>
        ))}
      </ul>
    </section>
  );

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-content exp-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Extracted experience"
      >
        <div className="modal-header">
          <div>
            <h2>Extracted experience</h2>
            <p className="modal-subtitle">{jobLabel}</p>
          </div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </div>

        <div className="modal-body">
          {result.generator === "fallback" && (
            <p className="notice exp-warn">
              Composed directly from database.json — the AI provider was
              unavailable, so these are not model-generated. Reconnect DeepSeek
              in Settings and extract again for tailored wording.
            </p>
          )}
          {result.search.mode === "lexical" && (
            <p className="notice exp-warn">
              Ranked by keyword overlap rather than semantic similarity.
            </p>
          )}

          {result.summary && (
            <section className="exp-section">
              <h3>
                Summary
                <span className="exp-meta">
                  Written from the bullets below · goes at the top of the resume
                </span>
              </h3>
              <p className="exp-summary">{result.summary}</p>
            </section>
          )}

          <Section label="Job 1 (first company)" job={job1} />
          <Section label="Job 2 (most recent)" job={job2} />
        </div>

        <div className="settings-actions">
          <span className="notice">
            {allBullets.length} bullets total
            {result.deepseekTurns > 0 &&
              ` · ${result.deepseekTurns} DeepSeek prompts in one session`}
          </span>
          <button type="button" className="primary" onClick={copyAll}>
            {copied ? "Copied ✓" : "Copy All"}
          </button>
        </div>
      </div>
    </div>
  );
}
