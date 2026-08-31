"""merge job-url and pipeline-prompt migrations

Revision ID: 5e3416b3d1a7
Revises: c7a9e2f4b6d8, 6c9d3b5e8a1f
Create Date: 2026-08-31 11:19:53.964296+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '5e3416b3d1a7'
down_revision = ('c7a9e2f4b6d8', '6c9d3b5e8a1f')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
