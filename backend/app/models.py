from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


def uuid_str() -> str:
    return str(uuid.uuid4())


class ApplicationStatus(enum.StrEnum):
    DISCOVERED = "DISCOVERED"
    ANALYZED = "ANALYZED"
    REJECTED = "REJECTED"
    SHORTLISTED = "SHORTLISTED"
    DOCUMENTS_PREPARED = "DOCUMENTS_PREPARED"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    APPROVED = "APPROVED"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    SUBMITTED = "SUBMITTED"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    WITHDRAWN = "WITHDRAWN"


class GeneratedDocumentStatus(enum.StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


class CoverLetterStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    VALIDATED = "VALIDATED"
    USER_EDITED = "USER_EDITED"
    APPROVED = "APPROVED"
    EXPORTED = "EXPORTED"


class CvImportStatus(enum.StrEnum):
    PDF_SELECTED = "PDF_SELECTED"
    PDF_VALIDATED = "PDF_VALIDATED"
    TEXT_EXTRACTED = "TEXT_EXTRACTED"
    PROFILE_PARSED = "PROFILE_PARSED"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    PROFILE_CONFIRMED = "PROFILE_CONFIRMED"
    PROFILE_SAVED = "PROFILE_SAVED"


class DiscoveryRunStatus(enum.StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class CvOptimizationStatus(enum.StrEnum):
    CV_ANALYSIS_REQUESTED = "CV_ANALYSIS_REQUESTED"
    GAP_ANALYSIS_COMPLETED = "GAP_ANALYSIS_COMPLETED"
    IMPROVEMENTS_PROPOSED = "IMPROVEMENTS_PROPOSED"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    RECOMMENDATIONS_APPROVED = "RECOMMENDATIONS_APPROVED"
    CV_VARIANT_GENERATED = "CV_VARIANT_GENERATED"
    CV_VARIANT_SAVED = "CV_VARIANT_SAVED"


class CvRecommendationDecisionValue(enum.StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EDITED = "EDITED"


class CvVariantStatus(enum.StrEnum):
    JOB_SPECIFIC_DRAFT = "JOB_SPECIFIC_DRAFT"
    USER_REVIEWED = "USER_REVIEWED"
    APPROVED = "APPROVED"
    EXPORTED = "EXPORTED"


class RetentionStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    PENDING_DELETION = "PENDING_DELETION"
    RETAINED = "RETAINED"
    DELETED = "DELETED"


class JobLifecycleStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REMOVED = "REMOVED"
    ARCHIVED = "ARCHIVED"


class JobSkillKind(enum.StrEnum):
    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"


class MatchSkillKind(enum.StrEnum):
    MATCHING = "MATCHING"
    MISSING_REQUIRED = "MISSING_REQUIRED"
    MISSING_PREFERRED = "MISSING_PREFERRED"


class IdempotencyStatus(enum.StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(64))
    professional_summary: Mapped[str | None] = mapped_column(Text)
    citizenships: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    eu_work_authorized: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_sponsorship: Mapped[bool] = mapped_column(Boolean, default=True)
    preferred_titles: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    preferred_locations: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    preferred_industries: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    total_years_experience: Mapped[float | None] = mapped_column(nullable=True)
    min_salary: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    workplace_preferences: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    relocation_available: Mapped[bool] = mapped_column(Boolean, default=False)
    common_answers: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __mapper_args__ = {"version_id_col": row_version}
    skills: Mapped[list[ProfileSkill]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    languages: Mapped[list[ProfileLanguage]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    employment: Mapped[list[EmploymentEntry]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    __table_args__ = (UniqueConstraint("user_id"),)


class CvImport(Base):
    __tablename__ = "cv_imports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[CvImportStatus] = mapped_column(Enum(CvImportStatus), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    media_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    extracted_pages: Mapped[list[dict]] = mapped_column(JSON_DOCUMENT, default=list)
    sections: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    draft: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)
    validation: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    model_metadata: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    file_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (Index("ix_cv_imports_user_created", "user_id", "created_at"),)


class ProfileVersion(Base):
    __tablename__ = "profile_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True
    )
    cv_import_id: Mapped[str | None] = mapped_column(
        ForeignKey("cv_imports.id", ondelete="SET NULL"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    strategy: Mapped[str] = mapped_column(String(20))
    snapshot: Mapped[dict] = mapped_column(JSON_DOCUMENT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("profile_id", "version", name="uq_profile_version"),
        Index("ix_profile_versions_profile_created", "profile_id", "created_at"),
    )


class ProfileSkill(Base):
    __tablename__ = "profile_skills"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    normalized_name: Mapped[str] = mapped_column(String(120), index=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="RESTRICT"))
    years_experience: Mapped[float | None] = mapped_column(nullable=True)
    proficiency: Mapped[str | None] = mapped_column(String(30))
    profile: Mapped[CandidateProfile] = relationship(back_populates="skills")
    __table_args__ = (UniqueConstraint("profile_id", "name", name="uq_profile_skill_name"),)


class ProfileLanguage(Base):
    __tablename__ = "profile_languages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    language: Mapped[str] = mapped_column(String(80))
    proficiency: Mapped[str] = mapped_column(String(30))
    profile: Mapped[CandidateProfile] = relationship(back_populates="languages")
    __table_args__ = (UniqueConstraint("profile_id", "language", name="uq_profile_language"),)


class EmploymentEntry(Base):
    __tablename__ = "employment_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    company: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    highlights: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    profile: Mapped[CandidateProfile] = relationship(back_populates="employment")


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    source: Mapped[str] = mapped_column(String(100), index=True)
    external_job_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url: Mapped[str | None] = mapped_column(Text)
    normalized_url: Mapped[str | None] = mapped_column(Text)
    company: Mapped[str] = mapped_column(String(200), index=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    industry: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(2), index=True)
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    workplace_type: Mapped[str | None] = mapped_column(String(30))
    employment_type: Mapped[str | None] = mapped_column(String(30))
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    description: Mapped[str] = mapped_column(Text)
    requirements: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    preferred_qualifications: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    normalized_title: Mapped[str | None] = mapped_column(String(200))
    application_url: Mapped[str | None] = mapped_column(Text)
    responsibilities: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    region: Mapped[str | None] = mapped_column(String(120))
    seniority: Mapped[str | None] = mapped_column(String(40))
    salary_period: Mapped[str | None] = mapped_column(String(20))
    required_languages: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    required_skills: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    preferred_skills: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    required_years_experience: Mapped[float | None] = mapped_column(nullable=True)
    work_authorization_information: Mapped[str | None] = mapped_column(Text)
    relocation_information: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_metadata: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    deadline: Mapped[date | None] = mapped_column(Date)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    language: Mapped[str | None] = mapped_column(String(20))
    sponsorship_information: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_payload: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    status: Mapped[JobLifecycleStatus] = mapped_column(
        Enum(JobLifecycleStatus), default=JobLifecycleStatus.ACTIVE, index=True
    )
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __mapper_args__ = {"version_id_col": row_version}
    __table_args__ = (
        UniqueConstraint("source", "external_job_id", name="uq_job_source_external_id"),
        Index("ix_jobs_normalized_url", "normalized_url", unique=True),
        Index("ix_jobs_content_hash", "content_hash", unique=True),
        Index("ix_jobs_company_title_city", "company", "title", "city"),
        Index("ix_jobs_company_normalized_title", "company", "normalized_title"),
        Index("ix_jobs_normalized_title", "normalized_title"),
        Index("ix_jobs_workplace_type", "workplace_type"),
        Index("ix_jobs_posted_at", "posted_at"),
        Index("ix_jobs_discovered_at", "discovered_at"),
    )


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus), default=ApplicationStatus.DISCOVERED
    )
    match_score: Mapped[int | None] = mapped_column(Integer)
    match_analysis: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    recruiter_contacts: Mapped[list[dict]] = mapped_column(JSON_DOCUMENT, default=list)
    interview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __mapper_args__ = {"version_id_col": row_version}
    history: Mapped[list[ApplicationStatusHistory]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_user_job_application"),
        Index("ix_applications_user_updated_at", "user_id", "updated_at"),
    )


class ApplicationStatusHistory(Base):
    __tablename__ = "application_status_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    from_status: Mapped[ApplicationStatus | None] = mapped_column(
        Enum(ApplicationStatus), nullable=True
    )
    to_status: Mapped[ApplicationStatus] = mapped_column(Enum(ApplicationStatus))
    reason: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    application: Mapped[Application] = relationship(back_populates="history")
    __table_args__ = (
        Index("ix_application_history_application_created", "application_id", "created_at"),
    )


class GeneratedDocument(Base):
    __tablename__ = "generated_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    document_type: Mapped[str] = mapped_column(
        String(30), default="APPLICATION_PACKAGE", index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    profile_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("profile_versions.id", ondelete="RESTRICT"), index=True
    )
    parent_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("generated_documents.id", ondelete="SET NULL"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(2))
    status: Mapped[GeneratedDocumentStatus] = mapped_column(Enum(GeneratedDocumentStatus))
    content: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    validation: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    prompt_version: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    provider_response_id: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[float | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cover_letter_status: Mapped[CoverLetterStatus | None] = mapped_column(
        Enum(CoverLetterStatus), index=True
    )
    variant: Mapped[str | None] = mapped_column(String(30))
    tone: Mapped[str | None] = mapped_column(String(30))
    length: Mapped[str | None] = mapped_column(String(20))
    configuration_json: Mapped[dict] = mapped_column("configuration", JSON_DOCUMENT, default=dict)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("application_id", "version", name="uq_document_version"),)


class DocumentExport(Base):
    __tablename__ = "document_exports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    generated_document_id: Mapped[str] = mapped_column(
        ForeignKey("generated_documents.id", ondelete="CASCADE"), index=True
    )
    format: Mapped[str] = mapped_column(String(10))
    storage_key: Mapped[str] = mapped_column(String(100), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("generated_document_id", "format", name="uq_document_export_format"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DiscoverySearchProfile(Base):
    __tablename__ = "discovery_search_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    preferences: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    generated_terms: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DiscoverySearchConfiguration(Base):
    __tablename__ = "discovery_search_configurations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    provider_settings: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    schedule_kind: Mapped[str] = mapped_column(String(20), default="MANUAL")
    schedule_time: Mapped[str] = mapped_column(String(5), default="09:00")
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    hard_filters: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_discovery_config_name"),)


class DiscoverySearchRun(Base):
    __tablename__ = "discovery_search_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    configuration_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_search_configurations.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[DiscoveryRunStatus] = mapped_column(Enum(DiscoveryRunStatus), index=True)
    trigger: Mapped[str] = mapped_column(String(20))
    lifecycle_stage: Mapped[str] = mapped_column(String(40), default="SEARCH_SCHEDULED")
    scheduled_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    counters: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_discovery_runs_user_started", "user_id", "started_at"),)


class DiscoverySearchQuery(Base):
    __tablename__ = "discovery_search_queries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_search_runs.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40), index=True)
    query: Mapped[dict] = mapped_column(JSON_DOCUMENT)


class DiscoveryProviderRun(Base):
    __tablename__ = "discovery_provider_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_search_runs.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[DiscoveryRunStatus] = mapped_column(Enum(DiscoveryRunStatus))
    counters: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    api_usage: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DiscoveryProviderCursor(Base):
    __tablename__ = "discovery_provider_cursors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    configuration_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_search_configurations.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40))
    cursor: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    circuit_open_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_allowed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("configuration_id", "provider", name="uq_discovery_cursor_provider"),
    )


class DiscoveryRawResult(Base):
    __tablename__ = "discovery_raw_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    provider_run_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_provider_runs.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40), index=True)
    external_job_id: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSON_DOCUMENT)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DiscoveryJobSource(Base):
    __tablename__ = "discovery_job_sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    external_job_id: Mapped[str | None] = mapped_column(String(200))
    canonical_url: Mapped[str | None] = mapped_column(Text)
    relationship: Mapped[str] = mapped_column(String(30), default="CANONICAL")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("provider", "external_job_id", name="uq_discovery_source_external"),
    )


class DiscoveryDuplicateGroup(Base):
    __tablename__ = "discovery_duplicate_groups"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    canonical_job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    relationship: Mapped[str] = mapped_column(String(30))
    signals: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DiscoveryMatchResult(Base):
    __tablename__ = "discovery_match_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_search_runs.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    score: Mapped[int] = mapped_column(Integer, index=True)
    recommendation: Mapped[str] = mapped_column(String(30), index=True)
    hard_rejected: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reasons: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    analysis: Mapped[dict] = mapped_column(JSON_DOCUMENT)
    user_state: Mapped[str] = mapped_column(String(20), default="NEW")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("run_id", "job_id", name="uq_discovery_match_run_job"),
        Index("ix_discovery_match_user_rank", "user_id", "hard_rejected", "score"),
    )


class DiscoveryProviderError(Base):
    __tablename__ = "discovery_provider_errors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    provider_run_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_provider_runs.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40), index=True)
    code: Mapped[str] = mapped_column(String(60))
    safe_message: Mapped[str] = mapped_column(String(500))
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DiscoveryNotification(Base):
    __tablename__ = "discovery_notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    deduplication_key: Mapped[str] = mapped_column(String(180))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(500))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("user_id", "deduplication_key", name="uq_notification_dedup"),
    )


class CvAnalysisRun(Base):
    __tablename__ = "cv_analysis_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    profile_version_id: Mapped[str] = mapped_column(
        ForeignKey("profile_versions.id", ondelete="RESTRICT"), index=True
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    match_result_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_match_results.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[CvOptimizationStatus] = mapped_column(Enum(CvOptimizationStatus), index=True)
    original_score: Mapped[int] = mapped_column(Integer)
    input_summary: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    validation: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    prompt_version: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(100))
    provider_response_id: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (Index("ix_cv_analysis_user_job_created", "user_id", "job_id", "created_at"),)


class CvRecommendation(Base):
    __tablename__ = "cv_recommendations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    analysis_run_id: Mapped[str] = mapped_column(
        ForeignKey("cv_analysis_runs.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(50), index=True)
    section: Mapped[str] = mapped_column(String(200))
    current_text: Mapped[str] = mapped_column(Text, default="")
    suggested_text: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text)
    expected_benefit: Mapped[str] = mapped_column(Text)
    related_job_requirement: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column()
    priority: Mapped[str] = mapped_column(String(20), index=True)
    recommendation_type: Mapped[str] = mapped_column(String(30))
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True)
    decision: Mapped[CvRecommendationDecisionValue] = mapped_column(
        Enum(CvRecommendationDecisionValue), default=CvRecommendationDecisionValue.PENDING
    )
    user_text: Mapped[str | None] = mapped_column(Text)
    validation: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_cv_recommendations_run_order", "analysis_run_id", "display_order"),)


class CvRecommendationEvidence(Base):
    __tablename__ = "cv_recommendation_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    recommendation_id: Mapped[str] = mapped_column(
        ForeignKey("cv_recommendations.id", ondelete="CASCADE"), index=True
    )
    fact_id: Mapped[str] = mapped_column(String(240))
    source_section: Mapped[str] = mapped_column(String(120))
    quote: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("recommendation_id", "fact_id", name="uq_cv_recommendation_fact"),
    )


class CvRecommendationDecision(Base):
    __tablename__ = "cv_recommendation_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    recommendation_id: Mapped[str] = mapped_column(
        ForeignKey("cv_recommendations.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    decision: Mapped[CvRecommendationDecisionValue] = mapped_column(
        Enum(CvRecommendationDecisionValue)
    )
    edited_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvVariant(Base):
    __tablename__ = "cv_variants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    base_profile_version_id: Mapped[str] = mapped_column(
        ForeignKey("profile_versions.id", ondelete="RESTRICT"), index=True
    )
    analysis_run_id: Mapped[str] = mapped_column(
        ForeignKey("cv_analysis_runs.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[CvVariantStatus] = mapped_column(Enum(CvVariantStatus), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        UniqueConstraint("user_id", "analysis_run_id", name="uq_cv_variant_analysis"),
    )


class CvVariantVersion(Base):
    __tablename__ = "cv_variant_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    variant_id: Mapped[str] = mapped_column(
        ForeignKey("cv_variants.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[CvVariantStatus] = mapped_column(Enum(CvVariantStatus))
    content: Mapped[dict] = mapped_column(JSON_DOCUMENT)
    applied_recommendation_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    rejected_recommendation_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    user_edits: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    original_score: Mapped[int] = mapped_column(Integer)
    estimated_score: Mapped[int] = mapped_column(Integer)
    score_explanation: Mapped[str] = mapped_column(Text)
    keywords_added: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    sections_improved: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    remaining_gaps: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    remaining_blockers: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    validation: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    prompt_version: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("variant_id", "version", name="uq_cv_variant_version"),)


class CvVariantValidation(Base):
    __tablename__ = "cv_variant_validations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    variant_version_id: Mapped[str] = mapped_column(
        ForeignKey("cv_variant_versions.id", ondelete="CASCADE"), unique=True
    )
    valid: Mapped[bool] = mapped_column(Boolean)
    issues: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    checked_claims: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvExport(Base):
    __tablename__ = "cv_exports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    variant_version_id: Mapped[str] = mapped_column(
        ForeignKey("cv_variant_versions.id", ondelete="CASCADE"), index=True
    )
    format: Mapped[str] = mapped_column(String(10))
    storage_key: Mapped[str] = mapped_column(String(100), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("variant_version_id", "format", name="uq_cv_export_format"),)


class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    normalized_name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CandidateEducation(Base):
    __tablename__ = "candidate_education"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True
    )
    institution: Mapped[str] = mapped_column(String(240))
    qualification: Mapped[str | None] = mapped_column(String(240))
    field_of_study: Mapped[str | None] = mapped_column(String(240))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("profile_id", "display_order", name="uq_candidate_education_order"),
    )


class CandidateCertification(Base):
    __tablename__ = "candidate_certifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(240))
    issuer: Mapped[str | None] = mapped_column(String(240))
    issued_date: Mapped[date | None] = mapped_column(Date)
    expiration_date: Mapped[date | None] = mapped_column(Date)
    credential_url: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("profile_id", "display_order", name="uq_candidate_certification_order"),
    )


class CandidateProject(Base):
    __tablename__ = "candidate_projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("profile_id", "display_order", name="uq_candidate_project_order"),
    )


class CandidateProjectSkill(Base):
    __tablename__ = "candidate_project_skills"
    project_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_projects.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"), primary_key=True, index=True
    )


class CandidateAchievement(Base):
    __tablename__ = "candidate_achievements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True
    )
    employment_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey("employment_entries.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("candidate_projects.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint(
            "employment_entry_id IS NULL OR project_id IS NULL",
            name="ck_candidate_achievement_single_parent",
        ),
    )


class StoredFile(Base):
    __tablename__ = "stored_files"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    cv_import_id: Mapped[str | None] = mapped_column(
        ForeignKey("cv_imports.id", ondelete="CASCADE"), unique=True
    )
    cv_export_id: Mapped[str | None] = mapped_column(
        ForeignKey("cv_exports.id", ondelete="CASCADE"), unique=True
    )
    document_export_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_exports.id", ondelete="CASCADE"), unique=True
    )
    storage_key: Mapped[str] = mapped_column(String(100), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    retention_status: Mapped[RetentionStatus] = mapped_column(
        Enum(RetentionStatus), default=RetentionStatus.ACTIVE, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="ck_stored_file_size"),
        CheckConstraint(
            "(CASE WHEN cv_import_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN cv_export_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN document_export_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_stored_file_single_owner",
        ),
    )


class CvExtractionRun(Base):
    __tablename__ = "cv_extraction_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    cv_import_id: Mapped[str] = mapped_column(
        ForeignKey("cv_imports.id", ondelete="CASCADE"), index=True
    )
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), index=True)
    model_metadata: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("cv_import_id", "attempt", name="uq_cv_extraction_attempt"),)


class CvExtractedField(Base):
    __tablename__ = "cv_extracted_fields"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("cv_extraction_runs.id", ondelete="CASCADE"), index=True
    )
    field_path: Mapped[str] = mapped_column(String(300))
    value: Mapped[dict] = mapped_column(JSON_DOCUMENT)
    confidence: Mapped[float] = mapped_column()
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        UniqueConstraint("extraction_run_id", "field_path", name="uq_cv_extracted_field_path"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_cv_field_confidence"),
    )


class CvExtractionEvidence(Base):
    __tablename__ = "cv_extraction_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    extracted_field_id: Mapped[str] = mapped_column(
        ForeignKey("cv_extracted_fields.id", ondelete="CASCADE"), index=True
    )
    page: Mapped[int] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(30))
    __table_args__ = (CheckConstraint("page > 0", name="ck_cv_evidence_page"),)


class CvFieldCorrection(Base):
    __tablename__ = "cv_field_corrections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    cv_import_id: Mapped[str] = mapped_column(
        ForeignKey("cv_imports.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    field_path: Mapped[str] = mapped_column(String(300))
    previous_value: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)
    corrected_value: Mapped[dict] = mapped_column(JSON_DOCUMENT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobProvider(Base):
    __tablename__ = "job_providers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    key: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    access_type: Mapped[str] = mapped_column(String(40))
    implementation_status: Mapped[str] = mapped_column(String(60))
    documentation_url: Mapped[str | None] = mapped_column(Text)
    capabilities: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserProviderConfiguration(Base):
    __tablename__ = "user_provider_configurations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("job_providers.id", ondelete="RESTRICT"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    configuration: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    authorization_reference: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        UniqueConstraint("user_id", "provider_id", name="uq_user_provider_configuration"),
    )


class JobVersion(Base):
    __tablename__ = "job_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    snapshot: Mapped[dict] = mapped_column(JSON_DOCUMENT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("job_id", "version", name="uq_job_version"),
        UniqueConstraint("job_id", "content_hash", name="uq_job_version_hash"),
    )


class JobRequirement(Base):
    __tablename__ = "job_requirements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_version_id: Mapped[str] = mapped_column(
        ForeignKey("job_versions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[JobSkillKind] = mapped_column(Enum(JobSkillKind))
    text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(String(500))
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        UniqueConstraint(
            "job_version_id", "kind", "display_order", name="uq_job_requirement_order"
        ),
    )


class JobSkill(Base):
    __tablename__ = "job_skills"
    job_version_id: Mapped[str] = mapped_column(
        ForeignKey("job_versions.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    kind: Mapped[JobSkillKind] = mapped_column(Enum(JobSkillKind), primary_key=True)


class JobStatusHistory(Base):
    __tablename__ = "job_status_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[JobLifecycleStatus | None] = mapped_column(Enum(JobLifecycleStatus))
    to_status: Mapped[JobLifecycleStatus] = mapped_column(Enum(JobLifecycleStatus), index=True)
    source_reference_id: Mapped[str | None] = mapped_column(
        ForeignKey("discovery_job_sources.id", ondelete="SET NULL")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MatchVersion(Base):
    __tablename__ = "match_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    match_result_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_match_results.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    profile_version_id: Mapped[str] = mapped_column(
        ForeignKey("profile_versions.id", ondelete="RESTRICT"), index=True
    )
    job_version_id: Mapped[str] = mapped_column(
        ForeignKey("job_versions.id", ondelete="RESTRICT"), index=True
    )
    score: Mapped[int] = mapped_column(Integer, index=True)
    recommendation: Mapped[str] = mapped_column(String(30), index=True)
    hard_rejected: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column()
    explanation: Mapped[str] = mapped_column(Text)
    engine_version: Mapped[str] = mapped_column(String(80), index=True)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("match_result_id", "version", name="uq_match_version"),
        UniqueConstraint(
            "profile_version_id",
            "job_version_id",
            "engine_version",
            name="uq_match_input_engine",
        ),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_match_version_score"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_match_confidence"),
    )


class MatchScoreComponent(Base):
    __tablename__ = "match_score_components"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    match_version_id: Mapped[str] = mapped_column(
        ForeignKey("match_versions.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(80))
    score: Mapped[float] = mapped_column()
    maximum: Mapped[float] = mapped_column()
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    __table_args__ = (
        UniqueConstraint("match_version_id", "category", name="uq_match_component_category"),
        CheckConstraint(
            "score >= 0 AND maximum >= 0 AND score <= maximum", name="ck_match_component_score"
        ),
    )


class MatchSkill(Base):
    __tablename__ = "match_skills"
    match_version_id: Mapped[str] = mapped_column(
        ForeignKey("match_versions.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    kind: Mapped[MatchSkillKind] = mapped_column(Enum(MatchSkillKind), primary_key=True)


class MatchBlocker(Base):
    __tablename__ = "match_blockers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    match_version_id: Mapped[str] = mapped_column(
        ForeignKey("match_versions.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    hard_rejection: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("match_version_id", "code", name="uq_match_blocker_code"),)


class MatchEvidence(Base):
    __tablename__ = "match_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    match_version_id: Mapped[str] = mapped_column(
        ForeignKey("match_versions.id", ondelete="CASCADE"), index=True
    )
    component_id: Mapped[str | None] = mapped_column(
        ForeignKey("match_score_components.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str] = mapped_column(String(240))
    quote: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON_DOCUMENT, default=dict)
    __table_args__ = (
        UniqueConstraint(
            "match_version_id", "source_type", "source_id", name="uq_match_evidence_source"
        ),
    )


class MatchRecommendationDecision(Base):
    __tablename__ = "match_recommendation_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    match_version_id: Mapped[str] = mapped_column(
        ForeignKey("match_versions.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    decision: Mapped[str] = mapped_column(String(30), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClaimValidationRun(Base):
    __tablename__ = "claim_validation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    generated_document_id: Mapped[str] = mapped_column(
        ForeignKey("generated_documents.id", ondelete="CASCADE"), index=True
    )
    valid: Mapped[bool] = mapped_column(Boolean, index=True)
    checked_claims: Mapped[int] = mapped_column(Integer, default=0)
    validator_version: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClaimValidationIssue(Base):
    __tablename__ = "claim_validation_issues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    validation_run_id: Mapped[str] = mapped_column(
        ForeignKey("claim_validation_runs.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(80), index=True)
    message: Mapped[str] = mapped_column(Text)
    paragraph_index: Mapped[int | None] = mapped_column(Integer)
    evidence: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    operation: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[IdempotencyStatus] = mapped_column(Enum(IdempotencyStatus), index=True)
    result_type: Mapped[str | None] = mapped_column(String(80))
    result_id: Mapped[str | None] = mapped_column(String(36))
    error_code: Mapped[str | None] = mapped_column(String(80))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        UniqueConstraint("user_id", "operation", "idempotency_key", name="uq_idempotency_scope"),
    )


class LocalDataMigrationRun(Base):
    __tablename__ = "local_data_migration_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    source_name: Mapped[str] = mapped_column(String(255))
    source_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    backup_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), index=True)
    table_counts: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LocalDataMigrationError(Base):
    __tablename__ = "local_data_migration_errors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    migration_run_id: Mapped[str] = mapped_column(
        ForeignKey("local_data_migration_runs.id", ondelete="CASCADE"), index=True
    )
    table_name: Mapped[str] = mapped_column(String(120))
    record_identifier: Mapped[str | None] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UploadRateLimitEvent(Base):
    __tablename__ = "upload_rate_limit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    __table_args__ = (Index("ix_upload_rate_limit_user_time", "user_id", "occurred_at"),)
