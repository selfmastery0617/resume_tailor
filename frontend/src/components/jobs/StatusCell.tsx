import { useEffect, useRef, useState } from "react";
import type { CustomCellEditorProps, CustomCellRendererProps } from "ag-grid-react";
import type { Job } from "../../types/job";

/** The two a person may choose. Empty is a state the row is in, never a choice. */
export const SELECTABLE_STATUSES = ["ready", "applied"] as const;

const LABELS: Record<string, string> = { ready: "Ready", applied: "Applied" };

export function StatusCellRenderer(props: CustomCellRendererProps<Job>) {
  const status = (props.value as string) || "";
  if (!status) {
    // Deliberately blank rather than "None": an empty Status means nothing has
    // happened to this row yet, and a label would imply a choice was made.
    return <span className="status-empty" aria-label="No status" />;
  }
  return <span className={`status-tag status-tag--${status}`}>{LABELS[status] ?? status}</span>;
}

/** A dropdown of exactly the two selectable values. */
export function StatusCellEditor(props: CustomCellEditorProps<Job>) {
  const [value, setValue] = useState<string>((props.value as string) || "ready");
  const ref = useRef<HTMLSelectElement>(null);

  useEffect(() => ref.current?.focus(), []);

  const commit = (next: string) => {
    setValue(next);
    props.onValueChange(next);
    // Close as soon as a choice is made; a dropdown with an OK step is worse.
    props.stopEditing();
  };

  return (
    <select
      ref={ref}
      className="status-editor"
      value={value}
      onChange={(event) => commit(event.target.value)}
      onBlur={() => props.stopEditing()}
    >
      {SELECTABLE_STATUSES.map((option) => (
        <option key={option} value={option}>
          {LABELS[option]}
        </option>
      ))}
    </select>
  );
}
