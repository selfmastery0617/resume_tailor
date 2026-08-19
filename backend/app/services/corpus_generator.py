"""Build a profile's database.json from what its resume already says.

Writing the corpus by hand is the slowest part of setting up a profile: four
nested levels, and every challenge needs a problem, an action, an achievement
and an impact. This drafts it from the profile's own experience section.

Nothing is saved. The draft lands in the editor for review, because the model
is being asked to phrase someone's career and a wrong metric that goes straight
to disk is a wrong metric on a resume.
"""

from __future__ import annotations

import json
from typing import Any

from app.schemas.experience_db import ExperienceDatabaseError, validate_database
from app.services.progress import progress

# Shown to the model as the target shape. One entry, every field populated, so
# there is no ambiguity about nesting or naming.
SCHEMA_EXAMPLE: list[dict[str, Any]] = [
    {
        "company": "Acme",
        "product": "Acme Payments",
        "timeline": "2019 - 2022",
        "summary": "One sentence on what the product does and your part in it.",
        "projects": [
            {
                "name": "Settlement pipeline",
                "description": "One sentence on the project.",
                "challenges": [
                    {
                        "id": "acme_payments_settlement_challenge1",
                        "challenge": "The problem, in one sentence.",
                        "action": "What you did about it, in one sentence.",
                        "achievement": "The measurable result, in one sentence.",
                        "business_impact": "Why it mattered to the business.",
                        "skills_used": ["Python", "PostgreSQL"],
                        "seniority_indicator": "Who you led and who you presented to.",
                    }
                ],
            }
        ],
    }
]


class CorpusGenerationError(RuntimeError):
    """Anything the user can act on: no experience, provider down, bad output."""


def _describe_experience(profile) -> str:
    """The profile's own experience, as the model's only source of fact."""
    lines: list[str] = []
    for entry in profile.data.experience:
        when = entry.startDate
        if entry.current:
            when = f"{when} - Present" if when else "Present"
        elif entry.endDate:
            when = f"{when} - {entry.endDate}"
        header = " · ".join(p for p in (entry.company, entry.title, when) if p)
        lines.append(f"- {header}")
        for detail in (entry.description or "").splitlines():
            if detail.strip():
                lines.append(f"    {detail.strip()}")
    return "\n".join(lines)


def _extract_json(reply: str) -> str:
    """Pull the array out of whatever the model wrapped it in."""
    text = (reply or "").strip()

    # Fenced blocks are the usual disobedience, despite the instruction.
    if "```" in text:
        chunks = text.split("```")
        for chunk in chunks:
            candidate = chunk.strip()
            if candidate.lower().startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("[") or candidate.startswith("{"):
                text = candidate
                break

    # Otherwise take the outermost array, ignoring any preamble.
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


async def generate_corpus(profile, notes: str = "") -> dict[str, Any]:
    """Draft a corpus for this profile. Returns the text and whether it parsed.

    Invalid JSON is returned rather than raised: the draft is still the useful
    part, and the editor is where it gets fixed.
    """
    from app.services import settings_service
    from app.services.deepseek import DeepSeekService

    experience = _describe_experience(profile)
    if not experience.strip():
        raise CorpusGenerationError(
            "This profile has no experience entries to build a database from. "
            "Add them above first."
        )

    template = (settings_service.get_settings().get("corpusPrompt") or "").strip()
    if not template:
        template = settings_service.DEFAULT_CORPUS_PROMPT

    prompt = settings_service.render_template(
        template,
        {
            "schema": json.dumps(SCHEMA_EXAMPLE, indent=2),
            "full_name": profile.data.profile.fullName or profile.name,
            "professional_title": profile.data.profile.professionalTitle or "(none set)",
            "experience": experience,
            "notes": notes.strip() or "(none)",
        },
    )

    progress.emit(
        "corpus",
        f"Drafting database.json for “{profile.name}” from "
        f"{len(profile.data.experience)} experience entries…",
        level="step",
    )

    try:
        reply = await DeepSeekService().ask(prompt)
    except Exception as exc:  # noqa: BLE001 - provider unavailable or expired
        progress.emit("corpus", f"Generation failed ({type(exc).__name__})", level="error")
        raise CorpusGenerationError(
            f"Could not reach DeepSeek ({type(exc).__name__}). Check the "
            "connection on the Settings tab."
        ) from exc

    text = _extract_json(reply)

    try:
        parsed = validate_database(json.loads(text))
    except (json.JSONDecodeError, ExperienceDatabaseError) as exc:
        progress.emit(
            "corpus",
            f"Draft did not validate: {exc}. Returned for editing anyway.",
            level="warn",
        )
        return {"text": text, "valid": False, "detail": str(exc), "companies": []}

    # Re-serialise: consistent formatting, and proves what is returned is what
    # the parser accepted rather than whatever the model happened to emit.
    pretty = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    challenges = sum(len(p.challenges) for e in parsed.entries for p in e.projects)
    progress.emit(
        "corpus",
        f"Drafted {len(parsed.entries)} entries, {challenges} challenges "
        f"({', '.join(parsed.company_names())})",
        level="result",
    )
    return {
        "text": pretty,
        "valid": True,
        "detail": None,
        "companies": parsed.company_names(),
    }
