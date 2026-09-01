from pydantic import BaseModel, ConfigDict, Field


class CoverLetterData(BaseModel):
    """The complete content payload handed to the cover letter renderer.

    Mirrors the shape _parse_cover_letter_xml() (experience_service.py)
    produces from step 10's <cover_letter> XML reply.
    """

    model_config = ConfigDict(extra="forbid")

    jobTitle: str = ""
    companyName: str = ""
    candidateName: str = ""
    # From the profile, not step 10's XML -- ProfileInfo already has these,
    # so there's no need to have the model restate them. Shown only when
    # non-empty (see CoverLetterRenderer.tsx).
    phone: str = ""
    email: str = ""
    linkedin: str = ""
    greeting: str = "Dear Hiring Manager,"
    paragraphs: list[str] = Field(default_factory=list)
    closing: str = "Sincerely,"
