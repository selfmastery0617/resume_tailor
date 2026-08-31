"""add job URL used for description extraction

Revision ID: c7a9e2f4b6d8
Revises: b3f6d1a9c4e2
Create Date: 2026-08-30 09:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c7a9e2f4b6d8"
down_revision = "b3f6d1a9c4e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 compiles the current model metadata. A database created from scratch
    # after this revision therefore already has job_url before Alembic replays
    # the later revisions; older databases still need this migration to add it.
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("jobs")}
    if "job_url" not in existing:
        op.add_column(
            "jobs",
            sa.Column("job_url", sa.Text(), nullable=False, server_default=sa.text("''")),
        )


def downgrade() -> None:
    op.drop_column("jobs", "job_url")
