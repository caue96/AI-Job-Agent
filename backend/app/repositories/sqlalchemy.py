"""SQLAlchemy/PostgreSQL repository adapters.

Only this module and database bootstrap/migration code construct SQLAlchemy queries for application
persistence. Services consume the repository protocols from ``contracts``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.matching import extracted_skills
from app.models import (
    Application,
    ApplicationStatusHistory,
    AuditLog,
    CandidateAchievement,
    CandidateCertification,
    CandidateEducation,
    CandidateProfile,
    CandidateProject,
    CandidateProjectSkill,
    CvAnalysisRun,
    CvExport,
    CvImport,
    CvRecommendation,
    CvRecommendationDecisionValue,
    CvRecommendationEvidence,
    CvVariant,
    CvVariantVersion,
    DiscoveryJobSource,
    DiscoveryMatchResult,
    DiscoveryNotification,
    DiscoveryProviderCursor,
    DiscoveryProviderError,
    DiscoveryProviderRun,
    DiscoverySearchConfiguration,
    DiscoverySearchProfile,
    DiscoverySearchRun,
    DocumentExport,
    EmploymentEntry,
    GeneratedDocument,
    GeneratedDocumentStatus,
    Job,
    JobProvider,
    JobRequirement,
    JobSkill,
    JobSkillKind,
    JobVersion,
    MatchBlocker,
    MatchEvidence,
    MatchRecommendationDecision,
    MatchScoreComponent,
    MatchSkill,
    MatchSkillKind,
    MatchVersion,
    ProfileVersion,
    Skill,
    StoredFile,
    UploadRateLimitEvent,
    User,
    UserProviderConfiguration,
    uuid_str,
)
from app.repositories.contracts import PersistenceConflict


def _get_or_create_skill_id(session: Session, name: str) -> str:
    display_name = name.strip()
    normalized = display_name.casefold()
    with session.no_autoflush:
        existing = session.scalar(select(Skill.id).where(Skill.normalized_name == normalized))
        if existing:
            return str(existing)
        identifier = uuid_str()
        insert = (
            postgres_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
        )
        created = session.scalar(
            insert(Skill)
            .values(
                id=identifier,
                normalized_name=normalized,
                display_name=display_name,
            )
            .on_conflict_do_nothing(index_elements=[Skill.normalized_name])
            .returning(Skill.id)
        )
        if created:
            return str(created)
        return str(session.scalar(select(Skill.id).where(Skill.normalized_name == normalized)))


class SqlAlchemyCandidateRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_profile(self, user_id: str, *, lock: bool = False) -> CandidateProfile | None:
        statement = select(CandidateProfile).where(CandidateProfile.user_id == user_id)
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def latest_profile_version(self, user_id: str) -> ProfileVersion | None:
        return self.session.scalar(
            select(ProfileVersion)
            .where(ProfileVersion.user_id == user_id)
            .order_by(ProfileVersion.version.desc())
            .limit(1)
        )

    def get_profile_version(self, version_id: str, user_id: str) -> ProfileVersion | None:
        return self.session.scalar(
            select(ProfileVersion).where(
                ProfileVersion.id == version_id, ProfileVersion.user_id == user_id
            )
        )

    def list_profile_versions(self, user_id: str) -> list[ProfileVersion]:
        return list(
            self.session.scalars(
                select(ProfileVersion)
                .where(ProfileVersion.user_id == user_id)
                .order_by(ProfileVersion.version.desc())
            )
        )

    def next_profile_version(self, profile_id: str) -> int:
        current = self.session.scalar(
            select(func.max(ProfileVersion.version)).where(ProfileVersion.profile_id == profile_id)
        )
        return (current or 0) + 1

    def sync_skills(self, profile: CandidateProfile) -> None:
        for item in profile.skills:
            item.normalized_name = item.name.strip().casefold()
            item.skill_id = _get_or_create_skill_id(self.session, item.name)

    @staticmethod
    def _value(value: Any) -> Any:
        return value.get("value") if isinstance(value, dict) and "value" in value else value

    @classmethod
    def _date(cls, value: Any) -> date | None:
        raw = cls._value(value)
        if not raw:
            return None
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            return None

    def replace_extended_profile(self, profile_id: str, snapshot: dict[str, Any]) -> None:
        self.session.execute(
            delete(CandidateAchievement).where(CandidateAchievement.profile_id == profile_id)
        )
        self.session.execute(
            delete(CandidateProject).where(CandidateProject.profile_id == profile_id)
        )
        self.session.execute(
            delete(CandidateCertification).where(CandidateCertification.profile_id == profile_id)
        )
        self.session.execute(
            delete(CandidateEducation).where(CandidateEducation.profile_id == profile_id)
        )
        for index, item in enumerate(snapshot.get("education", [])):
            self.session.add(
                CandidateEducation(
                    profile_id=profile_id,
                    institution=str(self._value(item.get("institution")) or "Unknown"),
                    qualification=self._value(item.get("qualification")),
                    field_of_study=self._value(item.get("field_of_study")),
                    start_date=self._date(item.get("start_date")),
                    end_date=self._date(item.get("end_date")),
                    display_order=index,
                )
            )
        for index, item in enumerate(snapshot.get("certifications", [])):
            name = self._value(item.get("name"))
            if not name:
                continue
            self.session.add(
                CandidateCertification(
                    profile_id=profile_id,
                    name=str(name),
                    issuer=self._value(item.get("issuer")),
                    issued_date=self._date(item.get("issued_date")),
                    expiration_date=self._date(item.get("expiration_date")),
                    credential_url=self._value(item.get("credential_url")),
                    display_order=index,
                )
            )
        for index, item in enumerate(snapshot.get("projects", [])):
            name = self._value(item.get("name"))
            if not name:
                continue
            project = CandidateProject(
                profile_id=profile_id,
                name=str(name),
                description=self._value(item.get("description")),
                role=self._value(item.get("role")),
                url=self._value(item.get("url")),
                display_order=index,
            )
            self.session.add(project)
            self.session.flush()
            for technology in item.get("technologies", []):
                skill_name = self._value(technology)
                if skill_name:
                    self.session.add(
                        CandidateProjectSkill(
                            project_id=project.id,
                            skill_id=_get_or_create_skill_id(self.session, str(skill_name)),
                        )
                    )
            for order, achievement in enumerate(item.get("achievements", [])):
                text = self._value(achievement)
                if text:
                    self.session.add(
                        CandidateAchievement(
                            profile_id=profile_id,
                            project_id=project.id,
                            text=str(text),
                            display_order=order,
                        )
                    )
        for index, achievement in enumerate(snapshot.get("achievements", [])):
            text = self._value(achievement)
            if text:
                self.session.add(
                    CandidateAchievement(profile_id=profile_id, text=str(text), display_order=index)
                )
        employment_entries = list(
            self.session.scalars(
                select(EmploymentEntry)
                .where(EmploymentEntry.profile_id == profile_id)
                .order_by(EmploymentEntry.start_date, EmploymentEntry.id)
            )
        )
        for employment in snapshot.get("employment", []):
            company = str(self._value(employment.get("company")) or "").casefold()
            title = str(self._value(employment.get("title")) or "").casefold()
            start_date = self._date(employment.get("start_date"))
            parent = next(
                (
                    entry
                    for entry in employment_entries
                    if entry.company.casefold() == company
                    and entry.title.casefold() == title
                    and entry.start_date == start_date
                ),
                None,
            )
            if parent is None:
                continue
            for order, achievement in enumerate(employment.get("achievements", [])):
                achievement_text = self._value(achievement)
                if achievement_text:
                    self.session.add(
                        CandidateAchievement(
                            profile_id=profile_id,
                            employment_entry_id=parent.id,
                            text=str(achievement_text),
                            display_order=order,
                        )
                    )


class SqlAlchemyCvRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_import(self, import_id: str, user_id: str, *, lock: bool = False) -> CvImport | None:
        statement = select(CvImport).where(CvImport.id == import_id, CvImport.user_id == user_id)
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def list_imports(self, user_id: str) -> list[CvImport]:
        return list(
            self.session.scalars(
                select(CvImport)
                .where(CvImport.user_id == user_id)
                .order_by(CvImport.created_at.desc())
            )
        )

    def expired_imports(self, cutoff: datetime) -> list[CvImport]:
        return list(
            self.session.scalars(
                select(CvImport).where(
                    CvImport.created_at < cutoff, CvImport.storage_key.is_not(None)
                )
            )
        )

    def file_for_import(self, import_id: str) -> StoredFile | None:
        return self.session.scalar(select(StoredFile).where(StoredFile.cv_import_id == import_id))

    def record_upload_attempt(self, user_id: str, limit: int, now: datetime) -> bool:
        if self.session.bind and self.session.bind.dialect.name == "postgresql":
            self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": f"cv-upload:{user_id}"},
            )
        cutoff = now - timedelta(minutes=1)
        count = int(
            self.session.scalar(
                select(func.count())
                .select_from(UploadRateLimitEvent)
                .where(
                    UploadRateLimitEvent.user_id == user_id,
                    UploadRateLimitEvent.occurred_at >= cutoff,
                )
            )
            or 0
        )
        if count >= limit:
            return False
        self.session.add(UploadRateLimitEvent(user_id=user_id, occurred_at=now))
        self.session.flush()
        return True


class SqlAlchemyJobRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, job_id: str) -> Job | None:
        return self.session.get(Job, job_id)

    def list_jobs(self, *, limit: int = 100) -> list[Job]:
        return list(
            self.session.scalars(select(Job).order_by(Job.discovered_at.desc()).limit(limit))
        )

    def duplicate_candidates(
        self, source: str, external_id: str | None, normalized_url: str | None, content_hash: str
    ) -> list[tuple[str, str | None, str | None, str]]:
        conditions = [Job.content_hash == content_hash]
        if normalized_url:
            conditions.append(Job.normalized_url == normalized_url)
        if external_id:
            conditions.append((Job.source == source) & (Job.external_job_id == external_id))
        rows = self.session.execute(
            select(Job.source, Job.external_job_id, Job.normalized_url, Job.content_hash).where(
                or_(*conditions)
            )
        )
        return [tuple(row) for row in rows]

    def latest_version(self, job_id: str) -> JobVersion | None:
        return self.session.scalar(
            select(JobVersion)
            .where(JobVersion.job_id == job_id)
            .order_by(JobVersion.version.desc())
            .limit(1)
        )

    def next_version(self, job_id: str) -> int:
        value = self.session.scalar(
            select(func.max(JobVersion.version)).where(JobVersion.job_id == job_id)
        )
        return (value or 0) + 1

    def _skill(self, name: str) -> Skill:
        normalized = name.strip().casefold()
        skill = self.session.scalar(select(Skill).where(Skill.normalized_name == normalized))
        if skill is None:
            skill = Skill(normalized_name=normalized, display_name=name.strip())
            self.session.add(skill)
            self.session.flush()
        return skill

    def save_version(self, job: Job) -> JobVersion:
        current = self.session.scalar(
            select(JobVersion).where(
                JobVersion.job_id == job.id, JobVersion.content_hash == job.content_hash
            )
        )
        if current:
            return current
        snapshot = {
            "title": job.title,
            "normalized_title": job.normalized_title,
            "company": job.company,
            "description": job.description,
            "requirements": job.requirements,
            "preferred_qualifications": job.preferred_qualifications,
            "required_skills": job.required_skills,
            "preferred_skills": job.preferred_skills,
            "country": job.country,
            "city": job.city,
            "region": job.region,
            "workplace_type": job.workplace_type,
            "employment_type": job.employment_type,
            "seniority": job.seniority,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "salary_currency": job.salary_currency,
            "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        }
        version = JobVersion(
            job_id=job.id,
            version=self.next_version(job.id),
            content_hash=job.content_hash,
            snapshot=snapshot,
        )
        self.session.add(version)
        self.session.flush()
        requirement_groups = (
            (job.requirements, JobSkillKind.REQUIRED),
            (job.preferred_qualifications, JobSkillKind.PREFERRED),
        )
        for values, kind in requirement_groups:
            for index, requirement_text in enumerate(values):
                self.session.add(
                    JobRequirement(
                        job_version_id=version.id,
                        kind=kind,
                        text=requirement_text,
                        normalized_text=" ".join(requirement_text.casefold().split())[:500],
                        display_order=index,
                    )
                )
        skill_groups = (
            (
                job.required_skills or sorted(extracted_skills(job.requirements)),
                JobSkillKind.REQUIRED,
            ),
            (job.preferred_skills, JobSkillKind.PREFERRED),
        )
        for values, kind in skill_groups:
            for name in dict.fromkeys(values):
                skill = self._skill(name)
                self.session.add(JobSkill(job_version_id=version.id, skill_id=skill.id, kind=kind))
        return version


class SqlAlchemyApplicationRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_owned(
        self, application_id: str, user_id: str, *, lock: bool = False
    ) -> Application | None:
        statement = select(Application).where(
            Application.id == application_id, Application.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def get_for_job(self, user_id: str, job_id: str, *, lock: bool = False) -> Application | None:
        statement = select(Application).where(
            Application.user_id == user_id, Application.job_id == job_id
        )
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def list_owned(self, user_id: str) -> list[Application]:
        return list(
            self.session.scalars(
                select(Application)
                .where(Application.user_id == user_id)
                .order_by(Application.updated_at.desc())
            )
        )

    def list_history(self, application_id: str) -> list[ApplicationStatusHistory]:
        return list(
            self.session.scalars(
                select(ApplicationStatusHistory)
                .where(ApplicationStatusHistory.application_id == application_id)
                .order_by(ApplicationStatusHistory.created_at)
            )
        )

    def next_document_version(self, application_id: str) -> int:
        value = self.session.scalar(
            select(func.max(GeneratedDocument.version)).where(
                GeneratedDocument.application_id == application_id
            )
        )
        return (value or 0) + 1

    def list_documents(
        self, application_id: str, *, latest_valid: bool = False
    ) -> list[GeneratedDocument]:
        statement = select(GeneratedDocument).where(
            GeneratedDocument.application_id == application_id,
            GeneratedDocument.document_type == "APPLICATION_PACKAGE",
        )
        if latest_valid:
            statement = (
                statement.where(GeneratedDocument.status == GeneratedDocumentStatus.VALID)
                .order_by(GeneratedDocument.version.desc())
                .limit(1)
            )
        else:
            statement = statement.order_by(GeneratedDocument.version.desc())
        return list(self.session.scalars(statement))


class SqlAlchemyDiscoveryRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_search_profile(self, user_id: str) -> DiscoverySearchProfile | None:
        return self.session.scalar(
            select(DiscoverySearchProfile).where(DiscoverySearchProfile.user_id == user_id)
        )

    def list_configurations(self, user_id: str) -> list[DiscoverySearchConfiguration]:
        return list(
            self.session.scalars(
                select(DiscoverySearchConfiguration)
                .where(DiscoverySearchConfiguration.user_id == user_id)
                .order_by(DiscoverySearchConfiguration.created_at.desc())
            )
        )

    def get_configuration(
        self, configuration_id: str, user_id: str | None = None, *, lock: bool = False
    ) -> DiscoverySearchConfiguration | None:
        statement = select(DiscoverySearchConfiguration).where(
            DiscoverySearchConfiguration.id == configuration_id
        )
        if user_id is not None:
            statement = statement.where(DiscoverySearchConfiguration.user_id == user_id)
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def list_runs(self, user_id: str, limit: int) -> list[DiscoverySearchRun]:
        return list(
            self.session.scalars(
                select(DiscoverySearchRun)
                .where(DiscoverySearchRun.user_id == user_id)
                .order_by(DiscoverySearchRun.started_at.desc())
                .limit(limit)
            )
        )

    def scheduled_run_exists(self, scheduled_key: str) -> bool:
        return (
            self.session.scalar(
                select(DiscoverySearchRun.id).where(
                    DiscoverySearchRun.scheduled_key == scheduled_key
                )
            )
            is not None
        )

    def due_configurations(self, now: datetime) -> list[DiscoverySearchConfiguration]:
        return list(
            self.session.scalars(
                select(DiscoverySearchConfiguration)
                .where(
                    DiscoverySearchConfiguration.enabled.is_(True),
                    DiscoverySearchConfiguration.next_run_at.is_not(None),
                    DiscoverySearchConfiguration.next_run_at <= now,
                )
                .with_for_update(skip_locked=True)
            )
        )

    def provider_cursor(
        self, configuration_id: str, provider: str, *, lock: bool = False
    ) -> DiscoveryProviderCursor | None:
        statement = select(DiscoveryProviderCursor).where(
            DiscoveryProviderCursor.configuration_id == configuration_id,
            DiscoveryProviderCursor.provider == provider,
        )
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def list_provider_cursors(self, user_id: str) -> list[DiscoveryProviderCursor]:
        return list(
            self.session.scalars(
                select(DiscoveryProviderCursor)
                .join(DiscoverySearchConfiguration)
                .where(DiscoverySearchConfiguration.user_id == user_id)
            )
        )

    def list_provider_errors(
        self, user_id: str, *, limit: int = 50
    ) -> list[DiscoveryProviderError]:
        return list(
            self.session.scalars(
                select(DiscoveryProviderError)
                .join(
                    DiscoveryProviderRun,
                    DiscoveryProviderRun.id == DiscoveryProviderError.provider_run_id,
                )
                .join(DiscoverySearchRun, DiscoverySearchRun.id == DiscoveryProviderRun.run_id)
                .where(DiscoverySearchRun.user_id == user_id)
                .order_by(DiscoveryProviderError.created_at.desc())
                .limit(limit)
            )
        )

    def latest_match(self, user_id: str, job_id: str) -> DiscoveryMatchResult | None:
        return self.session.scalar(
            select(DiscoveryMatchResult)
            .where(DiscoveryMatchResult.user_id == user_id, DiscoveryMatchResult.job_id == job_id)
            .order_by(DiscoveryMatchResult.created_at.desc())
            .limit(1)
        )

    def match_for_run(self, run_id: str, job_id: str) -> DiscoveryMatchResult | None:
        return self.session.scalar(
            select(DiscoveryMatchResult).where(
                DiscoveryMatchResult.run_id == run_id, DiscoveryMatchResult.job_id == job_id
            )
        )

    def get_match(
        self, match_id: str, user_id: str, *, lock: bool = False
    ) -> DiscoveryMatchResult | None:
        statement = select(DiscoveryMatchResult).where(
            DiscoveryMatchResult.id == match_id, DiscoveryMatchResult.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def list_ranked_matches(
        self, user_id: str, filters: dict[str, Any]
    ) -> list[tuple[DiscoveryMatchResult, Job]]:
        statement = (
            select(DiscoveryMatchResult, Job)
            .join(Job, Job.id == DiscoveryMatchResult.job_id)
            .where(
                DiscoveryMatchResult.user_id == user_id,
                DiscoveryMatchResult.score >= filters.get("min_score", 0),
            )
        )
        if not filters.get("include_rejected", False):
            statement = statement.where(DiscoveryMatchResult.hard_rejected.is_(False))
        exact = {
            "country": Job.country,
            "provider": Job.source,
            "recommendation": DiscoveryMatchResult.recommendation,
        }
        for key, column in exact.items():
            value = filters.get(key)
            if value:
                statement = statement.where(
                    column == (value.upper() if key == "country" else value)
                )
        fuzzy = {
            "city": Job.city,
            "company": Job.company,
            "role": Job.title,
            "seniority": Job.seniority,
            "workplace_type": Job.workplace_type,
            "industry": Job.industry,
        }
        for key, column in fuzzy.items():
            value = filters.get(key)
            if value:
                pattern = f"%{value}%" if key in {"company", "role"} else value
                statement = statement.where(column.ilike(pattern))
        if filters.get("minimum_salary") is not None:
            minimum = filters["minimum_salary"]
            statement = statement.where(or_(Job.salary_max >= minimum, Job.salary_min >= minimum))
        if filters.get("posted_after"):
            statement = statement.where(Job.posted_at >= filters["posted_after"])
        return [
            (row[0], row[1])
            for row in self.session.execute(
                statement.order_by(DiscoveryMatchResult.score.desc(), Job.posted_at.desc()).limit(
                    filters.get("limit", 100)
                )
            )
        ]

    def notification_exists(self, user_id: str, key: str) -> bool:
        return (
            self.session.scalar(
                select(DiscoveryNotification.id).where(
                    DiscoveryNotification.user_id == user_id,
                    DiscoveryNotification.deduplication_key == key,
                )
            )
            is not None
        )

    def list_notifications(
        self, user_id: str, *, unread_only: bool = False
    ) -> list[DiscoveryNotification]:
        statement = select(DiscoveryNotification).where(DiscoveryNotification.user_id == user_id)
        if unread_only:
            statement = statement.where(DiscoveryNotification.read_at.is_(None))
        return list(
            self.session.scalars(
                statement.order_by(DiscoveryNotification.created_at.desc()).limit(100)
            )
        )

    def get_notification(self, notification_id: str, user_id: str) -> DiscoveryNotification | None:
        return self.session.scalar(
            select(DiscoveryNotification).where(
                DiscoveryNotification.id == notification_id,
                DiscoveryNotification.user_id == user_id,
            )
        )

    def job_source(self, provider: str, external_id: str | None) -> DiscoveryJobSource | None:
        return self.session.scalar(
            select(DiscoveryJobSource).where(
                DiscoveryJobSource.provider == provider,
                DiscoveryJobSource.external_job_id == external_id,
            )
        )

    def job_by_normalized_url(self, value: str) -> Job | None:
        return self.session.scalar(select(Job).where(Job.normalized_url == value))

    def job_by_content_hash(self, value: str) -> Job | None:
        return self.session.scalar(select(Job).where(Job.content_hash == value))

    def likely_job(self, company: str, title: str, city: str | None) -> Job | None:
        return self.session.scalar(
            select(Job).where(
                Job.company.ilike(company),
                Job.title.ilike(title),
                or_(Job.city == city, Job.city.is_(None)),
            )
        )

    def configuration_named(self, user_id: str, name: str) -> DiscoverySearchConfiguration | None:
        return self.session.scalar(
            select(DiscoverySearchConfiguration).where(
                DiscoverySearchConfiguration.user_id == user_id,
                DiscoverySearchConfiguration.name == name,
            )
        )

    def sync_provider_configurations(
        self, user_id: str, settings: dict[str, dict[str, Any]]
    ) -> None:
        for key, configuration in settings.items():
            provider = self.session.scalar(select(JobProvider).where(JobProvider.key == key))
            if provider is None:
                continue
            record = self.session.scalar(
                select(UserProviderConfiguration).where(
                    UserProviderConfiguration.user_id == user_id,
                    UserProviderConfiguration.provider_id == provider.id,
                )
            )
            if record is None:
                record = UserProviderConfiguration(user_id=user_id, provider_id=provider.id)
                self.session.add(record)
            record.enabled = bool(configuration.get("enabled"))
            record.configuration = {
                name: value for name, value in configuration.items() if name != "enabled"
            }


class SqlAlchemyRecommendationRepository:
    def __init__(self, session: Session):
        self.session = session

    def latest_analysis_inputs(
        self, user_id: str, job_id: str
    ) -> tuple[ProfileVersion | None, DiscoveryMatchResult | None]:
        profile = SqlAlchemyCandidateRepository(self.session).latest_profile_version(user_id)
        match = SqlAlchemyDiscoveryRepository(self.session).latest_match(user_id, job_id)
        return profile, match

    def get_analysis(
        self, analysis_id: str, user_id: str, *, lock: bool = False
    ) -> CvAnalysisRun | None:
        statement = select(CvAnalysisRun).where(
            CvAnalysisRun.id == analysis_id, CvAnalysisRun.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def list_analyses(self, user_id: str, job_id: str | None = None) -> list[CvAnalysisRun]:
        statement = select(CvAnalysisRun).where(CvAnalysisRun.user_id == user_id)
        if job_id:
            statement = statement.where(CvAnalysisRun.job_id == job_id)
        return list(
            self.session.scalars(statement.order_by(CvAnalysisRun.created_at.desc()).limit(100))
        )

    def recommendations(self, analysis_id: str) -> list[CvRecommendation]:
        return list(
            self.session.scalars(
                select(CvRecommendation)
                .where(CvRecommendation.analysis_run_id == analysis_id)
                .order_by(CvRecommendation.display_order)
            )
        )

    def recommendation_with_analysis(
        self, recommendation_id: str, user_id: str, *, lock: bool = False
    ) -> tuple[CvRecommendation, CvAnalysisRun] | None:
        statement = (
            select(CvRecommendation, CvAnalysisRun)
            .join(CvAnalysisRun)
            .where(CvRecommendation.id == recommendation_id, CvAnalysisRun.user_id == user_id)
        )
        if lock:
            statement = statement.with_for_update()
        row = self.session.execute(statement).one_or_none()
        return (row[0], row[1]) if row else None

    def evidence(self, recommendation_id: str) -> list[CvRecommendationEvidence]:
        return list(
            self.session.scalars(
                select(CvRecommendationEvidence).where(
                    CvRecommendationEvidence.recommendation_id == recommendation_id
                )
            )
        )

    def pending_recommendation_count(self, analysis_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(CvRecommendation)
                .where(
                    CvRecommendation.analysis_run_id == analysis_id,
                    CvRecommendation.decision == CvRecommendationDecisionValue.PENDING,
                )
            )
            or 0
        )

    def get_variant(self, variant_id: str, user_id: str) -> CvVariant | None:
        return self.session.scalar(
            select(CvVariant).where(CvVariant.id == variant_id, CvVariant.user_id == user_id)
        )

    def variant_for_analysis(self, user_id: str, analysis_id: str) -> CvVariant | None:
        return self.session.scalar(
            select(CvVariant).where(
                CvVariant.user_id == user_id, CvVariant.analysis_run_id == analysis_id
            )
        )

    def list_variants(self, user_id: str, job_id: str | None = None) -> list[CvVariant]:
        statement = select(CvVariant).where(CvVariant.user_id == user_id)
        if job_id:
            statement = statement.where(CvVariant.job_id == job_id)
        return list(
            self.session.scalars(statement.order_by(CvVariant.created_at.desc()).limit(100))
        )

    def latest_variant_version(self, variant_id: str) -> CvVariantVersion | None:
        return self.session.scalar(
            select(CvVariantVersion)
            .where(CvVariantVersion.variant_id == variant_id)
            .order_by(CvVariantVersion.version.desc())
            .limit(1)
        )

    def export(self, version_id: str, format_name: str) -> CvExport | None:
        return self.session.scalar(
            select(CvExport).where(
                CvExport.variant_version_id == version_id, CvExport.format == format_name
            )
        )

    def export_for_download(self, export_id: str, user_id: str) -> CvExport | None:
        return self.session.scalar(
            select(CvExport)
            .join(CvVariantVersion)
            .join(CvVariant)
            .where(CvExport.id == export_id, CvVariant.user_id == user_id)
        )

    def export_keys(self, variant_id: str) -> list[str]:
        return list(
            self.session.scalars(
                select(CvExport.storage_key)
                .join(CvVariantVersion)
                .where(CvVariantVersion.variant_id == variant_id)
            )
        )


class SqlAlchemyCoverLetterRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(
        self, document_id: str, user_id: str, *, lock: bool = False
    ) -> GeneratedDocument | None:
        statement = (
            select(GeneratedDocument)
            .join(Application)
            .where(
                GeneratedDocument.id == document_id,
                GeneratedDocument.document_type == "COVER_LETTER",
                Application.user_id == user_id,
            )
        )
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def list_letters(self, user_id: str, job_id: str | None = None) -> list[GeneratedDocument]:
        statement = (
            select(GeneratedDocument)
            .join(Application)
            .where(
                Application.user_id == user_id,
                GeneratedDocument.document_type == "COVER_LETTER",
            )
        )
        if job_id:
            statement = statement.where(GeneratedDocument.job_id == job_id)
        return list(
            self.session.scalars(statement.order_by(GeneratedDocument.created_at.desc()).limit(100))
        )

    def selected_id(self, application_id: str) -> str | None:
        return self.session.scalar(
            select(GeneratedDocument.id).where(
                GeneratedDocument.application_id == application_id,
                GeneratedDocument.document_type == "COVER_LETTER",
                GeneratedDocument.selected.is_(True),
            )
        )

    def clear_selection(self, application_id: str) -> None:
        self.session.execute(
            update(GeneratedDocument)
            .where(
                GeneratedDocument.application_id == application_id,
                GeneratedDocument.document_type == "COVER_LETTER",
            )
            .values(selected=False)
        )

    def export(self, document_id: str, format_name: str) -> DocumentExport | None:
        return self.session.scalar(
            select(DocumentExport).where(
                DocumentExport.generated_document_id == document_id,
                DocumentExport.format == format_name,
            )
        )

    def export_for_download(self, export_id: str, user_id: str) -> DocumentExport | None:
        return self.session.scalar(
            select(DocumentExport)
            .join(GeneratedDocument)
            .join(Application)
            .where(DocumentExport.id == export_id, Application.user_id == user_id)
        )

    def export_keys(self, document_id: str) -> list[str]:
        return list(
            self.session.scalars(
                select(DocumentExport.storage_key).where(
                    DocumentExport.generated_document_id == document_id
                )
            )
        )


class SqlAlchemyMatchRepository:
    def __init__(self, session: Session):
        self.session = session

    def save_explainable(
        self,
        *,
        result: DiscoveryMatchResult,
        profile_version: ProfileVersion,
        job_version: JobVersion,
        analysis: dict[str, Any],
        engine_version: str,
    ) -> MatchVersion:
        existing = self.session.scalar(
            select(MatchVersion).where(
                MatchVersion.profile_version_id == profile_version.id,
                MatchVersion.job_version_id == job_version.id,
                MatchVersion.engine_version == engine_version,
            )
        )
        if existing:
            return existing
        current = self.session.scalar(
            select(func.max(MatchVersion.version)).where(MatchVersion.match_result_id == result.id)
        )
        record = MatchVersion(
            match_result_id=result.id,
            version=(current or 0) + 1,
            profile_version_id=profile_version.id,
            job_version_id=job_version.id,
            score=result.score,
            recommendation=result.recommendation,
            hard_rejected=result.hard_rejected,
            confidence=float(analysis.get("confidence", 0)),
            explanation=" ".join(analysis.get("reasons_to_apply", []))[:10000]
            or "Deterministic score components persisted.",
            engine_version=engine_version,
        )
        self.session.add(record)
        self.session.flush()
        for category, component in analysis.get("score_by_category", {}).items():
            evidence = {
                key: value
                for key, value in component.items()
                if key not in {"score", "maximum", "explanation"}
            }
            score_component = MatchScoreComponent(
                match_version_id=record.id,
                category=category,
                score=float(component.get("score", 0)),
                maximum=float(component.get("maximum", 0)),
                explanation=str(component.get("explanation", "")),
                evidence=evidence,
            )
            self.session.add(score_component)
            self.session.flush()
            self.session.add(
                MatchEvidence(
                    match_version_id=record.id,
                    component_id=score_component.id,
                    source_type="SCORE_COMPONENT",
                    source_id=str(category)[:240],
                    metadata_json=evidence,
                )
            )
        skill_groups = (
            ("matching_skills", MatchSkillKind.MATCHING),
            ("missing_required_skills", MatchSkillKind.MISSING_REQUIRED),
            ("missing_preferred_skills", MatchSkillKind.MISSING_PREFERRED),
        )
        for field, kind in skill_groups:
            for name in dict.fromkeys(analysis.get(field, [])):
                self.session.add(
                    MatchSkill(
                        match_version_id=record.id,
                        skill_id=_get_or_create_skill_id(self.session, str(name)),
                        kind=kind,
                    )
                )
        for index, message in enumerate(analysis.get("potential_blockers", [])):
            self.session.add(
                MatchBlocker(
                    match_version_id=record.id,
                    code=f"BLOCKER_{index + 1}",
                    message=str(message),
                    hard_rejection=str(message) in result.rejection_reasons,
                )
            )
        self.session.flush()
        return record

    def latest_version(self, result_id: str) -> MatchVersion | None:
        return self.session.scalar(
            select(MatchVersion)
            .where(MatchVersion.match_result_id == result_id)
            .order_by(MatchVersion.version.desc())
            .limit(1)
        )

    def record_decision(
        self, result_id: str, actor_id: str, decision: str, reason: str | None = None
    ) -> MatchRecommendationDecision | None:
        version = self.latest_version(result_id)
        if version is None:
            return None
        record = MatchRecommendationDecision(
            match_version_id=version.id,
            actor_id=actor_id,
            decision=decision,
            reason=reason,
        )
        self.session.add(record)
        return record


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session):
        self.session = session
        self.candidates = SqlAlchemyCandidateRepository(session)
        self.cvs = SqlAlchemyCvRepository(session)
        self.jobs = SqlAlchemyJobRepository(session)
        self.applications = SqlAlchemyApplicationRepository(session)
        self.discovery = SqlAlchemyDiscoveryRepository(session)
        self.recommendations = SqlAlchemyRecommendationRepository(session)
        self.cover_letters = SqlAlchemyCoverLetterRepository(session)
        self.matches = SqlAlchemyMatchRepository(session)

    def get_user(self, user_id: str) -> User | None:
        return self.session.get(User, user_id)

    def get_user_by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(User.email == email))

    def add(self, entity: object) -> None:
        self.session.add(entity)

    def add_all(self, entities: Iterable[object]) -> None:
        self.session.add_all(list(entities))

    def delete(self, entity: object) -> None:
        self.session.delete(entity)

    def flush(self) -> None:
        try:
            self.session.flush()
        except (IntegrityError, StaleDataError) as exc:
            raise PersistenceConflict(
                "Database integrity constraint rejected the operation"
            ) from exc

    def refresh(self, entity: object, *, lock: bool = False) -> None:
        self.session.refresh(entity, with_for_update=lock)

    def detach(self, entity: object) -> None:
        self.session.expunge(entity)

    def commit(self) -> None:
        try:
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise PersistenceConflict(
                "Database integrity constraint rejected the operation"
            ) from exc

    def rollback(self) -> None:
        self.session.rollback()

    def audit(
        self,
        user_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            AuditLog(
                user_id=user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                metadata_json=metadata or {},
            )
        )
