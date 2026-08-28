/** Shared by ProfilePage (where prompts are edited, one profile at a time)
 *  and anywhere else that needs to describe what each prompt does. */

/** Mirrors TAILORING_PLACEHOLDERS in backend settings_service.py. */
export const TAILORING_PLACEHOLDERS = [
  "count",
  "company",
  "product",
  "role_order",
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

/** Mirrors SKILL_SET_PLACEHOLDERS in backend settings_service.py. */
export const SKILL_SET_PLACEHOLDERS = [
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
  | "skillSetPrompt"
  | "wholeResumePrompt"
  | "revisionPrompt"
  | "keywordsPrompt"
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
        Pulls the required skills, the job mission, and the industry out of
        the description as XML. Every tag inside &lt;extraction&gt; becomes
        a labeled part of the search query (skills: ... - mission: ... -
        industry: ...) with no code change needed — add a tag here and it
        just works. Results appear in the console.
      </>
    ),
    rows: 8,
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
        Runs once, in one turn, once the summary exists — writes the
        professional title at the top of the generated resume AND each
        company's own title below its name, together. Leave it blank on a
        job and the profile's own title is used. Placeholders:{" "}
        <PlaceholderList tokens={TITLE_PLACEHOLDERS} />.
      </>
    ),
    placeholders: TITLE_PLACEHOLDERS,
    rows: 12,
  },
  {
    key: "skillSetPrompt",
    label: "6. Skill set prompt",
    description: (
      <>
        Runs in the DeepSeek chat, once the bullets, summary, and titles all
        exist, and writes the resume's skill set as a list. Positioned on
        the resume wherever the template's own "skills" block is placed —
        right after Summary by default. Placeholders:{" "}
        <PlaceholderList tokens={SKILL_SET_PLACEHOLDERS} />.
      </>
    ),
    placeholders: SKILL_SET_PLACEHOLDERS,
    rows: 10,
  },
  {
    key: "wholeResumePrompt",
    label: "7. Generate whole resume prompt",
    description: (
      <>
        Runs last in the DeepSeek chat — asks it to assemble everything
        written so far (both companies' bullets and summaries, the overall
        summary, the skill set) into the complete resume, using what it
        already has in context rather than that being pasted back in. No
        placeholders — pure style instruction, same as the revision and
        keyword prompts below.
      </>
    ),
    rows: 10,
  },
  {
    key: "revisionPrompt",
    label: "8. Final revision prompt",
    description: (
      <>
        Runs last, in a new ChatGPT chat — the resume DeepSeek just
        assembled is handed over first, then this prompt asks ChatGPT to
        revise it. Requires ChatGPT to be connected on the{" "}
        <strong>Settings</strong> tab; if it isn't, this step is skipped and
        DeepSeek's own text is used instead. No placeholders — it applies
        style rules to the resume ChatGPT was just given, not to individual
        fields.
      </>
    ),
    rows: 10,
  },
  {
    key: "keywordsPrompt",
    label: "9. Keyword marking prompt",
    description: (
      <>
        A second message in that SAME ChatGPT chat, right after the revision
        reply — so it still has the revised text in context — asking it to
        wrap the resume's main keywords in square brackets, like{" "}
        <code>[REST]</code>. The PDF renders anything between square brackets
        bold. No placeholders — like the revision prompt, this is pure style
        instruction applied to the resume ChatGPT just gave you.
      </>
    ),
    rows: 8,
  },
  {
    key: "corpusPrompt",
    label: "Database generation prompt",
    description: (
      <>
        Stored, not sent — separate from the eight above, and not part of
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
