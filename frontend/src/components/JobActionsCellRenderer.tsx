import type { CustomCellRendererProps } from "ag-grid-react";
import type { Job } from "../types/job";

export interface JobActionsGridContext {
  /** job id -> the action currently running, so both buttons can show progress. */
  jobActionBusy: Map<string, "applying" | "deleting">;
  onMarkApplied: (job: Job) => void;
  onDeleteJob: (job: Job) => void;
}

function appliedOn(job: Job): string {
  if (!job.applied_at) return "Applied";
  const when = new Date(job.applied_at);
  return Number.isNaN(when.getTime())
    ? "Applied"
    : `Applied ${when.toLocaleDateString()}`;
}

export function JobActionsCellRenderer(props: CustomCellRendererProps<Job>) {
  const { data } = props;
  const context = props.context as JobActionsGridContext;
  if (!data) return null;

  const busy = context.jobActionBusy.get(data.id);

  if (busy === "deleting") {
    return (
      <span className="skills-cell-loading">
        <span className="spinner" aria-hidden="true" />
        <span>Deleting…</span>
      </span>
    );
  }

  return (
    <span className="job-actions">
      {data.applied ? (
        // Not a button: the row is frozen, so there is nothing left to press.
        // Showing a disabled button would imply the state is still reversible.
        <span className="job-applied-badge" title={`Locked — applied ${data.applied_at ?? ""}`}>
          ✅ {appliedOn(data)}
        </span>
      ) : (
        <button
          type="button"
          className="job-apply-button"
          disabled={busy === "applying"}
          onClick={() => context.onMarkApplied(data)}
          title="Record that you applied. This locks the row — the resume and bullets can no longer change."
        >
          {busy === "applying" ? "Marking…" : "Mark applied"}
        </button>
      )}

      <button
        type="button"
        className="job-delete-button"
        onClick={() => context.onDeleteJob(data)}
        aria-label={`Delete ${data.title}`}
        title="Delete this job and everything generated from it"
      >
        🗑
      </button>
    </span>
  );
}
