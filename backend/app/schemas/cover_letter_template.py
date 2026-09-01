from pydantic import BaseModel, ConfigDict, Field

from app.schemas.cover_letter_style import CoverLetterStyleOverrides


class CoverLetterTemplateDefinition(BaseModel):
    """A registered cover letter template preset.

    Unlike resume TemplateDefinition (app/schemas/template.py), there is no
    rendererKey/layout/supportedStyleFields: every cover letter renders with
    the same fixed structure (greeting, paragraphs, closing, signature), so a
    "template" here is purely a named preset of defaultStyle -- page size,
    font, spacing, margins. All fields are always supported.

    defaultStyle is a partial style: only the fields this preset deviates
    from the system defaults on, so a later change to a system default still
    reaches presets that never overrode it.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    defaultStyle: dict = Field(default_factory=dict)


class CoverLetterTemplateListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    templates: list[CoverLetterTemplateDefinition]
    systemDefaultStyle: dict = Field(default_factory=dict)


class ProfileCoverLetterTemplateSettings(BaseModel):
    """Per-profile cover letter template selection and style overrides."""

    model_config = ConfigDict(extra="forbid")

    profileId: str
    templateId: str
    styleOverrides: dict = Field(default_factory=dict)
    effectiveStyle: dict = Field(default_factory=dict)
    updatedAt: str


class SaveCoverLetterTemplateSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    templateId: str
    styleOverrides: dict = Field(default_factory=dict)


__all__ = [
    "CoverLetterTemplateDefinition",
    "CoverLetterTemplateListResponse",
    "ProfileCoverLetterTemplateSettings",
    "SaveCoverLetterTemplateSettingsRequest",
    "CoverLetterStyleOverrides",
]
