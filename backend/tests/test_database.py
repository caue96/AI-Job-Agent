from unittest.mock import MagicMock

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import db as db_module
from app.db import get_db
from app.main import app
from app.models import Application


def test_sqlite_foreign_keys_are_enforced(client):
    session = Session(app.state.test_engine)
    session.add(Application(user_id="missing-user", job_id="missing-job"))

    try:
        with pytest.raises(IntegrityError):
            session.flush()
    finally:
        session.rollback()
        session.close()


def test_job_fingerprint_indexes_are_unique(client):
    indexes = {index["name"]: index for index in inspect(app.state.test_engine).get_indexes("jobs")}

    assert indexes["ix_jobs_normalized_url"]["unique"] == 1
    assert indexes["ix_jobs_content_hash"]["unique"] == 1


def test_request_session_rolls_back_on_unhandled_error(monkeypatch):
    session = MagicMock(spec=Session)
    monkeypatch.setattr(db_module, "SessionLocal", lambda: session)
    dependency = get_db()
    assert next(dependency) is session

    with pytest.raises(RuntimeError, match="failed request"):
        dependency.throw(RuntimeError("failed request"))

    session.rollback.assert_called_once()
    session.close.assert_called_once()
