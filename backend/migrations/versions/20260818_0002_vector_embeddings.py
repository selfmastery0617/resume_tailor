"""Embedding storage (needs pgvector)

Split from the initial schema on purpose. pgvector is a separate download and,
on Windows, a compile step against the PostgreSQL headers — while nothing in
the application reads these tables yet. Ranking still encodes with
sentence-transformers in Python and computes similarity there.

So the base schema installs on a stock PostgreSQL, and this revision is applied
when similarity search moves into the database:

    python -m alembic upgrade head          # includes this
    python -m alembic upgrade 0001_initial_schema   # stops before it

Skipping it costs nothing today. Applying it lets an unchanged challenge reuse
its stored vector rather than being re-encoded on every extraction.

Revision ID: 0002_vector_embeddings
Revises: 0001_initial_schema
Create Date: 2026-08-18
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable, DropIndex, DropTable

from app.models import DEFERRED_TABLES, VECTOR_EXTENSION, metadata

revision = "0002_vector_embeddings"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

_DIALECT = postgresql.dialect()


def _ddl(element) -> str:
    return str(element.compile(dialect=_DIALECT)).strip()


def _tables():
    # Same order as the base schema, filtered to what this revision owns.
    return [t for t in metadata.sorted_tables if t.name in DEFERRED_TABLES]


def upgrade() -> None:
    # Fails loudly if pgvector is not installed on the server. That is the
    # intent: this revision cannot half-apply.
    op.execute(f'CREATE EXTENSION IF NOT EXISTS "{VECTOR_EXTENSION}"')

    for table in _tables():
        op.execute(_ddl(CreateTable(table)))
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            op.execute(_ddl(CreateIndex(index)))


def downgrade() -> None:
    for table in reversed(_tables()):
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            op.execute(_ddl(DropIndex(index)))
        op.execute(_ddl(DropTable(table)))

    # The extension stays: another schema in this database may be using it, and
    # dropping it would take its types with it.
