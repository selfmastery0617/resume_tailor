import type { CustomCellRendererProps } from "ag-grid-react";
import type { Job } from "../../types/job";

export interface RowDeleteContext {
  /** Job ids currently being deleted, so the button can show progress. */
  deletingRows: Set<string>;
  onDeleteRow: (job: Job) => void;
  /** The placeholder row at the bottom has nothing to delete. */
  blankRowId: string;
}

export function RowDeleteCell(props: CustomCellRendererProps<Job>) {
  const { data } = props;
  const context = props.context as RowDeleteContext;
  if (!data) return null;

  // The bottom row is a placeholder for new data, not a record. Rendering a
  // disabled button there would suggest there is something to remove.
  if (data.id === context.blankRowId) return null;

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
