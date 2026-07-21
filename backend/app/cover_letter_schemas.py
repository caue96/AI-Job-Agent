"""Strict API and provider contracts for grounded cover letters."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import CoverLetterStatus, GeneratedDocumentStatus

CoverLetterLanguage = Literal["en", "es", "pt"]
CoverLetterTone = Literal[
    "PROFESSIONAL",
    "CONFIDENT",
    "CONCISE",
    "WARM",
    "TECHNICAL",
    "BUSINESS_ORIENTED",
    "STARTUP_ORIENTED",
    "CORPORATE",
]
CoverLetterLength = Literal["SHORT", "STANDARD", "DETAILED"]
CoverLetterVariant = Literal["BALANCED", "TECHNICAL", "BUSINESS_FOCUSED"]
ClosingStyle = Literal["PROFESSIONAL", "WARM", "CONCISE"]
GreetingStyle = Literal["AUTO", "HIRING_MANAGER", "HIRING_TEAM"]


class StrictCoverLetterModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CoverLetterGenerateRequest(StrictCoverLetterModel):
    job_id: str = Field(min_length=1, max_length=36)
    language: CoverLetterLanguage | None = None
    tone: CoverLetterTone = "PROFESSIONAL"
    length: CoverLetterLength = "STANDARD"
    variants: list[CoverLetterVariant] = Field(default=["BALANCED"], min_length=1, max_length=3)
    greeting_style: GreetingStyle = "AUTO"
    hiring_manager_name: str | None = Field(default=None, min_length=1, max_length=120)
    hiring_manager_verified: bool = False
    include_salary_expectations: bool = False
    include_relocation: bool = True
    include_work_authorization: bool = True
    include_current_employer: bool = True
    include_contact_details: bool = True
    excluded_achievement_fact_ids: list[str] = Field(default_factory=list, max_length=30)
    excluded_project_fact_ids: list[str] = Field(default_factory=list, max_length=30)
    closing_style: ClosingStyle = "PROFESSIONAL"

    @model_validator(mode="after")
    def validate_customization(self) -> CoverLetterGenerateRequest:
        if len(self.variants) != len(set(self.variants)):
            raise ValueError("Cover-letter variants must be unique")
        if self.hiring_manager_name and not self.hiring_manager_verified:
            raise ValueError("A hiring-manager name must be explicitly verified")
        if self.greeting_style == "HIRING_MANAGER" and not self.hiring_manager_name:
            raise ValueError("HIRING_MANAGER greeting requires a verified name")
        excluded = [
            *self.excluded_achievement_fact_ids,
            *self.excluded_project_fact_ids,
        ]
        if any(not value.startswith("candidate:") or len(value) > 240 for value in excluded):
            raise ValueError("Excluded evidence IDs must be candidate fact IDs")
        return self


class CoverLetterPlan(StrictCoverLetterModel):
    variant: CoverLetterVariant
    opening_fact_ids: list[str] = Field(min_length=1, max_length=3)
    qualification_fact_ids: list[str] = Field(min_length=1, max_length=8)
    achievement_fact_ids: list[str] = Field(default_factory=list, max_length=2)
    project_fact_ids: list[str] = Field(default_factory=list, max_length=1)
    authorization_fact_ids: list[str] = Field(default_factory=list, max_length=3)
    company_fact_ids: list[str] = Field(default_factory=list, max_length=3)


class CoverLetterPlanSet(StrictCoverLetterModel):
    plans: list[CoverLetterPlan] = Field(min_length=1, max_length=3)


class CoverLetterParagraph(StrictCoverLetterModel):
    kind: Literal[
        "OPENING",
        "MOTIVATION",
        "QUALIFICATIONS",
        "ACHIEVEMENT",
        "PROJECT",
        "AUTHORIZATION",
        "CLOSING",
    ]
    text: str = Field(min_length=1, max_length=5000)
    baseline_text: str = Field(min_length=1, max_length=5000)
    candidate_fact_ids: list[str] = Field(default_factory=list, max_length=12)
    company_fact_ids: list[str] = Field(default_factory=list, max_length=5)
    confidence: float = Field(ge=0, le=1)


class CoverLetterContent(StrictCoverLetterModel):
    candidate_name: str = Field(min_length=1, max_length=200)
    contact_line: str = Field(max_length=1000, default="")
    date: str = Field(min_length=10, max_length=10)
    company: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=200)
    greeting: str = Field(min_length=1, max_length=200)
    paragraphs: list[CoverLetterParagraph] = Field(min_length=3, max_length=10)
    signoff: str = Field(min_length=1, max_length=200)
    word_count: int = Field(ge=1, le=2000)


class ClaimValidationIssue(StrictCoverLetterModel):
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    paragraph_index: int | None = Field(default=None, ge=0)
    text: str = Field(max_length=1000, default="")


class CoverLetterValidation(StrictCoverLetterModel):
    valid: bool
    checked_claims: int = Field(ge=0)
    issues: list[ClaimValidationIssue] = Field(default_factory=list, max_length=100)
    low_confidence_paragraphs: list[int] = Field(default_factory=list, max_length=20)


class CoverLetterEvidence(StrictCoverLetterModel):
    fact_id: str
    source_section: str
    quote: str


class CoverLetterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    application_id: str
    job_id: str
    profile_version_id: str
    parent_document_id: str | None
    version: int
    language: str
    status: GeneratedDocumentStatus
    cover_letter_status: CoverLetterStatus
    variant: str
    tone: str
    length: str
    selected: bool
    content: CoverLetterContent
    validation: CoverLetterValidation
    evidence: list[CoverLetterEvidence]
    configuration: dict
    prompt_version: str
    model: str
    provider_response_id: str | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    latency_ms: int | None
    approved_at: datetime | None
    created_at: datetime


class CoverLetterEditRequest(StrictCoverLetterModel):
    greeting: str = Field(min_length=1, max_length=200)
    paragraphs: list[str] = Field(min_length=3, max_length=10)
    signoff: str = Field(min_length=1, max_length=200)


class CoverLetterExportRequest(StrictCoverLetterModel):
    format: Literal["txt", "docx", "pdf"]


class DocumentExportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    generated_document_id: str
    format: str
    sha256: str
    size_bytes: int
    created_at: datetime
