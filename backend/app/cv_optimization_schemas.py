"""Strict contracts for job-specific, evidence-grounded CV optimization."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.cv_schemas import CvProfileDraft
from app.models import CvOptimizationStatus, CvRecommendationDecisionValue, CvVariantStatus

RecommendationCategory = Literal[
    "HEADLINE",
    "SUMMARY",
    "SKILLS",
    "EXPERIENCE",
    "PROJECTS",
    "ORDERING",
    "ATS_KEYWORDS",
    "EDUCATION_CERTIFICATIONS",
    "LANGUAGES_AUTHORIZATION",
]
RecommendationType = Literal[
    "ADD",
    "REWRITE",
    "REMOVE",
    "REORDER",
    "EMPHASIZE",
    "DE_EMPHASIZE",
    "CLARIFY",
    "NORMALIZE",
    "SHORTEN",
]
RecommendationPriority = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class StrictOptimizationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OptimizationEvidence(StrictOptimizationModel):
    fact_id: str = Field(pattern=r"^candidate:[a-z0-9][a-z0-9:.-]*$", max_length=240)
    source_section: str = Field(min_length=1, max_length=120)
    quote: str = Field(min_length=1, max_length=2000)


class RecommendationProposal(StrictOptimizationModel):
    category: RecommendationCategory
    section: str = Field(min_length=1, max_length=200)
    current_text: str = Field(max_length=10_000, default="")
    suggested_text: str = Field(max_length=10_000, default="")
    reason: str = Field(min_length=1, max_length=2000)
    expected_benefit: str = Field(min_length=1, max_length=2000)
    related_job_requirement: str = Field(max_length=2000, default="")
    confidence: float = Field(ge=0, le=1)
    priority: RecommendationPriority
    recommendation_type: RecommendationType
    approval_required: bool = True
    evidence: list[OptimizationEvidence] = Field(max_length=20)

    @model_validator(mode="after")
    def enforce_evidence(self) -> RecommendationProposal:
        if not self.evidence:
            raise ValueError("Every recommendation requires candidate evidence")
        return self


class RecommendationPlan(StrictOptimizationModel):
    recommendations: list[RecommendationProposal] = Field(max_length=40)


class CvAnalysisRequest(StrictOptimizationModel):
    job_id: str = Field(min_length=1, max_length=36)


class RecommendationDecisionRequest(StrictOptimizationModel):
    decision: Literal["ACCEPTED", "REJECTED", "EDITED"]
    edited_text: str | None = Field(default=None, min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def validate_edited_text(self) -> RecommendationDecisionRequest:
        if self.decision == "EDITED" and not self.edited_text:
            raise ValueError("edited_text is required for an edited recommendation")
        if self.decision != "EDITED" and self.edited_text is not None:
            raise ValueError("edited_text is only allowed for an edited recommendation")
        return self


class RecommendationBatchRequest(StrictOptimizationModel):
    action: Literal["ACCEPT_SAFE", "RESET"]


class GenerateVariantRequest(StrictOptimizationModel):
    status: Literal["JOB_SPECIFIC_DRAFT", "USER_REVIEWED", "APPROVED"] = "JOB_SPECIFIC_DRAFT"


class ExportRequest(StrictOptimizationModel):
    format: Literal["pdf", "docx"]


class RecommendationEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    fact_id: str
    source_section: str
    quote: str


class RecommendationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    category: str
    section: str
    current_text: str
    suggested_text: str
    reason: str
    expected_benefit: str
    related_job_requirement: str
    confidence: float
    priority: str
    recommendation_type: str
    approval_required: bool
    decision: CvRecommendationDecisionValue
    user_text: str | None
    validation: dict
    display_order: int
    evidence: list[RecommendationEvidenceRead]


class CvAnalysisRead(BaseModel):
    id: str
    job_id: str
    profile_version_id: str
    match_result_id: str
    status: CvOptimizationStatus
    original_score: int
    input_summary: dict
    validation: dict
    prompt_version: str
    model: str
    created_at: datetime
    updated_at: datetime
    recommendations: list[RecommendationRead]


class CvVariantVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    variant_id: str
    version: int
    status: CvVariantStatus
    content: CvProfileDraft
    applied_recommendation_ids: list[str]
    rejected_recommendation_ids: list[str]
    user_edits: dict
    original_score: int
    estimated_score: int
    score_explanation: str
    keywords_added: list[str]
    sections_improved: list[str]
    remaining_gaps: list[str]
    remaining_blockers: list[str]
    validation: dict
    prompt_version: str
    model: str
    created_at: datetime


class CvVariantRead(BaseModel):
    id: str
    job_id: str
    base_profile_version_id: str
    analysis_run_id: str
    status: CvVariantStatus
    created_at: datetime
    updated_at: datetime
    latest_version: CvVariantVersionRead


class CvVariantComparison(StrictOptimizationModel):
    master: CvProfileDraft
    variant: CvProfileDraft
    applied_recommendations: list[RecommendationRead]
    unchanged_master: bool


class CvVariantPreview(StrictOptimizationModel):
    content: CvProfileDraft
    applied_recommendation_ids: list[str]
    rejected_recommendation_ids: list[str]
    original_score: int
    estimated_score: int
    score_explanation: str
    sections_improved: list[str]
    remaining_gaps: list[str]
    remaining_blockers: list[str]


class CvExportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    variant_version_id: str
    format: str
    sha256: str
    size_bytes: int
    created_at: datetime
