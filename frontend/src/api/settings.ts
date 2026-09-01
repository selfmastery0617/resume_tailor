import axios from "axios";
import { BACKEND_URL } from "../config";

export type GenerationModel = "deepseek" | "chatgpt";

export interface AppSettings {
  /** New pipeline architecture, step 1: parses the job description into a
   *  structured requirements object (JSON) for downstream retrieval and
   *  matching. */
  requirementsPrompt: string;
  /** Step 2, right after step 1 in the same chat: converts that analysis
   *  into atomic matching requirements (JSON). */
  matchingRequirementsPrompt: string;
  /** Step 4 (step 3 is pure Python/sentence-transformers, no prompt):
   *  chooses Company 2 from step 3's shortlist, selects grounding
   *  challenges, and classifies requirement coverage (JSON). */
  selectionPrompt: string;
  /** Step 5, right after step 4 in the same chat: generates structured
   *  synthetic experience (JSON) only for step 4's own gaps/
   *  generation_targets. */
  syntheticGenerationPrompt: string;
  /** Step 6, right after step 5 in the same chat: writes the final resume
   *  bullets (6 for Company 1, 8 for Company 2) from the retrieved and
   *  synthetic experience already established. */
  bulletsPrompt: string;
  /** Step 7, right after step 6 in the same chat: writes the overall resume
   *  title, professional summary, skill set, each company's own role title,
   *  and company summaries around step 6's now-final bullets, which it
   *  copies back unchanged. */
  resumeContentPrompt: string;
  /** Step 8, right after step 7 in the same chat: a format-only pass that
   *  wraps selective, already-existing words in [keyword] markers, bolds
   *  each skill category's name, and returns the whole resume as XML. */
  finalResumePrompt: string;
  /** Step 9: a validation-only pass that checks XML validity, Step 7->8
   *  content preservation, bullet counts, metric preservation, skills,
   *  keyword-marker limits, JD coverage, and a final job-match score --
   *  without rewriting anything. Currently skipped in extraction (step 10
   *  runs right after step 8 instead), but still editable here for
   *  whenever it's re-enabled. */
  validationPrompt: string;
  /** Step 10, right after step 8 in the same chat (step 9 is skipped):
   *  writes a tailored cover letter grounded in the finalized resume,
   *  returned as XML. Extraction currently stops right after this step. */
  coverLetterPrompt: string;
  skillsPrompt: string;
  tailoringPrompt: string;
  /** Writes the resume summary from the bullets, in the same ChatGPT chat
   *  every prompt for this job runs in. */
  summaryPrompt: string;
  /** Writes the resume headline and each company's own title together, in
   *  one turn, once the summary exists. */
  titlePrompt: string;
  /** Writes one summary per role (Job 1, Job 2), right after that role's own
   *  bullets, in the same chat. */
  companySummaryPrompt: string;
  /** Writes the resume's skill set in the same chat, before the whole
   *  resume is assembled. Positioned on the resume wherever the
   *  template's own "skills" block is placed (right after Summary by default). */
  skillSetPrompt: string;
  /** Runs in the same chat: assembles the complete resume from everything
   *  already written, before the revision prompt below revises it. */
  wholeResumePrompt: string;
  /** Runs last, still in the same chat: revises the resume it just assembled. */
  revisionPrompt: string;
  /** One further message in that same chat, marking main keywords by
   *  wrapping them in [square brackets] -- the PDF renders those bold. */
  keywordsPrompt: string;
  /** Drafts a profile's database.json from its experience. Not part of
   *  extraction — run on demand from the Profile tab. */
  corpusPrompt: string;
  outputFolder: string;
  generationModel: GenerationModel;
  /** Company used as Job 1 (the earlier role) in experience extraction. */
  firstCompany: string;
  /** The first company's years. Job 1 runs start->end and Job 2 runs
   *  end->present, so these two numbers date every tailored resume. */
  firstCompanyStartYear: string;
  firstCompanyEndYear: string;
  /** How much a challenge's industry-similarity score counts toward its
   *  ranking score during Job 1/Job 2 selection -- a number from 0 to 1,
   *  as a string (settings are stored as text). Profile-scoped, like
   *  firstCompany. */
  industryWeight: string;
  /** Profile used for tailored resume PDFs; its name becomes the file name.
   *  Empty means "use the first profile". */
  resumeProfile: string;
}

export interface FolderCheck {
  valid: boolean;
  detail: string;
  resolved?: string;
}

export interface FolderSelection extends FolderCheck {
  cancelled: boolean;
}

export async function fetchSettings(): Promise<AppSettings> {
  const response = await axios.get<AppSettings>(`${BACKEND_URL}/api/settings`);
  return response.data;
}

export async function saveSettings(patch: Partial<AppSettings>): Promise<AppSettings> {
  const response = await axios.put<AppSettings>(`${BACKEND_URL}/api/settings`, patch);
  return response.data;
}

export async function checkFolder(path: string): Promise<FolderCheck> {
  const response = await axios.post<FolderCheck>(`${BACKEND_URL}/api/settings/check-folder`, {
    path,
  });
  return response.data;
}

export async function selectFolder(initialPath?: string): Promise<FolderSelection> {
  const response = await axios.post<FolderSelection>(
    `${BACKEND_URL}/api/settings/select-folder`,
    { initialPath: initialPath || null },
  );
  return response.data;
}

// -- ChatGPT session (mirrors the DeepSeek client) ------------------------

