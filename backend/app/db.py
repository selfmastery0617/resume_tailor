"""Database access.

PostgreSQL through SQLAlchemy Core. The previous implementation spoke raw
`sqlite3` against a denormalised eight-table schema; this one speaks Core
against the schema in `app/models/`, which normalises what used to be JSON
blobs and gives every row an owner.

`get_db()` keeps its old shape — a context manager yielding something with
`.execute()`, committing on success and rolling back on error — so call sites
read much as they did. What changed is the argument: Core expressions
(`profiles.select().where(...)`) instead of SQL strings with `?` placeholders.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import Engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_ROOT / "data"

# The SQLite file this project used to run on. The application no longer opens
# it; only scripts/migrate_to_postgres.py does, and only for reading.
LEGACY_SQLITE_PATH = DATA_DIR / "jobtailor.sqlite3"

load_dotenv(BACKEND_ROOT / ".env")

_engine: Engine | None = None


class DatabaseNotConfigured(RuntimeError):
    """DATABASE_URL is missing, or the schema has never been created."""


def database_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise DatabaseNotConfigured(
            "DATABASE_URL is not set. Add it to backend/.env:\n"
            "  DATABASE_URL=postgresql+psycopg://postgres:PASSWORD@localhost:5432/jobtailor\n"
            "Then check it with: python scripts/check_db.py"
        )
    # Accept the bare forms hosting providers hand out.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def get_engine() -> Engine:
    """One engine per process, created on first use.

    pool_pre_ping costs a round trip per checkout and pays for itself: a
    developer restarting Postgres, or a managed host recycling connections,
    otherwise surfaces as a baffling failure on the next request.
    """
    global _engine
    if _engine is None:
        _engine = create_engine(
            database_url(),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            future=True,
        )
    return _engine


@contextmanager
def get_db() -> Iterator[Connection]:
    """Transactional connection: commits on success, rolls back on error."""
    with get_engine().begin() as conn:
        yield conn


def init_db() -> list[str]:
    """Check the schema is present and current. Creates nothing.

    Schema changes go through Alembic now rather than a CREATE TABLE IF NOT
    EXISTS string — two mechanisms racing to define the same tables is how a
    schema drifts from its own migrations.

    Returns a list of notes for startup to log; empty means fully up to date.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    with get_db() as conn:
        present = conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
        if present is None:
            raise DatabaseNotConfigured(
                "No schema in this database. Create it with:\n"
                "  cd backend && python -m alembic upgrade 0001_initial_schema"
            )
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    # 0002 needs pgvector and is optional, so being behind head is a normal
    # state worth reporting, never a failure.
    if current in heads:
        return []
    return [f"schema at {current}; head is {', '.join(heads)}"]
