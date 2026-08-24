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
    # Guard against 0001_initial_schema having already created this column on
    # a database built from scratch -- see the matching comment in
    # 20260818_2323_add_jobs_skills.py.
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("extraction_runs")}
    if "skill_set" not in existing:
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
