"""allow company summary prompt

Revision ID: f3a9c1d64e21
Revises: 88ab248a730b
Create Date: 2026-08-23 09:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'f3a9c1d64e21'
down_revision = '88ab248a730b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision', 'companysummary')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM prompts WHERE kind = 'companysummary'")
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision')",
    )
