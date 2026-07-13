from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Short = Annotated[str, Field(min_length=1, max_length=200)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SearchPreferences(StrictModel):
    target_titles: list[Short] = Field(default_factory=list, max_length=30)
    alternative_titles: list[Short] = Field(default_factory=list, max_length=60)
    seniority_levels: list[Short] = Field(default_factory=list, max_length=10)
    technical_skills: list[Short] = Field(default_factory=list, max_length=100)
    business_skills: list[Short] = Field(default_factory=list, max_length=100)
    languages: list[Short] = Field(default_factory=list, max_length=20)
    preferred_countries: list[Annotated[str, Field(min_length=2, max_length=2)]] = Field(
        default_factory=list, max_length=30
    )
    preferred_cities: list[Short] = Field(default_factory=list, max_length=50)
    workplace_preferences: list[Literal["REMOTE", "HYBRID", "ONSITE"]] = Field(default_factory=list)
    work_authorization: list[Short] = Field(default_factory=list, max_length=20)
    sponsorship_required: bool = False
    relocation_available: bool = False
    minimum_salary: int | None = Field(default=None, ge=0, le=10_000_000)
    salary_currency: Annotated[str, Field(min_length=3, max_length=3)] | None = None
    preferred_industries: list[Short] = Field(default_factory=list, max_length=30)
    excluded_industries: list[Short] = Field(default_factory=list, max_length=30)
    excluded_companies: list[Short] = Field(default_factory=list, max_length=100)
    excluded_keywords: list[Short] = Field(default_factory=list, max_length=100)
    required_keywords: list[Short] = Field(default_factory=list, max_length=100)
    optional_keywords: list[Short] = Field(default_factory=list, max_length=100)

    @field_validator("preferred_countries")
    @classmethod
    def normalize_countries(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.upper() for value in values))

    @field_validator("salary_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class SearchProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    preferences: SearchPreferences
    generated_terms: list[str]
    created_at: datetime
    updated_at: datetime


class HardFilters(StrictModel):
    countries: list[str] = Field(default_factory=list, max_length=30)
    cities: list[Short] = Field(default_factory=list, max_length=50)
    minimum_score: int = Field(default=0, ge=0, le=100)
    maximum_seniority: Short | None = None
    minimum_salary: int | None = Field(default=None, ge=0)
    required_workplace: list[Literal["REMOTE", "HYBRID", "ONSITE"]] = Field(default_factory=list)
    mandatory_languages: list[Short] = Field(default_factory=list, max_length=20)
    excluded_companies: list[Short] = Field(default_factory=list, max_length=100)
    excluded_industries: list[Short] = Field(default_factory=list, max_length=50)
    excluded_technologies: list[Short] = Field(default_factory=list, max_length=100)
    reject_sponsorship_required: bool = False
    reject_incompatible_work_permit: bool = True
    reject_temporary_or_freelance: bool = False
    reject_internships: bool = False


class ProviderSetting(StrictModel):
    enabled: bool = False
    feed_url: str | None = Field(default=None, max_length=2048)


class SearchConfigurationCreate(StrictModel):
    name: Short = "My discovery search"
    enabled: bool = True
    provider_settings: dict[str, ProviderSetting] = Field(default_factory=dict, max_length=10)
    schedule_kind: Literal["MANUAL", "DAILY", "WEEKDAYS"] = "MANUAL"
    schedule_time: str = "09:00"
    timezone: str = "UTC"
    hard_filters: HardFilters = Field(default_factory=HardFilters)

    @field_validator("schedule_time")
    @classmethod
    def valid_time(cls, value: str) -> str:
        try:
            hour, minute = map(int, value.split(":"))
        except (ValueError, AttributeError) as exc:
            raise ValueError("schedule_time must use HH:MM") from exc
        if hour not in range(24) or minute not in range(60) or len(value) != 5:
            raise ValueError("schedule_time must use HH:MM")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def automated_requires_provider(self) -> SearchConfigurationCreate:
        if self.schedule_kind != "MANUAL" and not any(
            item.enabled for item in self.provider_settings.values()
        ):
            raise ValueError("An automated schedule requires at least one enabled provider")
        return self


class SearchConfigurationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    enabled: bool
    provider_settings: dict[str, Any]
    schedule_kind: str
    schedule_time: str
    timezone: str
    hard_filters: dict[str, Any]
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SearchRunRequest(StrictModel):
    configuration_id: str


class SearchRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    configuration_id: str
    status: str
    trigger: str
    lifecycle_stage: str
    counters: dict[str, Any]
    started_at: datetime
    ended_at: datetime | None


class ManualJobImport(StrictModel):
    provider: str
    url: str | None = Field(default=None, max_length=2048)
    external_job_id: str | None = Field(default=None, max_length=200)
    company: Short
    title: Short
    description: Annotated[str, Field(min_length=1, max_length=50_000)]
    country: Annotated[str, Field(min_length=2, max_length=2)] | None = None
    city: str | None = Field(default=None, max_length=120)
    workplace_type: str | None = Field(default=None, max_length=30)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)


class CsvImportRequest(StrictModel):
    provider: str
    csv_text: str = Field(min_length=1, max_length=2_000_000)


class EmailImportRequest(StrictModel):
    provider: str
    eml_text: str = Field(min_length=1, max_length=500_000)


class ImportResult(BaseModel):
    imported: int
    duplicates: int
    job_ids: list[str]


class RankedJobRead(BaseModel):
    id: str
    match_id: str
    title: str
    company: str
    country: str | None
    city: str | None
    provider: str
    url: str | None
    workplace_type: str | None
    posted_at: datetime | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    score: int
    recommendation: str
    hard_rejected: bool
    analysis: dict[str, Any]
    user_state: str


class MatchAction(StrictModel):
    action: Literal["SAVE", "REJECT", "PREPARE_APPLICATION"]


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_type: str
    job_id: str | None
    title: str
    body: str
    read_at: datetime | None
    created_at: datetime
