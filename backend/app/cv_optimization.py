"""Application service for immutable, user-reviewed CV optimization workflows."""

from __future__ import annotations

import copy
import re
from hashlib import sha256

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cv_optimization_ai import (
    PROMPT_VERSION,
    CvOptimizationProvider,
    approved_profile_facts,
    validate_recommendation,
)
from app.cv_optimization_schemas import (
    CvAnalysisRead,
    CvVariantComparison,
    CvVariantPreview,
    CvVariantRead,
    CvVariantVersionRead,
    RecommendationDecisionRequest,
    RecommendationEvidenceRead,
    RecommendationRead,
)
from app.cv_schemas import CvProfileDraft
from app.models import (
    CvAnalysisRun,
    CvOptimizationStatus,
    CvRecommendation,
    CvRecommendationDecision,
    CvRecommendationDecisionValue,
    CvRecommendationEvidence,
    CvVariant,
    CvVariantStatus,
    CvVariantValidation,
    CvVariantVersion,
    DiscoveryMatchResult,
    Job,
    ProfileVersion,
    User,
)
from app.services import write_audit


def _not_found(name: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{name} not found")


def _latest_profile_version(db: Session, user_id: str) -> ProfileVersion:
    version = db.scalar(
        select(ProfileVersion)
        .where(ProfileVersion.user_id == user_id)
        .order_by(ProfileVersion.version.desc(), ProfileVersion.created_at.desc())
        .limit(1)
    )
    if not version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Confirm a CV profile before requesting job-specific improvements",
        )
    return version


def _latest_match(db: Session, user_id: str, job_id: str) -> DiscoveryMatchResult:
    match = db.scalar(
        select(DiscoveryMatchResult)
        .where(DiscoveryMatchResult.user_id == user_id, DiscoveryMatchResult.job_id == job_id)
        .order_by(DiscoveryMatchResult.created_at.desc())
        .limit(1)
    )
    if not match:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run deterministic matching for this job before analyzing the CV",
        )
    return match


def _job_hash(job: Job) -> str:
    value = "\0".join(
        [job.title, job.company, job.description, *job.requirements, *job.preferred_qualifications]
    )
    return sha256(value.encode("utf-8")).hexdigest()


def create_analysis(
    db: Session, user: User, job_id: str, provider: CvOptimizationProvider
) -> CvAnalysisRun:
    job = db.get(Job, job_id)
    if not job:
        raise _not_found("Job")
    profile_version = _latest_profile_version(db, user.id)
    match = _latest_match(db, user.id, job.id)
    profile = CvProfileDraft.model_validate(profile_version.snapshot)
    facts = approved_profile_facts(profile)
    user_id = user.id
    profile_version_id = profile_version.id
    match_result_id = match.id
    original_score = match.score
    input_summary = {
        "job_content_hash": _job_hash(job),
        "candidate_fact_count": len(facts),
        "matching_skills": match.analysis.get("matching_skills", []),
        "missing_required_skills": match.analysis.get("missing_required_skills", []),
        "potential_blockers": match.analysis.get("potential_blockers", []),
    }
    # End the read transaction before a potentially slow external provider request. The detached
    # Job contains only already-loaded scalar data and is revalidated before anything is stored.
    db.expunge(job)
    db.commit()
    plan, metadata = provider.propose(profile=profile, job=job, facts=facts)
    current_job = db.get(Job, job_id)
    current_profile_version = db.get(ProfileVersion, profile_version_id)
    current_match = db.get(DiscoveryMatchResult, match_result_id)
    if (
        not current_job
        or _job_hash(current_job) != input_summary["job_content_hash"]
        or not current_profile_version
        or current_profile_version.user_id != user_id
        or not current_match
        or current_match.user_id != user_id
        or current_match.job_id != job_id
    ):
        raise HTTPException(status_code=409, detail="The inputs changed during CV analysis; retry")
    run = CvAnalysisRun(
        user_id=user_id,
        profile_version_id=profile_version_id,
        job_id=job_id,
        match_result_id=match_result_id,
        status=CvOptimizationStatus.CV_ANALYSIS_REQUESTED,
        original_score=original_score,
        input_summary=input_summary,
        validation={},
        prompt_version=PROMPT_VERSION,
        model="pending",
    )
    db.add(run)
    db.flush()
    write_audit(db, user_id, "cv_optimization.analysis.requested", "cv_analysis_run", run.id)
    invalid: dict[str, list[str]] = {}
    accepted_count = 0
    for index, proposal in enumerate(plan.recommendations):
        issues = validate_recommendation(proposal, facts, job)
        if issues:
            invalid[str(index)] = issues
            continue
        record = CvRecommendation(
            analysis_run_id=run.id,
            category=proposal.category,
            section=proposal.section,
            current_text=proposal.current_text,
            suggested_text=proposal.suggested_text,
            reason=proposal.reason,
            expected_benefit=proposal.expected_benefit,
            related_job_requirement=proposal.related_job_requirement,
            confidence=proposal.confidence,
            priority=proposal.priority,
            recommendation_type=proposal.recommendation_type,
            approval_required=proposal.approval_required,
            validation={"valid": True, "issues": []},
            display_order=index,
        )
        db.add(record)
        db.flush()
        for evidence in proposal.evidence:
            db.add(
                CvRecommendationEvidence(
                    recommendation_id=record.id,
                    fact_id=evidence.fact_id,
                    source_section=evidence.source_section,
                    quote=evidence.quote,
                )
            )
        accepted_count += 1
    run.status = CvOptimizationStatus.AWAITING_REVIEW
    run.validation = {
        "valid": not invalid,
        "invalid_provider_recommendations": invalid,
        "persisted_recommendations": accepted_count,
    }
    run.model = metadata.model
    run.provider_response_id = metadata.provider_response_id
    run.input_tokens = metadata.input_tokens
    run.output_tokens = metadata.output_tokens
    run.latency_ms = metadata.latency_ms
    write_audit(
        db,
        user_id,
        "cv_optimization.analysis.completed",
        "cv_analysis_run",
        run.id,
        {"recommendations": accepted_count, "invalid_provider_items": len(invalid)},
    )
    return run


def owned_analysis(
    db: Session, user_id: str, analysis_id: str, lock: bool = False
) -> CvAnalysisRun:
    statement = select(CvAnalysisRun).where(
        CvAnalysisRun.id == analysis_id, CvAnalysisRun.user_id == user_id
    )
    if lock:
        statement = statement.with_for_update()
    result = db.scalar(statement)
    if not result:
        raise _not_found("CV analysis")
    return result


def _recommendations(db: Session, analysis_id: str) -> list[CvRecommendation]:
    return list(
        db.scalars(
            select(CvRecommendation)
            .where(CvRecommendation.analysis_run_id == analysis_id)
            .order_by(CvRecommendation.display_order, CvRecommendation.created_at)
        )
    )


def serialize_recommendation(db: Session, item: CvRecommendation) -> RecommendationRead:
    evidence = list(
        db.scalars(
            select(CvRecommendationEvidence).where(
                CvRecommendationEvidence.recommendation_id == item.id
            )
        )
    )
    return RecommendationRead(
        **{
            column: getattr(item, column)
            for column in (
                "id",
                "category",
                "section",
                "current_text",
                "suggested_text",
                "reason",
                "expected_benefit",
                "related_job_requirement",
                "confidence",
                "priority",
                "recommendation_type",
                "approval_required",
                "decision",
                "user_text",
                "validation",
                "display_order",
            )
        },
        evidence=[RecommendationEvidenceRead.model_validate(record) for record in evidence],
    )


def serialize_analysis(db: Session, run: CvAnalysisRun) -> CvAnalysisRead:
    return CvAnalysisRead(
        **{
            column: getattr(run, column)
            for column in (
                "id",
                "job_id",
                "profile_version_id",
                "match_result_id",
                "status",
                "original_score",
                "input_summary",
                "validation",
                "prompt_version",
                "model",
                "created_at",
                "updated_at",
            )
        },
        recommendations=[
            serialize_recommendation(db, item) for item in _recommendations(db, run.id)
        ],
    )


def decide_recommendation(
    db: Session,
    user: User,
    recommendation_id: str,
    payload: RecommendationDecisionRequest,
) -> CvRecommendation:
    item = db.scalar(
        select(CvRecommendation)
        .join(CvAnalysisRun)
        .where(CvRecommendation.id == recommendation_id, CvAnalysisRun.user_id == user.id)
        .with_for_update()
    )
    if not item:
        raise _not_found("Recommendation")
    run = owned_analysis(db, user.id, item.analysis_run_id, lock=True)
    job = db.get(Job, run.job_id)
    profile_version = db.get(ProfileVersion, run.profile_version_id)
    if not job or not profile_version:
        raise HTTPException(status_code=409, detail="The analysis inputs are no longer available")
    if payload.decision == "EDITED":
        evidence = list(
            db.scalars(
                select(CvRecommendationEvidence).where(
                    CvRecommendationEvidence.recommendation_id == item.id
                )
            )
        )
        proposal = _proposal_for_validation(item, evidence, payload.edited_text or "")
        facts = approved_profile_facts(CvProfileDraft.model_validate(profile_version.snapshot))
        issues = validate_recommendation(proposal, facts, job)
        if issues:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"message": "Edited text contains unsupported claims", "issues": issues},
            )
    decision = CvRecommendationDecisionValue(payload.decision)
    item.decision = decision
    item.user_text = payload.edited_text
    db.add(
        CvRecommendationDecision(
            recommendation_id=item.id,
            actor_id=user.id,
            decision=decision,
            edited_text=payload.edited_text,
        )
    )
    pending = db.scalar(
        select(func.count())
        .select_from(CvRecommendation)
        .where(
            CvRecommendation.analysis_run_id == run.id,
            CvRecommendation.id != item.id,
            CvRecommendation.decision == CvRecommendationDecisionValue.PENDING,
        )
    )
    run.status = (
        CvOptimizationStatus.RECOMMENDATIONS_APPROVED
        if pending == 0
        else CvOptimizationStatus.AWAITING_REVIEW
    )
    write_audit(
        db,
        user.id,
        "cv_optimization.recommendation.decided",
        "cv_recommendation",
        item.id,
        {"decision": decision.value},
    )
    return item


def _proposal_for_validation(
    item: CvRecommendation, evidence: list[CvRecommendationEvidence], suggested_text: str
):
    from app.cv_optimization_schemas import OptimizationEvidence, RecommendationProposal

    return RecommendationProposal.model_validate(
        {
            "category": item.category,
            "section": item.section,
            "current_text": item.current_text,
            "suggested_text": suggested_text,
            "reason": item.reason,
            "expected_benefit": item.expected_benefit,
            "related_job_requirement": item.related_job_requirement,
            "confidence": item.confidence,
            "priority": item.priority,
            "recommendation_type": item.recommendation_type,
            "approval_required": item.approval_required,
            "evidence": [
                OptimizationEvidence(
                    fact_id=record.fact_id,
                    source_section=record.source_section,
                    quote=record.quote,
                )
                for record in evidence
            ],
        }
    )


def batch_decide(db: Session, user: User, analysis_id: str, action: str) -> CvAnalysisRun:
    run = owned_analysis(db, user.id, analysis_id, lock=True)
    decision = (
        CvRecommendationDecisionValue.PENDING
        if action == "RESET"
        else CvRecommendationDecisionValue.ACCEPTED
    )
    for item in _recommendations(db, run.id):
        if action == "ACCEPT_SAFE" and not item.validation.get("valid"):
            continue
        item.decision = decision
        item.user_text = None
        db.add(
            CvRecommendationDecision(
                recommendation_id=item.id,
                actor_id=user.id,
                decision=decision,
            )
        )
    run.status = (
        CvOptimizationStatus.AWAITING_REVIEW
        if action == "RESET"
        else CvOptimizationStatus.RECOMMENDATIONS_APPROVED
    )
    write_audit(
        db,
        user.id,
        f"cv_optimization.recommendations.{action.casefold()}",
        "cv_analysis_run",
        run.id,
    )
    return run


def _replace_value(content: dict, field: str, value: str) -> bool:
    target = content.get(field)
    if isinstance(target, dict) and "value" in target:
        target["value"] = value
        return True
    return False


def _apply_recommendation(content: dict, item: CvRecommendation, text: str) -> bool:
    if item.recommendation_type == "REMOVE":
        return False
    if item.section in {"headline", "professional_summary"}:
        return _replace_value(content, item.section, text)
    if (
        item.section in {"technical_skills", "soft_skills", "languages"}
        and item.recommendation_type == "REORDER"
    ):
        current = content.get(item.section, [])
        by_value = {str(entry.get("value", "")).casefold(): entry for entry in current}
        requested = [value.strip() for value in text.split(",") if value.strip()]
        if set(value.casefold() for value in requested) != set(by_value):
            return False
        content[item.section] = [by_value[value.casefold()] for value in requested]
        return True
    match = re.fullmatch(r"employment\.(\d+)\.(achievements|responsibilities)\.(\d+)", item.section)
    if match:
        entry_index = int(match.group(1))
        collection = match.group(2)
        item_index = int(match.group(3))
        employment = content.get("employment", [])
        if entry_index >= len(employment):
            return False
        items = employment[entry_index].get(collection, [])
        if item_index >= len(items):
            return False
        if item.recommendation_type == "REORDER":
            items.insert(0, items.pop(item_index))
        elif item.recommendation_type in {
            "REWRITE",
            "EMPHASIZE",
            "CLARIFY",
            "SHORTEN",
        }:
            items[item_index]["value"] = text
        else:
            return False
        return True
    match = re.fullmatch(r"(projects|education|certifications)\.(\d+)", item.section)
    if match and item.recommendation_type in {"REORDER", "EMPHASIZE"}:
        section, item_index_text = match.groups()
        items = content.get(section, [])
        item_index = int(item_index_text)
        if item_index >= len(items):
            return False
        items.insert(0, items.pop(item_index))
        return True
    return False


def preview_variant(db: Session, user: User, analysis_id: str) -> CvVariantPreview:
    run = owned_analysis(db, user.id, analysis_id)
    profile_version = db.get(ProfileVersion, run.profile_version_id)
    if not profile_version:
        raise HTTPException(status_code=409, detail="The approved base CV version is unavailable")
    recommendations = _recommendations(db, run.id)
    accepted = [
        item
        for item in recommendations
        if item.decision
        in {
            CvRecommendationDecisionValue.ACCEPTED,
            CvRecommendationDecisionValue.EDITED,
        }
    ]
    if not accepted:
        raise HTTPException(status_code=409, detail="Accept at least one recommendation first")
    content = copy.deepcopy(profile_version.snapshot)
    applied: list[str] = []
    ignored: list[str] = []
    sections: list[str] = []
    for item in accepted:
        text = (
            item.user_text
            if item.decision == CvRecommendationDecisionValue.EDITED
            else item.suggested_text
        )
        if _apply_recommendation(content, item, text or ""):
            applied.append(item.id)
            sections.append(item.section)
        else:
            ignored.append(item.id)
    if not applied:
        raise HTTPException(
            status_code=409,
            detail="Accepted recommendations do not map to editable CV sections",
        )
    gaps = list(run.input_summary.get("missing_required_skills", []))
    return CvVariantPreview(
        content=CvProfileDraft.model_validate(content),
        applied_recommendation_ids=applied,
        rejected_recommendation_ids=[
            item.id
            for item in recommendations
            if item.decision == CvRecommendationDecisionValue.REJECTED
        ]
        + ignored,
        original_score=run.original_score,
        estimated_score=run.original_score,
        score_explanation=(
            "The deterministic match score is unchanged. Presentation edits do not create new "
            "qualifications or resolve substantive gaps."
        ),
        sections_improved=list(dict.fromkeys(sections)),
        remaining_gaps=list(dict.fromkeys(filter(None, gaps))),
        remaining_blockers=list(run.input_summary.get("potential_blockers", [])),
    )


def generate_variant(db: Session, user: User, analysis_id: str, requested_status: str) -> CvVariant:
    run = owned_analysis(db, user.id, analysis_id, lock=True)
    profile_version = db.get(ProfileVersion, run.profile_version_id)
    if not profile_version:
        raise HTTPException(status_code=409, detail="The approved base CV version is unavailable")
    recommendations = _recommendations(db, run.id)
    preview = preview_variant(db, user, analysis_id)
    user_edits = {
        item.id: item.user_text
        for item in recommendations
        if item.user_text
        and item.decision == CvRecommendationDecisionValue.EDITED
        and item.id in preview.applied_recommendation_ids
    }
    existing = db.scalar(
        select(CvVariant).where(CvVariant.user_id == user.id, CvVariant.analysis_run_id == run.id)
    )
    if existing:
        raise HTTPException(status_code=409, detail="A CV variant already exists for this analysis")
    variant_status = CvVariantStatus(requested_status)
    variant = CvVariant(
        user_id=user.id,
        job_id=run.job_id,
        base_profile_version_id=profile_version.id,
        analysis_run_id=run.id,
        status=variant_status,
    )
    db.add(variant)
    db.flush()
    version = CvVariantVersion(
        variant_id=variant.id,
        version=1,
        status=variant_status,
        content=preview.content.model_dump(mode="json"),
        applied_recommendation_ids=preview.applied_recommendation_ids,
        rejected_recommendation_ids=preview.rejected_recommendation_ids,
        user_edits=user_edits,
        original_score=preview.original_score,
        estimated_score=preview.estimated_score,
        score_explanation=preview.score_explanation,
        keywords_added=[],
        sections_improved=preview.sections_improved,
        remaining_gaps=preview.remaining_gaps,
        remaining_blockers=preview.remaining_blockers,
        validation={"valid": True, "issues": [], "base_profile_unchanged": True},
        prompt_version=run.prompt_version,
        model=run.model,
    )
    db.add(version)
    db.flush()
    db.add(
        CvVariantValidation(
            variant_version_id=version.id,
            valid=True,
            issues=[],
            checked_claims=len(preview.applied_recommendation_ids),
        )
    )
    run.status = CvOptimizationStatus.CV_VARIANT_SAVED
    write_audit(
        db,
        user.id,
        "cv_optimization.variant.created",
        "cv_variant",
        variant.id,
        {"applied_recommendations": len(preview.applied_recommendation_ids)},
    )
    return variant


def owned_variant(db: Session, user_id: str, variant_id: str) -> CvVariant:
    result = db.scalar(
        select(CvVariant).where(CvVariant.id == variant_id, CvVariant.user_id == user_id)
    )
    if not result:
        raise _not_found("CV variant")
    return result


def latest_variant_version(db: Session, variant_id: str) -> CvVariantVersion:
    version = db.scalar(
        select(CvVariantVersion)
        .where(CvVariantVersion.variant_id == variant_id)
        .order_by(CvVariantVersion.version.desc())
        .limit(1)
    )
    if not version:
        raise _not_found("CV variant version")
    return version


def serialize_variant(db: Session, variant: CvVariant) -> CvVariantRead:
    return CvVariantRead(
        **{
            column: getattr(variant, column)
            for column in (
                "id",
                "job_id",
                "base_profile_version_id",
                "analysis_run_id",
                "status",
                "created_at",
                "updated_at",
            )
        },
        latest_version=CvVariantVersionRead.model_validate(latest_variant_version(db, variant.id)),
    )


def compare_variant(db: Session, user_id: str, variant_id: str) -> CvVariantComparison:
    variant = owned_variant(db, user_id, variant_id)
    base = db.get(ProfileVersion, variant.base_profile_version_id)
    if not base:
        raise HTTPException(status_code=409, detail="The approved base CV version is unavailable")
    version = latest_variant_version(db, variant.id)
    applied = [
        item
        for item in _recommendations(db, variant.analysis_run_id)
        if item.id in set(version.applied_recommendation_ids)
    ]
    return CvVariantComparison(
        master=CvProfileDraft.model_validate(base.snapshot),
        variant=CvProfileDraft.model_validate(version.content),
        applied_recommendations=[serialize_recommendation(db, item) for item in applied],
        unchanged_master=True,
    )


def remove_variant(db: Session, user: User, variant_id: str) -> None:
    variant = owned_variant(db, user.id, variant_id)
    write_audit(db, user.id, "cv_optimization.variant.deleted", "cv_variant", variant.id)
    db.delete(variant)
