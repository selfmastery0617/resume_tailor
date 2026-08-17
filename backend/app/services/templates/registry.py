"""Canonical template registry (TM-FR-001, TM-FR-005).

This is the *only* template-to-renderer mapping. Definitions live in source
control so template defaults are reviewable and versioned; user edits are
stored separately as per-profile overrides and never rewrite this file.

Inactive templates stay resolvable so historical generated resumes can still
be reproduced (TM-FR-006 / US-TM-05).
"""

from app.schemas.style import ResumeStyle
from app.schemas.template import TemplateDefinition

DEFAULT_TEMPLATE_ID = "template-1"

# Style fields every renderer honours. Templates that support less declare it
# explicitly so the editor can disable those controls (RG-FR-011) rather than
# letting a user edit a setting the template silently ignores.
_UNIVERSAL_STYLE_FIELDS: tuple[str, ...] = tuple(ResumeStyle.model_fields.keys())


def _definition(
    number: int,
    name: str,
    description: str,
    default_style: dict,
    *,
    unsupported: tuple[str, ...] = (),
) -> TemplateDefinition:
    return TemplateDefinition(
        id=f"template-{number}",
        name=name,
        description=description,
        version=1,
        active=True,
        rendererKey=f"renderer-{number}",
        defaultStyle=default_style,
        supportedStyleFields=[f for f in _UNIVERSAL_STYLE_FIELDS if f not in unsupported],
    )


_TEMPLATES: tuple[TemplateDefinition, ...] = (
    _definition(
        1,
        "Template 1",
        "Classic single-column layout. The default configuration.",
        {},
    ),
    _definition(
        2,
        "Template 2",
        "Compact single-column layout for dense, experience-heavy resumes.",
        {"bodySize": 9.5, "sectionTopInches": 0.08, "bulletGapInches": 0.02},
    ),
    _definition(
        3,
        "Template 3",
        "Modern sans-serif with a centred header.",
        {
            "fontFamily": "Helvetica",
            "nameTextAlign": "center",
            "titleTextAlign": "center",
            "contactTextAlign": "center",
        },
    ),
    _definition(
        4,
        "Template 4",
        "Warm editorial design with serif headings.",
        {"fontFamily": "Georgia", "sectionColor": "#7c2d12", "nameColor": "#7c2d12"},
    ),
    _definition(
        5,
        "Template 5",
        "Traditional Times New Roman layout for conservative industries.",
        {"fontFamily": "Times New Roman", "showHeaderDivider": False},
    ),
    _definition(
        6,
        "Template 6",
        "Skills-forward ordering that leads with capabilities.",
        {"sectionOrder": ["summary", "skills", "experience", "education"]},
    ),
    _definition(
        7,
        "Template 7",
        "Academic layout leading with education.",
        {"sectionOrder": ["summary", "education", "experience", "skills"]},
    ),
    _definition(
        8,
        "Template 8",
        "High-contrast minimal design with no summary by default.",
        {"showSummary": False, "sectionColor": "#000000", "bulletChar": "-"},
    ),
    _definition(
        9,
        "Template 9",
        "Spacious layout with generous section separation.",
        {"sectionTopInches": 0.2, "sectionBottomInches": 0.14, "bodyLineHeight": 1.5},
    ),
    _definition(
        10,
        "Template 10",
        "Cool-toned professional design with blue section headings.",
        {"sectionColor": "#1d4ed8", "nameColor": "#1e3a8a", "fontFamily": "System UI"},
    ),
)

_BY_ID: dict[str, TemplateDefinition] = {t.id: t for t in _TEMPLATES}


def list_templates(include_inactive: bool = False) -> list[TemplateDefinition]:
    """Active templates in deterministic (registry) order."""
    return [t for t in _TEMPLATES if include_inactive or t.active]


def get_template(template_id: str) -> TemplateDefinition | None:
    """Exact lookup. Returns None when the id is unknown."""
    return _BY_ID.get(template_id)


def resolve_template(template_id: str | None, *, fallback: bool = True) -> TemplateDefinition:
    """Resolve a template for ordinary previews.

    Falls back to template-1 for unknown ids (TM-FR-004). Callers reproducing a
    historical resume must pass fallback=False so an unresolvable template
    raises instead of silently rendering the wrong design.
    """
    if template_id:
        found = _BY_ID.get(template_id)
        if found is not None:
            return found
    if not fallback:
        raise KeyError(f"Template not found: {template_id!r}")
    return _BY_ID[DEFAULT_TEMPLATE_ID]
