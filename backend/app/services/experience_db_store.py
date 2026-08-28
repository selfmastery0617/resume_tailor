"""Per-profile career corpora, stored as JSON documents on disk.

One `database.json` per profile, written by the user. Kept as a file rather
than a table because it is a document they edit wholesale in a JSON editor:
read whole, saved whole, four levels deep, and a file round-trips their
formatting intent more honestly than shredding it into rows and rebuilding it.

    backend/data/corpora/<profile-id>.json

Two things a database would have given for free have to be done by hand here,
and both are done below rather than left to be remembered:

* deleting a profile deletes its corpus (`delete_for_profile`), so a career
  history does not outlive the profile someone deleted;
* a corpus is only ever reachable through a profile id, so one profile cannot
  read another's.

Anything backing up this application must copy `data/corpora/` alongside the
database dump — they are two stores now, and only one is in `pg_dump`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import UUID

from app.db import DATA_DIR
from app.schemas.experience_db import (
    ExperienceDatabase,
    ExperienceDatabaseError,
    to_canonical,
    validate_database,
)

CORPUS_DIR = DATA_DIR / "corpora"

# The single-corpus file this project used to keep. Adopted by the default
# profile on first run; see adopt_legacy_file().
LEGACY_PATH = DATA_DIR / "database.json"

# A profile id is a UUID, but it arrives as a string from the API. Validating
# the shape is what stops "../../etc/passwd" becoming a path.
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")

# Shown when a profile has no corpus yet, so the expected shape is obvious.
# Canonical form: a flat array of company/product entries.
SEED = [
    {
        "company": "Google",
        "product": "Google Spanner (globally distributed database)",
        "industry": "Cloud Infrastructure",
        "timeline": "2021 - 2024",
        "summary": "Globally distributed, strongly consistent database.",
        "projects": [
            {
                "name": "Cross-region replication",
                "description": "Kept replicas consistent across continents.",
                "challenges": [
                    {
                        "id": "google_spanner_replication_challenge1",
                        "industry": "Cloud Infrastructure",
                        "challenge": "Replication lag spiked past 400ms during regional failover.",
                        "action": "Rewrote the leader election path and batched Paxos writes.",
                        "achievement": "Cut p99 failover lag to 90ms across 12 regions.",
                        "business_impact": "Met the 99.999% availability commitment for enterprise customers.",
                        "seniority_indicator": "Led three engineers and presented the design to the storage director.",
                    }
                ],
            }
        ],
    }
]


class CorpusNotFound(LookupError):
    """This profile has no corpus document yet."""


def _profile_key(profile_id: str | UUID) -> str:
    key = str(profile_id)
    if not _UUID_RE.match(key):
        # Never interpolate an unvalidated string into a path.
        raise ExperienceDatabaseError(f"Not a valid profile id: {profile_id!r}")
    return key.lower()


def path(profile_id: str | UUID) -> Path:
    return CORPUS_DIR / f"{_profile_key(profile_id)}.json"


def exists(profile_id: str | UUID) -> bool:
    return path(profile_id).is_file()


def load_database(profile_id: str | UUID) -> ExperienceDatabase:
    """Parsed corpus for one profile.

    Raises rather than seeding: a profile with no corpus is a real state the
    UI has to report, not something to paper over with example data that
    would then be extracted from as if it were the user's own history.
    """
    target = path(profile_id)
    if not target.is_file():
        raise CorpusNotFound(str(profile_id))
    try:
        # utf-8-sig so a BOM from Notepad or PowerShell doesn't break parsing.
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ExperienceDatabaseError(f"database.json is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise ExperienceDatabaseError(f"Could not read database.json: {exc}") from exc
    return validate_database(raw)


def load_raw(profile_id: str | UUID) -> str:
    """The file exactly as stored, for the editor. Empty when there is none."""
    target = path(profile_id)
    return target.read_text(encoding="utf-8-sig") if target.is_file() else ""


def save_database(
    profile_id: str | UUID, raw: object, normalise: bool = False
) -> ExperienceDatabase:
    """Validate then write. Invalid input never reaches disk.

    `normalise` rewrites the file in the canonical flat-array form; otherwise
    the user's own text is preserved verbatim, formatting included.
    """
    parsed = validate_database(raw)
    payload = to_canonical(parsed) if normalise else raw

    target = path(profile_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file and replace, so an interrupted write cannot leave a
    # truncated corpus behind.
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)
    return parsed


def save_raw_text(profile_id: str | UUID, text: str) -> ExperienceDatabase:
    """Save from the editor's raw text, reporting JSON errors precisely."""
    try:
        parsed_json = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExperienceDatabaseError(
            f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    return save_database(profile_id, parsed_json)


def delete_for_profile(profile_id: str | UUID) -> bool:
    """Remove a profile's corpus. Returns whether there was one.

    Called when a profile is deleted. Without this the document survives the
    profile, which is worse than untidy: someone deletes a profile expecting
    their career history to go with it.
    """
    try:
        target = path(profile_id)
    except ExperienceDatabaseError:
        return False
    if not target.is_file():
        return False
    target.unlink()
    return True


def list_orphans(known_profile_ids: set[str]) -> list[Path]:
    """Corpus files whose profile no longer exists.

    A safety net for files left behind by a delete that failed midway, or by a
    profile removed straight from the database.
    """
    if not CORPUS_DIR.is_dir():
        return []
    known = {p.lower() for p in known_profile_ids}
    return [f for f in CORPUS_DIR.glob("*.json") if f.stem.lower() not in known]


def adopt_legacy_file(profile_id: str | UUID) -> bool:
    """Move the old single data/database.json to this profile. Idempotent.

    The corpus used to be one file for the whole application. On first run
    after the split it belongs to the default profile — copied rather than
    moved, so the original stays put if anything goes wrong.
    """
    if not LEGACY_PATH.is_file() or exists(profile_id):
        return False
    target = path(profile_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(LEGACY_PATH.read_text(encoding="utf-8-sig"), encoding="utf-8")
    return True
