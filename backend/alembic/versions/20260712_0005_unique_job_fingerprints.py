"""Enforce normalized URL and content fingerprint uniqueness.

Revision ID: 20260712_0005
Revises: 20260711_0004
Create Date: 2026-07-12
"""

from alembic import op

revision = "20260712_0005"
down_revision = "20260711_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_jobs_normalized_url", table_name="jobs")
    op.drop_index("ix_jobs_content_hash", table_name="jobs")
    op.create_index("ix_jobs_normalized_url", "jobs", ["normalized_url"], unique=True)
    op.create_index("ix_jobs_content_hash", "jobs", ["content_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_jobs_content_hash", table_name="jobs")
    op.drop_index("ix_jobs_normalized_url", table_name="jobs")
    op.create_index("ix_jobs_content_hash", "jobs", ["content_hash"])
    op.create_index("ix_jobs_normalized_url", "jobs", ["normalized_url"])
