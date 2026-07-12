from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Job, User
from app.schemas import ApplicationCreate, JobCreate, ProfileCreate
from app.services import create_application, create_job, create_profile, current_development_user


def integrity_error() -> IntegrityError:
    return IntegrityError("INSERT", {}, RuntimeError("unique constraint"))


def test_create_job_translates_a_concurrent_duplicate_to_conflict():
    db = MagicMock(spec=Session)
    db.execute.return_value.all.return_value = []
    db.flush.side_effect = integrity_error()
    payload = JobCreate(
        source="manual", company="Example", title="Engineer", description="Build systems."
    )

    with pytest.raises(HTTPException) as raised:
        create_job(db, payload, "user-1")

    assert raised.value.status_code == 409
    assert raised.value.detail == "Job duplicates an existing vacancy"
    db.rollback.assert_called_once()


def test_create_application_translates_a_concurrent_duplicate_to_conflict():
    db = MagicMock(spec=Session)
    db.get.return_value = Job()
    db.scalar.return_value = None
    db.flush.side_effect = integrity_error()
    user = User(id="user-1", email="local@example.invalid")

    with pytest.raises(HTTPException) as raised:
        create_application(db, ApplicationCreate(job_id="job-1"), user)

    assert raised.value.status_code == 409
    assert raised.value.detail == "Application already exists for this job"
    db.rollback.assert_called_once()


def test_local_user_bootstrap_recovers_from_a_concurrent_insert():
    db = MagicMock(spec=Session)
    winner = User(id="user-1", email="local@example.invalid")
    db.scalar.side_effect = [None, winner]
    db.flush.side_effect = integrity_error()

    result = current_development_user(db)

    assert result is winner
    db.rollback.assert_called_once()


def test_create_profile_translates_a_concurrent_duplicate_to_conflict():
    db = MagicMock(spec=Session)
    db.scalar.return_value = None
    db.flush.side_effect = integrity_error()
    user = User(id="user-1", email="local@example.invalid")

    with pytest.raises(HTTPException) as raised:
        create_profile(
            db,
            ProfileCreate(full_name="Ana Silva", email="ana@example.com"),
            user,
        )

    assert raised.value.status_code == 409
    assert raised.value.detail == "Profile already exists"
    db.rollback.assert_called_once()
