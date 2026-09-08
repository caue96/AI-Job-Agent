import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.cli.migrate_local_data import _backup, _sha256
from app.db import Base, build_engine
from app.models import CandidateProfile, ProfileSkill, Skill, User
from app.repositories import SqlAlchemyUnitOfWork


@pytest.mark.parametrize(
    "module",
    [
        "services.py",
        "cv.py",
        "discovery.py",
        "cover_letters.py",
        "cv_optimization.py",
        "main.py",
        "discovery_api.py",
        "cover_letter_api.py",
        "cv_optimization_api.py",
    ],
)
def test_business_modules_do_not_depend_on_sqlalchemy(module):
    source = (Path(__file__).parents[1] / "app" / module).read_text(encoding="utf-8")
    assert "from sqlalchemy" not in source
    assert "Depends(get_db)" not in source


def test_unit_of_work_commit_rollback_and_restart_persistence(tmp_path):
    database = tmp_path / "uow.db"
    engine = build_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        user = User(email="persistent@example.invalid")
        uow.add(user)
        uow.commit()
        user_id = user.id
        uow.add(User(email="rolled-back@example.invalid"))
        uow.rollback()
    engine.dispose()

    restarted = build_engine(f"sqlite:///{database}")
    with sessionmaker(restarted)() as session:
        assert session.get(User, user_id) is not None
        assert (
            session.scalar(select(User).where(User.email == "rolled-back@example.invalid")) is None
        )
    restarted.dispose()


def test_normalized_skill_rows_are_reused(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'skills.db'}")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        user = User(email="skills@example.invalid")
        session.add(user)
        session.flush()
        profile = CandidateProfile(user_id=user.id, full_name="A", email="a@example.com")
        profile.skills = [ProfileSkill(name="Python", proficiency="ADVANCED")]
        session.add(profile)
        uow = SqlAlchemyUnitOfWork(session)
        uow.candidates.sync_skills(profile)
        session.flush()
        uow.candidates.sync_skills(profile)
        session.flush()
        assert session.scalar(select(Skill).where(Skill.normalized_name == "python"))
        assert session.scalar(select(ProfileSkill)).skill_id is not None
        assert len(list(session.scalars(select(Skill)))) == 1
    engine.dispose()


def test_legacy_backup_includes_committed_wal_data_and_passes_integrity_check(tmp_path):
    source = tmp_path / "legacy.db"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO records (value) VALUES ('preserved')")
        connection.commit()
        backup = _backup(source, tmp_path / "backups")
        assert backup.exists()
        assert len(_sha256(backup)) == 64
        with sqlite3.connect(backup) as restored:
            assert restored.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert restored.execute("SELECT value FROM records").fetchone() == ("preserved",)
