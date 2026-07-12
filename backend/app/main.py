from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import AIProvider, build_provider
from app.config import get_settings
from app.db import get_db
from app.matching import MatchingPolicy
from app.models import (
    Application,
    ApplicationStatusHistory,
    CandidateProfile,
    GeneratedDocument,
    GeneratedDocumentStatus,
    Job,
)
from app.schemas import (
    ApplicationCreate,
    ApplicationRead,
    ApplicationTransition,
    GeneratedDocumentRead,
    GenerateDocumentsRequest,
    HealthRead,
    JobCreate,
    JobRead,
    MatchAnalysisRead,
    ProfileCreate,
    ProfileRead,
    ProfileUpdate,
    StatusHistoryRead,
)
from app.services import (
    analyze_application,
    apply_profile_details,
    create_application,
    create_job,
    current_development_user,
    generate_application_documents,
    serialize_generated_document,
    transition_application,
    write_audit,
)
from app.services import (
    create_profile as create_profile_record,
)

settings = get_settings()
app = FastAPI(title="EU Job Agent API", version="1.0.0")
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)


@lru_cache(maxsize=1)
def get_ai_provider() -> AIProvider:
    try:
        return build_provider(settings)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


def serialize_profile(profile: CandidateProfile) -> ProfileRead:
    return ProfileRead.model_validate(profile)


@app.get("/health", response_model=HealthRead, tags=["system"])
def health() -> HealthRead:
    return HealthRead(status="ok")


@app.post(
    "/v1/profiles",
    response_model=ProfileRead,
    status_code=status.HTTP_201_CREATED,
    tags=["profiles"],
)
def create_profile(payload: ProfileCreate, db: Session = Depends(get_db)) -> ProfileRead:
    user = current_development_user(db)
    profile = create_profile_record(db, payload, user)
    db.commit()
    return serialize_profile(profile)


@app.get("/v1/profiles/me", response_model=ProfileRead, tags=["profiles"])
def get_profile(db: Session = Depends(get_db)) -> ProfileRead:
    user = current_development_user(db)
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return serialize_profile(profile)


@app.patch("/v1/profiles/me", response_model=ProfileRead, tags=["profiles"])
def update_profile(payload: ProfileUpdate, db: Session = Depends(get_db)) -> ProfileRead:
    user = current_development_user(db)
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    apply_profile_details(profile, payload)
    write_audit(db, user.id, "profile.updated", "candidate_profile", profile.id)
    db.commit()
    return serialize_profile(profile)


@app.post("/v1/jobs", response_model=JobRead, status_code=status.HTTP_201_CREATED, tags=["jobs"])
def import_job(payload: JobCreate, db: Session = Depends(get_db)) -> Job:
    user = current_development_user(db)
    job = create_job(db, payload, user.id)
    db.commit()
    return job


@app.get("/v1/jobs", response_model=list[JobRead], tags=["jobs"])
def list_jobs(db: Session = Depends(get_db)) -> list[Job]:
    return list(db.scalars(select(Job).order_by(Job.discovered_at.desc())))


@app.get("/v1/jobs/{job_id}", response_model=JobRead, tags=["jobs"])
def get_job(job_id: str, db: Session = Depends(get_db)) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@app.post(
    "/v1/applications",
    response_model=ApplicationRead,
    status_code=status.HTTP_201_CREATED,
    tags=["applications"],
)
def create_application_route(
    payload: ApplicationCreate, db: Session = Depends(get_db)
) -> Application:
    user = current_development_user(db)
    application = create_application(db, payload, user)
    db.commit()
    return application


@app.get("/v1/applications", response_model=list[ApplicationRead], tags=["applications"])
def list_applications(db: Session = Depends(get_db)) -> list[Application]:
    user = current_development_user(db)
    return list(
        db.scalars(
            select(Application)
            .where(Application.user_id == user.id)
            .order_by(Application.updated_at.desc())
        )
    )


@app.post(
    "/v1/applications/{application_id}/analyze",
    response_model=MatchAnalysisRead,
    tags=["applications"],
)
def analyze_application_match(
    application_id: str, db: Session = Depends(get_db)
) -> MatchAnalysisRead:
    user = current_development_user(db)
    application = db.scalar(
        select(Application)
        .where(Application.id == application_id, Application.user_id == user.id)
        .with_for_update()
    )
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Candidate profile is required"
        )
    job = db.get(Job, application.job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    analysis = analyze_application(
        db, application, profile, job, user.id, MatchingPolicy.from_settings(settings)
    )
    db.commit()
    return analysis


@app.post(
    "/v1/applications/{application_id}/documents/generate",
    response_model=GeneratedDocumentRead,
    status_code=status.HTTP_201_CREATED,
    tags=["documents"],
)
def generate_documents(
    application_id: str,
    payload: GenerateDocumentsRequest,
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_ai_provider),
) -> GeneratedDocumentRead:
    user = current_development_user(db)
    application = db.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user.id)
    )
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Candidate profile is required"
        )
    job = db.get(Job, application.job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    document = generate_application_documents(
        db, application, profile, job, user.id, payload, provider
    )
    db.commit()
    return serialize_generated_document(document)


@app.get(
    "/v1/applications/{application_id}/documents",
    response_model=list[GeneratedDocumentRead],
    tags=["documents"],
)
def list_generated_documents(
    application_id: str,
    latest_valid: bool = False,
    db: Session = Depends(get_db),
) -> list[GeneratedDocumentRead]:
    user = current_development_user(db)
    application = db.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user.id)
    )
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    statement = (
        select(GeneratedDocument)
        .where(GeneratedDocument.application_id == application.id)
        .order_by(GeneratedDocument.version.desc())
    )
    if latest_valid:
        statement = statement.where(
            GeneratedDocument.status == GeneratedDocumentStatus.VALID
        ).limit(1)
    documents = list(db.scalars(statement))
    return [serialize_generated_document(document) for document in documents]


@app.post(
    "/v1/applications/{application_id}/transition",
    response_model=ApplicationRead,
    tags=["applications"],
)
def change_application_status(
    application_id: str, payload: ApplicationTransition, db: Session = Depends(get_db)
) -> Application:
    user = current_development_user(db)
    application = db.scalar(
        select(Application)
        .where(Application.id == application_id, Application.user_id == user.id)
        .with_for_update()
    )
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    transition_application(db, application, user.id, payload)
    db.commit()
    return application


@app.get(
    "/v1/applications/{application_id}/history",
    response_model=list[StatusHistoryRead],
    tags=["applications"],
)
def application_history(
    application_id: str, db: Session = Depends(get_db)
) -> list[ApplicationStatusHistory]:
    user = current_development_user(db)
    application = db.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user.id)
    )
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return list(
        db.scalars(
            select(ApplicationStatusHistory)
            .where(ApplicationStatusHistory.application_id == application.id)
            .order_by(ApplicationStatusHistory.created_at)
        )
    )
