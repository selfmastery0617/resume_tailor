"""allow validation prompt

Revision ID: 6c9d3b5e8a1f
Revises: 3f7e2a9c5d0b
Create Date: 2026-08-30 21:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '6c9d3b5e8a1f'
down_revision = '3f7e2a9c5d0b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset', 'wholeresume', 'requirements',"
        " 'matchreqs', 'selection', 'synthetic', 'bullets', 'resumecontent',"
        " 'finalresume', 'validation')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM prompts WHERE kind = 'validation'")
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset', 'wholeresume', 'requirements',"
        " 'matchreqs', 'selection', 'synthetic', 'bullets', 'resumecontent',"
        " 'finalresume')",
    )
