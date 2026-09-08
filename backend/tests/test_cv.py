from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.cv import (
    LocalCvStorage,
    calculate_experience_years,
    ground_provider_draft,
    normalize_draft,
    purge_expired_files,
    safe_original_filename,
)
from app.cv_ai import empty_draft, found, list_found
from app.cv_schemas import CvEmployment
from app.models import CvImport, CvImportStatus, User
from app.repositories import SqlAlchemyUnitOfWork


def test_grounding_removes_unsupported_provider_claims():
    draft = empty_draft()
    draft.personal.full_name = found("Invented Name", 1, "not in the page")
    draft.technical_skills = [list_found("Python", 1, "Python")]

    grounded, unsupported = ground_provider_draft(draft, [{"page": 1, "text": "Skills\nPython"}])

    assert grounded.personal.full_name.value is None
    assert [item.value for item in grounded.technical_skills] == ["Python"]
    assert unsupported == ["personal.full_name"]


def test_normalization_deduplicates_and_calculates_non_overlapping_experience():
    draft = empty_draft()
    draft.technical_skills = [
        list_found(" Python ", 1, "Python"),
        list_found("python", 1, "python"),
    ]
    for start, end in (("2020-01", "2021-12"), ("2021-01", "2022-12")):
        job = CvEmployment.model_validate(
            {
                "company": found("Example", 1, "Example"),
                "title": found("Engineer", 1, "Engineer"),
                "location": found("Remote", 1, "Remote"),
                "start_date": found(start, 1, start),
                "end_date": found(end, 1, end),
                "current": found(False, 1, end),
                "responsibilities": [],
                "achievements": [],
                "technologies": [],
            }
        )
        draft.employment.append(job)

    normalized = normalize_draft(draft)

    assert [item.value for item in normalized.technical_skills] == ["Python"]
    assert normalized.calculated_years_experience.value == 3.0
    assert (
        calculate_experience_years(
            [item.model_dump() for item in normalized.employment], date(2023, 1, 1)
        )
        == 3.0
    )


def test_filename_sanitization_and_storage_key_path_guard(tmp_path):
    storage = LocalCvStorage(str(tmp_path))
    assert safe_original_filename("../../private/CV.pdf") == "CV.pdf"
    assert safe_original_filename("..\\private\\CV.pdf") == "CV.pdf"
    with pytest.raises(ValueError, match="Invalid stored file"):
        storage.path_for("../secret.pdf")


def test_upload_rate_limiter_is_database_backed_and_per_user(client):
    client.get("/v1/cv-imports")
    db = client.app.state.test_session
    first = User(email="rate-one@example.invalid")
    second = User(email="rate-two@example.invalid")
    db.add_all([first, second])
    db.flush()
    repository = SqlAlchemyUnitOfWork(db).cvs
    now = datetime(2026, 7, 12)
    assert repository.record_upload_attempt(first.id, 1, now)
    assert repository.record_upload_attempt(second.id, 1, now)
    assert not repository.record_upload_attempt(first.id, 1, now + timedelta(seconds=30))
    assert repository.record_upload_attempt(first.id, 1, now + timedelta(seconds=61))
    db.rollback()


def test_retention_deletes_only_file_and_preserves_import_record(client):
    client.get("/v1/cv-imports")
    db = client.app.state.test_session
    user = User(email="retention@example.invalid")
    db.add(user)
    db.flush()
    storage = client.app.state.test_cv_storage
    key = "a" * 32 + ".pdf"
    storage.path_for(key).write_bytes(b"%PDF-old")
    record = CvImport(
        user_id=user.id,
        status=CvImportStatus.TEXT_EXTRACTED,
        original_filename="old.pdf",
        storage_key=key,
        media_type="application/pdf",
        size_bytes=8,
        sha256="b" * 64,
        extracted_pages=[],
        sections={},
        validation={},
        model_metadata={},
        created_at=datetime.now() - timedelta(days=40),
    )
    db.add(record)
    db.commit()

    assert purge_expired_files(SqlAlchemyUnitOfWork(db), get_settings(), storage) == 1
    db.commit()

    assert db.scalar(select(CvImport).where(CvImport.id == record.id)) is not None
    assert not storage.exists(key)
