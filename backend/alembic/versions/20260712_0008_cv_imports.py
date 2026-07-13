"""Add grounded CV imports and immutable profile versions.

Revision ID: 20260712_0008
Revises: 20260712_0007
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "20260712_0008"
down_revision = "20260712_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    status = sa.Enum(
        "PDF_SELECTED", "PDF_VALIDATED", "TEXT_EXTRACTED", "PROFILE_PARSED",
        "AWAITING_REVIEW", "PROFILE_CONFIRMED", "PROFILE_SAVED", name="cvimportstatus",
    )
    op.create_table(
        "cv_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", status, nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(100), unique=True),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer()),
        sa.Column("extracted_pages", sa.JSON(), nullable=False),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.Column("draft", sa.JSON()),
        sa.Column("validation", sa.JSON(), nullable=False),
        sa.Column("model_metadata", sa.JSON(), nullable=False),
        sa.Column("file_deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cv_imports_user_id", "cv_imports", ["user_id"])
    op.create_index("ix_cv_imports_status", "cv_imports", ["status"])
    op.create_index("ix_cv_imports_sha256", "cv_imports", ["sha256"])
    op.create_index("ix_cv_imports_user_created", "cv_imports", ["user_id", "created_at"])
    op.create_table(
        "profile_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cv_import_id", sa.String(36), sa.ForeignKey("cv_imports.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("strategy", sa.String(20), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("profile_id", "version", name="uq_profile_version"),
    )
    op.create_index("ix_profile_versions_user_id", "profile_versions", ["user_id"])
    op.create_index("ix_profile_versions_profile_id", "profile_versions", ["profile_id"])
    op.create_index("ix_profile_versions_cv_import_id", "profile_versions", ["cv_import_id"])
    op.create_index("ix_profile_versions_profile_created", "profile_versions", ["profile_id", "created_at"])


def downgrade() -> None:
    op.drop_table("profile_versions")
    op.drop_table("cv_imports")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="cvimportstatus").drop(bind, checkfirst=True)
