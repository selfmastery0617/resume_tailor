/** Search options for an import, and its progress once running.
 *
 *  The same dialog does both: the form collapses to a progress view when a run
 *  starts, so the numbers appear where the button was rather than somewhere
 *  else on the page.
 */

import { useEffect, useRef, useState } from "react";
import type { ImportStatus } from "../../api/jobs";

interface ImportJobsDialogProps {
  open: boolean;
  status: ImportStatus | null;
  error: string | null;
  onStart: (options: { roles: string[]; limit: number; excludeCompanies: string[] }) => void;
  onCancel: () => void;
  onClose: () => void;
}

/** A chip list, as job boards use for skills. Enter or comma commits a value. */
function CompanyChips({
  values,
  onChange,
  disabled,
}: {
  values: string[];
  onChange: (next: string[]) => void;
  disabled: boolean;
}) {
  const [draft, setDraft] = useState("");

  const commit = (raw: string) => {
    // Splitting on comma here means a pasted list becomes chips too.
    const additions = raw
      .split(",")
      .map((part) => part.trim())
      .filter((part) => part && !values.some((v) => v.toLowerCase() === part.toLowerCase()));
    if (additions.length) onChange([...values, ...additions]);
    setDraft("");
  };

  return (
    <div className={`chip-input${disabled ? " chip-input--disabled" : ""}`}>
      {values.map((value) => (
        <span key={value} className="chip">
          {value}
          <button
            type="button"
            className="chip-remove"
            disabled={disabled}
            aria-label={`Remove ${value}`}
            onClick={() => onChange(values.filter((v) => v !== value))}
          >
            ×
          </button>
        </span>
      ))}
      <input
        type="text"
        value={draft}
        disabled={disabled}
        placeholder={values.length ? "" : "Type a company and press Enter"}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === ",") {
            event.preventDefault();
            commit(draft);
          } else if (event.key === "Backspace" && !draft && values.length) {
            // Backspace on an empty box removes the last chip, as elsewhere.
            onChange(values.slice(0, -1));
          }
        }}
        // Losing focus with text typed should keep it, not discard it.
        onBlur={() => draft.trim() && commit(draft)}
      />
    </div>
  );
}

export function ImportJobsDialog({
  open,
  status,
  error,
  onStart,
  onCancel,
  onClose,
}: ImportJobsDialogProps) {
  const [roles, setRoles] = useState("");
  const [limit, setLimit] = useState(10);
  const [excluded, setExcluded] = useState<string[]>([]);
  const firstField = useRef<HTMLInputElement>(null);

  const running = status?.state === "running";

  useEffect(() => {
    if (open && !running) firstField.current?.focus();
  }, [open, running]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      // Escape closes, but never abandons a run silently — cancel is explicit.
      if (event.key === "Escape" && !running) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, running, onClose]);

  if (!open) return null;

  const start = () =>
    onStart({
      // "Data Engineer, Software Engineer" is two roles; either may match.
      roles: roles.split(",").map((r) => r.trim()).filter(Boolean),
      limit,
      excludeCompanies: excluded,
    });

  const matched = status?.matched ?? 0;
  const target = status?.limit ?? limit;
  const percent = target ? Math.min(100, Math.round((matched / target) * 100)) : 0;

  return (
    <div className="modal-backdrop" onClick={running ? undefined : onClose}>
      <div
        className="modal-content import-modal"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Import jobs"
      >
        <div className="modal-header">
          <h2>Import jobs</h2>
        </div>

        <div className="modal-body">
          <div className="prompt-section">
            <label htmlFor="import-roles">Role</label>
            <p className="notice">
              Titles to look for. Separate several with commas — a job matches
              if any of them appears in its title.
            </p>
            <input
              ref={firstField}
              id="import-roles"
              type="text"
              value={roles}
              disabled={running}
              placeholder="Senior Data Engineer, Software Engineer"
              onChange={(event) => setRoles(event.target.value)}
            />
          </div>

          <div className="prompt-section">
            <label htmlFor="import-limit">Limit job count</label>
            <p className="notice">Stop once this many matching jobs are found.</p>
            <input
              id="import-limit"
              type="number"
              min={1}
              max={200}
              value={limit}
              disabled={running}
              onChange={(event) => setLimit(Number(event.target.value) || 1)}
            />
          </div>

          <div className="prompt-section">
            <label htmlFor="import-exclude">Exclude companies</label>
            <p className="notice">These are skipped even if the role matches.</p>
            <CompanyChips values={excluded} onChange={setExcluded} disabled={running} />
          </div>

          {status && status.state !== "idle" && (
            <div className="import-progress">
              <div className="import-count">
                <strong>
                  {matched}/{target}
                </strong>
                <span className="console-dim">
                  {" "}
                  matched · {status.scanned} scanned
                </span>
              </div>
              <div className="import-bar">
                <span style={{ width: `${percent}%` }} />
              </div>
              <p className="notice">
                {running
                  ? "Rows appear in the table as they are found. You can close this and keep working."
                  : status.state === "cancelled"
                    ? "Cancelled. The jobs found before stopping were kept."
                    : status.state === "failed"
                      ? status.error
                      : `Finished — ${matched} job${matched === 1 ? "" : "s"} imported.`}
              </p>
            </div>
          )}

          {error && <p className="error">{error}</p>}
        </div>

        <div className="settings-actions">
          {running ? (
            <>
              <button type="button" onClick={onClose}>
                Close
              </button>
              <button type="button" className="danger" onClick={onCancel}>
                Cancel import
              </button>
            </>
          ) : (
            <>
              <button type="button" onClick={onClose}>
                Cancel
              </button>
              <button type="button" className="primary" onClick={start}>
                Start
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
