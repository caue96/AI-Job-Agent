from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

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
from app.models import (
    CoverLetterStatus,
    DocumentExport,
    StoredFile,
)
from app.services import current_development_user, write_audit
from app.unit_of_work import UnitOfWorkDependency

router = APIRouter(prefix="/v1/cover-letters", tags=["cover-letters"])


@lru_cache(maxsize=1)
def get_cover_letter_provider() -> CoverLetterProvider:
    return build_cover_letter_provider(get_settings())


@router.post("", response_model=list[CoverLetterRead], status_code=status.HTTP_201_CREATED)
def generate(
    payload: CoverLetterGenerateRequest,
    uow: UnitOfWorkDependency,
    provider: CoverLetterProvider = Depends(get_cover_letter_provider),
) -> list[CoverLetterRead]:
    user = current_development_user(uow)
    records = generate_cover_letters(uow, user, payload, provider)
    uow.commit()
    for record in records:
        uow.refresh(record)
    return [serialize_cover_letter(uow, record, user.id) for record in records]


@router.get("", response_model=list[CoverLetterRead])
def list_letters(
    uow: UnitOfWorkDependency,
    job_id: str | None = Query(default=None, max_length=36),
) -> list[CoverLetterRead]:
    user = current_development_user(uow)
    records = uow.cover_letters.list_letters(user.id, job_id)
    return [serialize_cover_letter(uow, record, user.id) for record in records]


@router.get("/{document_id}", response_model=CoverLetterRead)
def read_letter(document_id: str, uow: UnitOfWorkDependency) -> CoverLetterRead:
    user = current_development_user(uow)
    return serialize_cover_letter(uow, owned_cover_letter(uow, user.id, document_id), user.id)


@router.patch("/{document_id}", response_model=CoverLetterRead, status_code=201)
def edit_letter(
    document_id: str,
    payload: CoverLetterEditRequest,
    uow: UnitOfWorkDependency,
) -> CoverLetterRead:
    user = current_development_user(uow)
    record = edit_cover_letter(uow, user, document_id, payload)
    uow.commit()
    uow.refresh(record)
    return serialize_cover_letter(uow, record, user.id)


@router.post("/{document_id}/validate", response_model=CoverLetterRead)
def validate_letter(document_id: str, uow: UnitOfWorkDependency) -> CoverLetterRead:
    user = current_development_user(uow)
    record = revalidate_cover_letter(uow, user, document_id)
    uow.commit()
    uow.refresh(record)
    return serialize_cover_letter(uow, record, user.id)


@router.post("/{document_id}/select", response_model=CoverLetterRead)
def select_letter(document_id: str, uow: UnitOfWorkDependency) -> CoverLetterRead:
    user = current_development_user(uow)
    record = select_cover_letter(uow, user, document_id)
    uow.commit()
    uow.refresh(record)
    return serialize_cover_letter(uow, record, user.id)


@router.post("/{document_id}/approve", response_model=CoverLetterRead)
def approve_letter(document_id: str, uow: UnitOfWorkDependency) -> CoverLetterRead:
    user = current_development_user(uow)
    record = approve_cover_letter(uow, user, document_id)
    uow.commit()
    uow.refresh(record)
    return serialize_cover_letter(uow, record, user.id)


@router.post("/{document_id}/regenerate", response_model=list[CoverLetterRead], status_code=201)
def regenerate_letter(
    document_id: str,
    uow: UnitOfWorkDependency,
    provider: CoverLetterProvider = Depends(get_cover_letter_provider),
) -> list[CoverLetterRead]:
    user = current_development_user(uow)
    source = owned_cover_letter(uow, user.id, document_id)
    records = generate_cover_letters(uow, user, request_from_configuration(source), provider)
    uow.commit()
    for record in records:
        uow.refresh(record)
    return [serialize_cover_letter(uow, record, user.id) for record in records]


@router.delete("/{document_id}", status_code=204)
def delete_letter(
    document_id: str,
    uow: UnitOfWorkDependency,
    storage: LocalCvExportStorage = Depends(get_cv_export_storage),
) -> None:
    user = current_development_user(uow)
    record = owned_cover_letter(uow, user.id, document_id, lock=True)
    if record.cover_letter_status in {
        CoverLetterStatus.APPROVED,
        CoverLetterStatus.EXPORTED,
    }:
        raise HTTPException(status_code=409, detail="Approved cover letters cannot be deleted")
    keys = uow.cover_letters.export_keys(record.id)
    write_audit(uow, user.id, "cover_letter.deleted", "generated_document", record.id)
    uow.delete(record)
    uow.commit()
    for key in keys:
        storage.delete(key)


@router.post("/{document_id}/exports", response_model=DocumentExportRead, status_code=201)
def export_letter(
    document_id: str,
    payload: CoverLetterExportRequest,
    uow: UnitOfWorkDependency,
    storage: LocalCvExportStorage = Depends(get_cv_export_storage),
) -> DocumentExport:
    user = current_development_user(uow)
    record = owned_cover_letter(uow, user.id, document_id, lock=True)
    if record.cover_letter_status not in {
        CoverLetterStatus.APPROVED,
        CoverLetterStatus.EXPORTED,
    }:
        raise HTTPException(status_code=409, detail="Approve the cover letter before export")
    existing = uow.cover_letters.export(record.id, payload.format)
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
    uow.add(export)
    uow.flush()
    media_types = {
        "txt": "text/plain; charset=utf-8",
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    uow.add(
        StoredFile(
            owner_id=user.id,
            document_export_id=export.id,
            storage_key=key,
            original_filename=f"cover-letter.{payload.format}",
            media_type=media_types[payload.format],
            size_bytes=size,
            sha256=digest,
        )
    )
    record.cover_letter_status = CoverLetterStatus.EXPORTED
    write_audit(
        uow,
        user.id,
        "cover_letter.exported",
        "generated_document",
        record.id,
        {"format": payload.format, "size_bytes": size},
    )
    try:
        uow.commit()
    except Exception:
        storage.delete(key)
        raise
    uow.refresh(export)
    return export


@router.get("/exports/{export_id}/download", response_class=FileResponse)
def download_export(
    export_id: str,
    uow: UnitOfWorkDependency,
    storage: LocalCvExportStorage = Depends(get_cv_export_storage),
) -> FileResponse:
    user = current_development_user(uow)
    record = uow.cover_letters.export_for_download(export_id, user.id)
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
