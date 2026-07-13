"""job discovery

Revision ID: 20260712_0009
Revises: 20260712_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260712_0009"
down_revision: str | None = "20260712_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

discovery_run_status = postgresql.ENUM(
    "PENDING",
    "RUNNING",
    "PARTIAL",
    "SUCCEEDED",
    "FAILED",
    name="discoveryrunstatus",
    create_type=False,
)


def upgrade() -> None:
    discovery_run_status.create(op.get_bind(), checkfirst=True)
    additions = (
        ("normalized_title", sa.String(200), True, None),
        ("application_url", sa.Text(), True, None),
        ("responsibilities", sa.JSON(), False, sa.text("'[]'")),
        ("region", sa.String(120), True, None),
        ("seniority", sa.String(40), True, None),
        ("salary_period", sa.String(20), True, None),
        ("required_languages", sa.JSON(), False, sa.text("'[]'")),
        ("required_skills", sa.JSON(), False, sa.text("'[]'")),
        ("preferred_skills", sa.JSON(), False, sa.text("'[]'")),
        ("required_years_experience", sa.Float(), True, None),
        ("work_authorization_information", sa.Text(), True, None),
        ("relocation_information", sa.Text(), True, None),
        ("posted_at", sa.DateTime(timezone=True), True, None),
        ("expires_at", sa.DateTime(timezone=True), True, None),
        ("last_checked_at", sa.DateTime(timezone=True), True, None),
        ("provider_metadata", sa.JSON(), False, sa.text("'{}'")),
    )
    for name, column_type, nullable, server_default in additions:
        op.add_column(
            "jobs",
            sa.Column(
                name, column_type, nullable=nullable, server_default=server_default
            ),
        )

    op.create_table("discovery_search_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("preferences", sa.JSON(), nullable=False), sa.Column("generated_terms", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table("discovery_search_configurations",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("provider_settings", sa.JSON(), nullable=False), sa.Column("schedule_kind", sa.String(20), nullable=False),
        sa.Column("schedule_time", sa.String(5), nullable=False), sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("hard_filters", sa.JSON(), nullable=False), sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_discovery_config_name"),
    )
    op.create_index("ix_discovery_search_configurations_user_id", "discovery_search_configurations", ["user_id"])
    op.create_index("ix_discovery_search_configurations_next_run_at", "discovery_search_configurations", ["next_run_at"])
    op.create_table("discovery_search_runs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("configuration_id", sa.String(36), sa.ForeignKey("discovery_search_configurations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", discovery_run_status, nullable=False), sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("lifecycle_stage", sa.String(40), nullable=False), sa.Column("scheduled_key", sa.String(160), unique=True),
        sa.Column("counters", sa.JSON(), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_discovery_search_runs_user_id", "discovery_search_runs", ["user_id"])
    op.create_index("ix_discovery_search_runs_configuration_id", "discovery_search_runs", ["configuration_id"])
    op.create_index("ix_discovery_search_runs_status", "discovery_search_runs", ["status"])
    op.create_index("ix_discovery_runs_user_started", "discovery_search_runs", ["user_id", "started_at"])
    op.create_table("discovery_search_queries",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("run_id", sa.String(36), sa.ForeignKey("discovery_search_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False), sa.Column("query", sa.JSON(), nullable=False),
    )
    op.create_index("ix_discovery_search_queries_run_id", "discovery_search_queries", ["run_id"])
    op.create_index("ix_discovery_search_queries_provider", "discovery_search_queries", ["provider"])
    op.create_table("discovery_provider_runs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("run_id", sa.String(36), sa.ForeignKey("discovery_search_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False), sa.Column("status", discovery_run_status, nullable=False),
        sa.Column("counters", sa.JSON(), nullable=False), sa.Column("api_usage", sa.JSON(), nullable=False), sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("ended_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_discovery_provider_runs_run_id", "discovery_provider_runs", ["run_id"])
    op.create_index("ix_discovery_provider_runs_provider", "discovery_provider_runs", ["provider"])
    op.create_table("discovery_provider_cursors",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("configuration_id", sa.String(36), sa.ForeignKey("discovery_search_configurations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False), sa.Column("cursor", sa.JSON(), nullable=False), sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("circuit_open_until", sa.DateTime(timezone=True)), sa.Column("next_allowed_at", sa.DateTime(timezone=True)), sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("configuration_id", "provider", name="uq_discovery_cursor_provider"),
    )
    op.create_index("ix_discovery_provider_cursors_configuration_id", "discovery_provider_cursors", ["configuration_id"])
    op.create_table("discovery_raw_results",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("provider_run_id", sa.String(36), sa.ForeignKey("discovery_provider_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False), sa.Column("external_job_id", sa.String(200)), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False), sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_discovery_raw_results_provider_run_id", "discovery_raw_results", ["provider_run_id"])
    op.create_index("ix_discovery_raw_results_provider", "discovery_raw_results", ["provider"])
    op.create_index("ix_discovery_raw_results_payload_hash", "discovery_raw_results", ["payload_hash"])
    op.create_table("discovery_job_sources",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False), sa.Column("external_job_id", sa.String(200)), sa.Column("canonical_url", sa.Text()),
        sa.Column("relationship", sa.String(30), nullable=False), sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "external_job_id", name="uq_discovery_source_external"),
    )
    op.create_index("ix_discovery_job_sources_job_id", "discovery_job_sources", ["job_id"])
    op.create_index("ix_discovery_job_sources_provider", "discovery_job_sources", ["provider"])
    op.create_table("discovery_duplicate_groups",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("canonical_job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relationship", sa.String(30), nullable=False), sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table("discovery_match_results",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("discovery_search_runs.id", ondelete="CASCADE"), nullable=False), sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False), sa.Column("recommendation", sa.String(30), nullable=False), sa.Column("hard_rejected", sa.Boolean(), nullable=False),
        sa.Column("rejection_reasons", sa.JSON(), nullable=False), sa.Column("analysis", sa.JSON(), nullable=False), sa.Column("user_state", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "job_id", name="uq_discovery_match_run_job"),
    )
    op.create_index("ix_discovery_match_results_user_id", "discovery_match_results", ["user_id"])
    op.create_index("ix_discovery_match_results_run_id", "discovery_match_results", ["run_id"])
    op.create_index("ix_discovery_match_results_job_id", "discovery_match_results", ["job_id"])
    op.create_index("ix_discovery_match_results_score", "discovery_match_results", ["score"])
    op.create_index("ix_discovery_match_results_recommendation", "discovery_match_results", ["recommendation"])
    op.create_index("ix_discovery_match_user_rank", "discovery_match_results", ["user_id", "hard_rejected", "score"])
    op.create_table("discovery_provider_errors",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("provider_run_id", sa.String(36), sa.ForeignKey("discovery_provider_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False), sa.Column("code", sa.String(60), nullable=False), sa.Column("safe_message", sa.String(500), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_discovery_provider_errors_provider_run_id", "discovery_provider_errors", ["provider_run_id"])
    op.create_index("ix_discovery_provider_errors_provider", "discovery_provider_errors", ["provider"])
    op.create_table("discovery_notifications",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False), sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("deduplication_key", sa.String(180), nullable=False), sa.Column("title", sa.String(200), nullable=False), sa.Column("body", sa.String(500), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "deduplication_key", name="uq_notification_dedup"),
    )
    op.create_index("ix_discovery_notifications_user_id", "discovery_notifications", ["user_id"])
    op.create_index("ix_discovery_notifications_event_type", "discovery_notifications", ["event_type"])


def downgrade() -> None:
    for table in ("discovery_notifications", "discovery_provider_errors", "discovery_match_results", "discovery_duplicate_groups", "discovery_job_sources", "discovery_raw_results", "discovery_provider_cursors", "discovery_provider_runs", "discovery_search_queries", "discovery_search_runs", "discovery_search_configurations", "discovery_search_profiles"):
        op.drop_table(table)
    for name in ("provider_metadata", "last_checked_at", "expires_at", "posted_at", "relocation_information", "work_authorization_information", "required_years_experience", "preferred_skills", "required_skills", "required_languages", "salary_period", "seniority", "region", "responsibilities", "application_url", "normalized_title"):
        op.drop_column("jobs", name)
    discovery_run_status.drop(op.get_bind(), checkfirst=True)
