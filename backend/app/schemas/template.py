from pydantic import BaseModel, ConfigDict, Field

from app.schemas.style import ResumeStyleOverrides


class TemplateDefinition(BaseModel):
    """A registered template (TM-FR-001).

    defaultStyle is a partial style: only the fields this template deviates
    from the system defaults on. That way a later change to a system default
    still reaches templates that never overrode it.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    version: int = Field(ge=1)
    active: bool = True
    rendererKey: str
    defaultStyle: dict = Field(default_factory=dict)
    supportedStyleFields: list[str] = Field(default_factory=list)


class TemplateListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    templates: list[TemplateDefinition]
    # The system-default layer. Shipped with the catalog so the client can
    # compute the same effective style the server would, without guessing at
    # defaults or needing a second request (§4.6: one calculation everywhere).
    systemDefaultStyle: dict = Field(default_factory=dict)


class ProfileTemplateSettings(BaseModel):
    """Per-profile template selection and style overrides."""

    model_config = ConfigDict(extra="forbid")

    profileId: str
    templateId: str
    templateVersion: int
    styleOverrides: dict = Field(default_factory=dict)
    effectiveStyle: dict = Field(default_factory=dict)
    updatedAt: str


class SaveTemplateSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    templateId: str
    styleOverrides: dict = Field(default_factory=dict)


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retryable: bool = False


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail


# Style overrides are validated through this model at the API boundary.
__all__ = [
    "TemplateDefinition",
    "TemplateListResponse",
    "ProfileTemplateSettings",
    "SaveTemplateSettingsRequest",
    "ErrorDetail",
    "ErrorResponse",
    "ResumeStyleOverrides",
]
