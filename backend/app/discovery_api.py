from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
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
    DiscoveryMatchResult,
    DiscoveryNotification,
    DiscoveryProviderCursor,
    DiscoveryProviderError,
    DiscoveryProviderRun,
    DiscoverySearchConfiguration,
    DiscoverySearchProfile,
    DiscoverySearchRun,
    Job,
)
from app.services import current_development_user, write_audit

router = APIRouter(prefix="/v1/discovery", tags=["discovery"])


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/providers")
def providers(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    user = current_development_user(db)
    settings = get_settings()
    cursors = list(
        db.scalars(
            select(DiscoveryProviderCursor)
            .join(DiscoverySearchConfiguration)
            .where(DiscoverySearchConfiguration.user_id == user.id)
        )
    )
    cursor_map = {item.provider: item for item in cursors}
    errors = list(
        db.scalars(
            select(DiscoveryProviderError)
            .join(
                DiscoveryProviderRun,
                DiscoveryProviderRun.id == DiscoveryProviderError.provider_run_id,
            )
            .join(DiscoverySearchRun, DiscoverySearchRun.id == DiscoveryProviderRun.run_id)
            .where(DiscoverySearchRun.user_id == user.id)
            .order_by(DiscoveryProviderError.created_at.desc())
            .limit(50)
        )
    )
    last_errors = {item.provider: item.safe_message for item in errors}
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
                for config in db.scalars(
                    select(DiscoverySearchConfiguration).where(
                        DiscoverySearchConfiguration.user_id == user.id
                    )
                )
            )
            if item["key"] == "tecnoempleo"
            else False
        )
    return result


@router.post("/search-profile/generate", response_model=SearchProfileRead)
def generate_profile(db: Session = Depends(get_db)) -> DiscoverySearchProfile:
    user = current_development_user(db)
    try:
        result = upsert_search_profile(db, user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.commit()
    db.refresh(result)
    return result


@router.get("/search-profile", response_model=SearchProfileRead)
def get_profile(db: Session = Depends(get_db)) -> DiscoverySearchProfile:
    user = current_development_user(db)
    result = db.scalar(
        select(DiscoverySearchProfile).where(DiscoverySearchProfile.user_id == user.id)
    )
    if not result:
        raise HTTPException(status_code=404, detail="Search profile not found")
    return result


@router.put("/search-profile", response_model=SearchProfileRead)
def replace_profile(
    payload: SearchPreferences, db: Session = Depends(get_db)
) -> DiscoverySearchProfile:
    user = current_development_user(db)
    try:
        result = upsert_search_profile(db, user, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(result)
    return result


@router.post("/configurations", response_model=SearchConfigurationRead, status_code=201)
def add_configuration(
    payload: SearchConfigurationCreate, db: Session = Depends(get_db)
) -> DiscoverySearchConfiguration:
    user = current_development_user(db)
    try:
        result = create_configuration(db, user, payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    db.refresh(result)
    return result


@router.get("/configurations", response_model=list[SearchConfigurationRead])
def configurations(db: Session = Depends(get_db)) -> list[DiscoverySearchConfiguration]:
    user = current_development_user(db)
    return list(
        db.scalars(
            select(DiscoverySearchConfiguration)
            .where(DiscoverySearchConfiguration.user_id == user.id)
            .order_by(DiscoverySearchConfiguration.created_at)
        )
    )


@router.put("/configurations/{configuration_id}", response_model=SearchConfigurationRead)
def replace_configuration(
    configuration_id: str, payload: SearchConfigurationCreate, db: Session = Depends(get_db)
) -> DiscoverySearchConfiguration:
    user = current_development_user(db)
    current = db.scalar(
        select(DiscoverySearchConfiguration)
        .where(
            DiscoverySearchConfiguration.id == configuration_id,
            DiscoverySearchConfiguration.user_id == user.id,
        )
        .with_for_update()
    )
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
    from app.discovery import calculate_next_run

    current.next_run_at = calculate_next_run(current)
    write_audit(
        db, user.id, "discovery.configuration.updated", "discovery_search_configuration", current.id
    )
    db.commit()
    db.refresh(current)
    return current


@router.post("/search-runs", response_model=SearchRunRead, status_code=201)
def start_search(payload: SearchRunRequest, db: Session = Depends(get_db)) -> DiscoverySearchRun:
    user = current_development_user(db)
    config = db.scalar(
        select(DiscoverySearchConfiguration).where(
            DiscoverySearchConfiguration.id == payload.configuration_id,
            DiscoverySearchConfiguration.user_id == user.id,
        )
    )
    if not config:
        raise HTTPException(status_code=404, detail="Search configuration not found")
    try:
        result = run_search(db, user, config, get_settings())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(result)
    return result


@router.post("/scheduler/tick", response_model=list[str])
def scheduler_tick(db: Session = Depends(get_db)) -> list[str]:
    current_development_user(db)
    result = run_due_searches(db, get_settings())
    db.commit()
    return result


@router.get("/search-runs", response_model=list[SearchRunRead])
def search_runs(
    limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)
) -> list[DiscoverySearchRun]:
    user = current_development_user(db)
    return list(
        db.scalars(
            select(DiscoverySearchRun)
            .where(DiscoverySearchRun.user_id == user.id)
            .order_by(DiscoverySearchRun.started_at.desc())
            .limit(limit)
        )
    )


@router.post("/imports/manual", response_model=ImportResult, status_code=201)
def manual_import(payload: ManualJobImport, db: Session = Depends(get_db)) -> ImportResult:
    user = current_development_user(db)
    try:
        imported, duplicates, ids = import_manual_jobs(db, user, [payload], get_settings())
    except ValueError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    return ImportResult(imported=imported, duplicates=duplicates, job_ids=ids)


@router.post("/imports/csv", response_model=ImportResult, status_code=201)
def csv_import(payload: CsvImportRequest, db: Session = Depends(get_db)) -> ImportResult:
    user = current_development_user(db)
    try:
        items = parse_csv_import(payload.provider, payload.csv_text)
        imported, duplicates, ids = import_manual_jobs(db, user, items, get_settings())
    except ValueError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    return ImportResult(imported=imported, duplicates=duplicates, job_ids=ids)


@router.post("/imports/email", response_model=ImportResult, status_code=201)
def email_import(payload: EmailImportRequest, db: Session = Depends(get_db)) -> ImportResult:
    user = current_development_user(db)
    try:
        items = parse_email_import(payload.provider, payload.eml_text)
        imported, duplicates, ids = import_manual_jobs(db, user, items, get_settings())
    except ValueError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    return ImportResult(imported=imported, duplicates=duplicates, job_ids=ids)


@router.get("/matches", response_model=list[RankedJobRead])
def ranked_matches(
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
    db: Session = Depends(get_db),
) -> list[RankedJobRead]:
    user = current_development_user(db)
    statement = (
        select(DiscoveryMatchResult, Job)
        .join(Job, Job.id == DiscoveryMatchResult.job_id)
        .where(DiscoveryMatchResult.user_id == user.id, DiscoveryMatchResult.score >= min_score)
    )
    if not include_rejected:
        statement = statement.where(DiscoveryMatchResult.hard_rejected.is_(False))
    if country:
        statement = statement.where(Job.country == country.upper())
    if provider:
        statement = statement.where(Job.source == provider)
    if recommendation:
        statement = statement.where(DiscoveryMatchResult.recommendation == recommendation)
    if city:
        statement = statement.where(Job.city.ilike(city))
    if company:
        statement = statement.where(Job.company.ilike(f"%{company}%"))
    if role:
        statement = statement.where(Job.title.ilike(f"%{role}%"))
    if seniority:
        statement = statement.where(Job.seniority.ilike(seniority))
    if workplace_type:
        statement = statement.where(Job.workplace_type.ilike(workplace_type))
    if industry:
        statement = statement.where(Job.industry.ilike(industry))
    if minimum_salary is not None:
        statement = statement.where(
            or_(Job.salary_max >= minimum_salary, Job.salary_min >= minimum_salary)
        )
    if posted_after:
        statement = statement.where(Job.posted_at >= posted_after)
    rows = db.execute(
        statement.order_by(DiscoveryMatchResult.score.desc(), Job.posted_at.desc()).limit(limit)
    ).all()
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
def match_detail(match_id: str, db: Session = Depends(get_db)) -> RankedJobRead:
    user = current_development_user(db)
    row = db.execute(
        select(DiscoveryMatchResult, Job)
        .join(Job)
        .where(DiscoveryMatchResult.id == match_id, DiscoveryMatchResult.user_id == user.id)
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Match not found")
    match, job = row
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
def match_action(
    match_id: str, payload: MatchAction, db: Session = Depends(get_db)
) -> dict[str, str]:
    user = current_development_user(db)
    match = db.scalar(
        select(DiscoveryMatchResult)
        .where(DiscoveryMatchResult.id == match_id, DiscoveryMatchResult.user_id == user.id)
        .with_for_update()
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if payload.action == "PREPARE_APPLICATION":
        application = prepare_application(db, user, match)
        result = {"state": match.user_state, "application_id": application.id}
    else:
        match.user_state = (
            payload.action.removesuffix("E") + "ED" if payload.action == "SAVE" else "REJECTED"
        )
        write_audit(
            db,
            user.id,
            f"discovery.match.{payload.action.lower()}",
            "discovery_match_result",
            match.id,
        )
        result = {"state": match.user_state}
    db.commit()
    return result


@router.get("/notifications", response_model=list[NotificationRead])
def notifications(
    unread_only: bool = False, db: Session = Depends(get_db)
) -> list[DiscoveryNotification]:
    user = current_development_user(db)
    statement = select(DiscoveryNotification).where(DiscoveryNotification.user_id == user.id)
    if unread_only:
        statement = statement.where(DiscoveryNotification.read_at.is_(None))
    return list(db.scalars(statement.order_by(DiscoveryNotification.created_at.desc()).limit(100)))


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
def read_notification(notification_id: str, db: Session = Depends(get_db)) -> DiscoveryNotification:
    user = current_development_user(db)
    item = db.scalar(
        select(DiscoveryNotification).where(
            DiscoveryNotification.id == notification_id, DiscoveryNotification.user_id == user.id
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="Notification not found")
    item.read_at = datetime.now(UTC)
    db.commit()
    db.refresh(item)
    return item
