"""allow bullets prompt

Revision ID: 02b6f9d3a7c5
Revises: f1a5d8c3b6e9
Create Date: 2026-08-30 18:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '02b6f9d3a7c5'
down_revision = 'f1a5d8c3b6e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset', 'wholeresume', 'requirements',"
        " 'matchreqs', 'selection', 'synthetic', 'bullets')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM prompts WHERE kind = 'bullets'")
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset', 'wholeresume', 'requirements',"
        " 'matchreqs', 'selection', 'synthetic')",
    )
