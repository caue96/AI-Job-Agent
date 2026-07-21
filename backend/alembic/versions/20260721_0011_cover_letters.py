"""evidence-grounded cover-letter documents

Revision ID: 20260721_0011
Revises: 20260720_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260721_0011"
down_revision: str | None = "20260720_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

cover_letter_status = postgresql.ENUM(
    "DRAFT",
    "GENERATED",
    "VALIDATED",
    "USER_EDITED",
    "APPROVED",
    "EXPORTED",
    name="coverletterstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    cover_letter_status.create(bind, checkfirst=True)
    with op.batch_alter_table("generated_documents") as batch_op:
        batch_op.add_column(
            sa.Column(
                "document_type",
                sa.String(30),
                nullable=False,
                server_default="APPLICATION_PACKAGE",
            )
        )
        batch_op.add_column(
            sa.Column(
                "job_id",
                sa.String(36),
                sa.ForeignKey("jobs.id", name="fk_generated_documents_job_id", ondelete="CASCADE"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "profile_version_id",
                sa.String(36),
                sa.ForeignKey(
                    "profile_versions.id",
                    name="fk_generated_documents_profile_version_id",
                    ondelete="RESTRICT",
                ),
            )
        )
        batch_op.add_column(
            sa.Column(
                "parent_document_id",
                sa.String(36),
                sa.ForeignKey(
                    "generated_documents.id",
                    name="fk_generated_documents_parent_document_id",
                    ondelete="SET NULL",
                ),
            )
        )
        batch_op.add_column(sa.Column("cover_letter_status", cover_letter_status))
        batch_op.add_column(sa.Column("variant", sa.String(30)))
        batch_op.add_column(sa.Column("tone", sa.String(30)))
        batch_op.add_column(sa.Column("length", sa.String(20)))
        batch_op.add_column(
            sa.Column("configuration", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
        batch_op.add_column(
            sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("approved_at", sa.DateTime(timezone=True)))
        batch_op.add_column(
            sa.Column(
                "approved_by",
                sa.String(36),
                sa.ForeignKey(
                    "users.id",
                    name="fk_generated_documents_approved_by",
                    ondelete="SET NULL",
                ),
            )
        )
        for column in (
            "document_type",
            "job_id",
            "profile_version_id",
            "parent_document_id",
            "cover_letter_status",
        ):
            batch_op.create_index(f"ix_generated_documents_{column}", [column])
    op.create_table(
        "document_exports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "generated_document_id",
            sa.String(36),
            sa.ForeignKey("generated_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("storage_key", sa.String(100), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("generated_document_id", "format", name="uq_document_export_format"),
    )
    op.create_index(
        "ix_document_exports_generated_document_id",
        "document_exports",
        ["generated_document_id"],
    )


def downgrade() -> None:
    op.drop_table("document_exports")
    with op.batch_alter_table("generated_documents") as batch_op:
        for column in (
            "cover_letter_status",
            "parent_document_id",
            "profile_version_id",
            "job_id",
            "document_type",
        ):
            batch_op.drop_index(f"ix_generated_documents_{column}")
        for column in (
            "approved_by",
            "approved_at",
            "selected",
            "configuration",
            "length",
            "tone",
            "variant",
            "cover_letter_status",
            "parent_document_id",
            "profile_version_id",
            "job_id",
            "document_type",
        ):
            batch_op.drop_column(column)
    cover_letter_status.drop(op.get_bind(), checkfirst=True)
