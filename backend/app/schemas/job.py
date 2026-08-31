from pydantic import BaseModel


class JobListing(BaseModel):
    id: str
    title: str
    company: str
    location: str
    url: str
    salary: str | None = None
    work_model: str | None = None
    publish_time: str | None = None
    publish_time_desc: str | None = None
    match_score: str | None = None
    description: str | None = None
    skills: str | None = None


class StoredJob(BaseModel):
    """A job as held in the database, which is what the table renders."""

    id: str
    source: str = "jobright"
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    description: str = ""
    salary: str = ""
    work_model: str = ""
    match_score: str = ""
    publish_time: str = ""
    publish_time_desc: str = ""
    skills: str = ""
    application_status: str = "not_applied"
    # The date the job was added, as the table shows and edits it.
    date_added: str = ""
    # "" | "ready" | "applied" -- what the Status column displays.
    status: str = ""
    # Status cannot be chosen until a resume exists for the row.
    hasResume: bool = False
    applied_at: str | None = None
    first_seen_at: str = ""
    last_seen_at: str = ""
    # Derived server-side so every caller agrees on what "applied" means.
    applied: bool = False
    # Nothing may act on a locked job: no extraction, no generation, no import
    # overwrite. Today that is exactly "applied", but the pipeline checks this
    # flag rather than the status, so a second reason to freeze a row is a
    # one-line change here.
    locked: bool = False


class ExtractSkillsRequest(BaseModel):
    description: str
    prompt: str


class ExtractSkillsResponse(BaseModel):
    skills: str
