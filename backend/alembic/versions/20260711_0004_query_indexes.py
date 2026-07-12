"""Add indexes for common ordered list queries.

Revision ID: 20260711_0004
Revises: 20260711_0003
Create Date: 2026-07-11
"""

from alembic import op

revision = "20260711_0004"
down_revision = "20260711_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_jobs_discovered_at", "jobs", ["discovered_at"])
    op.create_index(
        "ix_applications_user_updated_at", "applications", ["user_id", "updated_at"]
    )
    op.create_index(
        "ix_application_history_application_created",
        "application_status_history",
        ["application_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_application_history_application_created",
        table_name="application_status_history",
    )
    op.drop_index("ix_applications_user_updated_at", table_name="applications")
    op.drop_index("ix_jobs_discovered_at", table_name="jobs")
