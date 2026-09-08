"""PostgreSQL authoritative persistence and relational domain records.

Revision ID: 20260907_0012
Revises: 20260721_0011
Create Date: 2026-09-07 20:40:24.151201
"""

import json
import uuid

import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260907_0012"
down_revision = "20260721_0011"
branch_labels = None
depends_on = None

JSON_COLUMNS = {
    "applications": ("match_analysis", "recruiter_contacts"),
    "audit_logs": ("metadata",),
    "candidate_profiles": (
        "citizenships",
        "preferred_titles",
        "preferred_locations",
        "preferred_industries",
        "workplace_preferences",
        "common_answers",
    ),
    "cv_analysis_runs": ("input_summary", "validation"),
    "cv_imports": ("extracted_pages", "sections", "draft", "validation", "model_metadata"),
    "cv_recommendations": ("validation",),
    "cv_variant_validations": ("issues",),
    "cv_variant_versions": (
        "content",
        "applied_recommendation_ids",
        "rejected_recommendation_ids",
        "user_edits",
        "keywords_added",
        "sections_improved",
        "remaining_gaps",
        "remaining_blockers",
        "validation",
    ),
    "discovery_duplicate_groups": ("signals",),
    "discovery_match_results": ("rejection_reasons", "analysis"),
    "discovery_provider_cursors": ("cursor",),
    "discovery_provider_runs": ("counters", "api_usage"),
    "discovery_raw_results": ("payload",),
    "discovery_search_configurations": ("provider_settings", "hard_filters"),
    "discovery_search_profiles": ("preferences", "generated_terms"),
    "discovery_search_queries": ("query",),
    "discovery_search_runs": ("counters",),
    "employment_entries": ("highlights",),
    "generated_documents": ("configuration",),
    "generated_documents": ("content", "validation", "configuration_json"),
    "jobs": (
        "requirements",
        "preferred_qualifications",
        "responsibilities",
        "required_languages",
        "required_skills",
        "preferred_skills",
        "provider_metadata",
        "raw_payload",
    ),
    "profile_versions": ("snapshot",),
}


def _convert_json_columns(to_jsonb: bool) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table_name, columns in JSON_COLUMNS.items():
        for column_name in columns:
            if to_jsonb:
                op.alter_column(
                    table_name,
                    column_name,
                    type_=postgresql.JSONB(),
                    postgresql_using=f'"{column_name}"::jsonb',
                )
            else:
                op.alter_column(
                    table_name,
                    column_name,
                    type_=sa.JSON(),
                    postgresql_using=f'"{column_name}"::json',
                )


def _json_value(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _backfill_job_versions() -> None:
    bind = op.get_bind()
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    versions = sa.table(
        "job_versions",
        sa.column("id", sa.String()),
        sa.column("job_id", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("content_hash", sa.String()),
        sa.column("snapshot", json_type),
    )
    requirements_table = sa.table(
        "job_requirements",
        sa.column("id", sa.String()),
        sa.column("job_version_id", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("text", sa.Text()),
        sa.column("normalized_text", sa.String()),
        sa.column("display_order", sa.Integer()),
    )
    rows = bind.execute(
        sa.text(
            "SELECT id, content_hash, title, company, description, requirements, "
            "preferred_qualifications, required_skills, preferred_skills FROM jobs"
        )
    ).mappings()
    for row in rows:
        version_id = str(uuid.uuid4())
        required = _json_value(row["requirements"], [])
        preferred = _json_value(row["preferred_qualifications"], [])
        bind.execute(
            versions.insert(),
            {
                "id": version_id,
                "job_id": row["id"],
                "version": 1,
                "content_hash": row["content_hash"],
                "snapshot": {
                    "title": row["title"],
                    "company": row["company"],
                    "description": row["description"],
                    "requirements": required,
                    "preferred_qualifications": preferred,
                    "required_skills": _json_value(row["required_skills"], []),
                    "preferred_skills": _json_value(row["preferred_skills"], []),
                },
            },
        )
        for kind, values in (("REQUIRED", required), ("PREFERRED", preferred)):
            for index, requirement in enumerate(values):
                bind.execute(
                    requirements_table.insert(),
                    {
                        "id": str(uuid.uuid4()),
                        "job_version_id": version_id,
                        "kind": kind,
                        "text": str(requirement),
                        "normalized_text": " ".join(str(requirement).casefold().split()),
                        "display_order": index,
                    },
                )


def _backfill_stored_files() -> None:
    """Create ownership/retention metadata for legacy filesystem artifacts."""
    bind = op.get_bind()
    stored_files = sa.table(
        "stored_files",
        sa.column("id", sa.String()),
        sa.column("owner_id", sa.String()),
        sa.column("cv_import_id", sa.String()),
        sa.column("cv_export_id", sa.String()),
        sa.column("document_export_id", sa.String()),
        sa.column("storage_key", sa.String()),
        sa.column("original_filename", sa.String()),
        sa.column("media_type", sa.String()),
        sa.column("size_bytes", sa.Integer()),
        sa.column("sha256", sa.String()),
        sa.column("retention_status", sa.String()),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )

    imports = bind.execute(
        sa.text(
            "SELECT id, user_id, storage_key, original_filename, media_type, size_bytes, "
            "sha256, file_deleted_at FROM cv_imports WHERE storage_key IS NOT NULL"
        )
    ).mappings()
    for row in imports:
        bind.execute(
            stored_files.insert(),
            {
                "id": str(uuid.uuid4()),
                "owner_id": row["user_id"],
                "cv_import_id": row["id"],
                "cv_export_id": None,
                "document_export_id": None,
                "storage_key": row["storage_key"],
                "original_filename": row["original_filename"],
                "media_type": row["media_type"],
                "size_bytes": row["size_bytes"],
                "sha256": row["sha256"],
                "retention_status": "DELETED" if row["file_deleted_at"] else "ACTIVE",
                "deleted_at": row["file_deleted_at"],
            },
        )

    cv_exports = bind.execute(
        sa.text(
            "SELECT e.id, v.user_id, e.format, e.storage_key, e.sha256, e.size_bytes "
            "FROM cv_exports e JOIN cv_variant_versions vv ON vv.id = e.variant_version_id "
            "JOIN cv_variants v ON v.id = vv.variant_id"
        )
    ).mappings()
    for row in cv_exports:
        bind.execute(
            stored_files.insert(),
            {
                "id": str(uuid.uuid4()),
                "owner_id": row["user_id"],
                "cv_import_id": None,
                "cv_export_id": row["id"],
                "document_export_id": None,
                "storage_key": row["storage_key"],
                "original_filename": f"cv-{row['id']}.{row['format']}",
                "media_type": _export_media_type(row["format"]),
                "size_bytes": row["size_bytes"],
                "sha256": row["sha256"],
                "retention_status": "ACTIVE",
                "deleted_at": None,
            },
        )

    document_exports = bind.execute(
        sa.text(
            "SELECT e.id, a.user_id, e.format, e.storage_key, e.sha256, e.size_bytes "
            "FROM document_exports e JOIN generated_documents d "
            "ON d.id = e.generated_document_id "
            "JOIN applications a ON a.id = d.application_id"
        )
    ).mappings()
    for row in document_exports:
        bind.execute(
            stored_files.insert(),
            {
                "id": str(uuid.uuid4()),
                "owner_id": row["user_id"],
                "cv_import_id": None,
                "cv_export_id": None,
                "document_export_id": row["id"],
                "storage_key": row["storage_key"],
                "original_filename": f"application-{row['id']}.{row['format']}",
                "media_type": _export_media_type(row["format"]),
                "size_bytes": row["size_bytes"],
                "sha256": row["sha256"],
                "retention_status": "ACTIVE",
                "deleted_at": None,
            },
        )


def _export_media_type(file_format: str) -> str:
    return {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(str(file_format).casefold(), "application/octet-stream")


def upgrade() -> None:
    _convert_json_columns(True)
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "job_providers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("access_type", sa.String(length=40), nullable=False),
        sa.Column("implementation_status", sa.String(length=60), nullable=False),
        sa.Column("documentation_url", sa.Text(), nullable=True),
        sa.Column(
            "capabilities",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    provider_table = sa.table(
        "job_providers",
        sa.column("id", sa.String()),
        sa.column("key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("access_type", sa.String()),
        sa.column("implementation_status", sa.String()),
        sa.column("documentation_url", sa.Text()),
        sa.column("capabilities", sa.JSON().with_variant(postgresql.JSONB(), "postgresql")),
        sa.column("active", sa.Boolean()),
    )
    provider_rows = (
        (
            "linkedin",
            "LinkedIn Jobs",
            "MANUAL_URL_IMPORT",
            "FALLBACK_ONLY",
            "https://www.linkedin.com/legal/l/api-terms-of-use",
        ),
        (
            "tecnoempleo",
            "Tecnoempleo",
            "PUBLIC_FEED",
            "IMPLEMENTED_CONFIG_REQUIRED",
            "https://www.tecnoempleo.com/ayuda.php",
        ),
        (
            "itjobs",
            "ITJobs.pt",
            "OFFICIAL_API",
            "IMPLEMENTED_CONFIG_REQUIRED",
            "https://www.itjobs.pt/api",
        ),
        (
            "landing_jobs",
            "Landing.jobs",
            "EMAIL_ALERT_INGESTION",
            "FALLBACK_ONLY",
            "https://wp.landing.jobs/blog/what-we-shipped-in-the-new-landing-jobs/",
        ),
        (
            "irishjobs",
            "IrishJobs.ie",
            "EMAIL_ALERT_INGESTION",
            "FALLBACK_ONLY",
            "https://www.irishjobs.ie/about/help-and-support",
        ),
        (
            "infojobs",
            "InfoJobs",
            "OFFICIAL_API",
            "IMPLEMENTED_CONFIG_REQUIRED",
            "https://developer.infojobs.net/documentation/operation/offer-list-9.xhtml",
        ),
        (
            "eures",
            "EURES",
            "DOCUMENTED_PARTNER_API",
            "PARTNER_ACCESS_REQUIRED",
            "https://eures.europa.eu/employers/advertise-job_en",
        ),
        (
            "indeed",
            "Indeed",
            "MANUAL_DESCRIPTION_IMPORT",
            "FALLBACK_ONLY",
            "https://docs.indeed.com/api-guides/",
        ),
        (
            "wellfound",
            "Wellfound",
            "EMAIL_ALERT_INGESTION",
            "FALLBACK_ONLY",
            "https://wellfound.com/terms",
        ),
        (
            "welcome_to_the_jungle",
            "Welcome to the Jungle",
            "MANUAL_DESCRIPTION_IMPORT",
            "FALLBACK_ONLY",
            "https://www.welcometothejungle.com/en/pages/terms",
        ),
    )
    op.bulk_insert(
        provider_table,
        [
            {
                "id": str(uuid.uuid4()),
                "key": key,
                "name": name,
                "access_type": access_type,
                "implementation_status": implementation_status,
                "documentation_url": documentation_url,
                "capabilities": {
                    "automated": implementation_status == "IMPLEMENTED_CONFIG_REQUIRED"
                },
                "active": True,
            }
            for key, name, access_type, implementation_status, documentation_url in provider_rows
        ],
    )
    op.create_index(op.f("ix_job_providers_active"), "job_providers", ["active"], unique=False)
    op.create_table(
        "local_data_migration_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("backup_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column(
            "table_counts",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_sha256"),
    )
    op.create_index(
        op.f("ix_local_data_migration_runs_status"),
        "local_data_migration_runs",
        ["status"],
        unique=False,
    )
    op.create_table(
        "skills",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("normalized_name", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_skills_normalized_name"), "skills", ["normalized_name"], unique=True)
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("STARTED", "SUCCEEDED", "FAILED", name="idempotencystatus"),
            nullable=False,
        ),
        sa.Column("result_type", sa.String(length=80), nullable=True),
        sa.Column("result_id", sa.String(length=36), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "operation", "idempotency_key", name="uq_idempotency_scope"),
    )
    op.create_index(
        op.f("ix_idempotency_records_expires_at"),
        "idempotency_records",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_idempotency_records_status"), "idempotency_records", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_idempotency_records_user_id"), "idempotency_records", ["user_id"], unique=False
    )
    op.create_table(
        "job_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "snapshot",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "content_hash", name="uq_job_version_hash"),
        sa.UniqueConstraint("job_id", "version", name="uq_job_version"),
    )
    op.create_index(
        op.f("ix_job_versions_content_hash"), "job_versions", ["content_hash"], unique=False
    )
    op.create_index(op.f("ix_job_versions_job_id"), "job_versions", ["job_id"], unique=False)
    op.create_table(
        "local_data_migration_errors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("migration_run_id", sa.String(length=36), nullable=False),
        sa.Column("table_name", sa.String(length=120), nullable=False),
        sa.Column("record_identifier", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["migration_run_id"], ["local_data_migration_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_local_data_migration_errors_migration_run_id"),
        "local_data_migration_errors",
        ["migration_run_id"],
        unique=False,
    )
    op.create_table(
        "upload_rate_limit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_upload_rate_limit_events_occurred_at"),
        "upload_rate_limit_events",
        ["occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_upload_rate_limit_events_user_id"),
        "upload_rate_limit_events",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_upload_rate_limit_user_time",
        "upload_rate_limit_events",
        ["user_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "user_provider_configurations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "configuration",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("authorization_reference", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["job_providers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "provider_id", name="uq_user_provider_configuration"),
    )
    op.create_index(
        op.f("ix_user_provider_configurations_provider_id"),
        "user_provider_configurations",
        ["provider_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_provider_configurations_user_id"),
        "user_provider_configurations",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "candidate_certifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("issuer", sa.String(length=240), nullable=True),
        sa.Column("issued_date", sa.Date(), nullable=True),
        sa.Column("expiration_date", sa.Date(), nullable=True),
        sa.Column("credential_url", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "display_order", name="uq_candidate_certification_order"),
    )
    op.create_index(
        op.f("ix_candidate_certifications_profile_id"),
        "candidate_certifications",
        ["profile_id"],
        unique=False,
    )
    op.create_table(
        "candidate_education",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("institution", sa.String(length=240), nullable=False),
        sa.Column("qualification", sa.String(length=240), nullable=True),
        sa.Column("field_of_study", sa.String(length=240), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "display_order", name="uq_candidate_education_order"),
    )
    op.create_index(
        op.f("ix_candidate_education_profile_id"),
        "candidate_education",
        ["profile_id"],
        unique=False,
    )
    op.create_table(
        "candidate_projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("role", sa.String(length=200), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "display_order", name="uq_candidate_project_order"),
    )
    op.create_index(
        op.f("ix_candidate_projects_profile_id"), "candidate_projects", ["profile_id"], unique=False
    )
    op.create_table(
        "cv_extraction_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("cv_import_id", sa.String(length=36), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column(
            "model_metadata",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["cv_import_id"], ["cv_imports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cv_import_id", "attempt", name="uq_cv_extraction_attempt"),
    )
    op.create_index(
        op.f("ix_cv_extraction_runs_cv_import_id"),
        "cv_extraction_runs",
        ["cv_import_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_cv_extraction_runs_status"), "cv_extraction_runs", ["status"], unique=False
    )
    op.create_table(
        "cv_field_corrections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("cv_import_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("field_path", sa.String(length=300), nullable=False),
        sa.Column(
            "previous_value",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "corrected_value",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cv_import_id"], ["cv_imports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_cv_field_corrections_actor_id"), "cv_field_corrections", ["actor_id"], unique=False
    )
    op.create_index(
        op.f("ix_cv_field_corrections_cv_import_id"),
        "cv_field_corrections",
        ["cv_import_id"],
        unique=False,
    )
    op.create_table(
        "job_requirements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_version_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.Enum("REQUIRED", "PREFERRED", name="jobskillkind"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.String(length=500), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["job_version_id"], ["job_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_version_id", "kind", "display_order", name="uq_job_requirement_order"
        ),
    )
    op.create_index(
        op.f("ix_job_requirements_job_version_id"),
        "job_requirements",
        ["job_version_id"],
        unique=False,
    )
    op.create_table(
        "job_skills",
        sa.Column("job_version_id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM("REQUIRED", "PREFERRED", name="jobskillkind", create_type=False),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_version_id"], ["job_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("job_version_id", "skill_id", "kind"),
    )
    op.create_index(op.f("ix_job_skills_skill_id"), "job_skills", ["skill_id"], unique=False)
    op.create_table(
        "job_status_history",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column(
            "from_status",
            sa.Enum("ACTIVE", "EXPIRED", "REMOVED", "ARCHIVED", name="joblifecyclestatus"),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            postgresql.ENUM(
                "ACTIVE",
                "EXPIRED",
                "REMOVED",
                "ARCHIVED",
                name="joblifecyclestatus",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("source_reference_id", sa.String(length=36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_reference_id"], ["discovery_job_sources.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_job_status_history_job_id"), "job_status_history", ["job_id"], unique=False
    )
    op.create_index(
        op.f("ix_job_status_history_to_status"), "job_status_history", ["to_status"], unique=False
    )
    op.create_table(
        "candidate_achievements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("employment_entry_id", sa.String(length=36), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "employment_entry_id IS NULL OR project_id IS NULL",
            name="ck_candidate_achievement_single_parent",
        ),
        sa.ForeignKeyConstraint(
            ["employment_entry_id"], ["employment_entries.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["candidate_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_candidate_achievements_employment_entry_id"),
        "candidate_achievements",
        ["employment_entry_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_achievements_profile_id"),
        "candidate_achievements",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_achievements_project_id"),
        "candidate_achievements",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "candidate_project_skills",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["candidate_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("project_id", "skill_id"),
    )
    op.create_index(
        op.f("ix_candidate_project_skills_skill_id"),
        "candidate_project_skills",
        ["skill_id"],
        unique=False,
    )
    op.create_table(
        "cv_extracted_fields",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("extraction_run_id", sa.String(length=36), nullable=False),
        sa.Column("field_path", sa.String(length=300), nullable=False),
        sa.Column(
            "value",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("ambiguous", sa.Boolean(), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_cv_field_confidence"),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"], ["cv_extraction_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("extraction_run_id", "field_path", name="uq_cv_extracted_field_path"),
    )
    op.create_index(
        op.f("ix_cv_extracted_fields_extraction_run_id"),
        "cv_extracted_fields",
        ["extraction_run_id"],
        unique=False,
    )
    op.create_table(
        "claim_validation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("generated_document_id", sa.String(length=36), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("checked_claims", sa.Integer(), nullable=False),
        sa.Column("validator_version", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["generated_document_id"], ["generated_documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_claim_validation_runs_generated_document_id"),
        "claim_validation_runs",
        ["generated_document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_claim_validation_runs_valid"), "claim_validation_runs", ["valid"], unique=False
    )
    op.create_table(
        "cv_extraction_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("extracted_field_id", sa.String(length=36), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("method", sa.String(length=30), nullable=False),
        sa.CheckConstraint("page > 0", name="ck_cv_evidence_page"),
        sa.ForeignKeyConstraint(
            ["extracted_field_id"], ["cv_extracted_fields.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_cv_extraction_evidence_extracted_field_id"),
        "cv_extraction_evidence",
        ["extracted_field_id"],
        unique=False,
    )
    op.create_table(
        "match_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("match_result_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("profile_version_id", sa.String(length=36), nullable=False),
        sa.Column("job_version_id", sa.String(length=36), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("recommendation", sa.String(length=30), nullable=False),
        sa.Column("hard_rejected", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("engine_version", sa.String(length=80), nullable=False),
        sa.Column(
            "matched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_match_confidence"),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_match_version_score"),
        sa.ForeignKeyConstraint(["job_version_id"], ["job_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["match_result_id"], ["discovery_match_results.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["profile_version_id"], ["profile_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_result_id", "version", name="uq_match_version"),
        sa.UniqueConstraint(
            "profile_version_id", "job_version_id", "engine_version", name="uq_match_input_engine"
        ),
    )
    op.create_index(
        op.f("ix_match_versions_engine_version"), "match_versions", ["engine_version"], unique=False
    )
    op.create_index(
        op.f("ix_match_versions_job_version_id"), "match_versions", ["job_version_id"], unique=False
    )
    op.create_index(
        op.f("ix_match_versions_match_result_id"),
        "match_versions",
        ["match_result_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_match_versions_profile_version_id"),
        "match_versions",
        ["profile_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_match_versions_recommendation"), "match_versions", ["recommendation"], unique=False
    )
    op.create_index(op.f("ix_match_versions_score"), "match_versions", ["score"], unique=False)
    op.create_table(
        "claim_validation_issues",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("validation_run_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("paragraph_index", sa.Integer(), nullable=True),
        sa.Column(
            "evidence",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["validation_run_id"], ["claim_validation_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_claim_validation_issues_code"), "claim_validation_issues", ["code"], unique=False
    )
    op.create_index(
        op.f("ix_claim_validation_issues_validation_run_id"),
        "claim_validation_issues",
        ["validation_run_id"],
        unique=False,
    )
    op.create_table(
        "match_blockers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("match_version_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("hard_rejection", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["match_version_id"], ["match_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_version_id", "code", name="uq_match_blocker_code"),
    )
    op.create_index(
        op.f("ix_match_blockers_match_version_id"),
        "match_blockers",
        ["match_version_id"],
        unique=False,
    )
    op.create_table(
        "match_recommendation_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("match_version_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["match_version_id"], ["match_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_match_recommendation_decisions_actor_id"),
        "match_recommendation_decisions",
        ["actor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_match_recommendation_decisions_decision"),
        "match_recommendation_decisions",
        ["decision"],
        unique=False,
    )
    op.create_index(
        op.f("ix_match_recommendation_decisions_match_version_id"),
        "match_recommendation_decisions",
        ["match_version_id"],
        unique=False,
    )
    op.create_table(
        "match_score_components",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("match_version_id", sa.String(length=36), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("maximum", sa.Float(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "evidence",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "score >= 0 AND maximum >= 0 AND score <= maximum", name="ck_match_component_score"
        ),
        sa.ForeignKeyConstraint(["match_version_id"], ["match_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_version_id", "category", name="uq_match_component_category"),
    )
    op.create_index(
        op.f("ix_match_score_components_match_version_id"),
        "match_score_components",
        ["match_version_id"],
        unique=False,
    )
    op.create_table(
        "match_skills",
        sa.Column("match_version_id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("MATCHING", "MISSING_REQUIRED", "MISSING_PREFERRED", name="matchskillkind"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["match_version_id"], ["match_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("match_version_id", "skill_id", "kind"),
    )
    op.create_index(op.f("ix_match_skills_skill_id"), "match_skills", ["skill_id"], unique=False)
    op.create_table(
        "match_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("match_version_id", sa.String(length=36), nullable=False),
        sa.Column("component_id", sa.String(length=36), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=240), nullable=False),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["component_id"], ["match_score_components.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["match_version_id"], ["match_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_version_id", "source_type", "source_id", name="uq_match_evidence_source"
        ),
    )
    op.create_index(
        op.f("ix_match_evidence_component_id"), "match_evidence", ["component_id"], unique=False
    )
    op.create_index(
        op.f("ix_match_evidence_match_version_id"),
        "match_evidence",
        ["match_version_id"],
        unique=False,
    )
    op.create_table(
        "stored_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("cv_import_id", sa.String(length=36), nullable=True),
        sa.Column("cv_export_id", sa.String(length=36), nullable=True),
        sa.Column("document_export_id", sa.String(length=36), nullable=True),
        sa.Column("storage_key", sa.String(length=100), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "retention_status",
            sa.Enum("ACTIVE", "PENDING_DELETION", "RETAINED", "DELETED", name="retentionstatus"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(CASE WHEN cv_import_id IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN cv_export_id IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN document_export_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_stored_file_single_owner",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_stored_file_size"),
        sa.ForeignKeyConstraint(["cv_export_id"], ["cv_exports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cv_import_id"], ["cv_imports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_export_id"], ["document_exports.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cv_export_id"),
        sa.UniqueConstraint("cv_import_id"),
        sa.UniqueConstraint("document_export_id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        op.f("ix_stored_files_deleted_at"), "stored_files", ["deleted_at"], unique=False
    )
    op.create_index(op.f("ix_stored_files_owner_id"), "stored_files", ["owner_id"], unique=False)
    op.create_index(
        op.f("ix_stored_files_retention_status"), "stored_files", ["retention_status"], unique=False
    )
    op.create_index(op.f("ix_stored_files_sha256"), "stored_files", ["sha256"], unique=False)
    op.add_column(
        "applications", sa.Column("row_version", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column(
        "candidate_profiles",
        sa.Column("row_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "candidate_profiles", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        op.f("ix_candidate_profiles_deleted_at"), "candidate_profiles", ["deleted_at"], unique=False
    )
    op.add_column(
        "jobs",
        sa.Column(
            "status",
            postgresql.ENUM(
                "ACTIVE",
                "EXPIRED",
                "REMOVED",
                "ARCHIVED",
                name="joblifecyclestatus",
                create_type=False,
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
    )
    op.add_column(
        "jobs", sa.Column("row_version", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column("jobs", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_jobs_company_normalized_title", "jobs", ["company", "normalized_title"], unique=False
    )
    op.create_index(op.f("ix_jobs_deleted_at"), "jobs", ["deleted_at"], unique=False)
    op.create_index("ix_jobs_normalized_title", "jobs", ["normalized_title"], unique=False)
    op.create_index("ix_jobs_posted_at", "jobs", ["posted_at"], unique=False)
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)
    op.create_index("ix_jobs_workplace_type", "jobs", ["workplace_type"], unique=False)
    op.add_column(
        "profile_skills", sa.Column("normalized_name", sa.String(length=120), nullable=True)
    )
    op.add_column("profile_skills", sa.Column("skill_id", sa.String(length=36), nullable=True))
    bind = op.get_bind()
    skill_rows = bind.execute(
        sa.text(
            "SELECT lower(trim(name)) AS normalized_name, min(name) AS display_name "
            "FROM profile_skills WHERE trim(name) <> '' GROUP BY lower(trim(name))"
        )
    ).mappings()
    for row in skill_rows:
        bind.execute(
            sa.text(
                "INSERT INTO skills (id, normalized_name, display_name) "
                "VALUES (:id, :normalized_name, :display_name)"
            ),
            {"id": str(uuid.uuid4()), **row},
        )
    bind.execute(sa.text("UPDATE profile_skills SET normalized_name = lower(trim(name))"))
    bind.execute(
        sa.text(
            "UPDATE profile_skills SET skill_id = "
            "(SELECT skills.id FROM skills WHERE skills.normalized_name = profile_skills.normalized_name)"
        )
    )
    op.create_index(
        op.f("ix_profile_skills_normalized_name"),
        "profile_skills",
        ["normalized_name"],
        unique=False,
    )
    with op.batch_alter_table("profile_skills") as batch_op:
        batch_op.alter_column("normalized_name", nullable=False)
        batch_op.alter_column("skill_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_profile_skills_skill_id", "skills", ["skill_id"], ["id"], ondelete="RESTRICT"
        )
    _backfill_job_versions()
    _backfill_stored_files()
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("profile_skills") as batch_op:
        batch_op.drop_constraint("fk_profile_skills_skill_id", type_="foreignkey")
    op.drop_index(op.f("ix_profile_skills_normalized_name"), table_name="profile_skills")
    op.drop_column("profile_skills", "skill_id")
    op.drop_column("profile_skills", "normalized_name")
    op.drop_index("ix_jobs_workplace_type", table_name="jobs")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_index("ix_jobs_posted_at", table_name="jobs")
    op.drop_index("ix_jobs_normalized_title", table_name="jobs")
    op.drop_index(op.f("ix_jobs_deleted_at"), table_name="jobs")
    op.drop_index("ix_jobs_company_normalized_title", table_name="jobs")
    op.drop_column("jobs", "deleted_at")
    op.drop_column("jobs", "row_version")
    op.drop_column("jobs", "status")
    op.drop_index(op.f("ix_candidate_profiles_deleted_at"), table_name="candidate_profiles")
    op.drop_column("candidate_profiles", "deleted_at")
    op.drop_column("candidate_profiles", "row_version")
    op.drop_column("applications", "row_version")
    op.drop_index(op.f("ix_stored_files_sha256"), table_name="stored_files")
    op.drop_index(op.f("ix_stored_files_retention_status"), table_name="stored_files")
    op.drop_index(op.f("ix_stored_files_owner_id"), table_name="stored_files")
    op.drop_index(op.f("ix_stored_files_deleted_at"), table_name="stored_files")
    op.drop_table("stored_files")
    op.drop_index(op.f("ix_match_evidence_match_version_id"), table_name="match_evidence")
    op.drop_index(op.f("ix_match_evidence_component_id"), table_name="match_evidence")
    op.drop_table("match_evidence")
    op.drop_index(op.f("ix_match_skills_skill_id"), table_name="match_skills")
    op.drop_table("match_skills")
    op.drop_index(
        op.f("ix_match_score_components_match_version_id"), table_name="match_score_components"
    )
    op.drop_table("match_score_components")
    op.drop_index(
        op.f("ix_match_recommendation_decisions_match_version_id"),
        table_name="match_recommendation_decisions",
    )
    op.drop_index(
        op.f("ix_match_recommendation_decisions_decision"),
        table_name="match_recommendation_decisions",
    )
    op.drop_index(
        op.f("ix_match_recommendation_decisions_actor_id"),
        table_name="match_recommendation_decisions",
    )
    op.drop_table("match_recommendation_decisions")
    op.drop_index(op.f("ix_match_blockers_match_version_id"), table_name="match_blockers")
    op.drop_table("match_blockers")
    op.drop_index(
        op.f("ix_claim_validation_issues_validation_run_id"), table_name="claim_validation_issues"
    )
    op.drop_index(op.f("ix_claim_validation_issues_code"), table_name="claim_validation_issues")
    op.drop_table("claim_validation_issues")
    op.drop_index(op.f("ix_match_versions_score"), table_name="match_versions")
    op.drop_index(op.f("ix_match_versions_recommendation"), table_name="match_versions")
    op.drop_index(op.f("ix_match_versions_profile_version_id"), table_name="match_versions")
    op.drop_index(op.f("ix_match_versions_match_result_id"), table_name="match_versions")
    op.drop_index(op.f("ix_match_versions_job_version_id"), table_name="match_versions")
    op.drop_index(op.f("ix_match_versions_engine_version"), table_name="match_versions")
    op.drop_table("match_versions")
    op.drop_index(
        op.f("ix_cv_extraction_evidence_extracted_field_id"), table_name="cv_extraction_evidence"
    )
    op.drop_table("cv_extraction_evidence")
    op.drop_index(op.f("ix_claim_validation_runs_valid"), table_name="claim_validation_runs")
    op.drop_index(
        op.f("ix_claim_validation_runs_generated_document_id"), table_name="claim_validation_runs"
    )
    op.drop_table("claim_validation_runs")
    op.drop_index(
        op.f("ix_cv_extracted_fields_extraction_run_id"), table_name="cv_extracted_fields"
    )
    op.drop_table("cv_extracted_fields")
    op.drop_index(
        op.f("ix_candidate_project_skills_skill_id"), table_name="candidate_project_skills"
    )
    op.drop_table("candidate_project_skills")
    op.drop_index(op.f("ix_candidate_achievements_project_id"), table_name="candidate_achievements")
    op.drop_index(op.f("ix_candidate_achievements_profile_id"), table_name="candidate_achievements")
    op.drop_index(
        op.f("ix_candidate_achievements_employment_entry_id"), table_name="candidate_achievements"
    )
    op.drop_table("candidate_achievements")
    op.drop_index(op.f("ix_job_status_history_to_status"), table_name="job_status_history")
    op.drop_index(op.f("ix_job_status_history_job_id"), table_name="job_status_history")
    op.drop_table("job_status_history")
    op.drop_index(op.f("ix_job_skills_skill_id"), table_name="job_skills")
    op.drop_table("job_skills")
    op.drop_index(op.f("ix_job_requirements_job_version_id"), table_name="job_requirements")
    op.drop_table("job_requirements")
    op.drop_index(op.f("ix_cv_field_corrections_cv_import_id"), table_name="cv_field_corrections")
    op.drop_index(op.f("ix_cv_field_corrections_actor_id"), table_name="cv_field_corrections")
    op.drop_table("cv_field_corrections")
    op.drop_index(op.f("ix_cv_extraction_runs_status"), table_name="cv_extraction_runs")
    op.drop_index(op.f("ix_cv_extraction_runs_cv_import_id"), table_name="cv_extraction_runs")
    op.drop_table("cv_extraction_runs")
    op.drop_index(op.f("ix_candidate_projects_profile_id"), table_name="candidate_projects")
    op.drop_table("candidate_projects")
    op.drop_index(op.f("ix_candidate_education_profile_id"), table_name="candidate_education")
    op.drop_table("candidate_education")
    op.drop_index(
        op.f("ix_candidate_certifications_profile_id"), table_name="candidate_certifications"
    )
    op.drop_table("candidate_certifications")
    op.drop_index(
        op.f("ix_user_provider_configurations_user_id"), table_name="user_provider_configurations"
    )
    op.drop_index(
        op.f("ix_user_provider_configurations_provider_id"),
        table_name="user_provider_configurations",
    )
    op.drop_table("user_provider_configurations")
    op.drop_index("ix_upload_rate_limit_user_time", table_name="upload_rate_limit_events")
    op.drop_index(
        op.f("ix_upload_rate_limit_events_user_id"), table_name="upload_rate_limit_events"
    )
    op.drop_index(
        op.f("ix_upload_rate_limit_events_occurred_at"), table_name="upload_rate_limit_events"
    )
    op.drop_table("upload_rate_limit_events")
    op.drop_index(
        op.f("ix_local_data_migration_errors_migration_run_id"),
        table_name="local_data_migration_errors",
    )
    op.drop_table("local_data_migration_errors")
    op.drop_index(op.f("ix_job_versions_job_id"), table_name="job_versions")
    op.drop_index(op.f("ix_job_versions_content_hash"), table_name="job_versions")
    op.drop_table("job_versions")
    op.drop_index(op.f("ix_idempotency_records_user_id"), table_name="idempotency_records")
    op.drop_index(op.f("ix_idempotency_records_status"), table_name="idempotency_records")
    op.drop_index(op.f("ix_idempotency_records_expires_at"), table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index(op.f("ix_skills_normalized_name"), table_name="skills")
    op.drop_table("skills")
    op.drop_index(
        op.f("ix_local_data_migration_runs_status"), table_name="local_data_migration_runs"
    )
    op.drop_table("local_data_migration_runs")
    op.drop_index(op.f("ix_job_providers_active"), table_name="job_providers")
    op.drop_table("job_providers")
    _convert_json_columns(False)
    if op.get_bind().dialect.name == "postgresql":
        for enum_name in (
            "idempotencystatus",
            "jobskillkind",
            "joblifecyclestatus",
            "matchskillkind",
            "retentionstatus",
        ):
            postgresql.ENUM(name=enum_name).drop(op.get_bind(), checkfirst=True)
    # ### end Alembic commands ###
