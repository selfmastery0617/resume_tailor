"""remove rejected job-description extraction URL

Revision ID: 9f4c2a7d8e10
Revises: 5e3416b3d1a7
Create Date: 2026-08-31 14:00:00.000000+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "9f4c2a7d8e10"
down_revision = "5e3416b3d1a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep this as a forward migration instead of deleting the historical add:
    # c7a9e2f4b6d8 may already be installed on another database.
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("jobs")}
    if "job_url" in existing:
        op.drop_column("jobs", "job_url")


def downgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("jobs")}
    if "job_url" not in existing:
        op.add_column(
            "jobs",
            sa.Column("job_url", sa.Text(), nullable=False, server_default=sa.text("''")),
        )
