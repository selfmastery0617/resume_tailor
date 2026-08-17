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


class ExtractSkillsRequest(BaseModel):
    description: str
    prompt: str


class ExtractSkillsResponse(BaseModel):
    skills: str
