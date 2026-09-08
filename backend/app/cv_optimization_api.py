from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.ai import AIProviderError
from app.config import get_settings
from app.cv_exports import LocalCvExportStorage, render_export
from app.cv_optimization import (
    batch_decide,
    compare_variant,
    create_analysis,
    decide_recommendation,
    generate_variant,
    latest_variant_version,
    owned_analysis,
    owned_variant,
    preview_variant,
    remove_variant,
    serialize_analysis,
    serialize_recommendation,
    serialize_variant,
)
from app.cv_optimization_ai import CvOptimizationProvider, build_cv_optimization_provider
from app.cv_optimization_schemas import (
    CvAnalysisRead,
    CvAnalysisRequest,
    CvExportRead,
    CvVariantComparison,
    CvVariantPreview,
    CvVariantRead,
    ExportRequest,
    GenerateVariantRequest,
    RecommendationBatchRequest,
    RecommendationDecisionRequest,
    RecommendationRead,
)
from app.cv_schemas import CvProfileDraft
from app.models import CvExport, CvVariantStatus, StoredFile
from app.services import current_development_user, write_audit
from app.unit_of_work import UnitOfWorkDependency

router = APIRouter(prefix="/v1/cv-optimizations", tags=["cv-optimizations"])


@lru_cache(maxsize=1)
def get_cv_optimization_provider() -> CvOptimizationProvider:
    return build_cv_optimization_provider(get_settings())


@lru_cache(maxsize=1)
def get_cv_export_storage() -> LocalCvExportStorage:
    return LocalCvExportStorage(get_settings().cv_export_storage_path)


@router.post("/analyses", response_model=CvAnalysisRead, status_code=status.HTTP_201_CREATED)
def analyze_cv(
    payload: CvAnalysisRequest,
    uow: UnitOfWorkDependency,
    provider: CvOptimizationProvider = Depends(get_cv_optimization_provider),
) -> CvAnalysisRead:
    user = current_development_user(uow)
    try:
        run = create_analysis(uow, user, payload.job_id, provider)
        uow.commit()
        uow.refresh(run)
    except AIProviderError as exc:
        uow.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return serialize_analysis(uow, run)


@router.get("/analyses", response_model=list[CvAnalysisRead])
def analyses(
    uow: UnitOfWorkDependency, job_id: str | None = Query(default=None, max_length=36)
) -> list[CvAnalysisRead]:
    user = current_development_user(uow)
    records = uow.recommendations.list_analyses(user.id, job_id)
    return [serialize_analysis(uow, record) for record in records]


@router.get("/analyses/{analysis_id}", response_model=CvAnalysisRead)
def analysis(analysis_id: str, uow: UnitOfWorkDependency) -> CvAnalysisRead:
    user = current_development_user(uow)
    return serialize_analysis(uow, owned_analysis(uow, user.id, analysis_id))


@router.patch("/recommendations/{recommendation_id}", response_model=RecommendationRead)
def decide(
    recommendation_id: str,
    payload: RecommendationDecisionRequest,
    uow: UnitOfWorkDependency,
) -> RecommendationRead:
    user = current_development_user(uow)
    item = decide_recommendation(uow, user, recommendation_id, payload)
    uow.commit()
    uow.refresh(item)
    return serialize_recommendation(uow, item)


@router.post("/analyses/{analysis_id}/recommendations/batch", response_model=CvAnalysisRead)
def decide_batch(
    analysis_id: str,
    payload: RecommendationBatchRequest,
    uow: UnitOfWorkDependency,
) -> CvAnalysisRead:
    user = current_development_user(uow)
    run = batch_decide(uow, user, analysis_id, payload.action)
    uow.commit()
    uow.refresh(run)
    return serialize_analysis(uow, run)


@router.post("/analyses/{analysis_id}/variants", response_model=CvVariantRead, status_code=201)
def create_variant(
    analysis_id: str,
    payload: GenerateVariantRequest,
    uow: UnitOfWorkDependency,
) -> CvVariantRead:
    user = current_development_user(uow)
    variant = generate_variant(uow, user, analysis_id, payload.status)
    uow.commit()
    uow.refresh(variant)
    return serialize_variant(uow, variant)


@router.post("/analyses/{analysis_id}/preview", response_model=CvVariantPreview)
def preview(analysis_id: str, uow: UnitOfWorkDependency) -> CvVariantPreview:
    user = current_development_user(uow)
    return preview_variant(uow, user, analysis_id)


@router.get("/variants", response_model=list[CvVariantRead])
def variants(
    uow: UnitOfWorkDependency, job_id: str | None = Query(default=None, max_length=36)
) -> list[CvVariantRead]:
    user = current_development_user(uow)
    records = uow.recommendations.list_variants(user.id, job_id)
    return [serialize_variant(uow, record) for record in records]


@router.get("/variants/{variant_id}", response_model=CvVariantRead)
def variant(variant_id: str, uow: UnitOfWorkDependency) -> CvVariantRead:
    user = current_development_user(uow)
    return serialize_variant(uow, owned_variant(uow, user.id, variant_id))


@router.get("/variants/{variant_id}/compare", response_model=CvVariantComparison)
def compare(variant_id: str, uow: UnitOfWorkDependency) -> CvVariantComparison:
    user = current_development_user(uow)
    return compare_variant(uow, user.id, variant_id)


@router.delete("/variants/{variant_id}", status_code=204)
def delete_variant(
    variant_id: str,
    uow: UnitOfWorkDependency,
    storage: LocalCvExportStorage = Depends(get_cv_export_storage),
) -> None:
    user = current_development_user(uow)
    variant_record = owned_variant(uow, user.id, variant_id)
    export_keys = uow.recommendations.export_keys(variant_record.id)
    remove_variant(uow, user, variant_id)
    uow.commit()
    for key in export_keys:
        storage.delete(key)


@router.post("/variants/{variant_id}/exports", response_model=CvExportRead, status_code=201)
def export_variant(
    variant_id: str,
    payload: ExportRequest,
    uow: UnitOfWorkDependency,
    storage: LocalCvExportStorage = Depends(get_cv_export_storage),
) -> CvExport:
    user = current_development_user(uow)
    variant_record = owned_variant(uow, user.id, variant_id)
    version = latest_variant_version(uow, variant_record.id)
    existing = uow.recommendations.export(version.id, payload.format)
    if existing:
        return existing
    if variant_record.status not in {CvVariantStatus.APPROVED, CvVariantStatus.EXPORTED}:
        raise HTTPException(
            status_code=409,
            detail="Approve the reviewed CV variant before exporting it",
        )
    content = render_export(CvProfileDraft.model_validate(version.content), payload.format)
    key, digest, size = storage.store(payload.format, content)
    record = CvExport(
        variant_version_id=version.id,
        format=payload.format,
        storage_key=key,
        sha256=digest,
        size_bytes=size,
    )
    uow.add(record)
    uow.flush()
    uow.add(
        StoredFile(
            owner_id=user.id,
            cv_export_id=record.id,
            storage_key=key,
            original_filename=f"job-specific-cv.{payload.format}",
            media_type=(
                "application/pdf"
                if payload.format == "pdf"
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            size_bytes=size,
            sha256=digest,
        )
    )
    variant_record.status = CvVariantStatus.EXPORTED
    version.status = CvVariantStatus.EXPORTED
    write_audit(
        uow,
        user.id,
        "cv_optimization.variant.exported",
        "cv_variant",
        variant_record.id,
        {"format": payload.format, "size_bytes": size},
    )
    try:
        uow.commit()
    except Exception:
        storage.delete(key)
        raise
    uow.refresh(record)
    return record


@router.get("/exports/{export_id}/download", response_class=FileResponse)
def download_export(
    export_id: str,
    uow: UnitOfWorkDependency,
    storage: LocalCvExportStorage = Depends(get_cv_export_storage),
) -> FileResponse:
    user = current_development_user(uow)
    record = uow.recommendations.export_for_download(export_id, user.id)
    if not record:
        raise HTTPException(status_code=404, detail="CV export not found")
    media_type = (
        "application/pdf"
        if record.format == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(
        storage.path_for(record.storage_key),
        media_type=media_type,
        filename=f"job-specific-cv.{record.format}",
    )
