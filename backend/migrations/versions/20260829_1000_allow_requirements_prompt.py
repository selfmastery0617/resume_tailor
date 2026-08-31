"""allow requirements prompt

Revision ID: c7a2e9f1d6b3
Revises: b3f6d1a9c4e2
Create Date: 2026-08-29 10:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c7a2e9f1d6b3'
down_revision = 'b3f6d1a9c4e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset', 'wholeresume', 'requirements')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM prompts WHERE kind = 'requirements'")
    op.drop_constraint("kind_known", "prompts", type_="check")
    op.create_check_constraint(
        "kind_known",
        "prompts",
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus', 'revision',"
        " 'companysummary', 'keywords', 'skillset', 'wholeresume')",
    )
