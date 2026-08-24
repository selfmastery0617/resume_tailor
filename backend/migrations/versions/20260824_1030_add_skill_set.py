"""add skill set

Revision ID: c1d5a8f92e07
Revises: a7c2e9f184b3
Create Date: 2026-08-24 10:30:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c1d5a8f92e07'
down_revision = 'a7c2e9f184b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "extraction_runs",
        sa.Column("skill_set", sa.Text(), nullable=False, server_default=""),
    )
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision', 'companysummary', 'keywords', 'skillset')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM prompts WHERE kind = 'skillset'")
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision', 'companysummary', 'keywords')",
    )
    op.drop_column("extraction_runs", "skill_set")
