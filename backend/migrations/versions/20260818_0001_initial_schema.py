"""Initial Postgres schema

Creates all 34 tables in one revision. Later revisions use Alembic's
autogenerate as normal; this one emits DDL straight from the metadata rather
than transcribing every table into op.create_table() calls, because a
hand-copied initial schema is a large surface for a silent typo and the
metadata is already the source of truth.

Emitting compiled DDL (rather than calling metadata.create_all) keeps
`alembic upgrade head --sql` working, which is the only way to review the exact
statements before they touch a database.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-18
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable, DropIndex, DropTable

from app.models import REQUIRED_EXTENSIONS, metadata

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

_DIALECT = postgresql.dialect()


def _ddl(element) -> str:
    return str(element.compile(dialect=_DIALECT)).strip()


def _tables():
    """sorted_tables resolves foreign keys, so parents come first."""
    return list(metadata.sorted_tables)


def upgrade() -> None:
    # pgcrypto supplies gen_random_uuid() for the id defaults. It ships with
    # PostgreSQL, so this needs no download and no build.
    for extension in REQUIRED_EXTENSIONS:
        op.execute(f'CREATE EXTENSION IF NOT EXISTS "{extension}"')

    for table in _tables():
        op.execute(_ddl(CreateTable(table)))
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            op.execute(_ddl(CreateIndex(index)))


def downgrade() -> None:
    for table in reversed(_tables()):
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            op.execute(_ddl(DropIndex(index)))
        op.execute(_ddl(DropTable(table)))

    # Extensions are deliberately left in place: another schema in the same
    # database may be using them, and dropping vector would take its types with it.
