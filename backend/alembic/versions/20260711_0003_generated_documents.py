"""Add versioned AI-generated document storage.

Revision ID: 20260711_0003
Revises: 20260711_0002
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260711_0003"
down_revision = "20260711_0002"
branch_labels = None
depends_on = None

document_status = postgresql.ENUM(
    "VALID", "INVALID", name="generateddocumentstatus", create_type=False
)


def upgrade() -> None:
    document_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "generated_documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("application_id", sa.String(length=36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("status", document_status, nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("validation", sa.JSON(), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("provider_response_id", sa.String(length=100)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("estimated_cost_usd", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("application_id", "version", name="uq_document_version"),
    )
    op.create_index("ix_generated_documents_application_id", "generated_documents", ["application_id"])


def downgrade() -> None:
    op.drop_table("generated_documents")
    document_status.drop(op.get_bind(), checkfirst=True)
