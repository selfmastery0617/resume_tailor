"""Diagnose the Postgres connection.

    python scripts/check_db.py

Reports what DATABASE_URL points at, whether it connects, and what the schema
looks like — and names the specific fix for each failure rather than echoing a
driver traceback. The password is never printed.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_ROOT / ".env")

RESERVED = set("@:/?#[]!$&'()*+,;= ")


def mask(url: str) -> str:
    return re.sub(r"://([^:/@]*):([^@]*)@", r"://\1:********@", url)


def normalise(url: str) -> str:
    """Accept the bare forms hosting providers hand out."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def lint(url: str) -> list[str]:
    """Problems visible without connecting."""
    problems: list[str] = []
    match = re.search(r"://(?P<user>[^:]*):(?P<pw>.*)@(?P<rest>.+)$", url)
    if not match:
        return ["Could not find user:password@host in the URL."]

    user, password, rest = match["user"], match["pw"], match["rest"]

    if user[:1] in "\"'" or user[-1:] in "\"'":
        problems.append(
            f"The username is {user!r} — those quotes are part of the value. "
            "Write it bare: postgres, not 'postgres'."
        )
    if password[:1] in "\"'" or password[-1:] in "\"'":
        problems.append("The password is wrapped in quotes; they become part of it.")
    if password and (bad := sorted({c for c in password if c in RESERVED})):
        problems.append(
            f"The password contains {bad} which must be percent-encoded "
            "(@ -> %40, : -> %3A, / -> %2F, # -> %23, ? -> %3F)."
        )
    if "/" not in rest:
        problems.append("No database name after the port, e.g. .../jobtailor")
    return problems


def explain(exc: Exception, url: str) -> str:
    text = str(exc)
    password = re.search(r"://[^:]*:([^@]*)@", url)
    if password and password.group(1):
        text = text.replace(password.group(1), "********")

    if "password authentication failed" in text:
        who = re.search(r'for user "([^"]*)"', text)
        return (
            f"Wrong password for user {who.group(1) if who else 'postgres'}.\n"
            "     Fix the password in backend/.env, or reset it:\n"
            '       & "C:\\Program Files\\PostgreSQL\\17\\bin\\psql.exe" -U postgres\n'
            "       \\password postgres"
        )
    if "does not exist" in text and "database" in text:
        return (
            "That database does not exist yet. Create it:\n"
            '       $env:PGPASSWORD = \'YOUR_PASSWORD\'\n'
            '       & "C:\\Program Files\\PostgreSQL\\17\\bin\\createdb.exe" '
            "-U postgres -h localhost jobtailor"
        )
    if "could not connect" in text.lower() or "refused" in text.lower():
        return (
            "Nothing is listening. Start the service:\n"
            "       Start-Service postgresql-x64-17"
        )
    return text.splitlines()[0][:200]


def main() -> None:
    raw = (os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        print("DATABASE_URL is not set in backend/.env\n")
        print("Add one line:")
        print("  DATABASE_URL=postgresql+psycopg://postgres:PASSWORD@localhost:5432/jobtailor")
        raise SystemExit(1)

    url = normalise(raw)
    print("DATABASE_URL:", mask(url), "\n")

    if problems := lint(url):
        print("problems in the URL itself")
        for problem in problems:
            print(f"  ! {problem}")
        print()

    import sqlalchemy as sa

    try:
        engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
        with engine.connect() as conn:
            version = conn.execute(sa.text("SHOW server_version")).scalar()
            user = conn.execute(sa.text("SELECT current_user")).scalar()
            database = conn.execute(sa.text("SELECT current_database()")).scalar()
            tables = conn.execute(
                sa.text(
                    "SELECT count(*) FROM information_schema.tables"
                    " WHERE table_schema = 'public'"
                )
            ).scalar()
            revision = None
            if conn.execute(
                sa.text("SELECT to_regclass('public.alembic_version')")
            ).scalar():
                revision = conn.execute(
                    sa.text("SELECT version_num FROM alembic_version")
                ).scalar()
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        print("CONNECTION FAILED\n")
        print("  ->", explain(exc, url))
        raise SystemExit(1)

    print(f"CONNECTED  PostgreSQL {version}  as {user}  to {database}")
    print(f"  tables in public schema : {tables}")
    print(f"  alembic revision        : {revision or 'none — migrations not run yet'}")
    if not tables:
        print("\n  Nothing here yet. Create the schema:")
        print("    python -m alembic upgrade 0001_initial_schema")


if __name__ == "__main__":
    main()
