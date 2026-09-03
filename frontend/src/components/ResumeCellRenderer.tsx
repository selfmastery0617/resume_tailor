import type { CustomCellRendererProps } from "ag-grid-react";
import type { TailoredCoverLetter } from "../api/coverLetters";
import { tailoredCoverLetterUrl } from "../api/coverLetters";
import type { ExperienceResult } from "../api/experience";
import type { TailoredResume } from "../api/resumes";
import { tailoredResumeUrl } from "../api/resumes";
import type { Job } from "../types/job";
import { ExtractingIndicator } from "./ExtractingIndicator";

export interface ResumeGridContext {
  /** job id -> epoch ms the generation started. */
  resumeGenerating: Map<string, number>;
  /** job id -> saved PDF; drives the badge after a refresh. */
  resumeResults: Record<string, TailoredResume>;
  /** job id -> saved cover letter PDF, generated automatically alongside the
   *  resume once extraction reaches step 10 -- shown as a second, narrower
   *  badge in the same cell rather than its own column. */
  coverLetterResults: Record<string, TailoredCoverLetter>;
  /** job id -> epoch ms extraction started, for the first phase of the run. */
  experienceExtracting: Map<string, number>;
  /** Whether this job already has bullets, which decides the button's label. */
  experienceResults: Record<string, ExperienceResult>;
  /** A bulk run is in progress for other rows -- disable this row's own
   *  button rather than let a stray click race the shared DeepSeek/ChatGPT
   *  browser session the bulk run is already using. */
  bulkRunning: boolean;
  /** `force=true` always re-extracts (a fresh ChatGPT session) rather than
   *  reusing this job's cached experience data -- used by the Regenerate
   *  button on an already-generated resume. */
  onGenerateResume: (job: Job, force?: boolean) => void;
  onOpenFolder: (job: Job) => void;
}

/** A narrower companion badge to the resume's own -- only shown once a cover
 *  letter PDF actually exists (step 10 is best-effort, so not every job will
 *  have one, unlike the resume). No separate extract/generate button of its
 *  own: the resume button's own click already drives extraction, which
 *  produces both PDFs together (see the automatic-generation note in
 *  routers/experience.py). */
function CoverLetterBadge({ job, context }: { job: Job; context: ResumeGridContext }) {
  const saved = context.coverLetterResults[job.id];
  if (!saved || !saved.exists) return null;
  return (
    <a
      className="cover-letter-badge"
      href={tailoredCoverLetterUrl(job.id)}
      target="_blank"
      rel="noreferrer"
      title={`${saved.filePath}\n${saved.pageCount} page${saved.pageCount === 1 ? "" : "s"} · cover letter`}
    >
      ✉️
    </a>
  );
}

export function ResumeCellRenderer(props: CustomCellRendererProps<Job>) {
  const { data } = props;
  const context = props.context as ResumeGridContext;
  if (!data) return null;

  // Extraction runs first when this job has none, so the cell reports which of
  // the two phases is actually happening.
  const extractingSince = context.experienceExtracting.get(data.id);
  if (extractingSince !== undefined) {
    return (
      <ExtractingIndicator
        startedAt={extractingSince}
        label="Extracting"
        typicalSeconds={45}
        hint="Writing bullets and the summary — watch the console for details."
      />
    );
  }

  const startedAt = context.resumeGenerating.get(data.id);
  if (startedAt !== undefined) {
    return (
      <ExtractingIndicator
        startedAt={startedAt}
        label="Generating"
        typicalSeconds={8}
        hint="Rendering the PDF and saving it to the output folder."
      />
    );
  }

  // An applied job is a record of what was sent. Offering "Regenerate" would
  // overwrite the file on disk that the application was actually made with, so
  // the PDF stays openable and nothing else does.
  const locked = Boolean(data.locked ?? data.applied);

  const saved = context.resumeResults[data.id];
  if (saved) {
    // The file lives on disk and can be moved or deleted from Explorer, so a
    // stale badge must offer a rebuild rather than a download that 404s.
    if (!saved.exists) {
      // Locked, so it cannot be rebuilt — say where it went instead of offering
      // a button that would be refused.
      if (locked) {
        return (
          <span className="resume-missing" title={saved.filePath}>
            ⚠️ File missing
          </span>
        );
      }
      return (
        <button
          type="button"
          className="skills-extract-button"
          onClick={() => context.onGenerateResume(data)}
          disabled={context.bulkRunning}
          title={`${saved.filePath} is missing — click to generate it again.`}
        >
          ⚠️ Regenerate
        </button>
      );
    }
    return (
      <span className="resume-cell">
        <a
          className="experience-badge"
          href={tailoredResumeUrl(data.id)}
          target="_blank"
          rel="noreferrer"
          title={`${saved.filePath}\n${saved.pageCount} page${
            saved.pageCount === 1 ? "" : "s"
          } · saved as ${saved.profileName}`}
        >
          📄 {saved.fileName}
        </a>
        <CoverLetterBadge job={data} context={context} />
        <button
          type="button"
          className="resume-open-folder"
          onClick={() => context.onOpenFolder(data)}
          title={`Open the folder: ${saved.filePath}`}
          aria-label="Open containing folder"
        >
          📂
        </button>
        {!locked && (
          <button
            type="button"
            className="resume-regenerate"
            onClick={() => context.onGenerateResume(data, true)}
            disabled={context.bulkRunning}
            title="Start over: re-extract from a fresh ChatGPT session, then regenerate the resume and cover letter"
            aria-label="Regenerate resume from scratch"
          >
            ↻
          </button>
        )}
      </span>
    );
  }

  // Applied, but nothing was ever generated for it — there is no resume to
  // offer and making one now would misrepresent what was sent.
  if (locked) {
    return <span className="resume-none">No resume generated</span>;
  }

  // With the Experience column gone this button owns the whole flow: it
  // extracts first when the job has no bullets yet, then renders the PDF.
  const extracted = Boolean(context.experienceResults[data.id]);
  return (
    <button
      type="button"
      className="skills-extract-button"
      onClick={() => context.onGenerateResume(data)}
      disabled={context.bulkRunning}
      title={
        extracted
          ? "Render the extracted experience to a PDF and save it to the output folder"
          : "Extract experience for this job, then save the PDF to the output folder"
      }
    >
      {extracted ? "📄 Generate PDF" : "🧬 Extract"}
    </button>
  );
}
