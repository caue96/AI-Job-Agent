from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = Field(default="sqlite:///./job_agent.db", repr=False)
    cors_origins: str = "http://localhost:5173"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.4-mini-2026-03-17"
    openai_reasoning_effort: Literal["none", "low", "medium", "high"] = "none"
    ai_generation_mode: Literal["mock", "openai"] = "mock"
    ai_max_retries: int = Field(default=1, ge=0, le=2)
    ai_request_timeout_seconds: float = Field(default=45, gt=0, le=120)
    ai_max_output_tokens: int = Field(default=800, ge=100, le=4000)
    ai_max_job_description_chars: int = Field(default=12000, ge=1000, le=50000)
    ai_fallback_to_mock: bool = True
    ai_input_cost_per_million_usd: float = Field(default=0, ge=0)
    ai_cached_input_cost_per_million_usd: float = Field(default=0, ge=0)
    ai_output_cost_per_million_usd: float = Field(default=0, ge=0)
    cv_storage_path: str = "./data/cv_uploads"
    cv_export_storage_path: str = "./data/cv_exports"
    cv_max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=25 * 1024 * 1024)
    cv_max_pages: int = Field(default=40, ge=1, le=200)
    cv_min_extracted_characters: int = Field(default=80, ge=1, le=5000)
    cv_retention_days: int = Field(default=30, ge=1, le=3650)
    cv_uploads_per_minute: int = Field(default=10, ge=1, le=120)
    itjobs_api_key: SecretStr | None = None
    infojobs_client_id: str | None = Field(default=None, max_length=200)
    infojobs_client_secret: SecretStr | None = Field(default=None, repr=False)
    discovery_provider_timeout_seconds: float = Field(default=15, gt=0, le=60)
    discovery_max_provider_response_bytes: int = Field(default=2_000_000, ge=10_000, le=10_000_000)
    discovery_scheduler_poll_seconds: int = Field(default=60, ge=15, le=3600)
    matching_permitted_countries: str = "ES,PT,IE"
    matching_allow_remote: bool = True
    matching_hard_reject_missing_required_skills: bool = False
    matching_hard_reject_missing_language: bool = True
    matching_hard_reject_salary_below_min: bool = True
    matching_hard_reject_outside_location: bool = True
    matching_hard_reject_seniority_gap: bool = True
    matching_hard_reject_incompatible_work_authorization: bool = True
    matching_seniority_gap_years: float = Field(default=2, ge=0, le=20)

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        origins = [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
        if not origins:
            raise ValueError("CORS_ORIGINS must contain at least one origin")
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                origin == "*"
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(f"Invalid CORS origin: {origin}")
        return ",".join(origins)

    @field_validator("matching_permitted_countries")
    @classmethod
    def validate_permitted_countries(cls, value: str) -> str:
        countries = [country.strip().upper() for country in value.split(",") if country.strip()]
        if not countries or any(
            len(country) != 2 or not country.isascii() or not country.isalpha()
            for country in countries
        ):
            raise ValueError(
                "MATCHING_PERMITTED_COUNTRIES must contain comma-separated two-letter codes"
            )
        return ",".join(dict.fromkeys(countries))

    @model_validator(mode="after")
    def prevent_unsafe_production_deployment(self) -> "Settings":
        if self.app_env == "production":
            raise ValueError(
                "Production mode is disabled until authenticated user sessions "
                "and tenant ownership are implemented."
            )
        if self.ai_generation_mode == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when AI_GENERATION_MODE=openai")
        return self

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def permitted_countries(self) -> set[str]:
        return {
            country.strip().upper()
            for country in self.matching_permitted_countries.split(",")
            if country.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
