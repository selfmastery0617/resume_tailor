"""Job date and ready status

Revision ID: 004281189d70
Revises: 874680572750
Create Date: 2026-08-19 02:08:27.489445+00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '004281189d70'
down_revision = '874680572750'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("date_added", sa.Date(), nullable=True))

    # Autogenerate sees columns, not CHECK bodies or partial index predicates,
    # so the rest is written by hand.

    # 'ready' joins the statuses: set when a resume exists, before applying.
    op.drop_constraint("application_status_known", "jobs", type_="check")
    op.create_check_constraint(
        "application_status_known",
        "jobs",
        "application_status IN ('not_applied', 'ready', 'applied',"
        " 'interviewing', 'offer', 'rejected', 'withdrawn')",
    )

    # applied_at pairs with "did they apply", not with "is it not_applied" --
    # there are two pre-application states now, and the old form would have
    # demanded a date for 'ready'.
    op.drop_constraint("applied_at_matches_status", "jobs", type_="check")
    op.create_check_constraint(
        "applied_at_matches_status",
        "jobs",
        "(application_status IN ('applied', 'interviewing', 'offer', 'rejected',"
        " 'withdrawn')) = (applied_at IS NOT NULL)",
    )

    # The working list is everything not yet sent, which now includes 'ready'.
    op.drop_index("ix_jobs_todo", table_name="jobs")
    op.create_index(
        "ix_jobs_todo",
        "jobs",
        ["profile_id", sa.text("first_seen_at DESC")],
        postgresql_where=sa.text(
            "application_status IN ('not_applied', 'ready') AND archived_at IS NULL"
        ),
    )

    # Existing rows: a job with a resume is ready to send.
    op.execute(
        "UPDATE jobs SET application_status = 'ready'"
        " WHERE application_status = 'not_applied'"
        "   AND EXISTS (SELECT 1 FROM generated_documents d WHERE d.job_id = jobs.id)"
    )
    # Backfill the new column from when the row first appeared.
    op.execute("UPDATE jobs SET date_added = first_seen_at::date WHERE date_added IS NULL")


def downgrade() -> None:
    op.execute("UPDATE jobs SET application_status = 'not_applied' WHERE application_status = 'ready'")
    op.drop_index("ix_jobs_todo", table_name="jobs")
    op.create_index(
        "ix_jobs_todo",
        "jobs",
        ["profile_id", sa.text("first_seen_at DESC")],
        postgresql_where=sa.text(
            "application_status = 'not_applied' AND archived_at IS NULL"
        ),
    )
    op.drop_constraint("applied_at_matches_status", "jobs", type_="check")
    op.create_check_constraint(
        "applied_at_matches_status",
        "jobs",
        "(application_status = 'not_applied') = (applied_at IS NULL)",
    )
    op.drop_constraint("application_status_known", "jobs", type_="check")
    op.create_check_constraint(
        "application_status_known",
        "jobs",
        "application_status IN ('not_applied', 'applied', 'interviewing',"
        " 'offer', 'rejected', 'withdrawn')",
    )
    op.drop_column("jobs", "date_added")
