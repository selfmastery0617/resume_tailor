import type { CustomCellRendererProps } from "ag-grid-react";
import type { Job } from "../../types/job";

interface DescriptionContext {
  /** Opens the same editable popup either way — "View" when there is text
   *  to read (and revise), "Edit" when there is none yet to type one in. */
  onOpenDescription: (job: Job) => void;
}

export function DescriptionActionCell(props: CustomCellRendererProps<Job>) {
  const { data } = props;
  const context = props.context as DescriptionContext;
  if (!data) return null;

  const hasDescription = Boolean(data.description);

  return (
    <button
      type="button"
      className="skills-extract-button"
      onClick={() => context.onOpenDescription(data)}
      title={hasDescription ? "Read or revise the job description" : "Type in a job description"}
    >
      {hasDescription ? "📄 View" : "✏️ Edit"}
    </button>
  );
}
