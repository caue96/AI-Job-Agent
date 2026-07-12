"""Track cached tokens and provider latency.

Revision ID: 20260712_0007
Revises: 20260712_0006
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "20260712_0007"
down_revision = "20260712_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generated_documents", sa.Column("cached_input_tokens", sa.Integer()))
    op.add_column("generated_documents", sa.Column("latency_ms", sa.Integer()))


def downgrade() -> None:
    op.drop_column("generated_documents", "latency_ms")
    op.drop_column("generated_documents", "cached_input_tokens")
