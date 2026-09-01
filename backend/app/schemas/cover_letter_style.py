"""CoverLetterStyle model, validation, and the effective-style merge.

Deliberately not a subset of ResumeStyle (app/schemas/style.py): that model's
~30 fields are resume-section-specific (name/title/contact sizes, section
colors, bullet indent, section order, ...), none of which apply to a letter.
A cover letter has exactly one fixed structure (greeting, paragraphs,
closing, signature), so its style is narrowed to what the user actually
asked for: page size, font, spacing, and margins.

Same precedence and two-model pattern as style.py:

    system defaults -> template defaults -> profile overrides -> generation overrides

* ``CoverLetterStyle``          - every field populated; the system defaults.
* ``CoverLetterStyleOverrides`` - every field optional, derived via
  create_model so it can never drift from CoverLetterStyle.
"""

from pydantic import BaseModel, ConfigDict, create_model, field_validator

from app.schemas.layout import PaperSize
from app.schemas.style import APPROVED_FONTS


class CoverLetterStyle(BaseModel):
    """Fully-populated cover letter style. This is the system-default layer."""

    model_config = ConfigDict(extra="forbid")

    # -- Paging ------------------------------------------------------------
    pageSize: PaperSize = "letter"
    marginTopIn: float = 1.0
    marginBottomIn: float = 1.0
    marginLeftIn: float = 1.0
    marginRightIn: float = 1.0

    # -- Font ----------------------------------------------------------------
    fontFamily: str = "Times New Roman"
    fontSize: float = 11.0

    # -- Spacing -------------------------------------------------------------
    lineHeight: float = 1.15
    paragraphSpacingIn: float = 0.15

    @field_validator("fontFamily")
    @classmethod
    def _check_font(cls, v: str) -> str:
        if v not in APPROVED_FONTS:
            raise ValueError(f"Unapproved font {v!r}. Allowed: {', '.join(APPROVED_FONTS)}")
        return v

    @field_validator("fontSize")
    @classmethod
    def _check_font_size(cls, v: float) -> float:
        if not 8 <= v <= 14:
            raise ValueError(f"fontSize must be between 8 and 14 pt, got {v}")
        return v

    @field_validator("lineHeight")
    @classmethod
    def _check_line_height(cls, v: float) -> float:
        if not 1.0 <= v <= 2.0:
            raise ValueError(f"lineHeight must be between 1.0 and 2.0, got {v}")
        return v

    @field_validator("paragraphSpacingIn")
    @classmethod
    def _check_paragraph_spacing(cls, v: float) -> float:
        if not 0 <= v <= 0.5:
            raise ValueError(f"paragraphSpacingIn must be between 0 and 0.5, got {v}")
        return v

    @field_validator("marginTopIn", "marginBottomIn", "marginLeftIn", "marginRightIn")
    @classmethod
    def _check_margin(cls, v: float) -> float:
        if not 0 <= v <= 2:
            raise ValueError(f"Margins must be between 0 and 2 inches, got {v}")
        return v


# Every field optional, defaulting to None. Derived from CoverLetterStyle
# rather than restating fields by hand, which would drift out of sync.
#
# This model only checks *shape* (known keys, right types). Value rules
# (ranges, approved fonts) are enforced by merge_cover_letter_style() ->
# CoverLetterStyle, so overrides and full styles can never diverge on what
# counts as valid. Use validate_cover_letter_overrides() to check a payload
# alone.
CoverLetterStyleOverrides = create_model(
    "CoverLetterStyleOverrides",
    __config__=ConfigDict(extra="forbid"),
    **{
        name: (field.annotation | None, None)
        for name, field in CoverLetterStyle.model_fields.items()
    },
)


def merge_cover_letter_style(*layers: dict | None) -> CoverLetterStyle:
    """Merge style layers left-to-right; later layers win.

    Only keys that are actually present (non-None) override earlier layers, so
    a profile that never set ``fontSize`` keeps inheriting the template
    default even when that default later changes.
    """
    merged: dict = CoverLetterStyle().model_dump()
    for layer in layers:
        if not layer:
            continue
        for key, value in layer.items():
            if value is None:
                continue
            if key not in merged:
                raise ValueError(f"Unknown cover letter style field: {key!r}")
            merged[key] = value
    return CoverLetterStyle(**merged)


def validate_cover_letter_overrides(overrides: dict | None) -> dict:
    """Validate an override payload on its own and return the cleaned dict.

    Rejects unknown fields and invalid values, and drops None entries so a
    reset removes the override rather than pinning the current default.
    """
    if not overrides:
        return {}
    parsed = CoverLetterStyleOverrides(**overrides)
    cleaned = parsed.model_dump(exclude_none=True)
    normalized = merge_cover_letter_style(cleaned).model_dump()
    return {key: normalized[key] for key in cleaned}
