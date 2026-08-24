"""allow keywords prompt

Revision ID: a7c2e9f184b3
Revises: f3a9c1d64e21
Create Date: 2026-08-24 09:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a7c2e9f184b3'
down_revision = 'f3a9c1d64e21'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision', 'companysummary', 'keywords')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM prompts WHERE kind = 'keywords'")
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision', 'companysummary')",
    )
