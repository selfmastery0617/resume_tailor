import type { CustomCellRendererProps } from "ag-grid-react";
import type { Job } from "../types/job";

export function UrlCellRenderer({ value }: CustomCellRendererProps<Job, string>) {
  if (!value) return null;

  return (
    <a href={value} target="_blank" rel="noopener noreferrer" className="url-cell-link">
      {value}
    </a>
  );
}
