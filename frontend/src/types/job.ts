export interface Job {
  id: string;
  title: string;
  company: string;
  location: string;
  url: string;
  salary?: string | null;
  work_model?: string | null;
  publish_time?: string | null;
  publish_time_desc?: string | null;
  match_score?: string | null;
  description?: string | null;
  skills?: string | null;
}
