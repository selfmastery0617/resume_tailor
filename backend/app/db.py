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

-- User-created templates. The ten built-ins stay source-controlled in
-- services/templates/registry.py and are never written here, so TM-FR-005
-- ("user edits do not rewrite source-controlled template files") still holds.
CREATE TABLE IF NOT EXISTS template_definitions (
    id                 TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    description        TEXT NOT NULL DEFAULT '',
    -- Bumped on every save so generated_resumes can pin an exact revision.
    version            INTEGER NOT NULL DEFAULT 1,
    active             INTEGER NOT NULL DEFAULT 1,
    renderer_key       TEXT NOT NULL DEFAULT 'layout-v1',
    source             TEXT NOT NULL DEFAULT 'user'
                       CHECK (source IN ('builtin', 'user')),
    layout_json        TEXT NOT NULL,
    default_style_json TEXT NOT NULL DEFAULT '{}',
    -- NULL = available to every profile.
    owner_profile_id   TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    FOREIGN KEY (owner_profile_id) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_template_defs_active ON template_definitions(active);

-- Imported job listings. These used to live only in React state, which is why
-- job_experience and job_resume were keyed by an id with no row behind it and
-- the table emptied on every reload.
--
-- The id is the source's own id rather than a generated one, so the extraction
-- and resume rows already keyed by it keep working untouched.
--
-- Column shape deliberately mirrors the Postgres design in docs/database.md, so
-- moving over later is a data copy rather than a redesign.
CREATE TABLE IF NOT EXISTS jobs (
    id                 TEXT PRIMARY KEY,
    source             TEXT NOT NULL DEFAULT 'jobright',
    title              TEXT NOT NULL DEFAULT '',
    company            TEXT NOT NULL DEFAULT '',
    location           TEXT NOT NULL DEFAULT '',
    url                TEXT NOT NULL DEFAULT '',
    description        TEXT NOT NULL DEFAULT '',
    salary             TEXT NOT NULL DEFAULT '',
    work_model         TEXT NOT NULL DEFAULT '',
    match_score        TEXT NOT NULL DEFAULT '',
    publish_time       TEXT NOT NULL DEFAULT '',
    publish_time_desc  TEXT NOT NULL DEFAULT '',
    skills             TEXT NOT NULL DEFAULT '',
    -- What the user did in the outside world. Separate from whatever the
    -- pipeline has done, so marking a job applied cannot erase the fact that a
    -- resume was generated for it.
    application_status TEXT NOT NULL DEFAULT 'not_applied'
                       CHECK (application_status IN ('not_applied', 'applied')),
    applied_at         TEXT,
    first_seen_at      TEXT NOT NULL,
    last_seen_at       TEXT NOT NULL,
    -- Neither field can contradict the other in either direction.
    CHECK ((application_status = 'not_applied') = (applied_at IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(application_status);

-- Extracted experience per imported job. Keyed by the job's own id (from the
-- import source) because job rows themselves live in browser state; this is
-- what makes an extraction survive a page refresh.
CREATE TABLE IF NOT EXISTS job_experience (
    job_id       TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- The tailored PDF written to the output folder for a job. Keyed by job id like
-- job_experience, so the table can re-attach the file to its row after a
-- refresh. Regenerating overwrites the row and the file on disk.
CREATE TABLE IF NOT EXISTS job_resume (
    job_id       TEXT PRIMARY KEY,
    profile_id   TEXT,
    profile_name TEXT NOT NULL DEFAULT '',
    template_id  TEXT NOT NULL DEFAULT '',
    folder       TEXT NOT NULL,
    file_name    TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    page_count   INTEGER NOT NULL DEFAULT 0,
    byte_size    INTEGER NOT NULL DEFAULT 0,
    generated_at TEXT NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE SET NULL
);
"""

# Columns added after the first release. CREATE TABLE IF NOT EXISTS will not add
# them to an existing database, so they are applied separately.
MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    # A user template is mutable, so pinning only (template_id, version) would
    # let an edit retroactively change what a past PDF was rendered from.
    # Snapshotting the layout keeps generated resumes reproducible (US-RG-02).
    ("generated_resumes", "layout_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
)


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


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """Add columns missing from an existing database. Idempotent."""
    applied: list[str] = []
    for table, column, ddl in MIGRATIONS:
        if _table_exists(conn, table) and not _has_column(conn, table, column):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            applied.append(f"{table}.{column}")
    return applied


def init_db() -> list[str]:
    """Create missing tables and apply column migrations.

    Returns the migrations applied, so startup can log a schema change rather
    than silently altering the user's database.
    """
    with get_db() as conn:
        conn.executescript(SCHEMA)
        return _apply_migrations(conn)
