"""Synchronize timestamp nullability with ORM metadata.

Revision ID: 20260712_0006
Revises: 20260712_0005
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "20260712_0006"
down_revision = "20260712_0005"
branch_labels = None
depends_on = None

TIMESTAMP_COLUMNS = (
    ("users", "created_at"),
    ("candidate_profiles", "created_at"),
    ("candidate_profiles", "updated_at"),
    ("jobs", "discovered_at"),
    ("jobs", "created_at"),
    ("applications", "created_at"),
    ("applications", "updated_at"),
    ("application_status_history", "created_at"),
    ("audit_logs", "created_at"),
    ("generated_documents", "created_at"),
)


def set_nullability(nullable: bool) -> None:
    for table_name, column_name in TIMESTAMP_COLUMNS:
        if not nullable:
            op.execute(
                sa.text(
                    f'UPDATE "{table_name}" SET "{column_name}" = CURRENT_TIMESTAMP '
                    f'WHERE "{column_name}" IS NULL'
                )
            )
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                column_name,
                existing_type=sa.DateTime(timezone=True),
                nullable=nullable,
            )


def upgrade() -> None:
    set_nullability(nullable=False)


def downgrade() -> None:
    set_nullability(nullable=True)
