"""Add company summaries to profile and extracted experience rows.

Revision ID: b7f6e2a10900
Revises: 004281189d70
Create Date: 2026-08-20 09:00:00

The initial revision compiles the live SQLAlchemy metadata. Consequently, a
fresh database created from the current checkout already has these columns
before this revision runs. IF NOT EXISTS keeps both that path and upgrades of
existing databases safe.
"""

from __future__ import annotations

from alembic import op


revision = "b7f6e2a10900"
down_revision = "004281189d70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE profile_experiences "
        "ADD COLUMN IF NOT EXISTS company_summary TEXT NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE extraction_roles "
        "ADD COLUMN IF NOT EXISTS company_summary TEXT NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE extraction_roles DROP COLUMN IF EXISTS company_summary"
    )
    op.execute(
        "ALTER TABLE profile_experiences DROP COLUMN IF EXISTS company_summary"
    )
