import type { CustomCellRendererProps } from "ag-grid-react";
import type { Job } from "../../types/job";

export interface RowDeleteContext {
  /** Job ids currently being deleted, so the button can show progress. */
  deletingRows: Set<string>;
  onDeleteRow: (job: Job) => void;
}

export function RowDeleteCell(props: CustomCellRendererProps<Job>) {
  const { data } = props;
  const context = props.context as RowDeleteContext;
  if (!data) return null;

  const busy = context.deletingRows.has(data.id);

  return (
    <button
      type="button"
      className="row-delete-button"
      disabled={busy}
      onClick={() => context.onDeleteRow(data)}
      aria-label={`Delete ${data.title || "this row"}`}
      title="Delete this row and everything generated from it"
    >
      {busy ? "…" : "🗑"}
    </button>
  );
}
