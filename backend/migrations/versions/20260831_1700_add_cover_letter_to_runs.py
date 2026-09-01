"""add cover_letter column to extraction_runs

Revision ID: 2b8e6f0a4c73
Revises: 5a7f1e9c3d6b
Create Date: 2026-08-31 17:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '2b8e6f0a4c73'
down_revision = '5a7f1e9c3d6b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "extraction_runs",
        sa.Column(
            "cover_letter",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("extraction_runs", "cover_letter")
