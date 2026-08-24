"""Resume content model shared by every template (RG-FR-001).

Content is deliberately separate from styling: changing a template or style
must never modify resume content (RG-FR-012).
"""

from pydantic import BaseModel, ConfigDict, Field


class Education(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    university: str
    degree: str = ""
    # Spec asks for year-only periods, e.g. 2013-2017.
    startYear: str = ""
    endYear: str = ""
    location: str = ""


class Experience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    company: str
    title: str = ""
    location: str = ""
    startDate: str = ""
    endDate: str = ""
    # RG-FR-007: current roles render "Present" instead of an end date.
    current: bool = False
    # Optional company/product context rendered separately from achievement
    # bullets by layout v2 templates.
    companySummary: str = ""
    # Newline-separated; each line becomes its own bullet (RG-FR-005).
    description: str = ""


class Skill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    # RG-FR-006: uncategorised skills fall back to a consistent bucket.
    category: str = "Other"


class ProfileInfo(BaseModel):
    """Personal details captured during setup."""

    model_config = ConfigDict(extra="forbid")

    fullName: str = ""
    professionalTitle: str = ""
    email: str = ""
    phone: str = ""
    street: str = ""
    city: str = ""
    state: str = ""
    postal: str = ""
    birthday: str = ""
    linkedin: str = ""
    website: str = ""
    summary: str = ""


class ResumeData(BaseModel):
    """The complete content payload handed to a template renderer."""

    model_config = ConfigDict(extra="forbid")

    profile: ProfileInfo = Field(default_factory=ProfileInfo)
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)


class Profile(BaseModel):
    """A saved resume profile: identity plus its resume content."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    data: ResumeData = Field(default_factory=ResumeData)
    createdAt: str = ""
    updatedAt: str = ""


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    data: ResumeData = Field(default_factory=ResumeData)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    data: ResumeData | None = None
