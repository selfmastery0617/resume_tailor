"""allow matchreqs prompt

Revision ID: d4b8f2a5e7c1
Revises: c7a2e9f1d6b3
Create Date: 2026-08-29 11:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd4b8f2a5e7c1'
down_revision = 'c7a2e9f1d6b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset', 'wholeresume', 'requirements',"
        " 'matchreqs')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM prompts WHERE kind = 'matchreqs'")
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset', 'wholeresume', 'requirements')",
    )
