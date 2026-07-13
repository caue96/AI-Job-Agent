"""Job-discovery orchestration, deterministic ranking, imports, and scheduling."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import Parser
from typing import Any, Literal, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.discovery_providers import (
    PROVIDERS,
    HttpClient,
    JobProvider,
    ProviderError,
    build_provider,
    parse_datetime,
    safe_url,
    sanitize_text,
)
from app.discovery_schemas import (
    HardFilters,
    ManualJobImport,
    SearchConfigurationCreate,
    SearchPreferences,
)
from app.matching import MatchingPolicy, normalized, score_job
from app.models import (
    Application,
    ApplicationStatus,
    ApplicationStatusHistory,
    CandidateProfile,
    DiscoveryDuplicateGroup,
    DiscoveryJobSource,
    DiscoveryMatchResult,
    DiscoveryNotification,
    DiscoveryProviderCursor,
    DiscoveryProviderError,
    DiscoveryProviderRun,
    DiscoveryRawResult,
    DiscoveryRunStatus,
    DiscoverySearchConfiguration,
    DiscoverySearchProfile,
    DiscoverySearchQuery,
    DiscoverySearchRun,
    Job,
    User,
)
from app.services import write_audit

logger = logging.getLogger("app.discovery")

TITLE_TRANSLATIONS = {
    "Data Analyst": ("Analista de Datos", "Analista de Dados"),
    "Business Intelligence Analyst": (
        "Analista de Business Intelligence",
        "Analista de Business Intelligence",
    ),
    "BI Analyst": ("Analista BI", "Analista de BI"),
    "Power BI Developer": ("Desarrollador Power BI", "Desenvolvedor Power BI"),
    "Power Platform Developer": ("Desarrollador Power Platform", "Desenvolvedor Power Platform"),
    "Power Apps Developer": ("Desarrollador Power Apps", "Desenvolvedor Power Apps"),
    "Power Automate Developer": ("Desarrollador Power Automate", "Desenvolvedor Power Automate"),
    "Automation Developer": ("Desarrollador de Automatización", "Desenvolvedor de Automação"),
    "Business Analyst": ("Analista de Negocio", "Analista de Negócios"),
    "Data Visualization Specialist": (
        "Especialista en Visualización de Datos",
        "Especialista em Visualização de Dados",
    ),
    "Junior Data Engineer": ("Ingeniero de Datos Junior", "Engenheiro de Dados Júnior"),
    "Mid-level Data Engineer": ("Ingeniero de Datos", "Engenheiro de Dados Pleno"),
    "Process Automation Analyst": (
        "Analista de Automatización de Procesos",
        "Analista de Automação de Processos",
    ),
    "Digital Transformation Analyst": (
        "Analista de Transformación Digital",
        "Analista de Transformação Digital",
    ),
}
DEFAULT_LOCATIONS = {
    "ES": ["Valencia", "Málaga", "Madrid", "Barcelona", "Zaragoza", "Remote Spain"],
    "PT": ["Porto", "Braga", "Lisbon", "Coimbra", "Aveiro", "Remote Portugal"],
    "IE": ["Cork", "Limerick", "Dublin", "Galway", "Remote Ireland"],
}


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def generate_search_preferences(profile: CandidateProfile) -> tuple[SearchPreferences, list[str]]:
    skill_names = [skill.name for skill in profile.skills]
    skills = {normalized(name) for name in skill_names}
    titles = list(profile.preferred_titles)
    inferred: list[str] = []
    if any(skill in skills for skill in {"power bi", "dax", "sql", "excel"}):
        inferred += ["Data Analyst", "Business Intelligence Analyst", "Power BI Developer"]
    if any(skill in skills for skill in {"power apps", "power automate", "power fx"}):
        inferred += [
            "Power Platform Developer",
            "Power Apps Developer",
            "Power Automate Developer",
            "Automation Developer",
        ]
    if any(skill in skills for skill in {"python", "sql"}):
        inferred += ["Junior Data Engineer"]
    titles = _unique(titles + inferred)
    alternatives = _unique(
        [translation for title in titles for translation in TITLE_TRANSLATIONS.get(title, ())]
    )
    countries = [value.upper() for value in profile.preferred_locations if len(value) == 2]
    if not countries:
        countries = ["ES", "PT", "IE"]
    cities = [value for code in countries for value in DEFAULT_LOCATIONS.get(code, [])]
    cities += [value for value in profile.preferred_locations if len(value) != 2]
    preferences = SearchPreferences(
        target_titles=titles,
        alternative_titles=alternatives,
        technical_skills=skill_names,
        languages=[language.language for language in profile.languages],
        preferred_countries=countries,
        preferred_cities=_unique(cities),
        workplace_preferences=[
            cast(Literal["REMOTE", "HYBRID", "ONSITE"], value.upper())
            for value in profile.workplace_preferences
            if value.upper() in {"REMOTE", "HYBRID", "ONSITE"}
        ],
        work_authorization=["EU"] if profile.eu_work_authorized else [],
        sponsorship_required=profile.requires_sponsorship,
        relocation_available=profile.relocation_available,
        minimum_salary=profile.min_salary,
        salary_currency=profile.salary_currency,
        preferred_industries=profile.preferred_industries,
    )
    terms = _unique(preferences.target_titles + preferences.alternative_titles)
    return preferences, terms


def upsert_search_profile(
    db: Session, user: User, preferences: SearchPreferences | None = None
) -> DiscoverySearchProfile:
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    if not profile:
        raise ValueError("An approved candidate profile is required.")
    record = db.scalar(
        select(DiscoverySearchProfile).where(DiscoverySearchProfile.user_id == user.id)
    )
    generated, terms = generate_search_preferences(profile)
    selected = preferences or generated
    if preferences:
        terms = _unique(preferences.target_titles + preferences.alternative_titles)
    if record is None:
        record = DiscoverySearchProfile(user_id=user.id)
        db.add(record)
    record.preferences = selected.model_dump()
    record.generated_terms = terms
    db.flush()
    write_audit(
        db, user.id, "discovery.search_profile.updated", "discovery_search_profile", record.id
    )
    return record


def calculate_next_run(
    configuration: DiscoverySearchConfiguration, after: datetime | None = None
) -> datetime | None:
    if not configuration.enabled or configuration.schedule_kind == "MANUAL":
        return None
    now = (after or datetime.now(UTC)).astimezone(ZoneInfo(configuration.timezone))
    hour, minute = map(int, configuration.schedule_time.split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    if configuration.schedule_kind == "WEEKDAYS":
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


def create_configuration(
    db: Session, user: User, payload: SearchConfigurationCreate
) -> DiscoverySearchConfiguration:
    unknown = set(payload.provider_settings) - set(PROVIDERS)
    if unknown:
        raise ValueError(f"Unknown providers: {', '.join(sorted(unknown))}")
    for key, item in payload.provider_settings.items():
        if item.enabled and not PROVIDERS[key].automated_search:
            raise ValueError(f"{PROVIDERS[key].name} is fallback-only and cannot be scheduled.")
    record = DiscoverySearchConfiguration(
        user_id=user.id,
        name=payload.name,
        enabled=payload.enabled,
        provider_settings={
            key: item.model_dump() for key, item in payload.provider_settings.items()
        },
        schedule_kind=payload.schedule_kind,
        schedule_time=payload.schedule_time,
        timezone=payload.timezone,
        hard_filters=payload.hard_filters.model_dump(),
    )
    record.next_run_at = calculate_next_run(record)
    db.add(record)
    db.flush()
    write_audit(
        db, user.id, "discovery.configuration.created", "discovery_search_configuration", record.id
    )
    return record


def _canonical_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query)
        if not key.casefold().startswith(("utm_", "ref", "source"))
    ]
    return urlunsplit(
        ("https", parsed.hostname.casefold(), parsed.path.rstrip("/"), urlencode(query), "")
    )


def _content_hash(data: dict[str, Any]) -> str:
    content = "|".join(
        normalized(str(data.get(key) or "")) for key in ("company", "title", "city", "description")
    )
    return hashlib.sha256(content.encode()).hexdigest()


def normalize_job(data: dict[str, Any]) -> dict[str, Any]:
    source = str(data.get("source", ""))
    if source not in PROVIDERS:
        raise ValueError("Unknown provider")
    title = sanitize_text(data.get("title"), 200)
    company = sanitize_text(data.get("company"), 200)
    description = sanitize_text(data.get("description"))
    if not title or not company or not description:
        raise ValueError("Provider result requires title, company, and description")
    url = safe_url(data.get("url"), PROVIDERS[source].allowed_hosts)
    result = {
        **data,
        "source": source,
        "title": title,
        "normalized_title": normalized(title),
        "company": company,
        "description": description,
        "url": url,
        "normalized_url": _canonical_url(url),
        "application_url": safe_url(data.get("application_url"), PROVIDERS[source].allowed_hosts),
        "country": str(data.get("country") or "").upper()[:2] or None,
        "city": sanitize_text(data.get("city"), 120) or None,
        "region": sanitize_text(data.get("region"), 120) or None,
        "requirements": [sanitize_text(item, 500) for item in data.get("requirements", [])][:100],
        "preferred_qualifications": [
            sanitize_text(item, 500) for item in data.get("preferred_qualifications", [])
        ][:100],
        "responsibilities": [sanitize_text(item, 500) for item in data.get("responsibilities", [])][
            :100
        ],
        "required_languages": [
            sanitize_text(item, 80) for item in data.get("required_languages", [])
        ][:20],
        "required_skills": [sanitize_text(item, 120) for item in data.get("required_skills", [])][
            :100
        ],
        "preferred_skills": [sanitize_text(item, 120) for item in data.get("preferred_skills", [])][
            :100
        ],
        "posted_at": parse_datetime(data.get("posted_at")),
        "expires_at": parse_datetime(data.get("expires_at")),
        "last_checked_at": datetime.now(UTC),
        "provider_metadata": dict(data.get("provider_metadata") or {}),
    }
    result["requirements"] = _unique(result["requirements"] + result["required_skills"])
    result["preferred_qualifications"] = _unique(
        result["preferred_qualifications"] + result["preferred_skills"]
    )
    result["content_hash"] = _content_hash(result)
    return result


JOB_FIELDS = {
    "source",
    "external_job_id",
    "url",
    "normalized_url",
    "application_url",
    "company",
    "title",
    "normalized_title",
    "industry",
    "country",
    "city",
    "region",
    "workplace_type",
    "employment_type",
    "seniority",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "description",
    "requirements",
    "preferred_qualifications",
    "responsibilities",
    "required_languages",
    "required_skills",
    "preferred_skills",
    "required_years_experience",
    "sponsorship_information",
    "work_authorization_information",
    "relocation_information",
    "posted_at",
    "expires_at",
    "last_checked_at",
    "provider_metadata",
    "content_hash",
}


def merge_job(db: Session, data: dict[str, Any]) -> tuple[Job, str]:
    normalized_data = normalize_job(data)
    source, external_id = normalized_data["source"], normalized_data.get("external_job_id")
    exact = None
    if external_id:
        link = db.scalar(
            select(DiscoveryJobSource).where(
                DiscoveryJobSource.provider == source,
                DiscoveryJobSource.external_job_id == str(external_id),
            )
        )
        exact = db.get(Job, link.job_id) if link else None
    if exact is None and normalized_data.get("normalized_url"):
        exact = db.scalar(
            select(Job).where(Job.normalized_url == normalized_data["normalized_url"])
        )
    relationship = "EXACT_DUPLICATE" if exact else "CANONICAL"
    if exact is None:
        exact = db.scalar(select(Job).where(Job.content_hash == normalized_data["content_hash"]))
        relationship = "SAME_JOB_MULTIPLE_SOURCES" if exact else relationship
    if exact is None:
        exact = db.scalar(
            select(Job).where(
                Job.company.ilike(normalized_data["company"]),
                Job.title.ilike(normalized_data["title"]),
                or_(Job.city == normalized_data.get("city"), Job.city.is_(None)),
            )
        )
        relationship = "LIKELY_DUPLICATE" if exact else relationship
    if exact is None:
        exact = Job(
            **{key: value for key, value in normalized_data.items() if key in JOB_FIELDS},
            raw_payload={},
        )
        db.add(exact)
        db.flush()
    else:
        old_hash = exact.content_hash
        if exact.source == source and old_hash != normalized_data["content_hash"]:
            relationship = "UPDATED_JOB"
            for key in JOB_FIELDS:
                if key in normalized_data and normalized_data[key] is not None:
                    setattr(exact, key, normalized_data[key])
        elif (
            exact.posted_at
            and normalized_data.get("posted_at")
            and normalized_data["posted_at"] > exact.posted_at + timedelta(days=21)
        ):
            relationship = "REPOSTED_JOB"
        db.add(
            DiscoveryDuplicateGroup(
                canonical_job_id=exact.id,
                relationship=relationship,
                signals={
                    "url": bool(normalized_data.get("normalized_url")),
                    "content_hash": old_hash == normalized_data["content_hash"],
                },
            )
        )
    link = db.scalar(
        select(DiscoveryJobSource).where(
            DiscoveryJobSource.provider == source,
            DiscoveryJobSource.external_job_id == (str(external_id) if external_id else None),
        )
    )
    if link is None:
        db.add(
            DiscoveryJobSource(
                job_id=exact.id,
                provider=source,
                external_job_id=str(external_id) if external_id else None,
                canonical_url=normalized_data.get("normalized_url"),
                relationship=relationship,
            )
        )
    else:
        link.last_seen_at = datetime.now(UTC)
        link.relationship = relationship
    db.flush()
    return exact, relationship


def apply_hard_filters(job: Job, analysis: dict[str, Any], filters: HardFilters) -> list[str]:
    reasons: list[str] = []
    text = normalized(" ".join([job.title, job.description, *job.requirements]))
    if filters.countries and (job.country or "") not in {
        item.upper() for item in filters.countries
    }:
        reasons.append("Country is outside the configured hard filter.")
    if filters.cities and normalized(job.city or "") not in {
        normalized(item) for item in filters.cities
    }:
        reasons.append("City is outside the configured hard filter.")
    if analysis["overall_score"] < filters.minimum_score:
        reasons.append("Match score is below the configured minimum.")
    if (
        filters.minimum_salary
        and job.salary_max is not None
        and job.salary_max < filters.minimum_salary
    ):
        reasons.append("Salary is below the configured hard minimum.")
    if (
        filters.required_workplace
        and (job.workplace_type or "").upper() not in filters.required_workplace
    ):
        reasons.append("Workplace model does not satisfy the configured hard filter.")
    if filters.mandatory_languages:
        vacancy_languages = normalized(
            " ".join([job.language or "", *job.required_languages, *job.requirements])
        )
        if any(normalized(item) not in vacancy_languages for item in filters.mandatory_languages):
            reasons.append("Vacancy does not establish all mandatory languages.")
    if filters.maximum_seniority:
        levels = {"intern": 0, "junior": 1, "mid": 2, "senior": 3, "lead": 4, "principal": 5}
        job_level = next(
            (
                value
                for key, value in levels.items()
                if key in normalized(job.seniority or job.title)
            ),
            None,
        )
        maximum_level = levels.get(normalized(filters.maximum_seniority))
        if job_level is not None and maximum_level is not None and job_level > maximum_level:
            reasons.append("Vacancy seniority exceeds the configured maximum.")
    if filters.excluded_companies and normalized(job.company) in {
        normalized(item) for item in filters.excluded_companies
    }:
        reasons.append("Company is excluded.")
    if filters.excluded_industries and normalized(job.industry or "") in {
        normalized(item) for item in filters.excluded_industries
    }:
        reasons.append("Industry is excluded.")
    if any(normalized(item) in text for item in filters.excluded_technologies):
        reasons.append("Vacancy contains an excluded technology.")
    employment = normalized(job.employment_type or "")
    if filters.reject_temporary_or_freelance and any(
        value in employment for value in ("temporary", "freelance", "contract")
    ):
        reasons.append("Temporary or freelance work is excluded.")
    if filters.reject_internships and "intern" in text:
        reasons.append("Internships are excluded.")
    if filters.reject_sponsorship_required and "sponsorship required" in normalized(
        job.sponsorship_information or ""
    ):
        reasons.append("Roles requiring sponsorship are excluded.")
    if filters.reject_incompatible_work_permit and any(
        "work authorization" in normalized(reason)
        for reason in analysis.get("potential_blockers", [])
    ):
        reasons.append("Work-permit requirements are incompatible with the approved profile.")
    return reasons


def _notify(
    db: Session,
    user_id: str,
    event_type: str,
    key: str,
    title: str,
    body: str,
    job_id: str | None = None,
) -> None:
    if db.scalar(
        select(DiscoveryNotification.id).where(
            DiscoveryNotification.user_id == user_id, DiscoveryNotification.deduplication_key == key
        )
    ):
        return
    db.add(
        DiscoveryNotification(
            user_id=user_id,
            event_type=event_type,
            job_id=job_id,
            deduplication_key=key,
            title=title[:200],
            body=body[:500],
        )
    )


def score_and_store(
    db: Session,
    run: DiscoverySearchRun,
    profile: CandidateProfile,
    job: Job,
    settings: Settings,
    hard_filters: HardFilters,
) -> DiscoveryMatchResult:
    analysis_model = score_job(profile, job, MatchingPolicy.from_settings(settings))
    analysis = analysis_model.model_dump(mode="json")
    reasons = apply_hard_filters(job, analysis, hard_filters)
    hard_rejected = analysis_model.hard_rejected or bool(reasons)
    recommendation = "REJECT" if hard_rejected else analysis_model.recommendation
    result = db.scalar(
        select(DiscoveryMatchResult).where(
            DiscoveryMatchResult.run_id == run.id, DiscoveryMatchResult.job_id == job.id
        )
    )
    if result is None:
        result = DiscoveryMatchResult(
            user_id=run.user_id,
            run_id=run.id,
            job_id=job.id,
            score=analysis_model.overall_score,
            recommendation=recommendation,
            hard_rejected=hard_rejected,
            rejection_reasons=reasons,
            analysis=analysis,
        )
        db.add(result)
    if recommendation == "STRONG_MATCH":
        _notify(
            db,
            run.user_id,
            "NEW_STRONG_MATCH",
            f"strong:{job.id}:{job.content_hash}",
            f"Strong match: {job.title}",
            f"{job.company} scored {analysis_model.overall_score}.",
            job.id,
        )
    db.flush()
    return result


def provider_configuration(
    settings: Settings, key: str, user_setting: dict[str, Any]
) -> dict[str, Any]:
    if key == "itjobs":
        return {
            "api_key": settings.itjobs_api_key.get_secret_value()
            if settings.itjobs_api_key
            else None
        }
    if key == "infojobs":
        return {
            "client_id": settings.infojobs_client_id,
            "client_secret": settings.infojobs_client_secret.get_secret_value()
            if settings.infojobs_client_secret
            else None,
        }
    if key == "tecnoempleo":
        return {"feed_url": user_setting.get("feed_url")}
    return {}


def run_search(
    db: Session,
    user: User,
    configuration: DiscoverySearchConfiguration,
    settings: Settings,
    trigger: str = "MANUAL",
    providers: dict[str, JobProvider] | None = None,
    http_client: HttpClient | None = None,
    scheduled_key: str | None = None,
) -> DiscoverySearchRun:
    profile_record = db.scalar(
        select(DiscoverySearchProfile).where(DiscoverySearchProfile.user_id == user.id)
    )
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    if profile_record is None or profile is None:
        raise ValueError("Generate a search profile from an approved candidate profile first.")
    run = DiscoverySearchRun(
        user_id=user.id,
        configuration_id=configuration.id,
        status=DiscoveryRunStatus.RUNNING,
        trigger=trigger,
        scheduled_key=scheduled_key,
        counters={},
    )
    db.add(run)
    db.flush()
    counters = {
        "providers": 0,
        "provider_failures": 0,
        "raw_results": 0,
        "new_jobs": 0,
        "duplicates": 0,
        "strong_matches": 0,
        "rejected_jobs": 0,
    }
    enabled = {
        key: value for key, value in configuration.provider_settings.items() if value.get("enabled")
    }
    for key, user_setting in enabled.items():
        provider_run = DiscoveryProviderRun(
            run_id=run.id,
            provider=key,
            status=DiscoveryRunStatus.RUNNING,
            counters={},
            api_usage={},
        )
        db.add(provider_run)
        db.flush()
        counters["providers"] += 1
        cursor_row = db.scalar(
            select(DiscoveryProviderCursor).where(
                DiscoveryProviderCursor.configuration_id == configuration.id,
                DiscoveryProviderCursor.provider == key,
            )
        )
        if cursor_row is None:
            cursor_row = DiscoveryProviderCursor(configuration_id=configuration.id, provider=key)
            db.add(cursor_row)
            db.flush()
        try:
            now = datetime.now(UTC)
            if cursor_row.circuit_open_until and cursor_row.circuit_open_until > now:
                raise ProviderError(
                    "CIRCUIT_OPEN", "Provider circuit is temporarily open.", retryable=True
                )
            if cursor_row.next_allowed_at and cursor_row.next_allowed_at > now:
                raise ProviderError(
                    "RATE_LIMIT",
                    "Provider minimum synchronization interval has not elapsed.",
                    retryable=True,
                )
            provider = (providers or {}).get(key) or build_provider(
                key, provider_configuration(settings, key, user_setting), http_client
            )
            provider.validate_configuration()
            queries = provider.build_queries(
                {**profile_record.preferences, "generated_terms": profile_record.generated_terms}
            )
            seen_ids: set[str] = set()
            provider_counts = {
                "queries": len(queries),
                "raw_results": 0,
                "new_jobs": 0,
                "duplicates": 0,
            }
            for query in queries:
                db.add(DiscoverySearchQuery(run_id=run.id, provider=key, query=query))
                cursor: dict[str, Any] | None = None
                for _ in range(10):
                    items, cursor, usage, retries = provider.search_with_retry(query, cursor)
                    provider_run.retry_count += retries
                    provider_run.api_usage = usage
                    for raw in items:
                        raw_json = json.dumps(raw, sort_keys=True, default=str)
                        payload_hash = hashlib.sha256(raw_json.encode()).hexdigest()
                        db.add(
                            DiscoveryRawResult(
                                provider_run_id=provider_run.id,
                                provider=key,
                                external_job_id=str(raw.get("id") or raw.get("guid") or "") or None,
                                payload=raw,
                                payload_hash=payload_hash,
                            )
                        )
                        provider_counts["raw_results"] += 1
                        counters["raw_results"] += 1
                        job, relationship = merge_job(db, provider.normalize(raw))
                        if relationship == "CANONICAL":
                            provider_counts["new_jobs"] += 1
                            counters["new_jobs"] += 1
                        else:
                            provider_counts["duplicates"] += 1
                            counters["duplicates"] += 1
                        if job.id in seen_ids:
                            continue
                        seen_ids.add(job.id)
                        match = score_and_store(
                            db,
                            run,
                            profile,
                            job,
                            settings,
                            HardFilters.model_validate(configuration.hard_filters),
                        )
                        counters["strong_matches"] += int(match.recommendation == "STRONG_MATCH")
                        counters["rejected_jobs"] += int(match.hard_rejected)
                        if relationship == "UPDATED_JOB":
                            _notify(
                                db,
                                user.id,
                                "JOB_CHANGED",
                                f"job-changed:{job.id}:{job.content_hash}",
                                f"Job description changed: {job.title}",
                                "The normalized vacancy changed materially and was rescored.",
                                job.id,
                            )
                        if job.expires_at and job.expires_at <= datetime.now(UTC) + timedelta(
                            days=3
                        ):
                            _notify(
                                db,
                                user.id,
                                "JOB_EXPIRING",
                                f"job-expiring:{job.id}:{job.expires_at.date()}",
                                f"Job is about to expire: {job.title}",
                                "Review the original listing before its advertised expiration.",
                                job.id,
                            )
                    if not cursor:
                        break
            provider_run.status = DiscoveryRunStatus.SUCCEEDED
            provider_run.counters = provider_counts
            provider_run.ended_at = datetime.now(UTC)
            cursor_row.failure_count = 0
            cursor_row.circuit_open_until = None
            cursor_row.last_success_at = datetime.now(UTC)
            cursor_row.next_allowed_at = datetime.now(UTC) + timedelta(hours=24)
        except (ProviderError, ValueError) as exc:
            counters["provider_failures"] += 1
            provider_run.status = DiscoveryRunStatus.FAILED
            provider_run.ended_at = datetime.now(UTC)
            cursor_row.failure_count += 1
            if cursor_row.failure_count >= 3:
                cursor_row.circuit_open_until = datetime.now(UTC) + timedelta(hours=6)
            code = exc.code if isinstance(exc, ProviderError) else "NORMALIZATION_ERROR"
            message = (
                exc.safe_message
                if isinstance(exc, ProviderError)
                else "Provider data could not be normalized."
            )
            db.add(
                DiscoveryProviderError(
                    provider_run_id=provider_run.id,
                    provider=key,
                    code=code,
                    safe_message=message,
                    retryable=isinstance(exc, ProviderError) and exc.retryable,
                )
            )
            if cursor_row.failure_count >= 3:
                _notify(
                    db,
                    user.id,
                    "PROVIDER_FAILURE",
                    f"provider-failure:{key}:{cursor_row.failure_count // 3}",
                    f"{PROVIDERS[key].name} has failed repeatedly",
                    message,
                )
    run.status = (
        DiscoveryRunStatus.PARTIAL
        if counters["provider_failures"] and counters["providers"] > counters["provider_failures"]
        else DiscoveryRunStatus.FAILED
        if counters["provider_failures"]
        else DiscoveryRunStatus.SUCCEEDED
    )
    run.lifecycle_stage = "USER_NOTIFIED"
    run.counters = counters
    run.ended_at = datetime.now(UTC)
    configuration.last_run_at = run.ended_at
    configuration.next_run_at = calculate_next_run(configuration, run.ended_at)
    _notify(
        db,
        user.id,
        "SEARCH_COMPLETED",
        f"search-completed:{run.id}",
        "Saved search completed",
        f"Found {counters['new_jobs']} new jobs and {counters['strong_matches']} strong matches.",
    )
    write_audit(
        db,
        user.id,
        "discovery.search.completed",
        "discovery_search_run",
        run.id,
        {"status": run.status.value, **counters},
    )
    logger.info(
        json.dumps(
            {
                "event": "discovery.search.completed",
                "run_id": run.id,
                "status": run.status.value,
                **counters,
            }
        )
    )
    db.flush()
    return run


def import_manual_jobs(
    db: Session, user: User, items: list[ManualJobImport], settings: Settings
) -> tuple[int, int, list[str]]:
    search_profile = db.scalar(
        select(DiscoverySearchProfile).where(DiscoverySearchProfile.user_id == user.id)
    )
    if search_profile is None:
        upsert_search_profile(db, user)
    config = db.scalar(
        select(DiscoverySearchConfiguration).where(
            DiscoverySearchConfiguration.user_id == user.id,
            DiscoverySearchConfiguration.name == "Manual imports",
        )
    )
    if config is None:
        config = create_configuration(db, user, SearchConfigurationCreate(name="Manual imports"))
    run = DiscoverySearchRun(
        user_id=user.id,
        configuration_id=config.id,
        status=DiscoveryRunStatus.RUNNING,
        trigger="IMPORT",
        counters={},
    )
    db.add(run)
    db.flush()
    provider_run = DiscoveryProviderRun(
        run_id=run.id,
        provider="manual_import",
        status=DiscoveryRunStatus.RUNNING,
        counters={},
        api_usage={},
    )
    db.add(provider_run)
    db.flush()
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    if profile is None:
        raise ValueError("An approved candidate profile is required.")
    imported = duplicates = 0
    ids: list[str] = []
    for item in items[:500]:
        if item.provider not in PROVIDERS:
            raise ValueError("Unknown provider")
        data = item.model_dump()
        data["source"] = data.pop("provider")
        data["country"] = item.country.upper() if item.country else None
        raw_hash = hashlib.sha256(
            json.dumps(data, sort_keys=True, default=str).encode()
        ).hexdigest()
        db.add(
            DiscoveryRawResult(
                provider_run_id=provider_run.id,
                provider=item.provider,
                external_job_id=item.external_job_id,
                payload=data,
                payload_hash=raw_hash,
            )
        )
        job, relationship = merge_job(db, data)
        ids.append(job.id)
        imported += int(relationship == "CANONICAL")
        duplicates += int(relationship != "CANONICAL")
        score_and_store(db, run, profile, job, settings, HardFilters())
    provider_run.status = DiscoveryRunStatus.SUCCEEDED
    provider_run.counters = {"imported": imported, "duplicates": duplicates}
    provider_run.ended_at = datetime.now(UTC)
    run.status = DiscoveryRunStatus.SUCCEEDED
    run.lifecycle_stage = "USER_NOTIFIED"
    run.counters = {"new_jobs": imported, "duplicates": duplicates}
    run.ended_at = datetime.now(UTC)
    write_audit(
        db,
        user.id,
        "discovery.jobs.imported",
        "discovery_search_run",
        run.id,
        {"count": len(items)},
    )
    return imported, duplicates, ids


def parse_csv_import(provider: str, text: str) -> list[ManualJobImport]:
    reader = csv.DictReader(io.StringIO(text))
    required = {"company", "title", "description"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("CSV requires company, title, and description columns")
    return [
        ManualJobImport.model_validate(
            {
                "provider": provider,
                **{
                    key: value or None
                    for key, value in row.items()
                    if key in ManualJobImport.model_fields
                },
            }
        )
        for row in reader
    ]


def parse_email_import(provider: str, text: str) -> list[ManualJobImport]:
    if provider not in PROVIDERS:
        raise ValueError("Unknown provider")
    message = Parser(policy=policy.default).parsestr(text)
    subject = sanitize_text(message.get("Subject", "Job alert"), 200)
    body = message.get_body(preferencelist=("plain", "html")) if message.is_multipart() else message
    content = sanitize_text(body.get_content() if body else "", 50_000)
    urls = re.findall(r"https://[^\s<>'\"]+", text)
    allowed_url = next(
        (
            safe_url(url.rstrip(".),"), PROVIDERS[provider].allowed_hosts)
            for url in urls
            if safe_url(url.rstrip(".),"), PROVIDERS[provider].allowed_hosts)
        ),
        None,
    )
    if not content:
        raise ValueError("Imported email does not contain a readable job description")
    title, separator, company = subject.partition(" at ")
    return [
        ManualJobImport(
            provider=provider,
            url=allowed_url,
            company=company if separator else "Not specified",
            title=title or "Job alert",
            description=content,
        )
    ]


def run_due_searches(db: Session, settings: Settings, now: datetime | None = None) -> list[str]:
    moment = now or datetime.now(UTC)
    configs = list(
        db.scalars(
            select(DiscoverySearchConfiguration)
            .where(
                DiscoverySearchConfiguration.enabled.is_(True),
                DiscoverySearchConfiguration.next_run_at.is_not(None),
                DiscoverySearchConfiguration.next_run_at <= moment,
            )
            .with_for_update(skip_locked=True)
        )
    )
    run_ids: list[str] = []
    for config in configs:
        scheduled_at = config.next_run_at
        if scheduled_at is None:
            continue
        key = f"{config.id}:{scheduled_at.isoformat()}"
        if db.scalar(select(DiscoverySearchRun.id).where(DiscoverySearchRun.scheduled_key == key)):
            continue
        user = db.get(User, config.user_id)
        if user:
            run_ids.append(
                run_search(db, user, config, settings, "SCHEDULED", scheduled_key=key).id
            )
    return run_ids


def prepare_application(db: Session, user: User, match: DiscoveryMatchResult) -> Application:
    application = db.scalar(
        select(Application).where(
            Application.user_id == user.id, Application.job_id == match.job_id
        )
    )
    if application is None:
        application = Application(
            user_id=user.id,
            job_id=match.job_id,
            status=ApplicationStatus.SHORTLISTED,
            match_score=match.score,
            match_analysis=match.analysis,
        )
        db.add(application)
        db.flush()
        db.add(
            ApplicationStatusHistory(
                application_id=application.id,
                from_status=None,
                to_status=ApplicationStatus.SHORTLISTED,
                reason="User selected Prepare application from discovery.",
                actor_id=user.id,
            )
        )
    match.user_state = "PREPARED"
    write_audit(db, user.id, "discovery.application.prepared", "application", application.id)
    return application
