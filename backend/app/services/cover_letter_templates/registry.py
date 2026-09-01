"""Canonical cover letter template registry.

Mirrors app/services/templates/registry.py's pattern (source-controlled
definitions, never rewritten by user edits, which live separately as
per-profile overrides) but is much simpler: there is no renderer/layout
diversity to register, since every cover letter renders through the same
fixed structure (greeting, paragraphs, closing, signature) -- a "template"
here is purely a named preset of page size, font, spacing, and margins.
"""

from app.schemas.cover_letter_template import CoverLetterTemplateDefinition

DEFAULT_COVER_LETTER_TEMPLATE_ID = "coverletter-1"


def _definition(number: int, name: str, description: str, default_style: dict) -> CoverLetterTemplateDefinition:
    return CoverLetterTemplateDefinition(
        id=f"coverletter-{number}",
        name=name,
        description=description,
        defaultStyle=default_style,
    )


_TEMPLATES: tuple[CoverLetterTemplateDefinition, ...] = (
    _definition(
        1,
        "Classic",
        "Traditional Times New Roman letter with standard 1in margins. The default.",
        {},
    ),
    _definition(
        2,
        "Compact",
        "Tighter margins and paragraph spacing for a longer letter.",
        {
            "marginTopIn": 0.75, "marginBottomIn": 0.75,
            "marginLeftIn": 0.75, "marginRightIn": 0.75,
            "paragraphSpacingIn": 0.1,
        },
    ),
    _definition(
        3,
        "Modern Sans",
        "Clean Helvetica letterhead for a contemporary look.",
        {"fontFamily": "Helvetica"},
    ),
    _definition(
        4,
        "Spacious",
        "Generous margins and line height for an airy, formal feel.",
        {
            "marginTopIn": 1.25, "marginBottomIn": 1.25,
            "marginLeftIn": 1.25, "marginRightIn": 1.25,
            "lineHeight": 1.4, "paragraphSpacingIn": 0.22,
        },
    ),
    _definition(
        5,
        "Traditional Serif",
        "Warm Georgia serif for a conservative, editorial tone.",
        {"fontFamily": "Georgia"},
    ),
    _definition(
        6,
        "Minimal",
        "Calibri with narrow margins, favoring content over whitespace.",
        {
            "fontFamily": "Calibri",
            "marginTopIn": 0.6, "marginBottomIn": 0.6,
            "marginLeftIn": 0.6, "marginRightIn": 0.6,
        },
    ),
    _definition(
        7,
        "Executive",
        "Slightly larger type with generous spacing for a senior-level tone.",
        {"fontSize": 12.0, "lineHeight": 1.3, "paragraphSpacingIn": 0.2},
    ),
    _definition(
        8,
        "Narrow Margins",
        "Content-dense layout for a letter that runs a little long.",
        {"marginLeftIn": 0.6, "marginRightIn": 0.6},
    ),
    _definition(
        9,
        "Wide Margins",
        "Formal, letter-like framing with wide side margins.",
        {"marginLeftIn": 1.5, "marginRightIn": 1.5},
    ),
    _definition(
        10,
        "Clean Sans-serif",
        "System UI sans-serif for a crisp, modern default.",
        {"fontFamily": "System UI"},
    ),
)

_BY_ID: dict[str, CoverLetterTemplateDefinition] = {t.id: t for t in _TEMPLATES}


def list_cover_letter_templates() -> list[CoverLetterTemplateDefinition]:
    return list(_TEMPLATES)


def get_cover_letter_template(template_id: str) -> CoverLetterTemplateDefinition | None:
    return _BY_ID.get(template_id)


def resolve_cover_letter_template(
    template_id: str | None, *, fallback: bool = True
) -> CoverLetterTemplateDefinition:
    """Resolve a cover letter template, falling back to the default preset
    for an unknown id -- mirrors resolve_template() in the resume registry.
    Callers reproducing a historical letter must pass fallback=False so an
    unresolvable id raises instead of silently rendering the wrong preset.
    """
    if template_id:
        found = get_cover_letter_template(template_id)
        if found is not None:
            return found
    if not fallback:
        raise KeyError(f"Cover letter template not found: {template_id!r}")
    return _BY_ID[DEFAULT_COVER_LETTER_TEMPLATE_ID]
