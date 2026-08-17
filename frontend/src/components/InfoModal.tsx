import { useEffect } from "react";
import type { Job } from "../types/job";

interface InfoModalProps {
  job: Job | null;
  bodyText: string | null | undefined;
  onClose: () => void;
}

export function InfoModal({ job, bodyText, onClose }: InfoModalProps) {
  useEffect(() => {
    if (!job) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [job, onClose]);

  if (!job) return null;

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
          <p>{bodyText}</p>
        </div>
      </div>
    </div>
  );
}
