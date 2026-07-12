"""Phase 2 foundation schema.

Revision ID: 20260711_0001
Revises:
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa

revision = "20260711_0001"
down_revision = None
branch_labels = None
depends_on = None

application_status = sa.Enum(
    "DISCOVERED", "ANALYZED", "REJECTED", "SHORTLISTED", "DOCUMENTS_PREPARED", "AWAITING_REVIEW",
    "APPROVED", "READY_TO_SUBMIT", "SUBMITTED", "INTERVIEW", "OFFER", "WITHDRAWN", name="applicationstatus"
)


def upgrade() -> None:
    op.create_table("users", sa.Column("id", sa.String(36), primary_key=True), sa.Column("email", sa.String(320), nullable=False), sa.Column("password_hash", sa.String(255)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table("candidate_profiles", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("full_name", sa.String(200), nullable=False), sa.Column("email", sa.String(320), nullable=False), sa.Column("phone", sa.String(64)), sa.Column("professional_summary", sa.Text()), sa.Column("citizenships", sa.JSON(), nullable=False), sa.Column("eu_work_authorized", sa.Boolean(), nullable=False), sa.Column("requires_sponsorship", sa.Boolean(), nullable=False), sa.Column("preferred_titles", sa.JSON(), nullable=False), sa.Column("preferred_locations", sa.JSON(), nullable=False), sa.Column("min_salary", sa.Integer()), sa.Column("salary_currency", sa.String(3)), sa.Column("workplace_preferences", sa.JSON(), nullable=False), sa.Column("relocation_available", sa.Boolean(), nullable=False), sa.Column("common_answers", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.UniqueConstraint("user_id"))
    op.create_index("ix_candidate_profiles_user_id", "candidate_profiles", ["user_id"])
    op.create_table("profile_skills", sa.Column("id", sa.String(36), primary_key=True), sa.Column("profile_id", sa.String(36), sa.ForeignKey("candidate_profiles.id"), nullable=False), sa.Column("name", sa.String(120), nullable=False), sa.Column("years_experience", sa.Float()), sa.Column("proficiency", sa.String(30)), sa.UniqueConstraint("profile_id", "name", name="uq_profile_skill_name"))
    op.create_index("ix_profile_skills_profile_id", "profile_skills", ["profile_id"])
    op.create_table("profile_languages", sa.Column("id", sa.String(36), primary_key=True), sa.Column("profile_id", sa.String(36), sa.ForeignKey("candidate_profiles.id"), nullable=False), sa.Column("language", sa.String(80), nullable=False), sa.Column("proficiency", sa.String(30), nullable=False), sa.UniqueConstraint("profile_id", "language", name="uq_profile_language"))
    op.create_index("ix_profile_languages_profile_id", "profile_languages", ["profile_id"])
    op.create_table("employment_entries", sa.Column("id", sa.String(36), primary_key=True), sa.Column("profile_id", sa.String(36), sa.ForeignKey("candidate_profiles.id"), nullable=False), sa.Column("company", sa.String(200), nullable=False), sa.Column("title", sa.String(200), nullable=False), sa.Column("start_date", sa.Date()), sa.Column("end_date", sa.Date()), sa.Column("highlights", sa.JSON(), nullable=False))
    op.create_index("ix_employment_entries_profile_id", "employment_entries", ["profile_id"])
    op.create_table("jobs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("source", sa.String(100), nullable=False), sa.Column("external_job_id", sa.String(200)), sa.Column("url", sa.Text()), sa.Column("normalized_url", sa.Text()), sa.Column("company", sa.String(200), nullable=False), sa.Column("title", sa.String(200), nullable=False), sa.Column("country", sa.String(2)), sa.Column("city", sa.String(120)), sa.Column("workplace_type", sa.String(30)), sa.Column("employment_type", sa.String(30)), sa.Column("salary_min", sa.Integer()), sa.Column("salary_max", sa.Integer()), sa.Column("salary_currency", sa.String(3)), sa.Column("description", sa.Text(), nullable=False), sa.Column("requirements", sa.JSON(), nullable=False), sa.Column("preferred_qualifications", sa.JSON(), nullable=False), sa.Column("deadline", sa.Date()), sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("language", sa.String(20)), sa.Column("sponsorship_information", sa.Text()), sa.Column("content_hash", sa.String(64), nullable=False), sa.Column("raw_payload", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.UniqueConstraint("source", "external_job_id", name="uq_job_source_external_id"))
    for name, columns in [("ix_jobs_source", ["source"]), ("ix_jobs_normalized_url", ["normalized_url"]), ("ix_jobs_company", ["company"]), ("ix_jobs_title", ["title"]), ("ix_jobs_country", ["country"]), ("ix_jobs_city", ["city"]), ("ix_jobs_content_hash", ["content_hash"]), ("ix_jobs_company_title_city", ["company", "title", "city"])]: op.create_index(name, "jobs", columns)
    application_status.create(op.get_bind(), checkfirst=True)
    op.create_table("applications", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False), sa.Column("status", application_status, nullable=False), sa.Column("match_score", sa.Integer()), sa.Column("match_analysis", sa.JSON(), nullable=False), sa.Column("notes", sa.Text()), sa.Column("recruiter_contacts", sa.JSON(), nullable=False), sa.Column("interview_at", sa.DateTime(timezone=True)), sa.Column("follow_up_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.UniqueConstraint("user_id", "job_id", name="uq_user_job_application"))
    op.create_index("ix_applications_user_id", "applications", ["user_id"])
    op.create_index("ix_applications_job_id", "applications", ["job_id"])
    op.create_table("application_status_history", sa.Column("id", sa.String(36), primary_key=True), sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False), sa.Column("from_status", application_status), sa.Column("to_status", application_status, nullable=False), sa.Column("reason", sa.Text()), sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_application_status_history_application_id", "application_status_history", ["application_id"])
    op.create_table("audit_logs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("action", sa.String(100), nullable=False), sa.Column("entity_type", sa.String(100), nullable=False), sa.Column("entity_id", sa.String(36), nullable=False), sa.Column("metadata_json", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_entity_id", "audit_logs", ["entity_id"])


def downgrade() -> None:
    for table in ["audit_logs", "application_status_history", "applications", "jobs", "employment_entries", "profile_languages", "profile_skills", "candidate_profiles", "users"]:
        op.drop_table(table)
    application_status.drop(op.get_bind(), checkfirst=True)
