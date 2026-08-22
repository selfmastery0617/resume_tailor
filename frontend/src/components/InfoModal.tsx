import { useEffect, useState } from "react";
import type { Job } from "../types/job";

interface InfoModalProps {
  job: Job | null;
  bodyText: string | null | undefined;
  onClose: () => void;
  /** When provided, the body becomes an editable textarea with Save/Cancel
   *  instead of read-only text — used for editing a job's description. */
  onSave?: (text: string) => Promise<void>;
}

export function InfoModal({ job, bodyText, onClose, onSave }: InfoModalProps) {
  const [draft, setDraft] = useState(bodyText ?? "");
  const [saving, setSaving] = useState(false);

  // Re-seed the draft whenever a different job (or its text) is opened, not
  // on every keystroke — the effect depends on the job identity, not draft.
  useEffect(() => {
    setDraft(bodyText ?? "");
  }, [job, bodyText]);

  useEffect(() => {
    if (!job) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [job, onClose]);

  if (!job) return null;

  const handleSave = async () => {
    if (!onSave) return;
    setSaving(true);
    try {
      await onSave(draft);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-content" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2>{job.title}</h2>
            <p className="modal-subtitle">
              {job.company} · {job.location}
            </p>
          </div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </div>
        <div className="modal-body">
          {onSave ? (
            <textarea
              className="prompt-textarea"
              rows={16}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              autoFocus
              disabled={saving}
            />
          ) : (
            <p>{bodyText}</p>
          )}
        </div>
        {onSave && (
          <div className="settings-actions">
            <button type="button" onClick={onClose} disabled={saving}>
              Cancel
            </button>
            <button type="button" className="primary" onClick={() => void handleSave()} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
