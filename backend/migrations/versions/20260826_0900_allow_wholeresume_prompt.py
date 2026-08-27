"""allow wholeresume prompt

Revision ID: b3f6d1a9c4e2
Revises: e4b7f0a3c8d5
Create Date: 2026-08-26 09:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b3f6d1a9c4e2'
down_revision = 'e4b7f0a3c8d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset', 'wholeresume')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM prompts WHERE kind = 'wholeresume'")
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset')",
    )
