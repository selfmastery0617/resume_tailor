export interface Job {
  id: string;
  title: string;
  company: string;
  location: string;
  url: string;
  /** Direct posting URL used by the Extract JD batch. */
  job_url?: string;
  salary?: string | null;
  work_model?: string | null;
  publish_time?: string | null;
  publish_time_desc?: string | null;
  match_score?: string | null;
  description?: string | null;
  skills?: string | null;

  // -- persisted state (jobs are stored server-side now) -------------------
  source?: string;
  application_status?: string;
  /** The date the job was added, as the table shows and edits it. */
  date_added?: string;
  /** "" | "ready" | "applied" — what the Status column displays. */
  status?: string;
  /** Status cannot be chosen until a resume exists for the row. */
  hasResume?: boolean;
  /** ISO timestamp, null until the job is marked applied. */
  applied_at?: string | null;
  applied?: boolean;
  /** Nothing may act on a locked job: no extraction, no generation. */
  locked?: boolean;
  first_seen_at?: string;
  last_seen_at?: string;
}
