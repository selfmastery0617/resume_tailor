"""add role title

Revision ID: e4b7f0a3c8d5
Revises: c1d5a8f92e07
Create Date: 2026-08-25 09:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e4b7f0a3c8d5'
down_revision = 'c1d5a8f92e07'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "extraction_roles",
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("extraction_roles", "title")
