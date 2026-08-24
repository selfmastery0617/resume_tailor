"""allow revision prompt

Revision ID: d8caa1f58cf2
Revises: ed86868c01e8
Create Date: 2026-08-20 12:37:44.800398+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd8caa1f58cf2'
down_revision = 'ed86868c01e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM prompts WHERE kind = 'revision'")
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus')",
    )
