import type { CustomCellRendererProps } from "ag-grid-react";
import type { ExperienceResult } from "../api/experience";
import type { Job } from "../types/job";
import { ExtractingIndicator } from "./ExtractingIndicator";

export interface ExperienceGridContext {
  /** job id -> epoch ms the extraction started. */
  experienceExtracting: Map<string, number>;
  /** job id -> stored result; drives the badge after a refresh. */
  experienceResults: Record<string, ExperienceResult>;
  onExtractExperience: (job: Job) => void;
  onViewExperience: (job: Job) => void;
}

export function ExperienceCellRenderer(props: CustomCellRendererProps<Job>) {
  const { data } = props;
  const context = props.context as ExperienceGridContext;
  if (!data) return null;

  const startedAt = context.experienceExtracting.get(data.id);
  if (startedAt !== undefined) {
    return <ExtractingIndicator startedAt={startedAt} />;
  }

  const result = context.experienceResults[data.id];
  if (result) {
    const total = result.job1.bullets.length + result.job2.bullets.length;
    return (
      <button
        type="button"
        className="experience-badge"
        onClick={() => context.onViewExperience(data)}
        title={`${result.job1.company} + ${result.job2.company} — ${total} bullets`}
      >
        ✅ View Experience
      </button>
    );
  }

  return (
    <button
      type="button"
      className="skills-extract-button"
      onClick={() => context.onExtractExperience(data)}
      title="Generate experience bullets from database.json for this job"
    >
      🧬 Extract
    </button>
  );
}
