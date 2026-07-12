from __future__ import annotations

import hashlib
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai import (
    PROMPT_VERSION,
    AIProvider,
    AIProviderError,
    profile_facts,
    prompt_injection_markers,
    render_application_package,
    validate_document_plan,
    validate_grounding,
)
from app.matching import MatchingPolicy, score_job
from app.models import (
    Application,
    ApplicationStatus,
    ApplicationStatusHistory,
    AuditLog,
    CandidateProfile,
    EmploymentEntry,
    GeneratedDocument,
    GeneratedDocumentStatus,
    Job,
    ProfileLanguage,
    ProfileSkill,
    User,
)
from app.schemas import (
    ApplicationCreate,
    ApplicationTransition,
    GeneratedApplicationPackage,
    GeneratedDocumentRead,
    GenerateDocumentsRequest,
    GroundingValidationRead,
    JobCreate,
    MatchAnalysisRead,
    ProfileCreate,
    ProfileUpdate,
)

VALID_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.DISCOVERED: {ApplicationStatus.ANALYZED, ApplicationStatus.REJECTED},
    ApplicationStatus.ANALYZED: {ApplicationStatus.SHORTLISTED, ApplicationStatus.REJECTED},
    ApplicationStatus.SHORTLISTED: {
        ApplicationStatus.DOCUMENTS_PREPARED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.DOCUMENTS_PREPARED: {
        ApplicationStatus.AWAITING_REVIEW,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.AWAITING_REVIEW: {
        ApplicationStatus.APPROVED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.APPROVED: {ApplicationStatus.READY_TO_SUBMIT, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.READY_TO_SUBMIT: {ApplicationStatus.SUBMITTED, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.SUBMITTED: {
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.OFFER,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.INTERVIEW: {
        ApplicationStatus.OFFER,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.OFFER: {ApplicationStatus.WITHDRAWN},
    ApplicationStatus.REJECTED: set(),
    ApplicationStatus.WITHDRAWN: set(),
}


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def job_content_hash(payload: JobCreate) -> str:
    canonical = "|".join(
        [
            payload.company.strip().lower(),
            payload.title.strip().lower(),
            payload.description.strip().lower(),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_audit(
    db: Session,
    user_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    metadata: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=metadata or {},
        )
    )


def current_development_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.email == "local@example.invalid"))
    if user:
        return user
    user = User(email="local@example.invalid")
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        # Two first requests can race while bootstrapping the local-only identity.
        db.rollback()
        user = db.scalar(select(User).where(User.email == "local@example.invalid"))
        if user is None:
            raise
    return user


def apply_profile_details(
    profile: CandidateProfile, payload: ProfileCreate | ProfileUpdate
) -> None:
    values = payload.model_dump(exclude_unset=True, exclude={"skills", "languages", "employment"})
    for field, value in values.items():
        setattr(profile, field, value)
    if "skills" in payload.model_fields_set:
        profile.skills = [ProfileSkill(**skill.model_dump()) for skill in payload.skills or []]
    if "languages" in payload.model_fields_set:
        profile.languages = [
            ProfileLanguage(**language.model_dump()) for language in payload.languages or []
        ]
    if "employment" in payload.model_fields_set:
        profile.employment = [
            EmploymentEntry(**entry.model_dump()) for entry in payload.employment or []
        ]


def create_profile(db: Session, payload: ProfileCreate, user: User) -> CandidateProfile:
    if db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Profile already exists")
    profile = CandidateProfile(
        user_id=user.id, full_name=payload.full_name, email=str(payload.email)
    )
    apply_profile_details(profile, payload)
    db.add(profile)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Profile already exists"
        ) from exc
    write_audit(db, user.id, "profile.created", "candidate_profile", profile.id)
    return profile


def create_job(db: Session, payload: JobCreate, actor_id: str) -> Job:
    normalized = normalize_url(str(payload.url) if payload.url else None)
    content_hash = job_content_hash(payload)
    duplicate_conditions = [Job.content_hash == content_hash]
    if payload.external_job_id:
        duplicate_conditions.append(
            (Job.source == payload.source) & (Job.external_job_id == payload.external_job_id)
        )
    if normalized:
        duplicate_conditions.append(Job.normalized_url == normalized)
    duplicates = db.execute(
        select(Job.source, Job.external_job_id, Job.normalized_url, Job.content_hash).where(
            or_(*duplicate_conditions)
        )
    ).all()
    if payload.external_job_id:
        if any(
            job.source == payload.source and job.external_job_id == payload.external_job_id
            for job in duplicates
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Duplicate source and external job ID"
            )
    if normalized:
        if any(job.normalized_url == normalized for job in duplicates):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Duplicate normalized job URL"
            )
    if any(job.content_hash == content_hash for job in duplicates):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate job content")
    job = Job(
        **payload.model_dump(exclude={"url"}),
        url=str(payload.url) if payload.url else None,
        normalized_url=normalized,
        content_hash=content_hash,
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job duplicates an existing vacancy",
        ) from exc
    write_audit(db, actor_id, "job.created", "job", job.id, {"source": job.source})
    return job


def create_application(db: Session, payload: ApplicationCreate, user: User) -> Application:
    if not db.get(Job, payload.job_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    existing = db.scalar(
        select(Application).where(
            Application.user_id == user.id, Application.job_id == payload.job_id
        )
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application already exists for this job",
        )
    application = Application(user_id=user.id, job_id=payload.job_id, notes=payload.notes)
    db.add(application)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application already exists for this job",
        ) from exc
    db.add(
        ApplicationStatusHistory(
            application_id=application.id,
            from_status=None,
            to_status=application.status,
            reason="Application created",
            actor_id=user.id,
        )
    )
    write_audit(db, user.id, "application.created", "application", application.id)
    return application


def transition_application(
    db: Session, application: Application, actor_id: str, command: ApplicationTransition
) -> Application:
    source = application.status
    target = command.to_status
    if target not in VALID_TRANSITIONS[source]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid transition from {source.value} to {target.value}",
        )
    if (
        target in {ApplicationStatus.READY_TO_SUBMIT, ApplicationStatus.SUBMITTED}
        and not command.approved_by_user
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Explicit user approval is required",
        )
    application.status = target
    db.add(
        ApplicationStatusHistory(
            application_id=application.id,
            from_status=source,
            to_status=target,
            reason=command.reason,
            actor_id=actor_id,
        )
    )
    write_audit(
        db,
        actor_id,
        "application.status_changed",
        "application",
        application.id,
        {"from": source.value, "to": target.value, "explicit_approval": command.approved_by_user},
    )
    db.flush()
    return application


def analyze_application(
    db: Session,
    application: Application,
    profile: CandidateProfile,
    job: Job,
    actor_id: str,
    policy: MatchingPolicy,
) -> MatchAnalysisRead:
    if application.status not in {ApplicationStatus.DISCOVERED, ApplicationStatus.ANALYZED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Applications can only be analyzed before shortlisting or rejection.",
        )
    analysis = score_job(profile, job, policy)
    application.match_score = analysis.overall_score
    application.match_analysis = analysis.model_dump(mode="json")
    if application.status == ApplicationStatus.DISCOVERED:
        application.status = ApplicationStatus.ANALYZED
        db.add(
            ApplicationStatusHistory(
                application_id=application.id,
                from_status=ApplicationStatus.DISCOVERED,
                to_status=ApplicationStatus.ANALYZED,
                reason="Deterministic match analysis completed",
                actor_id=actor_id,
            )
        )
    write_audit(
        db,
        actor_id,
        "application.analyzed",
        "application",
        application.id,
        {
            "score": analysis.overall_score,
            "recommendation": analysis.recommendation,
            "hard_rejected": analysis.hard_rejected,
        },
    )
    db.flush()
    return analysis


def serialize_generated_document(document: GeneratedDocument) -> GeneratedDocumentRead:
    content = (
        GeneratedApplicationPackage.model_validate(document.content)
        if document.status == GeneratedDocumentStatus.VALID
        else None
    )
    return GeneratedDocumentRead(
        id=document.id,
        application_id=document.application_id,
        version=document.version,
        language=document.language,
        status=document.status,
        content=content,
        validation=GroundingValidationRead.model_validate(document.validation),
        prompt_version=document.prompt_version,
        model=document.model,
        provider_response_id=document.provider_response_id,
        input_tokens=document.input_tokens,
        cached_input_tokens=document.cached_input_tokens,
        output_tokens=document.output_tokens,
        estimated_cost_usd=document.estimated_cost_usd,
        latency_ms=document.latency_ms,
        created_at=document.created_at,
    )


def generate_application_documents(
    db: Session,
    application: Application,
    profile: CandidateProfile,
    job: Job,
    actor_id: str,
    request: GenerateDocumentsRequest,
    provider: AIProvider,
) -> GeneratedDocument:
    ensure_document_generation_allowed(application)
    facts = profile_facts(profile)
    # End the read transaction before the potentially slow external call. Objects remain
    # usable because request sessions do not expire state on commit.
    db.commit()
    try:
        plan, metadata = provider.select_plan(
            profile=profile, job=job, facts=facts, language=request.language
        )
        validate_document_plan(plan, facts)
        package = render_application_package(plan, facts=facts, job=job, language=request.language)
    except AIProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Document generation provider is temporarily unavailable",
        ) from exc
    validation = validate_grounding(package, facts, job)
    db.refresh(application, with_for_update=True)
    ensure_document_generation_allowed(application)
    previous_version = db.scalar(
        select(func.max(GeneratedDocument.version)).where(
            GeneratedDocument.application_id == application.id
        )
    )
    document = GeneratedDocument(
        application_id=application.id,
        version=(previous_version or 0) + 1,
        language=request.language,
        status=GeneratedDocumentStatus.VALID
        if validation.valid
        else GeneratedDocumentStatus.INVALID,
        content=package.model_dump(mode="json"),
        validation=validation.model_dump(mode="json"),
        prompt_version=PROMPT_VERSION,
        model=metadata.model,
        provider_response_id=metadata.provider_response_id,
        input_tokens=metadata.input_tokens,
        cached_input_tokens=metadata.cached_input_tokens,
        output_tokens=metadata.output_tokens,
        estimated_cost_usd=metadata.estimated_cost_usd,
        latency_ms=metadata.latency_ms,
    )
    db.add(document)
    db.flush()
    write_audit(
        db,
        actor_id,
        "application.documents_generated",
        "generated_document",
        document.id,
        {
            "application_id": application.id,
            "version": document.version,
            "valid": validation.valid,
            "model": metadata.model,
            "fallback_used": metadata.model == "deterministic-fallback",
            "latency_ms": metadata.latency_ms,
            "prompt_injection_markers": prompt_injection_markers(job),
        },
    )
    if validation.valid and application.status == ApplicationStatus.SHORTLISTED:
        application.status = ApplicationStatus.DOCUMENTS_PREPARED
        db.add(
            ApplicationStatusHistory(
                application_id=application.id,
                from_status=ApplicationStatus.SHORTLISTED,
                to_status=ApplicationStatus.DOCUMENTS_PREPARED,
                reason="Grounded application documents prepared",
                actor_id=actor_id,
            )
        )
    db.flush()
    return document


def ensure_document_generation_allowed(application: Application) -> None:
    if application.status not in {
        ApplicationStatus.SHORTLISTED,
        ApplicationStatus.DOCUMENTS_PREPARED,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Documents can only be generated for shortlisted applications.",
        )
