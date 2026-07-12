from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator
from pydantic.functional_validators import model_validator

from app.models import ApplicationStatus, GeneratedDocumentStatus

ShortText = Annotated[str, Field(min_length=1, max_length=200)]
ListText = Annotated[str, Field(min_length=1, max_length=500)]
AnswerKey = Annotated[str, Field(min_length=1, max_length=200)]
AnswerValue = Annotated[str, Field(max_length=4000)]


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def reject_duplicate_named_items(
    items: Sequence[object] | None, attribute: str, label: str
) -> None:
    if not items:
        return
    names = [str(getattr(item, attribute)).casefold() for item in items]
    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate {label} entries are not allowed")


class SkillInput(StrictRequestModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=120)]
    years_experience: float | None = Field(default=None, ge=0, le=60)
    proficiency: str | None = Field(default=None, max_length=30)


class LanguageInput(StrictRequestModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    language: Annotated[str, Field(min_length=1, max_length=80)]
    proficiency: Annotated[str, Field(min_length=1, max_length=30)]


class EmploymentInput(StrictRequestModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    company: Annotated[str, Field(min_length=1, max_length=200)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    start_date: date | None = None
    end_date: date | None = None
    highlights: list[Annotated[str, Field(max_length=500)]] = Field(
        default_factory=list, max_length=20
    )

    @model_validator(mode="after")
    def validate_date_range(self) -> EmploymentInput:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be greater than or equal to start_date")
        return self


class ProfileCreate(StrictRequestModel):
    full_name: Annotated[str, Field(min_length=1, max_length=200)]
    email: EmailStr
    phone: str | None = Field(default=None, max_length=64)
    professional_summary: str | None = Field(default=None, max_length=4000)
    citizenships: list[ShortText] = Field(default_factory=list, max_length=10)
    eu_work_authorized: bool = False
    requires_sponsorship: bool = True
    preferred_titles: list[ShortText] = Field(default_factory=list, max_length=20)
    preferred_locations: list[ShortText] = Field(default_factory=list, max_length=30)
    preferred_industries: list[ShortText] = Field(default_factory=list, max_length=20)
    total_years_experience: float | None = Field(default=None, ge=0, le=60)
    min_salary: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    workplace_preferences: list[Annotated[str, Field(min_length=1, max_length=30)]] = Field(
        default_factory=list, max_length=3
    )
    relocation_available: bool = False
    common_answers: dict[AnswerKey, AnswerValue] = Field(default_factory=dict, max_length=50)
    skills: list[SkillInput] = Field(default_factory=list, max_length=100)
    languages: list[LanguageInput] = Field(default_factory=list, max_length=20)
    employment: list[EmploymentInput] = Field(default_factory=list, max_length=50)

    @field_validator("salary_currency")
    @classmethod
    def uppercase_currency(cls, value: str | None) -> str | None:
        if value and (not value.isascii() or not value.isalpha()):
            raise ValueError("salary_currency must contain three ASCII letters")
        return value.upper() if value else value

    @model_validator(mode="after")
    def reject_duplicate_facts(self) -> ProfileCreate:
        reject_duplicate_named_items(self.skills, "name", "skill")
        reject_duplicate_named_items(self.languages, "language", "language")
        return self


class ProfileUpdate(StrictRequestModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=64)
    professional_summary: str | None = Field(default=None, max_length=4000)
    citizenships: list[ShortText] | None = Field(default=None, max_length=10)
    eu_work_authorized: bool | None = None
    requires_sponsorship: bool | None = None
    preferred_titles: list[ShortText] | None = Field(default=None, max_length=20)
    preferred_locations: list[ShortText] | None = Field(default=None, max_length=30)
    preferred_industries: list[ShortText] | None = Field(default=None, max_length=20)
    total_years_experience: float | None = Field(default=None, ge=0, le=60)
    min_salary: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    workplace_preferences: list[Annotated[str, Field(min_length=1, max_length=30)]] | None = Field(
        default=None, max_length=3
    )
    relocation_available: bool | None = None
    common_answers: dict[AnswerKey, AnswerValue] | None = Field(default=None, max_length=50)
    skills: list[SkillInput] | None = Field(default=None, max_length=100)
    languages: list[LanguageInput] | None = Field(default=None, max_length=20)
    employment: list[EmploymentInput] | None = Field(default=None, max_length=50)

    @field_validator("salary_currency")
    @classmethod
    def uppercase_currency(cls, value: str | None) -> str | None:
        if value and (not value.isascii() or not value.isalpha()):
            raise ValueError("salary_currency must contain three ASCII letters")
        return value.upper() if value else value

    @model_validator(mode="after")
    def reject_null_for_required_fields(self) -> ProfileUpdate:
        required_fields = {
            "full_name",
            "email",
            "citizenships",
            "eu_work_authorized",
            "requires_sponsorship",
            "preferred_titles",
            "preferred_locations",
            "preferred_industries",
            "workplace_preferences",
            "relocation_available",
            "common_answers",
            "skills",
            "languages",
            "employment",
        }
        null_fields = sorted(
            field
            for field in required_fields & self.model_fields_set
            if getattr(self, field) is None
        )
        if null_fields:
            raise ValueError(f"Fields may not be null: {', '.join(null_fields)}")
        reject_duplicate_named_items(self.skills, "name", "skill")
        reject_duplicate_named_items(self.languages, "language", "language")
        return self


class ProfileRead(ProfileCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime


class JobCreate(StrictRequestModel):
    source: Annotated[str, Field(min_length=1, max_length=100)]
    external_job_id: str | None = Field(default=None, max_length=200)
    url: HttpUrl | None = None
    company: Annotated[str, Field(min_length=1, max_length=200)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    industry: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    city: str | None = Field(default=None, max_length=120)
    workplace_type: str | None = Field(default=None, max_length=30)
    employment_type: str | None = Field(default=None, max_length=30)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    description: Annotated[str, Field(min_length=1, max_length=100000)]
    requirements: list[ListText] = Field(default_factory=list, max_length=100)
    preferred_qualifications: list[ListText] = Field(default_factory=list, max_length=100)
    deadline: date | None = None
    language: str | None = Field(default=None, max_length=20)
    sponsorship_information: str | None = Field(default=None, max_length=4000)

    @field_validator("country", "salary_currency")
    @classmethod
    def uppercase_codes(cls, value: str | None) -> str | None:
        if value and (not value.isascii() or not value.isalpha()):
            raise ValueError("country and currency codes must contain only ASCII letters")
        return value.upper() if value else value

    @field_validator("salary_max")
    @classmethod
    def salary_range_is_valid(cls, value: int | None, info) -> int | None:
        minimum = info.data.get("salary_min")
        if value is not None and minimum is not None and value < minimum:
            raise ValueError("salary_max must be greater than or equal to salary_min")
        return value


class JobRead(JobCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    normalized_url: str | None
    content_hash: str
    discovered_at: datetime
    created_at: datetime


class ApplicationCreate(StrictRequestModel):
    job_id: str = Field(min_length=1, max_length=36)
    notes: str | None = Field(default=None, max_length=10000)


class ApplicationTransition(StrictRequestModel):
    to_status: ApplicationStatus
    reason: str | None = Field(default=None, max_length=2000)
    approved_by_user: bool = False


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    job_id: str
    status: ApplicationStatus
    match_score: int | None
    match_analysis: dict
    notes: str | None
    created_at: datetime
    updated_at: datetime


class StatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus
    reason: str | None
    created_at: datetime


class HealthRead(BaseModel):
    status: str


class ScoreCategory(BaseModel):
    score: int = Field(ge=0)
    maximum: int = Field(gt=0)
    explanation: str


class MatchAnalysisRead(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    score_by_category: dict[str, ScoreCategory]
    matching_skills: list[str]
    missing_required_skills: list[str]
    missing_preferred_skills: list[str]
    potential_blockers: list[str]
    reasons_to_apply: list[str]
    reasons_not_to_apply: list[str]
    confidence_level: str
    recommendation: str
    hard_rejected: bool


class GeneratedStatement(StrictRequestModel):
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    fact_ids: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        min_length=1, max_length=8
    )


class GeneratedAnswer(StrictRequestModel):
    question: Annotated[str, Field(min_length=1, max_length=500)]
    answer: GeneratedStatement


class KeywordComparison(StrictRequestModel):
    matching_keywords: list[str] = Field(default_factory=list, max_length=100)
    missing_keywords: list[str] = Field(default_factory=list, max_length=100)


class GeneratedApplicationPackage(StrictRequestModel):
    professional_summary: list[GeneratedStatement] = Field(min_length=1, max_length=5)
    cv_highlights: list[GeneratedStatement] = Field(min_length=1, max_length=12)
    cover_letter_paragraphs: list[GeneratedStatement] = Field(min_length=1, max_length=6)
    recruiter_introduction: GeneratedStatement
    linkedin_message: GeneratedStatement
    application_answers: list[GeneratedAnswer] = Field(default_factory=list, max_length=20)
    keyword_comparison: KeywordComparison


class GenerateDocumentsRequest(StrictRequestModel):
    language: str = Field(default="en", pattern="^(en|es|pt)$")


class GroundingValidationRead(BaseModel):
    valid: bool
    unsupported_claims: list[str] = Field(default_factory=list)
    invalid_fact_ids: list[str] = Field(default_factory=list)


class GeneratedDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    application_id: str
    version: int
    language: str
    status: GeneratedDocumentStatus
    content: GeneratedApplicationPackage | None
    validation: GroundingValidationRead
    prompt_version: str
    model: str
    provider_response_id: str | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    latency_ms: int | None
    created_at: datetime
