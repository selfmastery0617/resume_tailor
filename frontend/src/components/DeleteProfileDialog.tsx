import { useEffect, useState } from "react";
import type { ProfileDeletionImpact } from "../api/templates";

interface DeleteProfileDialogProps {
  impact: ProfileDeletionImpact | null;
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Rows worth naming individually in the confirmation. */
function losses(impact: ProfileDeletionImpact) {
  const plural = (count: number, one: string, many: string) =>
    count === 1 ? one : many;

  return [
    { key: "jobs", label: plural(impact.jobs, "imported job", "imported jobs"), count: impact.jobs },
    {
      key: "extractions",
      label: plural(impact.extractions, "extraction", "extractions"),
      count: impact.extractions,
    },
    {
      key: "bullets",
      label: plural(impact.bullets, "generated bullet", "generated bullets"),
      count: impact.bullets,
    },
    {
      key: "documents",
      label: plural(impact.documents, "resume record", "resume records"),
      count: impact.documents,
    },
    {
      key: "experiences",
      label: plural(impact.experiences, "experience entry", "experience entries"),
      count: impact.experiences,
    },
  ].filter((row) => row.count > 0);
}

export function DeleteProfileDialog({
  impact,
  busy,
  error,
  onConfirm,
  onCancel,
}: DeleteProfileDialogProps) {
  const [typed, setTyped] = useState("");

  useEffect(() => setTyped(""), [impact?.profileId]);

  useEffect(() => {
    if (!impact) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [impact, busy, onCancel]);

  if (!impact) return null;

  const rows = losses(impact);
  // Typing the name is asked for only when there is something to lose. A
  // confirmation that fires for an empty profile trains people to click through
  // it, which is exactly when it stops protecting the full one.
  const needsTyping = rows.length > 0;
  const confirmed = !needsTyping || typed.trim() === impact.name;

  return (
    <div className="modal-backdrop" onClick={busy ? undefined : onCancel}>
      <div
        className="modal-content delete-profile-modal"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Delete ${impact.name}`}
      >
        <div className="modal-header">
          <h2>Delete “{impact.name}”?</h2>
        </div>

        <div className="modal-body">
          {impact.isOnly ? (
            <p className="error">
              This is your only profile. Jobs belong to a profile, so deleting it
              would leave nowhere to import them — create another one first.
            </p>
          ) : (
            <>
              {rows.length === 0 ? (
                <p>This profile holds no resume content and owns no jobs.</p>
              ) : (
                <>
                  <p>Deleting it also removes:</p>
                  <ul className="delete-impact">
                    {rows.map((row) => (
                      <li key={row.key}>
                        <strong>{row.count}</strong> {row.label}
                      </li>
                    ))}
                  </ul>
                  <p className="notice">
                    {impact.filesLeftOnDisk > 0 && (
                      <>
                        {impact.filesLeftOnDisk} PDF
                        {impact.filesLeftOnDisk === 1 ? "" : "s"} already saved to
                        your output folder stay on disk.{" "}
                      </>
                    )}
                    This cannot be undone.
                  </p>
                </>
              )}

              {impact.isDefault && (
                <p className="notice exp-warn">
                  This is your default profile. Another will take over.
                </p>
              )}

              {needsTyping && (
                <label className="delete-confirm">
                  Type <strong>{impact.name}</strong> to confirm
                  <input
                    type="text"
                    value={typed}
                    onChange={(event) => setTyped(event.target.value)}
                    placeholder={impact.name}
                    autoFocus
                    disabled={busy}
                  />
                </label>
              )}
            </>
          )}

          {error && <p className="error">{error}</p>}
        </div>

        <div className="settings-actions">
          <button type="button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          {!impact.isOnly && (
            <button
              type="button"
              className="danger"
              onClick={onConfirm}
              disabled={busy || !confirmed}
            >
              {busy ? "Deleting…" : "Delete profile"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
