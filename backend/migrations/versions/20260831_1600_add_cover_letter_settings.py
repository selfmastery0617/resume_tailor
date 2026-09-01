"""add profile_cover_letter_settings table

Emits DDL straight from the model (app/models/documents.py), same approach
as the initial schema migration -- the metadata is the source of truth, so
this can't drift from what app/models/documents.py actually declares.

Revision ID: 5a7f1e9c3d6b
Revises: 9f4c2a7d8e10
Create Date: 2026-08-31 16:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable, DropTable

from app.models.documents import profile_cover_letter_settings

revision = '5a7f1e9c3d6b'
down_revision = '9f4c2a7d8e10'
branch_labels = None
depends_on = None

_DIALECT = postgresql.dialect()


def _ddl(element) -> str:
    return str(element.compile(dialect=_DIALECT)).strip()


def upgrade() -> None:
    op.execute(_ddl(CreateTable(profile_cover_letter_settings)))


def downgrade() -> None:
    op.execute(_ddl(DropTable(profile_cover_letter_settings)))
