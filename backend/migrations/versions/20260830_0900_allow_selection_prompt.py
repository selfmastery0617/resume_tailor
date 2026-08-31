"""allow selection prompt

Revision ID: e9c3a7b2f4d6
Revises: d4b8f2a5e7c1
Create Date: 2026-08-30 09:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e9c3a7b2f4d6'
down_revision = 'd4b8f2a5e7c1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset', 'wholeresume', 'requirements',"
        " 'matchreqs', 'selection')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM prompts WHERE kind = 'selection'")
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset', 'wholeresume', 'requirements',"
        " 'matchreqs')",
    )
