import type { CustomCellRendererProps } from "ag-grid-react";
import type { Job } from "../types/job";

interface DescriptionCellRendererProps extends CustomCellRendererProps<Job> {
  onView: (job: Job) => void;
}

export function DescriptionCellRenderer({ data, onView }: DescriptionCellRendererProps) {
  if (!data?.description) {
    return <span className="description-cell-empty">N/A</span>;
  }

  return (
    <button type="button" className="info-view-button" onClick={() => onView(data)}>
      📄 View
    </button>
  );
}
