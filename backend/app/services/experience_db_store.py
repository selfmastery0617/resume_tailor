"""Reads and writes backend/data/database.json.

Kept as a file rather than a table: it is a document the user edits wholesale in
a JSON editor, and a file round-trips their formatting intent more honestly than
shredding it into rows and rebuilding it.
"""

import json
from pathlib import Path

from app.db import DATA_DIR
from app.schemas.experience_db import (
    ExperienceDatabase,
    ExperienceDatabaseError,
    to_canonical,
    validate_database,
)

DATABASE_PATH = DATA_DIR / "database.json"

# Shown the first time the editor is opened, so the expected shape is obvious.
# Canonical form: a flat array of company/product entries.
SEED = [
    {
        "company": "Google",
        "product": "Google Spanner (globally distributed database)",
        "timeline": "2021 - 2024",
        "summary": "Globally distributed, strongly consistent database.",
        "projects": [
            {
                "name": "Multi-region replication",
                "description": "Cut cross-region replication lag.",
                "challenges": [
                    {
                        "id": "goog-spanner-1",
                        "challenge": "Cross-region writes exceeded the latency SLO.",
                        "action": "Redesigned the commit path to batch Paxos rounds.",
                        "achievement": "Reduced p99 write latency by 38%.",
                        "business_impact": "Unblocked three enterprise launches.",
                        "skills_used": ["Go", "Distributed systems", "Paxos"],
                        "seniority_indicator": "Led four engineers across two teams.",
                    }
                ],
            }
        ],
    }
]


def load_database() -> ExperienceDatabase:
    """Parsed database.json, seeding the file on first use."""
    if not DATABASE_PATH.exists():
        save_database(SEED)
        return validate_database(SEED)
    try:
        # utf-8-sig so a BOM from Notepad or PowerShell doesn't break parsing.
        raw = json.loads(DATABASE_PATH.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ExperienceDatabaseError(f"database.json is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise ExperienceDatabaseError(f"Could not read database.json: {exc}") from exc
    return validate_database(raw)


def load_raw() -> str:
    """The file exactly as stored, for the editor."""
    if not DATABASE_PATH.exists():
        save_database(SEED)
    return DATABASE_PATH.read_text(encoding="utf-8-sig")


def save_database(raw: object, normalise: bool = False) -> ExperienceDatabase:
    """Validate then write. Invalid input never reaches disk.

    `normalise` rewrites the file in the canonical flat-array form; otherwise
    the user's own text is preserved verbatim, formatting included.
    """
    parsed = validate_database(raw)
    payload = to_canonical(parsed) if normalise else raw

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Write to a temp file and replace, so an interrupted write cannot leave a
    # truncated database.json behind.
    tmp = DATABASE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DATABASE_PATH)
    return parsed


def migrate_to_canonical() -> tuple[bool, str]:
    """Rewrite a legacy nested file as the flat array. Returns (changed, detail)."""
    if not DATABASE_PATH.exists():
        return False, "No database.json yet."
    try:
        raw = json.loads(DATABASE_PATH.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ExperienceDatabaseError(f"database.json is not valid JSON: {exc}") from exc

    if isinstance(raw, list):
        return False, "Already in the canonical array form."

    parsed = validate_database(raw)
    save_database(to_canonical(parsed), normalise=True)
    return True, f"Converted {len(parsed.entries)} company/product entries."


def save_raw_text(text: str) -> ExperienceDatabase:
    """Save from the editor's raw text, reporting JSON errors precisely."""
    try:
        parsed_json = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExperienceDatabaseError(
            f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    return save_database(parsed_json)


def path() -> Path:
    return DATABASE_PATH
