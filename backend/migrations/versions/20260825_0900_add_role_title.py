"""add role title

Revision ID: e4b7f0a3c8d5
Revises: c1d5a8f92e07
Create Date: 2026-08-25 09:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e4b7f0a3c8d5'
down_revision = 'c1d5a8f92e07'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guard against 0001_initial_schema having already created this column on
    # a database built from scratch -- see the matching comment in
    # 20260818_2323_add_jobs_skills.py.
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("extraction_roles")}
    if "title" not in existing:
        op.add_column(
            "extraction_roles",
            sa.Column("title", sa.Text(), nullable=False, server_default=""),
        )


def downgrade() -> None:
    op.drop_column("extraction_roles", "title")
