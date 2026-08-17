"""SQLite persistence.

TM-FR-015 / 9.2: user template settings must live in persistent storage, not
source-controlled JSON, and must survive a server restart. The database file is
git-ignored (see the `data/` entry in .gitignore).
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_ROOT / "data"
DB_PATH = DATA_DIR / "jobtailor.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    data_json   TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_template_settings (
    profile_id           TEXT PRIMARY KEY,
    template_id          TEXT NOT NULL,
    template_version     INTEGER NOT NULL,
    style_overrides_json TEXT NOT NULL DEFAULT '{}',
    updated_at           TEXT NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE
);

-- Immutable history: snapshots must survive later profile/template edits.
CREATE TABLE IF NOT EXISTS generated_resumes (
    id                    TEXT PRIMARY KEY,
    profile_id            TEXT,
    job_application_id    TEXT,
    template_id           TEXT NOT NULL,
    template_version      INTEGER NOT NULL,
    profile_snapshot_json TEXT NOT NULL,
    style_snapshot_json   TEXT NOT NULL,
    file_name             TEXT NOT NULL,
    file_path             TEXT,
    content_hash          TEXT,
    generated_at          TEXT NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_generated_profile
    ON generated_resumes(profile_id);

-- Single-row key/value store for app settings (output folder, prompt, ...).
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Off by default in SQLite; required for the ON DELETE rules above.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Transactional connection: commits on success, rolls back on error.

    9.2 requires a failed save to leave previous settings unchanged.
    """
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(SCHEMA)
