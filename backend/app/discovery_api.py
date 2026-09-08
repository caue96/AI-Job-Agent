from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from app.config import get_settings
from app.discovery import (
    create_configuration,
    import_manual_jobs,
    parse_csv_import,
    parse_email_import,
    prepare_application,
    run_due_searches,
    run_search,
    upsert_search_profile,
)
from app.discovery_providers import PROVIDERS, provider_registry
from app.discovery_schemas import (
    CsvImportRequest,
    EmailImportRequest,
    ImportResult,
    ManualJobImport,
    MatchAction,
    NotificationRead,
    RankedJobRead,
    SearchConfigurationCreate,
    SearchConfigurationRead,
    SearchPreferences,
    SearchProfileRead,
    SearchRunRead,
    SearchRunRequest,
)
from app.models import (
    DiscoveryNotification,
    DiscoverySearchConfiguration,
    DiscoverySearchProfile,
    DiscoverySearchRun,
)
from app.services import current_development_user, write_audit
from app.unit_of_work import UnitOfWorkDependency

router = APIRouter(prefix="/v1/discovery", tags=["discovery"])


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/providers")
def providers(uow: UnitOfWorkDependency) -> list[dict[str, Any]]:
    user = current_development_user(uow)
    settings = get_settings()
    cursors = uow.discovery.list_provider_cursors(user.id)
    cursor_map = {item.provider: item for item in cursors}
    errors = uow.discovery.list_provider_errors(user.id)
    last_errors = {item.provider: item.safe_message for item in errors}
    configurations = uow.discovery.list_configurations(user.id)
    result = provider_registry()
    for item in result:
        cursor = cursor_map.get(item["key"])
        item["last_successful_sync"] = cursor.last_success_at if cursor else None
        item["health"] = "HEALTHY" if cursor and cursor.last_success_at else "NOT_RUN"
        item["last_error"] = last_errors.get(item["key"])
        item["configured"] = (
            bool(settings.itjobs_api_key)
            if item["key"] == "itjobs"
            else bool(settings.infojobs_client_id and settings.infojobs_client_secret)
            if item["key"] == "infojobs"
            else any(
                bool(config.provider_settings.get("tecnoempleo", {}).get("feed_url"))
                for config in configurations
            )
            if item["key"] == "tecnoempleo"
            else False
        )
    return result


@router.post("/search-profile/generate", response_model=SearchProfileRead)
def generate_profile(uow: UnitOfWorkDependency) -> DiscoverySearchProfile:
    user = current_development_user(uow)
    try:
        result = upsert_search_profile(uow, user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    uow.commit()
    uow.refresh(result)
    return result


@router.get("/search-profile", response_model=SearchProfileRead)
def get_profile(uow: UnitOfWorkDependency) -> DiscoverySearchProfile:
    user = current_development_user(uow)
    result = uow.discovery.get_search_profile(user.id)
    if not result:
        raise HTTPException(status_code=404, detail="Search profile not found")
    return result


@router.put("/search-profile", response_model=SearchProfileRead)
def replace_profile(
    payload: SearchPreferences, uow: UnitOfWorkDependency
) -> DiscoverySearchProfile:
    user = current_development_user(uow)
    try:
        result = upsert_search_profile(uow, user, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    uow.commit()
    uow.refresh(result)
    return result


@router.post("/configurations", response_model=SearchConfigurationRead, status_code=201)
def add_configuration(
    payload: SearchConfigurationCreate, uow: UnitOfWorkDependency
) -> DiscoverySearchConfiguration:
    user = current_development_user(uow)
    try:
        result = create_configuration(uow, user, payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    uow.commit()
    uow.refresh(result)
    return result


@router.get("/configurations", response_model=list[SearchConfigurationRead])
def configurations(uow: UnitOfWorkDependency) -> list[DiscoverySearchConfiguration]:
    user = current_development_user(uow)
    return uow.discovery.list_configurations(user.id)


@router.put("/configurations/{configuration_id}", response_model=SearchConfigurationRead)
def replace_configuration(
    configuration_id: str, payload: SearchConfigurationCreate, uow: UnitOfWorkDependency
) -> DiscoverySearchConfiguration:
    user = current_development_user(uow)
    current = uow.discovery.get_configuration(configuration_id, user.id, lock=True)
    if not current:
        raise HTTPException(status_code=404, detail="Search configuration not found")
    unknown = set(payload.provider_settings) - set(PROVIDERS)
    if unknown or any(
        item.enabled and not PROVIDERS[key].automated_search
        for key, item in payload.provider_settings.items()
    ):
        raise HTTPException(
            status_code=422, detail="Only providers with permitted automated access can be enabled"
        )
    current.name = payload.name
    current.enabled = payload.enabled
    current.provider_settings = {
        key: value.model_dump() for key, value in payload.provider_settings.items()
    }
    current.schedule_kind = payload.schedule_kind
    current.schedule_time = payload.schedule_time
    current.timezone = payload.timezone
    current.hard_filters = payload.hard_filters.model_dump()
    uow.discovery.sync_provider_configurations(user.id, current.provider_settings)
    from app.discovery import calculate_next_run

    current.next_run_at = calculate_next_run(current)
    write_audit(
        uow,
        user.id,
        "discovery.configuration.updated",
        "discovery_search_configuration",
        current.id,
    )
    uow.commit()
    uow.refresh(current)
    return current


@router.post("/search-runs", response_model=SearchRunRead, status_code=201)
def start_search(payload: SearchRunRequest, uow: UnitOfWorkDependency) -> DiscoverySearchRun:
    user = current_development_user(uow)
    config = uow.discovery.get_configuration(payload.configuration_id, user.id)
    if not config:
        raise HTTPException(status_code=404, detail="Search configuration not found")
    try:
        result = run_search(uow, user, config, get_settings())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    uow.commit()
    uow.refresh(result)
    return result


@router.post("/scheduler/tick", response_model=list[str])
def scheduler_tick(uow: UnitOfWorkDependency) -> list[str]:
    current_development_user(uow)
    result = run_due_searches(uow, get_settings())
    uow.commit()
    return result


@router.get("/search-runs", response_model=list[SearchRunRead])
def search_runs(
    uow: UnitOfWorkDependency, limit: int = Query(20, ge=1, le=100)
) -> list[DiscoverySearchRun]:
    user = current_development_user(uow)
    return uow.discovery.list_runs(user.id, limit)


@router.post("/imports/manual", response_model=ImportResult, status_code=201)
def manual_import(payload: ManualJobImport, uow: UnitOfWorkDependency) -> ImportResult:
    user = current_development_user(uow)
    try:
        imported, duplicates, ids = import_manual_jobs(uow, user, [payload], get_settings())
    except ValueError as exc:
        raise _bad_request(exc) from exc
    uow.commit()
    return ImportResult(imported=imported, duplicates=duplicates, job_ids=ids)


@router.post("/imports/csv", response_model=ImportResult, status_code=201)
def csv_import(payload: CsvImportRequest, uow: UnitOfWorkDependency) -> ImportResult:
    user = current_development_user(uow)
    try:
        items = parse_csv_import(payload.provider, payload.csv_text)
        imported, duplicates, ids = import_manual_jobs(uow, user, items, get_settings())
    except ValueError as exc:
        raise _bad_request(exc) from exc
    uow.commit()
    return ImportResult(imported=imported, duplicates=duplicates, job_ids=ids)


@router.post("/imports/email", response_model=ImportResult, status_code=201)
def email_import(payload: EmailImportRequest, uow: UnitOfWorkDependency) -> ImportResult:
    user = current_development_user(uow)
    try:
        items = parse_email_import(payload.provider, payload.eml_text)
        imported, duplicates, ids = import_manual_jobs(uow, user, items, get_settings())
    except ValueError as exc:
        raise _bad_request(exc) from exc
    uow.commit()
    return ImportResult(imported=imported, duplicates=duplicates, job_ids=ids)


@router.get("/matches", response_model=list[RankedJobRead])
def ranked_matches(
    uow: UnitOfWorkDependency,
    min_score: int = Query(0, ge=0, le=100),
    country: str | None = Query(None, max_length=2),
    provider: str | None = Query(None, max_length=40),
    city: str | None = Query(None, max_length=120),
    company: str | None = Query(None, max_length=200),
    role: str | None = Query(None, max_length=200),
    seniority: str | None = Query(None, max_length=40),
    workplace_type: str | None = Query(None, max_length=30),
    industry: str | None = Query(None, max_length=120),
    minimum_salary: int | None = Query(None, ge=0),
    language: str | None = Query(None, max_length=80),
    posted_after: datetime | None = None,
    work_authorization_compatible: bool | None = None,
    sponsorship_available: bool | None = None,
    recommendation: str | None = Query(None, max_length=30),
    include_rejected: bool = False,
    limit: int = Query(100, ge=1, le=500),
) -> list[RankedJobRead]:
    user = current_development_user(uow)
    rows = uow.discovery.list_ranked_matches(
        user.id,
        {
            "min_score": min_score,
            "country": country,
            "provider": provider,
            "city": city,
            "company": company,
            "role": role,
            "seniority": seniority,
            "workplace_type": workplace_type,
            "industry": industry,
            "minimum_salary": minimum_salary,
            "posted_after": posted_after,
            "recommendation": recommendation,
            "include_rejected": include_rejected,
            "limit": limit,
        },
    )
    seen: set[str] = set()
    output: list[RankedJobRead] = []
    for match, job in rows:
        if language:
            language_text = " ".join([job.language or "", *job.required_languages]).casefold()
            if language.casefold() not in language_text:
                continue
        if work_authorization_compatible is not None:
            category = match.analysis.get("score_by_category", {}).get("eu_work_authorization", {})
            compatible = category.get("score", 0) > 0
            if compatible != work_authorization_compatible:
                continue
        if sponsorship_available is not None:
            sponsorship_text = (job.sponsorship_information or "").casefold()
            available = "sponsorship available" in sponsorship_text
            if available != sponsorship_available:
                continue
        if job.id in seen:
            continue
        seen.add(job.id)
        output.append(
            RankedJobRead(
                id=job.id,
                match_id=match.id,
                title=job.title,
                company=job.company,
                country=job.country,
                city=job.city,
                provider=job.source,
                url=job.url,
                workplace_type=job.workplace_type,
                posted_at=job.posted_at,
                salary_min=job.salary_min,
                salary_max=job.salary_max,
                salary_currency=job.salary_currency,
                score=match.score,
                recommendation=match.recommendation,
                hard_rejected=match.hard_rejected,
                analysis=match.analysis,
                user_state=match.user_state,
            )
        )
    return output


@router.get("/matches/{match_id}", response_model=RankedJobRead)
def match_detail(match_id: str, uow: UnitOfWorkDependency) -> RankedJobRead:
    user = current_development_user(uow)
    match = uow.discovery.get_match(match_id, user.id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    job = uow.jobs.get(match.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return RankedJobRead(
        id=job.id,
        match_id=match.id,
        title=job.title,
        company=job.company,
        country=job.country,
        city=job.city,
        provider=job.source,
        url=job.url,
        workplace_type=job.workplace_type,
        posted_at=job.posted_at,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
        score=match.score,
        recommendation=match.recommendation,
        hard_rejected=match.hard_rejected,
        analysis=match.analysis,
        user_state=match.user_state,
    )


@router.post("/matches/{match_id}/action")
def match_action(match_id: str, payload: MatchAction, uow: UnitOfWorkDependency) -> dict[str, str]:
    user = current_development_user(uow)
    match = uow.discovery.get_match(match_id, user.id, lock=True)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if payload.action == "PREPARE_APPLICATION":
        application = prepare_application(uow, user, match)
        result = {"state": match.user_state, "application_id": application.id}
    else:
        match.user_state = (
            payload.action.removesuffix("E") + "ED" if payload.action == "SAVE" else "REJECTED"
        )
        write_audit(
            uow,
            user.id,
            f"discovery.match.{payload.action.lower()}",
            "discovery_match_result",
            match.id,
        )
        result = {"state": match.user_state}
    uow.matches.record_decision(match.id, user.id, match.user_state)
    uow.commit()
    return result


@router.get("/notifications", response_model=list[NotificationRead])
def notifications(
    uow: UnitOfWorkDependency, unread_only: bool = False
) -> list[DiscoveryNotification]:
    user = current_development_user(uow)
    return uow.discovery.list_notifications(user.id, unread_only=unread_only)


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
def read_notification(notification_id: str, uow: UnitOfWorkDependency) -> DiscoveryNotification:
    user = current_development_user(uow)
    item = uow.discovery.get_notification(notification_id, user.id)
    if not item:
        raise HTTPException(status_code=404, detail="Notification not found")
    item.read_at = datetime.now(UTC)
    uow.commit()
    uow.refresh(item)
    return item
