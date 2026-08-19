import type { CustomCellRendererProps } from "ag-grid-react";
import type { Job } from "../../types/job";

interface DescriptionContext {
  onViewDescription: (job: Job) => void;
  onGenerateDescription: (job: Job) => void;
}

/** Good enough to decide whether a description could be fetched for this row.
 *  Mirrors _valid_url in job_store.py — the backend enforces it either way. */
function hasUsableUrl(url: string | null | undefined): boolean {
  const text = (url || "").trim();
  if (!text) return false;
  try {
    const parsed = new URL(text.includes("://") ? text : `https://${text}`);
    return (
      (parsed.protocol === "http:" || parsed.protocol === "https:") &&
      parsed.hostname.includes(".")
    );
  } catch {
    return false;
  }
}

export function DescriptionActionCell(props: CustomCellRendererProps<Job>) {
  const { data } = props;
  const context = props.context as DescriptionContext;
  if (!data) return null;

  // Without a posting to read, there is nothing to show and nothing to fetch.
  if (!hasUsableUrl(data.url)) {
    return (
      <span className="description-disabled" title="Add a valid URL to enable this">
        —
      </span>
    );
  }

  if (data.description) {
    return (
      <button
        type="button"
        className="skills-extract-button"
        onClick={() => context.onViewDescription(data)}
        title="Read the full job description"
      >
        📄 View
      </button>
    );
  }

  return (
    <button
      type="button"
      className="skills-extract-button"
      onClick={() => context.onGenerateDescription(data)}
      title="Fetch the description for this posting"
    >
      ✨ Generate
    </button>
  );
}
