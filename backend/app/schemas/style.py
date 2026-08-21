"""ResumeStyle model, validation, and the effective-style merge.

Precedence (TM-FR / section 4.6):

    system defaults -> template defaults -> profile overrides -> generation overrides

Two models exist deliberately:

* ``ResumeStyle``          - every field populated; the system defaults.
* ``ResumeStyleOverrides`` - every field optional; used for template defaults,
  per-profile overrides, and one-time generation overrides.

Unknown fields are rejected rather than silently persisted.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

SectionId = Literal["summary", "experience", "skills", "education"]
PersonalField = Literal["address", "phone", "email", "birthday"]
TextAlign = Literal["left", "center", "right"]

# Broad document-font catalog shared with the frontend. Chromium uses an
# installed face when available and a category-safe fallback otherwise.
APPROVED_FONTS = (
    "Template default",
    "Arial",
    "Arial Black",
    "Arial Narrow",
    "Book Antiqua",
    "Calibri",
    "Cambria",
    "Candara",
    "Century Gothic",
    "Comic Sans MS",
    "Consolas",
    "Courier New",
    "Garamond",
    "Georgia",
    "Helvetica",
    "Impact",
    "Lucida Console",
    "Lucida Sans Unicode",
    "Palatino Linotype",
    "Segoe UI",
    "System UI",
    "Tahoma",
    "Times New Roman",
    "Trebuchet MS",
    "Verdana",
    "Alegreya",
    "Bitter",
    "Cabin",
    "Comfortaa",
    "Crimson Text",
    "EB Garamond",
    "Fira Sans",
    "IBM Plex Sans",
    "Inconsolata",
    "Inter",
    "Lato",
    "Lexend",
    "Libre Baskerville",
    "Libre Franklin",
    "Merriweather",
    "Montserrat",
    "Noto Sans",
    "Noto Serif",
    "Open Sans",
    "Oswald",
    "Playfair Display",
    "Poppins",
    "PT Sans",
    "PT Serif",
    "Raleway",
    "Roboto",
    "Roboto Condensed",
    "Roboto Mono",
    "Source Sans 3",
    "Source Serif 4",
    "Ubuntu",
    "Work Sans",
)

ALLOWED_BULLET_CHARS = ("●", "•", "◦", "-", "*", "▪", "▸")

DEFAULT_SECTION_ORDER: list[SectionId] = ["summary", "experience", "skills", "education"]
DEFAULT_PERSONAL_ORDER: list[PersonalField] = ["address", "phone", "email", "birthday"]

_HEX_COLOR = r"^#[0-9a-fA-F]{6}$"


def _unique_order(values: list[str], allowed: tuple[str, ...], label: str) -> list[str]:
    """Reject duplicates/unknowns, then append any missing ids in default order."""
    seen: set[str] = set()
    for value in values:
        if value not in allowed:
            raise ValueError(f"Unknown {label}: {value!r}. Allowed: {', '.join(allowed)}")
        if value in seen:
            raise ValueError(f"Duplicate {label}: {value!r}")
        seen.add(value)
    # Missing entries are appended in the template's default order rather than
    # dropped, so a partial order never hides a section permanently.
    return list(values) + [item for item in allowed if item not in seen]


class ResumeStyle(BaseModel):
    """Fully-populated style. This is the system-default layer."""

    model_config = ConfigDict(extra="forbid")

    # -- Typography ------------------------------------------------------
    fontFamily: str = "Template default"
    nameSize: float = 22
    titleSize: float = 12
    contactSize: float = 10
    sectionSize: float = 12
    bodySize: float = 10
    bodyLineHeight: float = 1.35
    nameBold: bool = True
    nameItalic: bool = False
    titleBold: bool = False
    titleItalic: bool = False
    contactBold: bool = False
    contactItalic: bool = False

    # -- Colors ----------------------------------------------------------
    nameColor: str = "#111111"
    titleColor: str = "#333333"
    contactColor: str = "#444444"
    sectionColor: str = "#111111"
    bodyColor: str = "#222222"

    # -- Alignment -------------------------------------------------------
    nameTextAlign: TextAlign = "left"
    titleTextAlign: TextAlign = "left"
    contactTextAlign: TextAlign = "left"

    # -- Sections --------------------------------------------------------
    sectionOrder: list[SectionId] = Field(default_factory=lambda: list(DEFAULT_SECTION_ORDER))
    showSummary: bool = True
    showHeaderDivider: bool = True

    # -- Contact visibility / order --------------------------------------
    personalOrder: list[PersonalField] = Field(default_factory=lambda: list(DEFAULT_PERSONAL_ORDER))
    showEmail: bool = True
    showPhone: bool = True
    showStreet: bool = False
    showCity: bool = True
    showState: bool = True
    showPostal: bool = False
    showBirthday: bool = False

    # -- Spacing (inches) ------------------------------------------------
    sectionTopInches: float = 0.12
    sectionBottomInches: float = 0.08
    bulletIndentInches: float = 0.18
    bulletGapInches: float = 0.04

    # -- Bullets ---------------------------------------------------------
    bulletChar: str = "•"
    bulletCount: int | None = None
    bulletLines: int | None = None
    perExperienceBulletCount: dict[str, int] = Field(default_factory=dict)

    # -- Page breaks -----------------------------------------------------
    forcePageBreakBeforeSections: list[SectionId] = Field(default_factory=list)
    forcePageBreakBeforeExperienceIds: list[str] = Field(default_factory=list)
    forcePageBreakBeforeEducationIds: list[str] = Field(default_factory=list)

    # -- Validators ------------------------------------------------------

    @field_validator("fontFamily")
    @classmethod
    def _check_font(cls, v: str) -> str:
        if v not in APPROVED_FONTS:
            raise ValueError(f"Unapproved font {v!r}. Allowed: {', '.join(APPROVED_FONTS)}")
        return v

    @field_validator("nameSize", "titleSize", "contactSize", "sectionSize", "bodySize")
    @classmethod
    def _check_pt(cls, v: float) -> float:
        if not 8 <= v <= 32:
            raise ValueError(f"Font size must be between 8 and 32 pt, got {v}")
        return v

    @field_validator("bodyLineHeight")
    @classmethod
    def _check_line_height(cls, v: float) -> float:
        if not 1.0 <= v <= 2.0:
            raise ValueError(f"bodyLineHeight must be between 1.0 and 2.0, got {v}")
        return v

    @field_validator("nameColor", "titleColor", "contactColor", "sectionColor", "bodyColor")
    @classmethod
    def _check_color(cls, v: str) -> str:
        import re

        if not re.match(_HEX_COLOR, v):
            raise ValueError(f"Color must be #RRGGBB, got {v!r}")
        return v

    @field_validator("sectionOrder")
    @classmethod
    def _check_section_order(cls, v: list[str]) -> list[str]:
        return _unique_order(v, tuple(DEFAULT_SECTION_ORDER), "section id")

    @field_validator("personalOrder")
    @classmethod
    def _check_personal_order(cls, v: list[str]) -> list[str]:
        return _unique_order(v, tuple(DEFAULT_PERSONAL_ORDER), "personal field")

    @field_validator("sectionTopInches", "sectionBottomInches", "bulletIndentInches")
    @classmethod
    def _check_inches_1(cls, v: float) -> float:
        if not 0 <= v <= 1:
            raise ValueError(f"Value must be between 0 and 1 inches, got {v}")
        return v

    @field_validator("bulletGapInches")
    @classmethod
    def _check_gap(cls, v: float) -> float:
        if not 0 <= v <= 0.5:
            raise ValueError(f"bulletGapInches must be between 0 and 0.5, got {v}")
        return v

    @field_validator("bulletChar")
    @classmethod
    def _check_bullet(cls, v: str) -> str:
        if v not in ALLOWED_BULLET_CHARS:
            raise ValueError(
                f"Unsupported bullet {v!r}. Allowed: {' '.join(ALLOWED_BULLET_CHARS)}"
            )
        return v

    @field_validator("bulletCount", "bulletLines")
    @classmethod
    def _check_bullet_count(cls, v: int | None) -> int | None:
        if v is not None and not 0 <= v <= 20:
            raise ValueError(f"Bullet count must be between 0 and 20, got {v}")
        return v

    @field_validator("perExperienceBulletCount")
    @classmethod
    def _check_per_experience(cls, v: dict[str, int]) -> dict[str, int]:
        for key, count in v.items():
            if not isinstance(count, int) or isinstance(count, bool):
                raise ValueError(f"Bullet count for {key!r} must be an integer")
            if not 0 <= count <= 20:
                raise ValueError(f"Bullet count for {key!r} must be between 0 and 20")
        return v


# Every field optional, defaulting to None. Derived from ResumeStyle rather
# than restating ~45 fields by hand, which would drift out of sync.
#
# This model only checks *shape* (known keys, right types). Value rules
# (ranges, hex colors, approved fonts, unique orders) are enforced by
# merge_style() -> ResumeStyle, so overrides and full styles can never diverge
# on what counts as valid. Use validate_overrides() to check a payload alone.
ResumeStyleOverrides = create_model(
    "ResumeStyleOverrides",
    __config__=ConfigDict(extra="forbid"),
    **{
        name: (field.annotation | None, None)
        for name, field in ResumeStyle.model_fields.items()
    },
)


def merge_style(*layers: dict | None) -> ResumeStyle:
    """Merge style layers left-to-right; later layers win.

    Only keys that are actually present (non-None) override earlier layers, so
    a profile that never set ``bodySize`` keeps inheriting the template default
    even when that default later changes.
    """
    merged: dict = ResumeStyle().model_dump()
    for layer in layers:
        if not layer:
            continue
        for key, value in layer.items():
            if value is None:
                continue
            if key not in merged:
                raise ValueError(f"Unknown style field: {key!r}")
            merged[key] = value
    return ResumeStyle(**merged)


def validate_overrides(overrides: dict | None) -> dict:
    """Validate an override payload on its own and return the cleaned dict.

    Rejects unknown fields and invalid values, and drops None entries so a
    reset removes the override rather than pinning the current default (4.5).
    """
    if not overrides:
        return {}
    parsed = ResumeStyleOverrides(**overrides)
    # Return Pydantic's normalized values, not the original input. Besides
    # making JSON storage deterministic, this prevents block-level overrides
    # from retaining coercible-but-wrong runtime types such as "12" for a
    # numeric font size.
    cleaned = parsed.model_dump(exclude_none=True)
    normalized = merge_style(cleaned).model_dump()
    # Keep override sparsity while retaining transformations made by the full
    # model (notably completing partial section/contact order arrays). This
    # makes the JSON consumed by browser preview identical to PDF rendering.
    return {key: normalized[key] for key in cleaned}
