"""Secure CV ingestion, extraction, grounding, review, and profile persistence."""

from __future__ import annotations

import hashlib
import re
import threading
import uuid
from collections import defaultdict, deque
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from pydantic import EmailStr, TypeAdapter, ValidationError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.ai import AIProviderError
from app.config import Settings
from app.cv_ai import CvExtractionProvider
from app.cv_schemas import (
    CvComparison,
    CvConflict,
    CvImportRead,
    CvImportSummary,
    CvProfileDraft,
)
from app.models import (
    CandidateProfile,
    CvImport,
    CvImportStatus,
    EmploymentEntry,
    ProfileLanguage,
    ProfileSkill,
    ProfileVersion,
    User,
)
from app.services import write_audit

PDF_MEDIA_TYPES = {"application/pdf", "application/x-pdf"}
SECTION_HEADINGS = {
    "summary": ("summary", "profile", "about"),
    "skills": ("skills", "technical skills", "competencies", "technologies"),
    "employment": ("experience", "employment", "work history", "professional experience"),
    "education": ("education", "academic background"),
    "certifications": ("certifications", "certificates"),
    "projects": ("projects", "selected projects"),
    "languages": ("languages",),
}


class CvValidationError(ValueError):
    pass


class UploadRateLimiter:
    """Small process-local limiter suitable for the deliberately local-only deployment."""

    def __init__(self) -> None:
        self._events: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, user_id: str, limit: int, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        cutoff = current - timedelta(minutes=1)
        with self._lock:
            events = self._events[user_id]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many CV uploads. Wait one minute and try again.",
                )
            events.append(current)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


upload_rate_limiter = UploadRateLimiter()


class LocalCvStorage:
    def __init__(self, configured_path: str):
        self.root = Path(configured_path).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}\.pdf", key):
            raise CvValidationError("Invalid stored file identifier")
        target = (self.root / key).resolve()
        if target.parent != self.root:
            raise CvValidationError("Invalid stored file path")
        return target

    async def store(self, upload: UploadFile, max_bytes: int) -> tuple[str, int, str, bytes]:
        key = f"{uuid.uuid4().hex}.pdf"
        target = self._path(key)
        digest = hashlib.sha256()
        size = 0
        prefix = b""
        try:
            with target.open("xb") as destination:
                while chunk := await upload.read(64 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise CvValidationError(
                            f"PDF exceeds the {max_bytes // (1024 * 1024)} MB upload limit"
                        )
                    if len(prefix) < 8:
                        prefix += chunk[: 8 - len(prefix)]
                    digest.update(chunk)
                    destination.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        if size == 0:
            target.unlink(missing_ok=True)
            raise CvValidationError("The selected PDF is empty")
        return key, size, digest.hexdigest(), prefix

    def path_for(self, key: str) -> Path:
        return self._path(key)

    def delete(self, key: str | None) -> bool:
        if not key:
            return False
        path = self._path(key)
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed

    def exists(self, key: str | None) -> bool:
        return bool(key and self._path(key).is_file())


def safe_original_filename(value: str | None) -> str:
    filename = (value or "cv.pdf").replace("\\", "/").rsplit("/", 1)[-1]
    filename = "".join(char for char in filename if char.isprintable()).strip()
    return (filename or "cv.pdf")[:255]


def validate_upload_metadata(upload: UploadFile) -> str:
    filename = safe_original_filename(upload.filename)
    if Path(filename).suffix.casefold() != ".pdf":
        raise CvValidationError("Only files with a .pdf extension are accepted")
    if (upload.content_type or "").casefold() not in PDF_MEDIA_TYPES:
        raise CvValidationError("Only the PDF media type is accepted")
    return filename


def normalize_extracted_text(value: str) -> str:
    value = value.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    result: list[str] = []
    blank = False
    for line in lines:
        if line:
            result.append(line)
            blank = False
        elif result and not blank:
            result.append("")
            blank = True
    return "\n".join(result).strip()


def extract_pdf(path: Path, max_pages: int) -> list[dict]:
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise CvValidationError("Password-protected PDFs are not supported")
        if not reader.pages:
            raise CvValidationError("The PDF contains no pages")
        if len(reader.pages) > max_pages:
            raise CvValidationError(f"The PDF exceeds the {max_pages}-page limit")
        pages = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = normalize_extracted_text(page.extract_text() or "")
            except Exception as exc:
                raise CvValidationError(f"Page {page_number} could not be read") from exc
            pages.append({"page": page_number, "text": text})
        return pages
    except CvValidationError:
        raise
    except (PdfReadError, OSError, ValueError) as exc:
        raise CvValidationError("The PDF is corrupt or unreadable") from exc


def identify_sections(pages: list[dict]) -> dict[str, list[int]]:
    sections: dict[str, list[int]] = {name: [] for name in SECTION_HEADINGS}
    for page in pages:
        for line in str(page["text"]).splitlines():
            normalized = re.sub(r"[^a-z ]", "", line.casefold()).strip()
            for name, headings in SECTION_HEADINGS.items():
                if normalized in headings and page["page"] not in sections[name]:
                    sections[name].append(page["page"])
    return {name: page_numbers for name, page_numbers in sections.items() if page_numbers}


def _evidence_is_grounded(evidence: list[dict], page_text: dict[int, str]) -> bool:
    return bool(evidence) and all(
        item.get("method") in {"ai", "deterministic"}
        and isinstance(item.get("page"), int)
        and isinstance(item.get("quote"), str)
        and item["quote"] in page_text.get(item["page"], "")
        for item in evidence
    )


def ground_provider_draft(
    draft: CvProfileDraft, pages: list[dict]
) -> tuple[CvProfileDraft, list[str]]:
    """Remove every provider claim whose evidence is not an exact page excerpt."""
    page_text = {int(page["page"]): str(page["text"]) for page in pages}
    unsupported: list[str] = []

    def cleanse(value: Any, path: str, list_item: bool = False) -> Any:
        if isinstance(value, dict) and {"value", "confidence", "evidence"} <= value.keys():
            if value["value"] is None:
                return value
            if _evidence_is_grounded(value["evidence"], page_text):
                return value
            unsupported.append(path)
            if list_item:
                return None
            return {"value": None, "confidence": 0, "ambiguous": False, "evidence": []}
        if isinstance(value, dict):
            return {
                key: cleanse(item, f"{path}.{key}" if path else key) for key, item in value.items()
            }
        if isinstance(value, list):
            cleaned = [cleanse(item, f"{path}[{index}]", True) for index, item in enumerate(value)]
            return [item for item in cleaned if item is not None]
        return value

    return CvProfileDraft.model_validate(cleanse(draft.model_dump(), "")), unsupported


def normalize_draft(draft: CvProfileDraft) -> CvProfileDraft:
    data = draft.model_dump()
    for field in (
        "technical_skills",
        "soft_skills",
        "languages",
        "achievements",
        "citizenships",
        "preferred_locations",
        "preferred_titles",
        "preferred_industries",
        "workplace_preferences",
    ):
        items = data[field]
        seen: set[str] = set()
        normalized = []
        for item in items:
            item["value"] = re.sub(r"\s+", " ", item["value"]).strip()
            key = item["value"].casefold()
            if key and key not in seen:
                seen.add(key)
                normalized.append(item)
        data[field] = normalized
    phone = data["personal"]["phone"]
    if isinstance(phone["value"], str):
        phone["value"] = re.sub(r"(?<!^)\D", "", phone["value"].replace("00", "+", 1))
    calculated = calculate_experience_years(data["employment"])
    if calculated is not None:
        evidence = [
            evidence
            for job in data["employment"]
            for field in ("start_date", "end_date")
            for evidence in job[field]["evidence"]
        ][:10]
        data["calculated_years_experience"] = {
            "value": calculated,
            "confidence": 1,
            "ambiguous": False,
            "evidence": evidence,
        }
    return CvProfileDraft.model_validate(data)


def _month(value: object, default_month: int) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(19|20)\d{2}(?:-(0[1-9]|1[0-2]))?", value.strip())
    if not match:
        return None
    return int(value[:4]) * 12 + int(match.group(2) or default_month) - 1


def calculate_experience_years(employment: list[dict], today: date | None = None) -> float | None:
    current_month = (today or date.today()).year * 12 + (today or date.today()).month - 1
    months: set[int] = set()
    found_range = False
    for job in employment:
        start = _month(job["start_date"]["value"], 1)
        is_current = job["current"]["value"] is True
        end = current_month if is_current else _month(job["end_date"]["value"], 12)
        if start is None or end is None or end < start:
            continue
        found_range = True
        months.update(range(start, min(end, current_month) + 1))
    return round(len(months) / 12, 1) if found_range else None


def serialize_import(record: CvImport, storage: LocalCvStorage) -> CvImportRead:
    return CvImportRead.model_validate(
        {**record.__dict__, "file_available": storage.exists(record.storage_key)}
    )


def serialize_import_summary(record: CvImport, storage: LocalCvStorage) -> CvImportSummary:
    return CvImportSummary.model_validate(
        {**record.__dict__, "file_available": storage.exists(record.storage_key)}
    )


async def create_cv_import(
    db: Session,
    upload: UploadFile,
    user: User,
    settings: Settings,
    provider: CvExtractionProvider,
    storage: LocalCvStorage,
) -> CvImport:
    upload_rate_limiter.check(user.id, settings.cv_uploads_per_minute)
    try:
        filename = validate_upload_metadata(upload)
    except CvValidationError as exc:
        await upload.close()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    key: str | None = None
    try:
        key, size, digest, prefix = await storage.store(upload, settings.cv_max_upload_bytes)
        if not prefix.startswith(b"%PDF-"):
            raise CvValidationError("The file signature is not a PDF")
        pages = await run_in_threadpool(extract_pdf, storage.path_for(key), settings.cv_max_pages)
    except CvValidationError as exc:
        storage.delete(key)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    finally:
        await upload.close()
    record = CvImport(
        user_id=user.id,
        status=CvImportStatus.PDF_VALIDATED,
        original_filename=filename,
        storage_key=key,
        media_type="application/pdf",
        size_bytes=size,
        sha256=digest,
        page_count=len(pages),
        extracted_pages=pages,
        validation={"unsupported_claims": [], "scanned_likely": False, "user_edited": False},
    )
    db.add(record)
    db.flush()
    record.status = CvImportStatus.TEXT_EXTRACTED
    extracted_characters = sum(len(re.sub(r"\s", "", page["text"])) for page in pages)
    if extracted_characters < settings.cv_min_extracted_characters:
        record.validation = {**record.validation, "scanned_likely": True}
        write_audit(db, user.id, "cv_import.scanned_detected", "cv_import", record.id)
        return record
    record.sections = identify_sections(pages)
    try:
        draft, metadata = await run_in_threadpool(
            partial(provider.extract, pages=pages, sections=record.sections)
        )
    except AIProviderError as exc:
        storage.delete(key)
        db.delete(record)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CV extraction is temporarily unavailable. Please try again.",
        ) from exc
    grounded, unsupported = ground_provider_draft(draft, pages)
    record.draft = normalize_draft(grounded).model_dump(mode="json")
    record.validation = {**record.validation, "unsupported_claims": unsupported}
    record.model_metadata = metadata.__dict__
    record.status = CvImportStatus.PROFILE_PARSED
    record.status = CvImportStatus.AWAITING_REVIEW
    write_audit(
        db,
        user.id,
        "cv_import.created",
        "cv_import",
        record.id,
        {"status": record.status.value, "page_count": record.page_count, "size_bytes": size},
    )
    return record


def get_owned_import(db: Session, import_id: str, user_id: str, lock: bool = False) -> CvImport:
    query = select(CvImport).where(CvImport.id == import_id, CvImport.user_id == user_id)
    if lock:
        query = query.with_for_update()
    record = db.scalar(query)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV import not found")
    return record


def update_cv_draft(db: Session, record: CvImport, draft: CvProfileDraft, user: User) -> CvImport:
    if record.status != CvImportStatus.AWAITING_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This CV draft is not editable"
        )
    sanitized, user_fields = sanitize_review_draft(
        draft, record.extracted_pages, record.draft or {}
    )
    record.draft = normalize_draft(sanitized).model_dump(mode="json")
    record.validation = {
        **record.validation,
        "user_edited": True,
        "user_confirmed_fields": user_fields,
    }
    write_audit(db, user.id, "cv_import.draft_updated", "cv_import", record.id)
    return record


def sanitize_review_draft(
    draft: CvProfileDraft, pages: list[dict], original: dict | None = None
) -> tuple[CvProfileDraft, list[str]]:
    """Relabel non-grounded review values as explicit user assertions."""
    page_text = {int(page["page"]): str(page["text"]) for page in pages}
    user_fields: list[str] = []

    def sanitize(value: Any, path: str, previous: Any = None) -> Any:
        if isinstance(value, dict) and {"value", "confidence", "evidence"} <= value.keys():
            changed = not isinstance(previous, dict) or previous.get("value") != value["value"]
            if value["value"] is None or (
                not changed and _evidence_is_grounded(value["evidence"], page_text)
            ):
                return value
            user_fields.append(path)
            value["evidence"] = [
                {
                    "page": 1,
                    "quote": "User-confirmed during CV review",
                    "method": "user",
                }
            ]
            value["confidence"] = 1
            if "ambiguous" in value:
                value["ambiguous"] = False
            return value
        if isinstance(value, dict):
            return {
                key: sanitize(
                    item,
                    f"{path}.{key}" if path else key,
                    previous.get(key) if isinstance(previous, dict) else None,
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                sanitize(
                    item,
                    f"{path}[{index}]",
                    previous[index]
                    if isinstance(previous, list) and index < len(previous)
                    else None,
                )
                for index, item in enumerate(value)
            ]
        return value

    return CvProfileDraft.model_validate(
        sanitize(draft.model_dump(), "", original or {})
    ), user_fields


def _value(field: dict) -> Any:
    return field.get("value")


def compare_import(db: Session, record: CvImport, user: User) -> CvComparison:
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    if not profile or not record.draft:
        return CvComparison(profile_exists=bool(profile), conflicts=[], additions=[])
    draft = record.draft
    mappings = {
        "full_name": _value(draft["personal"]["full_name"]),
        "email": _value(draft["personal"]["email"]),
        "phone": _value(draft["personal"]["phone"]),
        "professional_summary": _value(draft["professional_summary"]),
    }
    conflicts = [
        CvConflict(field=field, existing=getattr(profile, field), imported=imported)
        for field, imported in mappings.items()
        if imported not in (None, "")
        and getattr(profile, field) not in (None, "")
        and str(getattr(profile, field)).casefold() != str(imported).casefold()
    ]
    existing_skills = {skill.name.casefold() for skill in profile.skills}
    additions = [
        f"skills.{item['value']}"
        for item in draft["technical_skills"]
        if item["value"].casefold() not in existing_skills
    ]
    return CvComparison(profile_exists=True, conflicts=conflicts, additions=additions)


def _bool_value(field: dict, default: bool) -> bool:
    return field["value"] if isinstance(field.get("value"), bool) else default


def _profile_values(draft: dict) -> dict:
    personal = draft["personal"]
    full_name = _value(personal["full_name"])
    email = _value(personal["email"])
    if not isinstance(full_name, str) or not full_name.strip() or len(full_name) > 200:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A valid full name and email are required before the profile can be saved",
        )
    try:
        validated_email = str(TypeAdapter(EmailStr).validate_python(email))
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A valid email is required before the profile can be saved",
        ) from exc
    phone = _value(personal["phone"])
    if phone is not None and (not isinstance(phone, str) or len(phone) > 64):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The reviewed phone number is too long",
        )
    return {
        "full_name": full_name,
        "email": validated_email,
        "phone": phone,
        "professional_summary": _value(draft["professional_summary"]),
        "citizenships": [item["value"] for item in draft["citizenships"]],
        "eu_work_authorized": _value(personal["work_authorization"]) is True,
        "requires_sponsorship": _bool_value(draft["requires_sponsorship"], True),
        "preferred_titles": [item["value"] for item in draft["preferred_titles"]],
        "preferred_locations": [item["value"] for item in draft["preferred_locations"]],
        "preferred_industries": [item["value"] for item in draft["preferred_industries"]],
        "total_years_experience": _numeric_years(
            _value(draft["calculated_years_experience"])
            or _value(draft["declared_years_experience"])
        ),
        "workplace_preferences": [item["value"] for item in draft["workplace_preferences"]],
        "relocation_available": _bool_value(draft["relocation_available"], False),
    }


def _numeric_years(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return min(60, max(0, float(value)))
    if isinstance(value, str):
        match = re.search(r"\d+(?:\.\d+)?", value)
        if match:
            return min(60, float(match.group()))
    return None


def _profile_children(
    draft: dict,
) -> tuple[list[ProfileSkill], list[ProfileLanguage], list[EmploymentEntry]]:
    skills = [
        ProfileSkill(name=item["value"])
        for item in draft["technical_skills"]
        if len(item["value"]) <= 120
    ]
    languages = [
        ProfileLanguage(language=item["value"], proficiency="unspecified")
        for item in draft["languages"]
        if len(item["value"]) <= 80
    ]
    employment = []
    for item in draft["employment"]:
        company, title = _value(item["company"]), _value(item["title"])
        if (
            not isinstance(company, str)
            or not isinstance(title, str)
            or len(company) > 200
            or len(title) > 200
        ):
            continue
        employment.append(
            EmploymentEntry(
                company=company,
                title=title,
                start_date=_parse_date(_value(item["start_date"])),
                end_date=None
                if _value(item["current"]) is True
                else _parse_date(_value(item["end_date"])),
                highlights=[
                    entry["value"]
                    for entry in item["achievements"] + item["responsibilities"]
                    if len(entry["value"]) <= 500
                ][:20],
            )
        )
    return skills, languages, employment


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"((?:19|20)\d{2})(?:-(0[1-9]|1[0-2]))?", value)
    return date(int(match.group(1)), int(match.group(2) or 1), 1) if match else None


def confirm_cv_import(
    db: Session,
    record: CvImport,
    user: User,
    strategy: str,
    accept_conflicts: bool,
) -> tuple[CandidateProfile, ProfileVersion]:
    if record.status != CvImportStatus.AWAITING_REVIEW or record.draft is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="CV import is not ready to confirm"
        )
    comparison = compare_import(db, record, user)
    if strategy == "merge" and comparison.conflicts and not accept_conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Merge conflicts require explicit confirmation",
                "conflicts": [item.model_dump() for item in comparison.conflicts],
            },
        )
    values = _profile_values(record.draft)
    profile = db.scalar(
        select(CandidateProfile).where(CandidateProfile.user_id == user.id).with_for_update()
    )
    children = _profile_children(record.draft)
    if profile is None:
        profile = CandidateProfile(user_id=user.id, **values)
        profile.skills, profile.languages, profile.employment = children
        db.add(profile)
        db.flush()
    elif strategy == "replace":
        for field, value in values.items():
            setattr(profile, field, value)
        profile.skills, profile.languages, profile.employment = children
    else:
        for field, value in values.items():
            if getattr(profile, field) in (None, "", [], {}) and value not in (None, "", [], {}):
                setattr(profile, field, value)
        existing_skills = {item.name.casefold() for item in profile.skills}
        profile.skills.extend(
            item for item in children[0] if item.name.casefold() not in existing_skills
        )
        existing_languages = {item.language.casefold() for item in profile.languages}
        profile.languages.extend(
            item for item in children[1] if item.language.casefold() not in existing_languages
        )
        existing_jobs = {
            (item.company.casefold(), item.title.casefold(), item.start_date)
            for item in profile.employment
        }
        profile.employment.extend(
            item
            for item in children[2]
            if (item.company.casefold(), item.title.casefold(), item.start_date)
            not in existing_jobs
        )
    record.status = CvImportStatus.PROFILE_CONFIRMED
    next_version = (
        db.scalar(
            select(func.max(ProfileVersion.version)).where(ProfileVersion.profile_id == profile.id)
        )
        or 0
    ) + 1
    version = ProfileVersion(
        user_id=user.id,
        profile_id=profile.id,
        cv_import_id=record.id,
        version=next_version,
        strategy=strategy,
        snapshot=record.draft,
    )
    db.add(version)
    record.status = CvImportStatus.PROFILE_SAVED
    write_audit(
        db,
        user.id,
        "cv_import.profile_saved",
        "cv_import",
        record.id,
        {"strategy": strategy, "version": next_version, "explicit_confirmation": True},
    )
    return profile, version


def delete_cv_file(db: Session, record: CvImport, user: User, storage: LocalCvStorage) -> None:
    storage.delete(record.storage_key)
    record.storage_key = None
    record.file_deleted_at = datetime.now(UTC)
    write_audit(db, user.id, "cv_import.file_deleted", "cv_import", record.id)


def delete_cv_import(db: Session, record: CvImport, user: User, storage: LocalCvStorage) -> None:
    storage.delete(record.storage_key)
    write_audit(db, user.id, "cv_import.deleted", "cv_import", record.id)
    db.delete(record)


def purge_expired_files(db: Session, settings: Settings, storage: LocalCvStorage) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=settings.cv_retention_days)
    records = list(
        db.scalars(
            select(CvImport).where(CvImport.created_at < cutoff, CvImport.storage_key.is_not(None))
        )
    )
    for record in records:
        storage.delete(record.storage_key)
        record.storage_key = None
        record.file_deleted_at = datetime.now(UTC)
    return len(records)
