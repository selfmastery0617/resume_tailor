"""merge dev's company-summary migration with revision-prompt migration

Revision ID: 88ab248a730b
Revises: b7f6e2a10900, d8caa1f58cf2
Create Date: 2026-08-21 04:12:26.813192+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '88ab248a730b'
down_revision = ('b7f6e2a10900', 'd8caa1f58cf2')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
