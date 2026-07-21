"""job-specific grounded CV optimization

Revision ID: 20260720_0010
Revises: 20260712_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260720_0010"
down_revision: str | None = "20260712_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

analysis_status = postgresql.ENUM(
    "CV_ANALYSIS_REQUESTED", "GAP_ANALYSIS_COMPLETED", "IMPROVEMENTS_PROPOSED",
    "AWAITING_REVIEW", "RECOMMENDATIONS_APPROVED", "CV_VARIANT_GENERATED",
    "CV_VARIANT_SAVED", name="cvoptimizationstatus", create_type=False,
)
decision_status = postgresql.ENUM(
    "PENDING", "ACCEPTED", "REJECTED", "EDITED",
    name="cvrecommendationdecisionvalue", create_type=False,
)
variant_status = postgresql.ENUM(
    "JOB_SPECIFIC_DRAFT", "USER_REVIEWED", "APPROVED", "EXPORTED",
    name="cvvariantstatus", create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    analysis_status.create(bind, checkfirst=True)
    decision_status.create(bind, checkfirst=True)
    variant_status.create(bind, checkfirst=True)
    op.create_table(
        "cv_analysis_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_version_id", sa.String(36), sa.ForeignKey("profile_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("match_result_id", sa.String(36), sa.ForeignKey("discovery_match_results.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", analysis_status, nullable=False),
        sa.Column("original_score", sa.Integer(), nullable=False),
        sa.Column("input_summary", sa.JSON(), nullable=False),
        sa.Column("validation", sa.JSON(), nullable=False),
        sa.Column("prompt_version", sa.String(60), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("provider_response_id", sa.String(100)),
        sa.Column("input_tokens", sa.Integer()), sa.Column("output_tokens", sa.Integer()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in ("user_id", "profile_version_id", "job_id", "match_result_id", "status"):
        op.create_index(f"ix_cv_analysis_runs_{column}", "cv_analysis_runs", [column])
    op.create_index("ix_cv_analysis_user_job_created", "cv_analysis_runs", ["user_id", "job_id", "created_at"])
    op.create_table(
        "cv_recommendations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_run_id", sa.String(36), sa.ForeignKey("cv_analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(50), nullable=False), sa.Column("section", sa.String(200), nullable=False),
        sa.Column("current_text", sa.Text(), nullable=False), sa.Column("suggested_text", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False), sa.Column("expected_benefit", sa.Text(), nullable=False),
        sa.Column("related_job_requirement", sa.Text(), nullable=False), sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False), sa.Column("recommendation_type", sa.String(30), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False), sa.Column("decision", decision_status, nullable=False),
        sa.Column("user_text", sa.Text()), sa.Column("validation", sa.JSON(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cv_recommendations_analysis_run_id", "cv_recommendations", ["analysis_run_id"])
    op.create_index("ix_cv_recommendations_category", "cv_recommendations", ["category"])
    op.create_index("ix_cv_recommendations_priority", "cv_recommendations", ["priority"])
    op.create_index("ix_cv_recommendations_run_order", "cv_recommendations", ["analysis_run_id", "display_order"])
    op.create_table(
        "cv_recommendation_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recommendation_id", sa.String(36), sa.ForeignKey("cv_recommendations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fact_id", sa.String(240), nullable=False), sa.Column("source_section", sa.String(120), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.UniqueConstraint("recommendation_id", "fact_id", name="uq_cv_recommendation_fact"),
    )
    op.create_index("ix_cv_recommendation_evidence_recommendation_id", "cv_recommendation_evidence", ["recommendation_id"])
    op.create_table(
        "cv_recommendation_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recommendation_id", sa.String(36), sa.ForeignKey("cv_recommendations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", decision_status, nullable=False), sa.Column("edited_text", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cv_recommendation_decisions_recommendation_id", "cv_recommendation_decisions", ["recommendation_id"])
    op.create_index("ix_cv_recommendation_decisions_actor_id", "cv_recommendation_decisions", ["actor_id"])
    op.create_table(
        "cv_variants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("base_profile_version_id", sa.String(36), sa.ForeignKey("profile_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("analysis_run_id", sa.String(36), sa.ForeignKey("cv_analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", variant_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "analysis_run_id", name="uq_cv_variant_analysis"),
    )
    for column in ("user_id", "job_id", "base_profile_version_id", "analysis_run_id", "status"):
        op.create_index(f"ix_cv_variants_{column}", "cv_variants", [column])
    op.create_table(
        "cv_variant_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("variant_id", sa.String(36), sa.ForeignKey("cv_variants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("status", variant_status, nullable=False),
        sa.Column("content", sa.JSON(), nullable=False), sa.Column("applied_recommendation_ids", sa.JSON(), nullable=False),
        sa.Column("rejected_recommendation_ids", sa.JSON(), nullable=False), sa.Column("user_edits", sa.JSON(), nullable=False),
        sa.Column("original_score", sa.Integer(), nullable=False), sa.Column("estimated_score", sa.Integer(), nullable=False),
        sa.Column("score_explanation", sa.Text(), nullable=False), sa.Column("keywords_added", sa.JSON(), nullable=False),
        sa.Column("sections_improved", sa.JSON(), nullable=False), sa.Column("remaining_gaps", sa.JSON(), nullable=False),
        sa.Column("remaining_blockers", sa.JSON(), nullable=False), sa.Column("validation", sa.JSON(), nullable=False),
        sa.Column("prompt_version", sa.String(60), nullable=False), sa.Column("model", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("variant_id", "version", name="uq_cv_variant_version"),
    )
    op.create_index("ix_cv_variant_versions_variant_id", "cv_variant_versions", ["variant_id"])
    op.create_table(
        "cv_variant_validations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("variant_version_id", sa.String(36), sa.ForeignKey("cv_variant_versions.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("valid", sa.Boolean(), nullable=False), sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("checked_claims", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "cv_exports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("variant_version_id", sa.String(36), sa.ForeignKey("cv_variant_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("format", sa.String(10), nullable=False), sa.Column("storage_key", sa.String(100), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False), sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("variant_version_id", "format", name="uq_cv_export_format"),
    )
    op.create_index("ix_cv_exports_variant_version_id", "cv_exports", ["variant_version_id"])


def downgrade() -> None:
    for table in (
        "cv_exports", "cv_variant_validations", "cv_variant_versions", "cv_variants",
        "cv_recommendation_decisions", "cv_recommendation_evidence", "cv_recommendations",
        "cv_analysis_runs",
    ):
        op.drop_table(table)
    bind = op.get_bind()
    variant_status.drop(bind, checkfirst=True)
    decision_status.drop(bind, checkfirst=True)
    analysis_status.drop(bind, checkfirst=True)
