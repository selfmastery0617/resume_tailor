"""allow coverletter prompt

Revision ID: 7d2f9b4e6a81
Revises: 2b8e6f0a4c73
Create Date: 2026-08-31 18:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '7d2f9b4e6a81'
down_revision = '2b8e6f0a4c73'
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
        " 'finalresume', 'validation', 'coverletter')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM prompts WHERE kind = 'coverletter'")
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset', 'wholeresume', 'requirements',"
        " 'matchreqs', 'selection', 'synthetic', 'bullets', 'resumecontent',"
        " 'finalresume', 'validation')",
    )
