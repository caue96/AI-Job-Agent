from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


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
    citizenships: Mapped[list[str]] = mapped_column(JSON, default=list)
    eu_work_authorized: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_sponsorship: Mapped[bool] = mapped_column(Boolean, default=True)
    preferred_titles: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_industries: Mapped[list[str]] = mapped_column(JSON, default=list)
    total_years_experience: Mapped[float | None] = mapped_column(nullable=True)
    min_salary: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    workplace_preferences: Mapped[list[str]] = mapped_column(JSON, default=list)
    relocation_available: Mapped[bool] = mapped_column(Boolean, default=False)
    common_answers: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
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


class ProfileSkill(Base):
    __tablename__ = "profile_skills"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
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
    highlights: Mapped[list[str]] = mapped_column(JSON, default=list)
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
    requirements: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_qualifications: Mapped[list[str]] = mapped_column(JSON, default=list)
    deadline: Mapped[date | None] = mapped_column(Date)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    language: Mapped[str | None] = mapped_column(String(20))
    sponsorship_information: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("source", "external_job_id", name="uq_job_source_external_id"),
        Index("ix_jobs_normalized_url", "normalized_url", unique=True),
        Index("ix_jobs_content_hash", "content_hash", unique=True),
        Index("ix_jobs_company_title_city", "company", "title", "city"),
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
    match_analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    recruiter_contacts: Mapped[list[dict]] = mapped_column(JSON, default=list)
    interview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
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
    version: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(2))
    status: Mapped[GeneratedDocumentStatus] = mapped_column(Enum(GeneratedDocumentStatus))
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    prompt_version: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    provider_response_id: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[float | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("application_id", "version", name="uq_document_version"),)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
