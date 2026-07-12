"""Add deterministic matching fields.

Revision ID: 20260711_0002
Revises: 20260711_0001
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa

revision = "20260711_0002"
down_revision = "20260711_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_profiles",
        sa.Column("preferred_industries", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column("candidate_profiles", sa.Column("total_years_experience", sa.Float()))
    op.add_column("jobs", sa.Column("industry", sa.String(length=120)))


def downgrade() -> None:
    op.drop_column("jobs", "industry")
    op.drop_column("candidate_profiles", "total_years_experience")
    op.drop_column("candidate_profiles", "preferred_industries")
