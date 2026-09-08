"""Safely copy a legacy SQLite database into the authoritative PostgreSQL schema."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import SQLAlchemyError

from alembic import command
from app.config import get_settings

EXCLUDED_TABLES = {
    "alembic_version",
    "local_data_migration_errors",
    "local_data_migration_runs",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup(source: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"{source.name}.{stamp}.{uuid.uuid4().hex[:8]}.bak"
    try:
        with (
            sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as source_db,
            sqlite3.connect(destination) as backup_db,
        ):
            source_db.backup(backup_db)
            result = backup_db.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error:
        destination.unlink(missing_ok=True)
        raise RuntimeError("SQLite backup failed integrity validation") from None
    if result != ("ok",):
        destination.unlink(missing_ok=True)
        raise RuntimeError("SQLite backup failed integrity validation")
    return destination


def _upgrade_target(database_url: str) -> None:
    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _identifier(table: sa.Table, row: dict[str, Any]) -> str | None:
    values = [str(row[column.name]) for column in table.primary_key if row.get(column.name)]
    return ":".join(values)[:255] or None


def _safe_error(exc: Exception) -> str:
    code = getattr(getattr(exc, "orig", None), "sqlstate", None)
    return f"{type(exc).__name__}{f' ({code})' if code else ''}"[:500]


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _skill_id(target: sa.Connection, target_meta: sa.MetaData, display_name: str) -> str:
    skills = target_meta.tables["skills"]
    normalized_name = _normalized(display_name)
    existing = target.execute(
        sa.select(skills.c.id).where(skills.c.normalized_name == normalized_name)
    ).scalar_one_or_none()
    if existing:
        return str(existing)
    identifier = str(uuid.uuid4())
    target.execute(
        postgres_insert(skills)
        .values(
            id=identifier,
            normalized_name=normalized_name,
            display_name=display_name.strip(),
        )
        .on_conflict_do_nothing(index_elements=[skills.c.normalized_name])
    )
    return str(
        target.execute(
            sa.select(skills.c.id).where(skills.c.normalized_name == normalized_name)
        ).scalar_one()
    )


def _prepare_values(
    source_table: sa.Table,
    source_row: sa.RowMapping,
    target_columns: set[str],
    target: sa.Connection,
    target_meta: sa.MetaData,
) -> dict[str, Any]:
    values = {key: value for key, value in source_row.items() if key in target_columns}
    if source_table.name == "profile_skills":
        display_name = str(source_row["name"])
        values["normalized_name"] = _normalized(display_name)
        values["skill_id"] = _skill_id(target, target_meta, display_name)
    return values


def _copy_tables(
    source: sa.Connection,
    target: sa.Connection,
    source_meta: sa.MetaData,
    target_meta: sa.MetaData,
    run_id: str,
) -> tuple[dict[str, dict[str, int]], int]:
    report: dict[str, dict[str, int]] = {}
    rejected = 0
    errors = target_meta.tables["local_data_migration_errors"]
    for source_table in source_meta.sorted_tables:
        if source_table.name in EXCLUDED_TABLES or source_table.name not in target_meta.tables:
            continue
        target_table = target_meta.tables[source_table.name]
        target_columns = {column.name for column in target_table.columns}
        counts = {"read": 0, "inserted": 0, "existing": 0, "rejected": 0}
        for source_row in source.execute(sa.select(source_table)).mappings():
            counts["read"] += 1
            values = _prepare_values(source_table, source_row, target_columns, target, target_meta)
            savepoint = target.begin_nested()
            try:
                result = target.execute(
                    postgres_insert(target_table).values(**values).on_conflict_do_nothing()
                )
                savepoint.commit()
                counts["inserted" if result.rowcount else "existing"] += 1
            except SQLAlchemyError as exc:
                savepoint.rollback()
                counts["rejected"] += 1
                rejected += 1
                target.execute(
                    errors.insert().values(
                        id=str(uuid.uuid4()),
                        migration_run_id=run_id,
                        table_name=source_table.name,
                        record_identifier=_identifier(source_table, dict(source_row)),
                        reason=_safe_error(exc),
                    )
                )
        report[source_table.name] = counts
    return report, rejected


def _reconcile_normalized_records(
    target: sa.Connection, target_meta: sa.MetaData
) -> dict[str, int]:
    """Derive new relational records after legacy rows have been copied."""
    versions = target_meta.tables["job_versions"]
    requirements = target_meta.tables["job_requirements"]
    jobs = target_meta.tables["jobs"]
    stored_files = target_meta.tables["stored_files"]
    counts = {"job_versions": 0, "job_requirements": 0, "stored_files": 0}

    existing_jobs = sa.select(versions.c.job_id)
    for job in target.execute(sa.select(jobs).where(~jobs.c.id.in_(existing_jobs))).mappings():
        version_id = str(uuid.uuid4())
        required = job.get("requirements") or []
        preferred = job.get("preferred_qualifications") or []
        target.execute(
            versions.insert().values(
                id=version_id,
                job_id=job["id"],
                version=1,
                content_hash=job["content_hash"],
                snapshot={
                    "title": job["title"],
                    "company": job["company"],
                    "description": job["description"],
                    "requirements": required,
                    "preferred_qualifications": preferred,
                    "required_skills": job.get("required_skills") or [],
                    "preferred_skills": job.get("preferred_skills") or [],
                },
            )
        )
        counts["job_versions"] += 1
        for kind, items in (("REQUIRED", required), ("PREFERRED", preferred)):
            for index, item in enumerate(items):
                target.execute(
                    requirements.insert().values(
                        id=str(uuid.uuid4()),
                        job_version_id=version_id,
                        kind=kind,
                        text=str(item),
                        normalized_text=_normalized(str(item)),
                        display_order=index,
                    )
                )
                counts["job_requirements"] += 1

    existing_keys = sa.select(stored_files.c.storage_key)
    imports = target_meta.tables["cv_imports"]
    for row in target.execute(
        sa.select(imports).where(
            imports.c.storage_key.is_not(None),
            ~imports.c.storage_key.in_(existing_keys),
        )
    ).mappings():
        target.execute(
            stored_files.insert().values(
                id=str(uuid.uuid4()),
                owner_id=row["user_id"],
                cv_import_id=row["id"],
                storage_key=row["storage_key"],
                original_filename=row["original_filename"],
                media_type=row["media_type"],
                size_bytes=row["size_bytes"],
                sha256=row["sha256"],
                retention_status="DELETED" if row["file_deleted_at"] else "ACTIVE",
                deleted_at=row["file_deleted_at"],
            )
        )
        counts["stored_files"] += 1

    cv_exports = target_meta.tables["cv_exports"]
    variant_versions = target_meta.tables["cv_variant_versions"]
    variants = target_meta.tables["cv_variants"]
    cv_query = (
        sa.select(cv_exports, variants.c.user_id)
        .join(variant_versions, variant_versions.c.id == cv_exports.c.variant_version_id)
        .join(variants, variants.c.id == variant_versions.c.variant_id)
        .where(~cv_exports.c.storage_key.in_(existing_keys))
    )
    for row in target.execute(cv_query).mappings():
        _insert_export_file(target, stored_files, row, "cv_export_id", "cv")
        counts["stored_files"] += 1

    document_exports = target_meta.tables["document_exports"]
    documents = target_meta.tables["generated_documents"]
    applications = target_meta.tables["applications"]
    document_query = (
        sa.select(document_exports, applications.c.user_id)
        .join(documents, documents.c.id == document_exports.c.generated_document_id)
        .join(applications, applications.c.id == documents.c.application_id)
        .where(~document_exports.c.storage_key.in_(existing_keys))
    )
    for row in target.execute(document_query).mappings():
        _insert_export_file(target, stored_files, row, "document_export_id", "application")
        counts["stored_files"] += 1
    return counts


def _insert_export_file(
    target: sa.Connection,
    stored_files: sa.Table,
    row: sa.RowMapping,
    relation: str,
    filename_prefix: str,
) -> None:
    media_type = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(str(row["format"]).casefold(), "application/octet-stream")
    target.execute(
        stored_files.insert().values(
            id=str(uuid.uuid4()),
            owner_id=row["user_id"],
            **{relation: row["id"]},
            storage_key=row["storage_key"],
            original_filename=f"{filename_prefix}-{row['id']}.{row['format']}",
            media_type=media_type,
            size_bytes=row["size_bytes"],
            sha256=row["sha256"],
            retention_status="ACTIVE",
        )
    )


def migrate(source_path: Path, database_url: str, backup_dir: Path) -> dict[str, Any]:
    source = source_path.resolve(strict=True)
    if not source.is_file():
        raise ValueError("The SQLite source must be a regular file")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("The migration target must be PostgreSQL")
    backup = _backup(source, backup_dir.resolve())
    checksum = _sha256(backup)
    _upgrade_target(database_url)

    source_engine = sa.create_engine(sa.URL.create("sqlite", database=str(source)))
    target_engine = sa.create_engine(database_url, pool_pre_ping=True)
    source_meta, target_meta = sa.MetaData(), sa.MetaData()
    with source_engine.connect() as source_connection, target_engine.begin() as target:
        source_meta.reflect(bind=source_connection)
        target_meta.reflect(bind=target)
        runs = target_meta.tables["local_data_migration_runs"]
        existing = (
            target.execute(sa.select(runs).where(runs.c.source_sha256 == checksum))
            .mappings()
            .first()
        )
        if existing:
            return {
                "status": "ALREADY_MIGRATED",
                "run_id": existing["id"],
                "source_sha256": checksum,
                "backup": backup.name,
                "table_counts": existing["table_counts"],
                "rejected_count": existing["rejected_count"],
                "source_preserved": True,
            }
        run_id = str(uuid.uuid4())
        target.execute(
            runs.insert().values(
                id=run_id,
                source_name=source.name,
                source_sha256=checksum,
                backup_name=backup.name,
                status="RUNNING",
                table_counts={},
                rejected_count=0,
            )
        )
        table_counts, rejected = _copy_tables(
            source_connection, target, source_meta, target_meta, run_id
        )
        table_counts["_reconciled"] = _reconcile_normalized_records(target, target_meta)
        status = "COMPLETED_WITH_REJECTIONS" if rejected else "COMPLETED"
        target.execute(
            runs.update()
            .where(runs.c.id == run_id)
            .values(
                status=status,
                table_counts=table_counts,
                rejected_count=rejected,
                completed_at=datetime.now(UTC),
            )
        )
    return {
        "status": status,
        "run_id": run_id,
        "source_sha256": checksum,
        "backup": backup.name,
        "table_counts": table_counts,
        "rejected_count": rejected,
        "source_preserved": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Back up and migrate a legacy AI Job Agent SQLite database to PostgreSQL"
    )
    parser.add_argument("source", type=Path, help="Path to the legacy SQLite database")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="Authoritative PostgreSQL URL (defaults to DATABASE_URL)",
    )
    parser.add_argument("--backup-dir", type=Path, default=Path("./data/migration_backups"))
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    try:
        report = migrate(args.source, args.database_url, args.backup_dir)
    except (OSError, RuntimeError, ValueError, SQLAlchemyError) as exc:
        parser.exit(1, f"Migration failed safely: {_safe_error(exc)}\n")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
