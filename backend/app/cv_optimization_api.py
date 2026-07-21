from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

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
from app.db import get_db
from app.models import CvAnalysisRun, CvExport, CvVariant, CvVariantStatus, CvVariantVersion
from app.services import current_development_user, write_audit

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
    db: Session = Depends(get_db),
    provider: CvOptimizationProvider = Depends(get_cv_optimization_provider),
) -> CvAnalysisRead:
    user = current_development_user(db)
    try:
        run = create_analysis(db, user, payload.job_id, provider)
        db.commit()
        db.refresh(run)
    except AIProviderError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return serialize_analysis(db, run)


@router.get("/analyses", response_model=list[CvAnalysisRead])
def analyses(
    job_id: str | None = Query(default=None, max_length=36), db: Session = Depends(get_db)
) -> list[CvAnalysisRead]:
    user = current_development_user(db)
    statement = select(CvAnalysisRun).where(CvAnalysisRun.user_id == user.id)
    if job_id:
        statement = statement.where(CvAnalysisRun.job_id == job_id)
    records = list(db.scalars(statement.order_by(CvAnalysisRun.created_at.desc()).limit(100)))
    return [serialize_analysis(db, record) for record in records]


@router.get("/analyses/{analysis_id}", response_model=CvAnalysisRead)
def analysis(analysis_id: str, db: Session = Depends(get_db)) -> CvAnalysisRead:
    user = current_development_user(db)
    return serialize_analysis(db, owned_analysis(db, user.id, analysis_id))


@router.patch("/recommendations/{recommendation_id}", response_model=RecommendationRead)
def decide(
    recommendation_id: str,
    payload: RecommendationDecisionRequest,
    db: Session = Depends(get_db),
) -> RecommendationRead:
    user = current_development_user(db)
    item = decide_recommendation(db, user, recommendation_id, payload)
    db.commit()
    db.refresh(item)
    return serialize_recommendation(db, item)


@router.post("/analyses/{analysis_id}/recommendations/batch", response_model=CvAnalysisRead)
def decide_batch(
    analysis_id: str,
    payload: RecommendationBatchRequest,
    db: Session = Depends(get_db),
) -> CvAnalysisRead:
    user = current_development_user(db)
    run = batch_decide(db, user, analysis_id, payload.action)
    db.commit()
    db.refresh(run)
    return serialize_analysis(db, run)


@router.post("/analyses/{analysis_id}/variants", response_model=CvVariantRead, status_code=201)
def create_variant(
    analysis_id: str,
    payload: GenerateVariantRequest,
    db: Session = Depends(get_db),
) -> CvVariantRead:
    user = current_development_user(db)
    variant = generate_variant(db, user, analysis_id, payload.status)
    db.commit()
    db.refresh(variant)
    return serialize_variant(db, variant)


@router.post("/analyses/{analysis_id}/preview", response_model=CvVariantPreview)
def preview(analysis_id: str, db: Session = Depends(get_db)) -> CvVariantPreview:
    user = current_development_user(db)
    return preview_variant(db, user, analysis_id)


@router.get("/variants", response_model=list[CvVariantRead])
def variants(
    job_id: str | None = Query(default=None, max_length=36), db: Session = Depends(get_db)
) -> list[CvVariantRead]:
    user = current_development_user(db)
    statement = select(CvVariant).where(CvVariant.user_id == user.id)
    if job_id:
        statement = statement.where(CvVariant.job_id == job_id)
    records = list(db.scalars(statement.order_by(CvVariant.created_at.desc()).limit(100)))
    return [serialize_variant(db, record) for record in records]


@router.get("/variants/{variant_id}", response_model=CvVariantRead)
def variant(variant_id: str, db: Session = Depends(get_db)) -> CvVariantRead:
    user = current_development_user(db)
    return serialize_variant(db, owned_variant(db, user.id, variant_id))


@router.get("/variants/{variant_id}/compare", response_model=CvVariantComparison)
def compare(variant_id: str, db: Session = Depends(get_db)) -> CvVariantComparison:
    user = current_development_user(db)
    return compare_variant(db, user.id, variant_id)


@router.delete("/variants/{variant_id}", status_code=204)
def delete_variant(
    variant_id: str,
    db: Session = Depends(get_db),
    storage: LocalCvExportStorage = Depends(get_cv_export_storage),
) -> None:
    user = current_development_user(db)
    variant_record = owned_variant(db, user.id, variant_id)
    export_keys = list(
        db.scalars(
            select(CvExport.storage_key)
            .join(CvVariantVersion, CvVariantVersion.id == CvExport.variant_version_id)
            .where(CvVariantVersion.variant_id == variant_record.id)
        )
    )
    remove_variant(db, user, variant_id)
    db.commit()
    for key in export_keys:
        storage.delete(key)


@router.post("/variants/{variant_id}/exports", response_model=CvExportRead, status_code=201)
def export_variant(
    variant_id: str,
    payload: ExportRequest,
    db: Session = Depends(get_db),
    storage: LocalCvExportStorage = Depends(get_cv_export_storage),
) -> CvExport:
    user = current_development_user(db)
    variant_record = owned_variant(db, user.id, variant_id)
    version = latest_variant_version(db, variant_record.id)
    existing = db.scalar(
        select(CvExport).where(
            CvExport.variant_version_id == version.id, CvExport.format == payload.format
        )
    )
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
    db.add(record)
    variant_record.status = CvVariantStatus.EXPORTED
    version.status = CvVariantStatus.EXPORTED
    write_audit(
        db,
        user.id,
        "cv_optimization.variant.exported",
        "cv_variant",
        variant_record.id,
        {"format": payload.format, "size_bytes": size},
    )
    try:
        db.commit()
    except Exception:
        storage.delete(key)
        raise
    db.refresh(record)
    return record


@router.get("/exports/{export_id}/download", response_class=FileResponse)
def download_export(
    export_id: str,
    db: Session = Depends(get_db),
    storage: LocalCvExportStorage = Depends(get_cv_export_storage),
) -> FileResponse:
    user = current_development_user(db)
    record = db.scalar(
        select(CvExport)
        .join(CvVariantVersion, CvVariantVersion.id == CvExport.variant_version_id)
        .join(CvVariant, CvVariant.id == CvVariantVersion.variant_id)
        .where(CvExport.id == export_id, CvVariant.user_id == user.id)
    )
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
