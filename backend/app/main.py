from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.ai import AIProvider, build_provider
from app.config import get_settings
from app.cover_letter_api import router as cover_letter_router
from app.cv import (
    LocalCvStorage,
    compare_import,
    confirm_cv_import,
    create_cv_import,
    delete_cv_file,
    delete_cv_import,
    get_owned_import,
    purge_expired_files,
    serialize_import,
    serialize_import_summary,
    update_cv_draft,
)
from app.cv_ai import CvExtractionProvider, build_cv_provider
from app.cv_optimization_api import router as cv_optimization_router
from app.cv_schemas import (
    CvComparison,
    CvConfirmRequest,
    CvDraftUpdate,
    CvImportExport,
    CvImportRead,
    CvImportSummary,
    CvProfileVersionRead,
)
from app.discovery_api import router as discovery_router
from app.matching import MatchingPolicy
from app.models import (
    Application,
    ApplicationStatusHistory,
    CandidateProfile,
    Job,
    ProfileVersion,
)
from app.repositories import PersistenceConflict
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
    create_application,
    create_job,
    current_development_user,
    generate_application_documents,
    serialize_generated_document,
    transition_application,
    update_candidate_profile,
    write_audit,
)
from app.services import (
    create_profile as create_profile_record,
)
from app.unit_of_work import UnitOfWorkDependency

settings = get_settings()
app = FastAPI(title="EU Job Agent API", version="1.0.0")


@app.exception_handler(PersistenceConflict)
async def persistence_conflict_handler(
    _request: Request, _exc: PersistenceConflict
) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"detail": "The record changed; retry the request"}
    )


app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(discovery_router)
app.include_router(cv_optimization_router)
app.include_router(cover_letter_router)


@lru_cache(maxsize=1)
def get_ai_provider() -> AIProvider:
    try:
        return build_provider(settings)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@lru_cache(maxsize=1)
def get_cv_provider() -> CvExtractionProvider:
    try:
        return build_cv_provider(settings)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@lru_cache(maxsize=1)
def get_cv_storage() -> LocalCvStorage:
    return LocalCvStorage(settings.cv_storage_path)


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
def create_profile(payload: ProfileCreate, uow: UnitOfWorkDependency) -> ProfileRead:
    user = current_development_user(uow)
    profile = create_profile_record(uow, payload, user)
    uow.commit()
    return serialize_profile(profile)


@app.get("/v1/profiles/me", response_model=ProfileRead, tags=["profiles"])
def get_profile(uow: UnitOfWorkDependency) -> ProfileRead:
    user = current_development_user(uow)
    profile = uow.candidates.get_profile(user.id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return serialize_profile(profile)


@app.patch("/v1/profiles/me", response_model=ProfileRead, tags=["profiles"])
def update_profile(payload: ProfileUpdate, uow: UnitOfWorkDependency) -> ProfileRead:
    user = current_development_user(uow)
    profile = update_candidate_profile(uow, payload, user)
    uow.commit()
    return serialize_profile(profile)


@app.delete("/v1/profiles/me", status_code=status.HTTP_204_NO_CONTENT, tags=["profiles"])
def delete_profile(uow: UnitOfWorkDependency) -> None:
    user = current_development_user(uow)
    profile = uow.candidates.get_profile(user.id, lock=True)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    write_audit(uow, user.id, "profile.deleted", "candidate_profile", profile.id)
    uow.delete(profile)
    uow.commit()


@app.post(
    "/v1/cv-imports",
    response_model=CvImportRead,
    status_code=status.HTTP_201_CREATED,
    tags=["cv-imports"],
)
async def upload_cv(
    uow: UnitOfWorkDependency,
    file: UploadFile = File(...),
    provider: CvExtractionProvider = Depends(get_cv_provider),
    storage: LocalCvStorage = Depends(get_cv_storage),
) -> CvImportRead:
    user = current_development_user(uow)
    purge_expired_files(uow, settings, storage)
    record = await create_cv_import(uow, file, user, settings, provider, storage)
    uow.commit()
    uow.refresh(record)
    return serialize_import(record, storage)


@app.get("/v1/cv-imports", response_model=list[CvImportSummary], tags=["cv-imports"])
def list_cv_imports(
    uow: UnitOfWorkDependency, storage: LocalCvStorage = Depends(get_cv_storage)
) -> list[CvImportSummary]:
    user = current_development_user(uow)
    records = uow.cvs.list_imports(user.id)
    return [serialize_import_summary(record, storage) for record in records]


@app.get("/v1/cv-imports/{import_id}", response_model=CvImportRead, tags=["cv-imports"])
def get_cv_import(
    import_id: str,
    uow: UnitOfWorkDependency,
    storage: LocalCvStorage = Depends(get_cv_storage),
) -> CvImportRead:
    user = current_development_user(uow)
    return serialize_import(get_owned_import(uow, import_id, user.id), storage)


@app.patch("/v1/cv-imports/{import_id}", response_model=CvImportRead, tags=["cv-imports"])
def edit_cv_import(
    import_id: str,
    payload: CvDraftUpdate,
    uow: UnitOfWorkDependency,
    storage: LocalCvStorage = Depends(get_cv_storage),
) -> CvImportRead:
    user = current_development_user(uow)
    record = get_owned_import(uow, import_id, user.id, lock=True)
    update_cv_draft(uow, record, payload.draft, user)
    uow.commit()
    uow.refresh(record)
    return serialize_import(record, storage)


@app.get("/v1/cv-imports/{import_id}/compare", response_model=CvComparison, tags=["cv-imports"])
def compare_cv_import(import_id: str, uow: UnitOfWorkDependency) -> CvComparison:
    user = current_development_user(uow)
    return compare_import(uow, get_owned_import(uow, import_id, user.id), user)


@app.post(
    "/v1/cv-imports/{import_id}/confirm",
    response_model=CvProfileVersionRead,
    tags=["cv-imports"],
)
def confirm_cv_import_route(
    import_id: str, payload: CvConfirmRequest, uow: UnitOfWorkDependency
) -> ProfileVersion:
    user = current_development_user(uow)
    record = get_owned_import(uow, import_id, user.id, lock=True)
    _, version = confirm_cv_import(uow, record, user, payload.strategy, payload.accept_conflicts)
    uow.commit()
    uow.refresh(version)
    return version


@app.get("/v1/cv-imports/{import_id}/export", response_model=CvImportExport, tags=["cv-imports"])
def export_cv_import(
    import_id: str,
    uow: UnitOfWorkDependency,
    storage: LocalCvStorage = Depends(get_cv_storage),
) -> CvImportExport:
    user = current_development_user(uow)
    record = get_owned_import(uow, import_id, user.id)
    versions = sorted(
        (
            version
            for version in uow.candidates.list_profile_versions(user.id)
            if version.cv_import_id == record.id
        ),
        key=lambda version: version.version,
    )
    return CvImportExport(
        import_record=serialize_import(record, storage),
        versions=[CvProfileVersionRead.model_validate(version) for version in versions],
    )


@app.delete(
    "/v1/cv-imports/{import_id}/file", status_code=status.HTTP_204_NO_CONTENT, tags=["cv-imports"]
)
def remove_cv_file(
    import_id: str,
    uow: UnitOfWorkDependency,
    storage: LocalCvStorage = Depends(get_cv_storage),
) -> None:
    user = current_development_user(uow)
    delete_cv_file(uow, get_owned_import(uow, import_id, user.id, lock=True), user, storage)
    uow.commit()


@app.delete(
    "/v1/cv-imports/{import_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["cv-imports"]
)
def remove_cv_import(
    import_id: str,
    uow: UnitOfWorkDependency,
    storage: LocalCvStorage = Depends(get_cv_storage),
) -> None:
    user = current_development_user(uow)
    delete_cv_import(uow, get_owned_import(uow, import_id, user.id, lock=True), user, storage)
    uow.commit()


@app.post("/v1/jobs", response_model=JobRead, status_code=status.HTTP_201_CREATED, tags=["jobs"])
def import_job(payload: JobCreate, uow: UnitOfWorkDependency) -> Job:
    user = current_development_user(uow)
    job = create_job(uow, payload, user.id)
    uow.commit()
    return job


@app.get("/v1/jobs", response_model=list[JobRead], tags=["jobs"])
def list_jobs(uow: UnitOfWorkDependency) -> list[Job]:
    return uow.jobs.list_jobs()


@app.get("/v1/jobs/{job_id}", response_model=JobRead, tags=["jobs"])
def get_job(job_id: str, uow: UnitOfWorkDependency) -> Job:
    job = uow.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@app.post(
    "/v1/applications",
    response_model=ApplicationRead,
    status_code=status.HTTP_201_CREATED,
    tags=["applications"],
)
def create_application_route(payload: ApplicationCreate, uow: UnitOfWorkDependency) -> Application:
    user = current_development_user(uow)
    application = create_application(uow, payload, user)
    uow.commit()
    return application


@app.get("/v1/applications", response_model=list[ApplicationRead], tags=["applications"])
def list_applications(uow: UnitOfWorkDependency) -> list[Application]:
    user = current_development_user(uow)
    return uow.applications.list_owned(user.id)


@app.post(
    "/v1/applications/{application_id}/analyze",
    response_model=MatchAnalysisRead,
    tags=["applications"],
)
def analyze_application_match(application_id: str, uow: UnitOfWorkDependency) -> MatchAnalysisRead:
    user = current_development_user(uow)
    application = uow.applications.get_owned(application_id, user.id, lock=True)
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    profile = uow.candidates.get_profile(user.id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Candidate profile is required"
        )
    job = uow.jobs.get(application.job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    analysis = analyze_application(
        uow, application, profile, job, user.id, MatchingPolicy.from_settings(settings)
    )
    uow.commit()
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
    uow: UnitOfWorkDependency,
    provider: AIProvider = Depends(get_ai_provider),
) -> GeneratedDocumentRead:
    user = current_development_user(uow)
    application = uow.applications.get_owned(application_id, user.id)
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    profile = uow.candidates.get_profile(user.id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Candidate profile is required"
        )
    job = uow.jobs.get(application.job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    document = generate_application_documents(
        uow, application, profile, job, user.id, payload, provider
    )
    uow.commit()
    return serialize_generated_document(document)


@app.get(
    "/v1/applications/{application_id}/documents",
    response_model=list[GeneratedDocumentRead],
    tags=["documents"],
)
def list_generated_documents(
    application_id: str,
    uow: UnitOfWorkDependency,
    latest_valid: bool = False,
) -> list[GeneratedDocumentRead]:
    user = current_development_user(uow)
    application = uow.applications.get_owned(application_id, user.id)
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    documents = uow.applications.list_documents(application.id, latest_valid=latest_valid)
    return [serialize_generated_document(document) for document in documents]


@app.post(
    "/v1/applications/{application_id}/transition",
    response_model=ApplicationRead,
    tags=["applications"],
)
def change_application_status(
    application_id: str, payload: ApplicationTransition, uow: UnitOfWorkDependency
) -> Application:
    user = current_development_user(uow)
    application = uow.applications.get_owned(application_id, user.id, lock=True)
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    transition_application(uow, application, user.id, payload)
    uow.commit()
    return application


@app.get(
    "/v1/applications/{application_id}/history",
    response_model=list[StatusHistoryRead],
    tags=["applications"],
)
def application_history(
    application_id: str, uow: UnitOfWorkDependency
) -> list[ApplicationStatusHistory]:
    user = current_development_user(uow)
    application = uow.applications.get_owned(application_id, user.id)
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return uow.applications.list_history(application.id)
