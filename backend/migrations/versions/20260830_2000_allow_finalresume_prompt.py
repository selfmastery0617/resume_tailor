"""allow finalresume prompt

Revision ID: 3f7e2a9c5d0b
Revises: 8d4a1c7f9b2e
Create Date: 2026-08-30 20:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '3f7e2a9c5d0b'
down_revision = '8d4a1c7f9b2e'
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
        " 'finalresume')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM prompts WHERE kind = 'finalresume'")
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset', 'wholeresume', 'requirements',"
        " 'matchreqs', 'selection', 'synthetic', 'bullets', 'resumecontent')",
    )
