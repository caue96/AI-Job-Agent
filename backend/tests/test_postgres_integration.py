from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.cli.migrate_local_data import migrate
from app.config import get_settings
from app.db import build_engine
from app.models import (
    CandidateProfile,
    CvImport,
    CvImportStatus,
    DiscoveryMatchResult,
    DiscoveryRunStatus,
    DiscoverySearchConfiguration,
    DiscoverySearchRun,
    JobVersion,
    MatchScoreComponent,
    MatchVersion,
    ProfileSkill,
    ProfileVersion,
    Skill,
    User,
)
from app.repositories import SqlAlchemyUnitOfWork
from app.schemas import JobCreate, ProfileCreate, SkillInput
from app.services import create_job, create_profile

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")


@pytest.fixture(scope="module")
def postgres_engine():
    assert POSTGRES_URL is not None
    database = urlsplit(POSTGRES_URL.replace("postgresql+psycopg", "postgresql")).path
    if not database.rstrip("/").endswith("test"):
        pytest.fail("TEST_POSTGRES_URL must target a database whose name ends in 'test'")
    engine = build_engine(POSTGRES_URL)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA public CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    os.environ["DATABASE_URL"] = POSTGRES_URL
    get_settings.cache_clear()
    command.upgrade(config, "head")
    command.downgrade(config, "20260721_0011")
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


def test_migrations_constraints_jsonb_and_rollback(postgres_engine):
    inspector = sa.inspect(postgres_engine)
    assert inspector.get_table_names()
    requirements_type = next(
        column["type"]
        for column in inspector.get_columns("jobs")
        if column["name"] == "requirements"
    )
    assert isinstance(requirements_type, JSONB)

    with Session(postgres_engine) as session:
        user = User(email="postgres@example.invalid")
        session.add(user)
        session.flush()
        profile = CandidateProfile(
            user_id=user.id,
            full_name="Postgres Candidate",
            email="postgres@example.invalid",
            common_answers={"availability": {"value": "immediate"}},
        )
        session.add(profile)
        session.commit()
        profile_id = profile.id
        with pytest.raises(IntegrityError):
            session.add(
                ProfileSkill(
                    profile_id=profile_id,
                    skill_id="missing-skill",
                    name="Missing",
                    normalized_name="missing",
                    proficiency="BASIC",
                )
            )
            session.commit()
        session.rollback()
        assert (
            session.scalar(
                sa.select(CandidateProfile.id).where(
                    CandidateProfile.common_answers.op("@>")(
                        {"availability": {"value": "immediate"}}
                    )
                )
            )
            == profile_id
        )
        session.add(Skill(normalized_name="rollback", display_name="Rollback"))
        session.flush()
        session.rollback()
        assert session.scalar(sa.select(Skill).where(Skill.normalized_name == "rollback")) is None


def test_unique_constraint_is_safe_under_concurrency_and_survives_restart(postgres_engine):
    def insert_profile(index: int) -> str:
        with Session(postgres_engine) as session:
            uow = SqlAlchemyUnitOfWork(session)
            user = User(email=f"concurrent-{index}@example.invalid")
            uow.add(user)
            uow.flush()
            create_profile(
                uow,
                ProfileCreate(
                    full_name=f"Concurrent {index}",
                    email=f"concurrent-{index}@example.invalid",
                    skills=[SkillInput(name="Power BI")],
                ),
                user,
            )
            uow.commit()
            return "inserted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(insert_profile, [1, 2]))
    assert outcomes == ["inserted", "inserted"]
    postgres_engine.dispose()
    restarted = build_engine(POSTGRES_URL)
    with Session(restarted) as session:
        assert (
            session.scalar(
                sa.select(sa.func.count())
                .select_from(Skill)
                .where(Skill.normalized_name == "power bi")
            )
            == 1
        )
    restarted.dispose()


def test_profile_job_and_explainable_match_survive_restart(postgres_engine):
    with Session(postgres_engine, expire_on_commit=False) as session:
        uow = SqlAlchemyUnitOfWork(session)
        user = User(email="restart-flow@example.invalid")
        uow.add(user)
        uow.flush()
        profile = create_profile(
            uow,
            ProfileCreate(
                full_name="Restart Candidate",
                email="restart-flow@example.invalid",
                skills=[SkillInput(name="Python")],
            ),
            user,
        )
        imported = CvImport(
            user_id=user.id,
            status=CvImportStatus.PROFILE_SAVED,
            original_filename="candidate.pdf",
            media_type="application/pdf",
            size_bytes=123,
            sha256="a" * 64,
            extracted_pages=[],
            sections={},
            validation={},
            model_metadata={},
        )
        uow.add(imported)
        uow.flush()
        profile_version = ProfileVersion(
            user_id=user.id,
            profile_id=profile.id,
            cv_import_id=imported.id,
            version=2,
            strategy="replace",
            snapshot={"skills": [{"name": {"value": "Python"}}]},
        )
        uow.add(profile_version)
        job = create_job(
            uow,
            JobCreate(
                source="manual",
                external_job_id="restart-job",
                company="Persistence Ltd",
                title="Data Engineer",
                description="Build reliable Python data services.",
                requirements=["Python"],
            ),
            user.id,
        )
        configuration = DiscoverySearchConfiguration(user_id=user.id, name="Restart test")
        uow.add(configuration)
        uow.flush()
        run = DiscoverySearchRun(
            user_id=user.id,
            configuration_id=configuration.id,
            status=DiscoveryRunStatus.SUCCEEDED,
            trigger="TEST",
            counters={"new_jobs": 1},
        )
        uow.add(run)
        uow.flush()
        result = DiscoveryMatchResult(
            user_id=user.id,
            run_id=run.id,
            job_id=job.id,
            score=92,
            recommendation="STRONG_MATCH",
            hard_rejected=False,
            rejection_reasons=[],
            analysis={"matching_skills": ["Python"]},
        )
        uow.add(result)
        uow.flush()
        job_version = uow.jobs.latest_version(job.id)
        assert job_version is not None
        match_version = uow.matches.save_explainable(
            result=result,
            profile_version=profile_version,
            job_version=job_version,
            analysis={
                "confidence": 0.9,
                "matching_skills": ["Python"],
                "score_by_category": {
                    "skills": {
                        "score": 25,
                        "maximum": 25,
                        "explanation": "Candidate has Python.",
                    }
                },
            },
            engine_version="restart-test-v1",
        )
        uow.commit()
        ids = (profile.id, job.id, match_version.id)

    postgres_engine.dispose()
    restarted = build_engine(POSTGRES_URL)
    with Session(restarted) as session:
        assert session.get(CandidateProfile, ids[0]) is not None
        assert session.scalar(sa.select(JobVersion).where(JobVersion.job_id == ids[1]))
        assert session.get(MatchVersion, ids[2]) is not None
        assert session.scalar(
            sa.select(MatchScoreComponent).where(MatchScoreComponent.match_version_id == ids[2])
        )
    restarted.dispose()


def test_local_sqlite_migration_is_backed_up_reported_and_idempotent(postgres_engine, tmp_path):
    source = tmp_path / "legacy.db"
    with sqlite3.connect(source) as connection:
        connection.execute(
            "CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, email VARCHAR(320) NOT NULL, "
            "password_hash VARCHAR(255), created_at DATETIME)"
        )
        connection.execute(
            "INSERT INTO users VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            ("legacy-user", "legacy@example.invalid", None),
        )
    first = migrate(source, POSTGRES_URL, tmp_path / "backups")
    second = migrate(source, POSTGRES_URL, tmp_path / "backups")
    assert first["status"] == "COMPLETED"
    assert first["table_counts"]["users"]["inserted"] == 1
    assert second["status"] == "ALREADY_MIGRATED"
    assert source.exists()
    assert list((tmp_path / "backups").glob("*.bak"))
    with Session(postgres_engine) as session:
        assert session.get(User, "legacy-user").email == "legacy@example.invalid"
