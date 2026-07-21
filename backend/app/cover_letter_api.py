from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.cover_letter_ai import CoverLetterProvider, build_cover_letter_provider
from app.cover_letter_schemas import (
    CoverLetterEditRequest,
    CoverLetterExportRequest,
    CoverLetterGenerateRequest,
    CoverLetterRead,
    DocumentExportRead,
)
from app.cover_letters import (
    DOCUMENT_TYPE,
    approve_cover_letter,
    edit_cover_letter,
    generate_cover_letters,
    owned_cover_letter,
    request_from_configuration,
    revalidate_cover_letter,
    select_cover_letter,
    serialize_cover_letter,
)
from app.cv_exports import LocalCvExportStorage, render_cover_letter_export
from app.cv_optimization_api import get_cv_export_storage
from app.db import get_db
from app.models import (
    Application,
    CoverLetterStatus,
    DocumentExport,
    GeneratedDocument,
)
from app.services import current_development_user, write_audit

router = APIRouter(prefix="/v1/cover-letters", tags=["cover-letters"])


@lru_cache(maxsize=1)
def get_cover_letter_provider() -> CoverLetterProvider:
    return build_cover_letter_provider(get_settings())


@router.post("", response_model=list[CoverLetterRead], status_code=status.HTTP_201_CREATED)
def generate(
    payload: CoverLetterGenerateRequest,
    db: Session = Depends(get_db),
    provider: CoverLetterProvider = Depends(get_cover_letter_provider),
) -> list[CoverLetterRead]:
    user = current_development_user(db)
    records = generate_cover_letters(db, user, payload, provider)
    db.commit()
    for record in records:
        db.refresh(record)
    return [serialize_cover_letter(db, record) for record in records]


@router.get("", response_model=list[CoverLetterRead])
def list_letters(
    job_id: str | None = Query(default=None, max_length=36),
    db: Session = Depends(get_db),
) -> list[CoverLetterRead]:
    user = current_development_user(db)
    statement = (
        select(GeneratedDocument)
        .join(Application)
        .where(
            Application.user_id == user.id,
            GeneratedDocument.document_type == DOCUMENT_TYPE,
        )
    )
    if job_id:
        statement = statement.where(GeneratedDocument.job_id == job_id)
    records = list(db.scalars(statement.order_by(GeneratedDocument.created_at.desc()).limit(100)))
    return [serialize_cover_letter(db, record) for record in records]


@router.get("/{document_id}", response_model=CoverLetterRead)
def read_letter(document_id: str, db: Session = Depends(get_db)) -> CoverLetterRead:
    user = current_development_user(db)
    return serialize_cover_letter(db, owned_cover_letter(db, user.id, document_id))


@router.patch("/{document_id}", response_model=CoverLetterRead, status_code=201)
def edit_letter(
    document_id: str,
    payload: CoverLetterEditRequest,
    db: Session = Depends(get_db),
) -> CoverLetterRead:
    user = current_development_user(db)
    record = edit_cover_letter(db, user, document_id, payload)
    db.commit()
    db.refresh(record)
    return serialize_cover_letter(db, record)


@router.post("/{document_id}/validate", response_model=CoverLetterRead)
def validate_letter(document_id: str, db: Session = Depends(get_db)) -> CoverLetterRead:
    user = current_development_user(db)
    record = revalidate_cover_letter(db, user, document_id)
    db.commit()
    db.refresh(record)
    return serialize_cover_letter(db, record)


@router.post("/{document_id}/select", response_model=CoverLetterRead)
def select_letter(document_id: str, db: Session = Depends(get_db)) -> CoverLetterRead:
    user = current_development_user(db)
    record = select_cover_letter(db, user, document_id)
    db.commit()
    db.refresh(record)
    return serialize_cover_letter(db, record)


@router.post("/{document_id}/approve", response_model=CoverLetterRead)
def approve_letter(document_id: str, db: Session = Depends(get_db)) -> CoverLetterRead:
    user = current_development_user(db)
    record = approve_cover_letter(db, user, document_id)
    db.commit()
    db.refresh(record)
    return serialize_cover_letter(db, record)


@router.post("/{document_id}/regenerate", response_model=list[CoverLetterRead], status_code=201)
def regenerate_letter(
    document_id: str,
    db: Session = Depends(get_db),
    provider: CoverLetterProvider = Depends(get_cover_letter_provider),
) -> list[CoverLetterRead]:
    user = current_development_user(db)
    source = owned_cover_letter(db, user.id, document_id)
    records = generate_cover_letters(db, user, request_from_configuration(source), provider)
    db.commit()
    for record in records:
        db.refresh(record)
    return [serialize_cover_letter(db, record) for record in records]


@router.delete("/{document_id}", status_code=204)
def delete_letter(
    document_id: str,
    db: Session = Depends(get_db),
    storage: LocalCvExportStorage = Depends(get_cv_export_storage),
) -> None:
    user = current_development_user(db)
    record = owned_cover_letter(db, user.id, document_id, lock=True)
    if record.cover_letter_status in {
        CoverLetterStatus.APPROVED,
        CoverLetterStatus.EXPORTED,
    }:
        raise HTTPException(status_code=409, detail="Approved cover letters cannot be deleted")
    keys = list(
        db.scalars(
            select(DocumentExport.storage_key).where(
                DocumentExport.generated_document_id == record.id
            )
        )
    )
    write_audit(db, user.id, "cover_letter.deleted", "generated_document", record.id)
    db.delete(record)
    db.commit()
    for key in keys:
        storage.delete(key)


@router.post("/{document_id}/exports", response_model=DocumentExportRead, status_code=201)
def export_letter(
    document_id: str,
    payload: CoverLetterExportRequest,
    db: Session = Depends(get_db),
    storage: LocalCvExportStorage = Depends(get_cv_export_storage),
) -> DocumentExport:
    user = current_development_user(db)
    record = owned_cover_letter(db, user.id, document_id, lock=True)
    if record.cover_letter_status not in {
        CoverLetterStatus.APPROVED,
        CoverLetterStatus.EXPORTED,
    }:
        raise HTTPException(status_code=409, detail="Approve the cover letter before export")
    existing = db.scalar(
        select(DocumentExport).where(
            DocumentExport.generated_document_id == record.id,
            DocumentExport.format == payload.format,
        )
    )
    if existing:
        return existing
    from app.cover_letter_schemas import CoverLetterContent

    content = render_cover_letter_export(
        CoverLetterContent.model_validate(record.content), payload.format
    )
    key, digest, size = storage.store(payload.format, content)
    export = DocumentExport(
        generated_document_id=record.id,
        format=payload.format,
        storage_key=key,
        sha256=digest,
        size_bytes=size,
    )
    db.add(export)
    record.cover_letter_status = CoverLetterStatus.EXPORTED
    write_audit(
        db,
        user.id,
        "cover_letter.exported",
        "generated_document",
        record.id,
        {"format": payload.format, "size_bytes": size},
    )
    try:
        db.commit()
    except Exception:
        storage.delete(key)
        raise
    db.refresh(export)
    return export


@router.get("/exports/{export_id}/download", response_class=FileResponse)
def download_export(
    export_id: str,
    db: Session = Depends(get_db),
    storage: LocalCvExportStorage = Depends(get_cv_export_storage),
) -> FileResponse:
    user = current_development_user(db)
    record = db.scalar(
        select(DocumentExport)
        .join(GeneratedDocument)
        .join(Application)
        .where(DocumentExport.id == export_id, Application.user_id == user.id)
    )
    if not record:
        raise HTTPException(status_code=404, detail="Cover-letter export not found")
    media_types = {
        "txt": "text/plain; charset=utf-8",
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    return FileResponse(
        storage.path_for(record.storage_key),
        media_type=media_types[record.format],
        filename=f"cover-letter.{record.format}",
    )
