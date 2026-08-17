import type { CustomCellRendererProps } from "ag-grid-react";
import type { Job } from "../types/job";
import { ExtractingIndicator } from "./ExtractingIndicator";

export interface SkillsGridContext {
  /** job id -> epoch ms when its extraction started. */
  extractingSince: Map<string, number>;
  /** False until a DeepSeek session exists; Extract is disabled meanwhile. */
  connected: boolean;
  onExtractSkills: (job: Job) => void;
  onViewSkills: (job: Job) => void;
}

export function SkillsCellRenderer(props: CustomCellRendererProps<Job>) {
  const { data } = props;
  const context = props.context as SkillsGridContext;

  if (!data) return null;

  const startedAt = context.extractingSince.get(data.id);
  if (startedAt !== undefined) {
    return <ExtractingIndicator startedAt={startedAt} />;
  }

  if (data.skills) {
    return (
      <button type="button" className="info-view-button" onClick={() => context.onViewSkills(data)}>
        🏷️ View
      </button>
    );
  }

  return (
    <button
      type="button"
      className="skills-extract-button"
      onClick={() => context.onExtractSkills(data)}
      disabled={!context.connected}
      title={
        context.connected
          ? "Ask DeepSeek to extract skills from this job description."
          : "Connect DeepSeek first — use the Connect DeepSeek button above."
      }
    >
      ✨ Extract
    </button>
  );
}
