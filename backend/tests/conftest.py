from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_job_agent.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import Base, build_engine, get_db
from app.main import app


@pytest.fixture()
def client(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'test.db'}")
    TestingSessionLocal = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = TestingSessionLocal()
        app.state.test_session = db
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.state.test_engine = engine
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
