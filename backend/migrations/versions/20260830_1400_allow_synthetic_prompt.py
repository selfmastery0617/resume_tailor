"""allow synthetic prompt

Revision ID: f1a5d8c3b6e9
Revises: e9c3a7b2f4d6
Create Date: 2026-08-30 14:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'f1a5d8c3b6e9'
down_revision = 'e9c3a7b2f4d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset', 'wholeresume', 'requirements',"
        " 'matchreqs', 'selection', 'synthetic')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM prompts WHERE kind = 'synthetic'")
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset', 'wholeresume', 'requirements',"
        " 'matchreqs', 'selection')",
    )
