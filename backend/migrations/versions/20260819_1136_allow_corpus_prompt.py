"""Allow corpus prompt

Revision ID: ed86868c01e8
Revises: 004281189d70
Create Date: 2026-08-19 11:36:06.012267+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'ed86868c01e8'
down_revision = '004281189d70'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM prompts WHERE kind = 'corpus'")
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known", "prompts", "kind IN ('skills', 'tailoring', 'summary', 'title')"
    )
