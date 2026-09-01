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
  | "requirementsPrompt"
  | "matchingRequirementsPrompt"
  | "selectionPrompt"
  | "syntheticGenerationPrompt"
  | "bulletsPrompt"
  | "resumeContentPrompt"
  | "finalResumePrompt"
  | "validationPrompt"
  | "coverLetterPrompt"
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
    key: "requirementsPrompt",
    label: "0a. Job requirements prompt (new architecture, step 1)",
    description: (
      <>
        The new pipeline's actual step 1 — parses the job description into a
        structured requirements object (skills, responsibilities, system
        types, leadership expectations, business outcomes, ATS keywords, a
        weighted matching-priority list) as JSON, for downstream retrieval
        and matching to consume. Its full output is logged to the console.
        The numbered prompts below are the old pipeline; extraction
        currently stops right after step 10 (below), before reaching them,
        while the rest of the new architecture is built out.
      </>
    ),
    rows: 8,
  },
  {
    key: "matchingRequirementsPrompt",
    label: "0b. Matching requirements prompt (new architecture, step 2)",
    description: (
      <>
        Runs right after step 1, in that same chat — converts the structured
        analysis into atomic, independently matchable requirements (one
        semantic-search query each) for retrieval, coverage-gap detection,
        synthetic experience generation, and match scoring. No
        placeholders: it's a pure follow-up relying entirely on step 1's
        reply already being in the conversation. Its full output is logged
        to the console.
      </>
    ),
    rows: 8,
  },
  {
    key: "selectionPrompt",
    label: "0c. Selection & coverage prompt (new architecture, step 4)",
    description: (
      <>
        Runs right after step 2, in that same chat — but step 3's own
        output (Company 1's candidate challenges, the Company 2 shortlist)
        is pure Python/sentence-transformers, so it's not already in the
        conversation; it's included in this message explicitly, followed by
        this prompt exactly as written. Chooses exactly one Company 2 from
        step 3's shortlist, selects which retrieved challenges ground each
        company's section, and classifies every important requirement as
        strong/partial/uncovered with gap recommendations for a future
        generation step. Its full output is logged to the console.
      </>
    ),
    rows: 8,
  },
  {
    key: "syntheticGenerationPrompt",
    label: "0d. Synthetic experience prompt (new architecture, step 5)",
    description: (
      <>
        Runs right after step 4, in that same chat — a pure follow-up, no
        placeholders and nothing re-sent: step 4 ran in this chat, so its
        gaps/generation_targets (and the retrieved challenges it saw) are
        already in the conversation. Generates structured synthetic
        challenges ONLY for the requirements step 4 flagged as still
        needing coverage, fit to whichever company (1 or 2) and timeline
        each gap was recommended for. Does not write resume bullets — this
        is still source experience, one level below that. Its full output
        is logged to the console.
      </>
    ),
    rows: 8,
  },
  {
    key: "bulletsPrompt",
    label: "0e. Resume bullets prompt (new architecture, step 6)",
    description: (
      <>
        Runs right after step 5, in that same chat — a pure follow-up, no
        placeholders and nothing re-sent: steps 4 and 5 ran in this chat,
        so the grounding plan, retrieved challenges, and synthetic
        experience it needs are already in the conversation. Writes exactly
        6 final resume bullets for Company 1 and 8 for Company 2, grounded
        only in that already-established experience — no new facts,
        metrics, or technologies. Its full output is logged to the console.
      </>
    ),
    rows: 8,
  },
  {
    key: "resumeContentPrompt",
    label: "0f. Resume content prompt (new architecture, step 7)",
    description: (
      <>
        Runs right after step 6, in that same chat — a pure follow-up, no
        placeholders and nothing re-sent: everything it needs (coverage,
        both companies' established role levels, and step 6's final
        bullets) is already in the conversation. Writes the overall resume
        title, professional summary, skill set, each company's own role
        title, and company summaries — and copies step 6's bullets back
        exactly, unchanged. Its full output is logged to the console.
      </>
    ),
    rows: 8,
  },
  {
    key: "finalResumePrompt",
    label: "0g. Final formatting prompt (new architecture, step 8)",
    description: (
      <>
        Runs right after step 7, in that same chat — a pure follow-up, no
        placeholders and nothing re-sent: step 7 ran in this chat, so the
        finalized content it must preserve verbatim is already in the
        conversation. Format-only: wraps selective, already-existing words
        in [keyword] markers, bolds each skill category's name, and returns
        the whole resume as the &lt;resume&gt; XML structure the rest of the
        app expects — no new content, no rewording. Its full output is
        logged to the console.
      </>
    ),
    rows: 8,
  },
  {
    key: "validationPrompt",
    label: "0h. Final validation prompt (new architecture, step 9)",
    description: (
      <>
        Would run right after step 8, in that same chat — a pure follow-up,
        no placeholders and nothing re-sent: every prior step ran in this
        chat, so everything it checks against is already in the
        conversation. Validation-only: checks XML validity, Step 7→8
        content preservation, each company's bullet count, metric
        preservation, skills, keyword-marker limits, JD requirement
        coverage, and a final job-match score — without rewriting the
        resume. Currently skipped in extraction (step 10, below, runs right
        after step 8 instead), but still editable here for whenever it's
        re-enabled.
      </>
    ),
    rows: 8,
  },
  {
    key: "coverLetterPrompt",
    label: "0i. Cover letter prompt (new architecture, step 10)",
    description: (
      <>
        Runs right after step 8, in that same chat (step 9 is skipped) — a
        pure follow-up, no placeholders and nothing re-sent: the finalized
        resume it must stay consistent with is already in the conversation.
        Writes a concise, tailored cover letter grounded only in
        already-established resume evidence, returned as XML. Extraction
        currently stops right after this step, before reaching the numbered
        prompts below, while the rest of the new architecture is built out.
        Its full output is logged to the console.
      </>
    ),
    rows: 8,
  },
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
        Runs in the first ChatGPT chat, once the bullets, summary, and titles all
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
        Runs in that same chat — asks it to assemble everything
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
        Runs last, still in that same chat — the resume it just assembled is
        included in the same message, then this prompt asks ChatGPT to
        revise it. Requires ChatGPT to be connected on the{" "}
        <strong>Settings</strong> tab; if it isn't, this step is skipped and
        the unrevised text is used instead. No placeholders — it applies
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
