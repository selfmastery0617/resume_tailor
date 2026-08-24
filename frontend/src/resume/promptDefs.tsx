/** Shared by ProfilePage (where prompts are edited, one profile at a time)
 *  and anywhere else that needs to describe what each prompt does. */

/** Mirrors TAILORING_PLACEHOLDERS in backend settings_service.py. */
export const TAILORING_PLACEHOLDERS = [
  "count",
  "company",
  "product",
  "job_description",
  "achievements",
] as const;

/** Mirrors SUMMARY_PLACEHOLDERS in backend settings_service.py. */
export const SUMMARY_PLACEHOLDERS = [
  "sentences",
  "job_title",
  "job_description",
  "companies",
  "bullets",
] as const;

/** Mirrors TITLE_PLACEHOLDERS in backend settings_service.py. */
export const TITLE_PLACEHOLDERS = [
  "job_title",
  "current_title",
  "job_description",
  "summary",
  "bullets",
] as const;

/** Mirrors COMPANY_SUMMARY_PLACEHOLDERS in backend settings_service.py. */
export const COMPANY_SUMMARY_PLACEHOLDERS = [
  "sentences",
  "company",
  "product",
  "job_title",
  "job_description",
  "bullets",
] as const;

export function PlaceholderList({ tokens }: { tokens: readonly string[] }) {
  return (
    <>
      {tokens.map((token, index) => (
        <span key={token}>
          {index > 0 && ", "}
          <code>{`{${token}}`}</code>
        </span>
      ))}
    </>
  );
}

export type PromptKey =
  | "skillsPrompt"
  | "tailoringPrompt"
  | "companySummaryPrompt"
  | "summaryPrompt"
  | "titlePrompt"
  | "revisionPrompt"
  | "corpusPrompt";

export interface PromptDef {
  key: PromptKey;
  label: string;
  description: React.ReactNode;
  placeholders?: readonly string[];
  rows: number;
}

// One entry per prompt, driving the dropdown on the Profile page instead of
// stacking all seven textareas at once.
export const PROMPT_DEFS: PromptDef[] = [
  {
    key: "skillsPrompt",
    label: "1. Skill extraction prompt",
    description: (
      <>
        Pulls the required skills and the job mission out of the description.
        Results appear in the console.
      </>
    ),
    rows: 6,
  },
  {
    key: "tailoringPrompt",
    label: "2. Bullet tailoring prompt",
    description: (
      <>
        Turns the selected challenges into resume bullets — run twice, once
        per role. These placeholders are substituted before sending:{" "}
        <PlaceholderList tokens={TAILORING_PLACEHOLDERS} />. Any other braces
        are left as written.
      </>
    ),
    placeholders: TAILORING_PLACEHOLDERS,
    rows: 12,
  },
  {
    key: "companySummaryPrompt",
    label: "3. Company summary prompt",
    description: (
      <>
        Runs right after each role's own bullets — once for Job 1, once for
        Job 2 — and writes the short summary that introduces that
        company/product above its bullets on the resume. Placeholders:{" "}
        <PlaceholderList tokens={COMPANY_SUMMARY_PLACEHOLDERS} />.
      </>
    ),
    placeholders: COMPANY_SUMMARY_PLACEHOLDERS,
    rows: 12,
  },
  {
    key: "summaryPrompt",
    label: "4. Summary extraction prompt",
    description: (
      <>
        Runs last, once both sets of bullets exist, and writes the summary
        that goes at the top of the generated resume. Placeholders:{" "}
        <PlaceholderList tokens={SUMMARY_PLACEHOLDERS} />.
      </>
    ),
    placeholders: SUMMARY_PLACEHOLDERS,
    rows: 12,
  },
  {
    key: "titlePrompt",
    label: "5. Title generation prompt",
    description: (
      <>
        Runs last, once the summary exists, and writes the professional title
        at the top of the generated resume. Leave it blank on a job and the
        profile's own title is used. Placeholders:{" "}
        <PlaceholderList tokens={TITLE_PLACEHOLDERS} />.
      </>
    ),
    placeholders: TITLE_PLACEHOLDERS,
    rows: 12,
  },
  {
    key: "revisionPrompt",
    label: "6. Final revision prompt",
    description: (
      <>
        Runs last, in a new ChatGPT chat — the bullets, company summaries, and
        overall summary just written are handed over first, then this prompt
        asks ChatGPT to revise them. Requires ChatGPT to be connected on the{" "}
        <strong>Settings</strong> tab; if it isn't, this step is skipped and
        DeepSeek's own text is used instead. No placeholders — it applies
        style rules to the resume ChatGPT was just given, not to individual
        fields.
      </>
    ),
    rows: 10,
  },
  {
    key: "corpusPrompt",
    label: "Database generation prompt",
    description: (
      <>
        Stored, not sent — separate from the six above, and not part of
        extraction. This is the prompt you paste into your AI tool to produce
        a <code>database.json</code>, kept here so the wording that produced
        a corpus is recorded beside it and you can start from the same
        instructions next time. Paste the result into the database editor
        below.
      </>
    ),
    rows: 14,
  },
];
