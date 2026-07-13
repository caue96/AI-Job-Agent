"""Strict API and provider schemas for grounded CV imports."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import CvImportStatus

TextValue = str | float | bool | None
ShortValue = Annotated[str, Field(min_length=1, max_length=500)]


class StrictCvModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CvEvidence(StrictCvModel):
    page: int = Field(ge=1, le=200)
    quote: Annotated[str, Field(min_length=1, max_length=1000)]
    method: Literal["ai", "deterministic", "user"]


class CvValue(StrictCvModel):
    value: TextValue
    confidence: float = Field(ge=0, le=1)
    ambiguous: bool
    evidence: list[CvEvidence] = Field(max_length=10)


class CvListValue(StrictCvModel):
    value: ShortValue
    confidence: float = Field(ge=0, le=1)
    evidence: list[CvEvidence] = Field(min_length=1, max_length=10)


class CvPersonalDetails(StrictCvModel):
    full_name: CvValue
    email: CvValue
    phone: CvValue
    city: CvValue
    country: CvValue
    linkedin_url: CvValue
    github_url: CvValue
    portfolio_url: CvValue
    work_authorization: CvValue


class CvEmployment(StrictCvModel):
    company: CvValue
    title: CvValue
    location: CvValue
    start_date: CvValue
    end_date: CvValue
    current: CvValue
    responsibilities: list[CvListValue] = Field(max_length=30)
    achievements: list[CvListValue] = Field(max_length=30)
    technologies: list[CvListValue] = Field(max_length=50)


class CvEducation(StrictCvModel):
    institution: CvValue
    qualification: CvValue
    field_of_study: CvValue
    location: CvValue
    start_date: CvValue
    end_date: CvValue
    details: list[CvListValue] = Field(max_length=20)


class CvCertification(StrictCvModel):
    name: CvValue
    issuer: CvValue
    issued_date: CvValue
    expiry_date: CvValue
    credential_id: CvValue


class CvProject(StrictCvModel):
    name: CvValue
    description: CvValue
    role: CvValue
    url: CvValue
    technologies: list[CvListValue] = Field(max_length=30)
    achievements: list[CvListValue] = Field(max_length=20)


class CvProfileDraft(StrictCvModel):
    personal: CvPersonalDetails
    headline: CvValue
    professional_summary: CvValue
    technical_skills: list[CvListValue] = Field(max_length=150)
    soft_skills: list[CvListValue] = Field(max_length=60)
    languages: list[CvListValue] = Field(max_length=30)
    employment: list[CvEmployment] = Field(max_length=60)
    education: list[CvEducation] = Field(max_length=30)
    certifications: list[CvCertification] = Field(max_length=50)
    projects: list[CvProject] = Field(max_length=50)
    achievements: list[CvListValue] = Field(max_length=50)
    citizenships: list[CvListValue] = Field(max_length=10)
    preferred_locations: list[CvListValue] = Field(max_length=30)
    preferred_titles: list[CvListValue] = Field(max_length=30)
    preferred_industries: list[CvListValue] = Field(max_length=30)
    workplace_preferences: list[CvListValue] = Field(max_length=5)
    salary_expectation: CvValue
    availability: CvValue
    declared_years_experience: CvValue
    calculated_years_experience: CvValue
    requires_sponsorship: CvValue
    relocation_available: CvValue


class CvDraftUpdate(StrictCvModel):
    draft: CvProfileDraft


class CvConfirmRequest(StrictCvModel):
    strategy: Literal["replace", "merge"]
    accept_conflicts: bool = False


class CvConflict(StrictCvModel):
    field: str
    existing: object
    imported: object


class CvComparison(StrictCvModel):
    profile_exists: bool
    conflicts: list[CvConflict]
    additions: list[str]


class CvImportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: CvImportStatus
    original_filename: str
    media_type: str
    size_bytes: int
    page_count: int | None
    draft: CvProfileDraft | None
    validation: dict
    model_metadata: dict
    file_available: bool
    created_at: datetime
    updated_at: datetime


class CvImportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: CvImportStatus
    original_filename: str
    size_bytes: int
    page_count: int | None
    file_available: bool
    created_at: datetime
    updated_at: datetime


class CvProfileVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    profile_id: str
    cv_import_id: str | None
    version: int
    strategy: str
    snapshot: CvProfileDraft
    created_at: datetime


class CvImportExport(StrictCvModel):
    import_record: CvImportRead
    versions: list[CvProfileVersionRead]
