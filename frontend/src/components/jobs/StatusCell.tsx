import type { CustomCellRendererProps } from "ag-grid-react";
import type { Job } from "../../types/job";

/** The two a person may choose. Empty is a state the row is in, never a choice. */
export const SELECTABLE_STATUSES = ["ready", "applied"] as const;

const LABELS: Record<string, string> = { ready: "Ready", applied: "Applied" };

export interface StatusContext {
  onChangeStatus: (job: Job, status: string) => void;
}

/** Always a dropdown, never a click-to-edit cell.
 *
 *  AG Grid's editor only appears on double-click, which hides the fact that
 *  the column is changeable at all. Rendering the select itself makes the
 *  choice visible, and keeps the colour that says which state the row is in.
 */
export function StatusCellRenderer(props: CustomCellRendererProps<Job>) {
  const { data } = props;
  const context = props.context as StatusContext;
  if (!data) return null;

  const status = (data.status as string) || "";
  // Nothing to be ready with until a resume exists, so the control is visible
  // but inert rather than absent — the column reads consistently either way.
  const locked = !data.hasResume;

  return (
    <select
      className={`status-select${status ? ` status-select--${status}` : ""}`}
      value={status}
      disabled={locked}
      title={
        locked
          ? "Generate a resume for this row before setting its status"
          : "Set the application status"
      }
      onChange={(event) => context.onChangeStatus(data, event.target.value)}
    >
      {/* Present only until a status is set; picking it again is not possible
          once one is, because a row cannot go back to having none. */}
      {!status && <option value="">—</option>}
      {SELECTABLE_STATUSES.map((option) => (
        <option key={option} value={option}>
          {LABELS[option]}
        </option>
      ))}
    </select>
  );
}
