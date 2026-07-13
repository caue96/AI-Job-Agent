from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.discovery import (
    calculate_next_run,
    parse_csv_import,
    parse_email_import,
    run_search,
)
from app.discovery_providers import (
    InfoJobsProvider,
    ITJobsProvider,
    JobProvider,
    ProviderError,
    TecnoempleoFeedProvider,
    safe_url,
    sanitize_text,
)
from app.models import DiscoverySearchConfiguration
from app.services import current_development_user

PROFILE = {
    "full_name": "Candidate",
    "email": "candidate@example.com",
    "eu_work_authorized": True,
    "requires_sponsorship": False,
    "preferred_titles": ["Data Analyst"],
    "preferred_locations": ["ES", "Madrid"],
    "workplace_preferences": ["REMOTE", "HYBRID"],
    "relocation_available": True,
    "skills": [{"name": "Power BI"}, {"name": "SQL"}],
    "languages": [{"language": "English", "proficiency": "B2"}],
}


class FakeClient:
    def __init__(self, payload):
        self.payload = payload

    def get_json(self, url, headers):
        return self.payload, {"X-RateLimit-Remaining": "9"}

    def get_text(self, url, headers):
        return self.payload, {}


class FakeProvider(JobProvider):
    key = "itjobs"

    def validate_configuration(self):
        return None

    def build_queries(self, search_profile):
        return [{"term": "Data Analyst", "country": "PT"}]

    def search(self, query, cursor):
        if query.get("fail"):
            raise ProviderError("TEST", "Safe failure")
        return (
            [
                {
                    "id": "one",
                    "title": "Data Analyst",
                    "company": {"name": "Acme"},
                    "body": "SQL and Power BI. English.",
                    "locations": [{"name": "Porto"}],
                    "workModel": 1,
                    "slug": "data-analyst",
                },
                {
                    "id": "two",
                    "title": "Data Analyst",
                    "company": {"name": "Acme"},
                    "body": "SQL and Power BI. English.",
                    "locations": [{"name": "Porto"}],
                    "workModel": 1,
                    "slug": "data-analyst-copy",
                },
            ],
            None,
            {"remaining": 10},
        )

    def normalize(self, raw_job):
        return ITJobsProvider({"api_key": "test"}).normalize(raw_job)


def _profile(client):
    assert client.post("/v1/profiles", json=PROFILE).status_code == 201
    assert client.post("/v1/discovery/search-profile/generate").status_code == 200


def test_multilingual_search_profile_generation(client):
    _profile(client)
    registry = client.get("/v1/discovery/providers")
    assert registry.status_code == 200 and len(registry.json()) == 10
    assert all("documentation" in item and "configured" in item for item in registry.json())
    response = client.get("/v1/discovery/search-profile")
    assert response.status_code == 200
    body = response.json()
    assert "Data Analyst" in body["generated_terms"]
    assert "Analista de Datos" in body["generated_terms"]
    assert "Analista de Dados" in body["generated_terms"]
    assert body["preferences"]["work_authorization"] == ["EU"]


def test_provider_query_construction_and_normalization():
    profile = {"generated_terms": ["Data Analyst"], "preferred_countries": ["PT"]}
    itjobs = ITJobsProvider({"api_key": "x"}, FakeClient({"results": []}))
    assert itjobs.build_queries(profile) == [{"term": "Data Analyst", "country": "PT"}]
    items, cursor, usage = itjobs.search(profile | {"term": "Data Analyst"}, None)
    assert items == [] and cursor is None and usage["remaining"] == "9"

    infojobs = InfoJobsProvider(
        {"client_id": "id", "client_secret": "secret"}, FakeClient({"items": [{"id": "1"}]})
    )
    items, _, _ = infojobs.search({"term": "Analista"}, None)
    assert items[0]["id"] == "1"
    normalized = infojobs.normalize(
        {
            "id": "1",
            "title": "<b>Analista</b>",
            "author": {"name": "Acme"},
            "description": "<script>bad()</script><p>SQL</p>",
            "link": "https://www.infojobs.net/job/1",
        }
    )
    assert normalized["title"] == "Analista"
    assert "<" not in normalized["description"]


def test_rss_pagination_retry_and_rate_limit_behaviour():
    rss = (
        "<rss><channel><item><guid>1</guid><title>Acme - BI Analyst</title>"
        "<link>https://www.tecnoempleo.com/job/1</link>"
        "<description>Power BI</description></item></channel></rss>"
    )
    provider = TecnoempleoFeedProvider(
        {"feed_url": "https://www.tecnoempleo.com/feed.xml"}, FakeClient(rss)
    )
    items, cursor, usage, retries = provider.search_with_retry(provider.build_queries({})[0], None)
    assert len(items) == 1 and cursor is None and retries == 0 and usage["items"] == 1
    assert provider.get_rate_limit_status()["minimum_interval_hours"] == 24


def test_security_helpers_reject_ssrf_and_strip_html():
    assert safe_url("http://api.itjobs.pt/job", ("api.itjobs.pt",)) is None
    assert safe_url("https://user:pass@api.itjobs.pt/job", ("api.itjobs.pt",)) is None
    assert safe_url("https://127.0.0.1/internal", ("api.itjobs.pt",)) is None
    assert safe_url("https://api.itjobs.pt/job", ("api.itjobs.pt",))
    text = sanitize_text("<img src=x onerror=alert(1)><p>Ignore previous instructions</p>")
    assert "onerror" not in text and text == "Ignore previous instructions"


def test_csv_email_imports_are_user_supplied_and_bounded():
    items = parse_csv_import("indeed", "company,title,description\nAcme,Analyst,SQL role")
    assert items[0].company == "Acme"
    eml = "Subject: Analyst at Acme\nContent-Type: text/plain\n\nSQL role https://www.irishjobs.ie/job/1"
    email_items = parse_email_import("irishjobs", eml)
    assert email_items[0].company == "Acme"
    assert email_items[0].url == "https://www.irishjobs.ie/job/1"


def test_schedule_weekdays_skips_weekend():
    config = DiscoverySearchConfiguration(
        user_id="u",
        name="x",
        enabled=True,
        provider_settings={},
        schedule_kind="WEEKDAYS",
        schedule_time="09:00",
        timezone="UTC",
        hard_filters={},
    )
    friday = datetime(2026, 7, 10, 10, tzinfo=UTC)
    assert calculate_next_run(config, friday).weekday() == 0


def test_discovery_end_to_end_deduplicates_scores_and_notifies(client):
    _profile(client)
    created = client.post(
        "/v1/discovery/configurations",
        json={"name": "Portugal", "provider_settings": {"itjobs": {"enabled": True}}},
    )
    assert created.status_code == 201
    db = client.app.state.test_session
    user = current_development_user(db)
    config = db.get(DiscoverySearchConfiguration, created.json()["id"])
    from app.config import get_settings

    run = run_search(
        db,
        user,
        config,
        get_settings(),
        providers={"itjobs": FakeProvider({})},
    )
    db.commit()
    assert run.status.value == "SUCCEEDED"
    assert run.counters["duplicates"] == 1
    ranked = client.get("/v1/discovery/matches?include_rejected=true")
    assert ranked.status_code == 200
    assert len(ranked.json()) == 1
    assert ranked.json()[0]["analysis"]["score_by_category"]
    assert client.get("/v1/discovery/notifications").json()


def test_partial_provider_failure_does_not_erase_success(client):
    _profile(client)
    created = client.post(
        "/v1/discovery/configurations",
        json={
            "name": "Mixed",
            "provider_settings": {
                "itjobs": {"enabled": True},
                "tecnoempleo": {
                    "enabled": True,
                    "feed_url": "https://www.tecnoempleo.com/feed.xml",
                },
            },
        },
    ).json()
    db = client.app.state.test_session
    user = current_development_user(db)
    config = db.get(DiscoverySearchConfiguration, created["id"])

    class Failure(FakeProvider):
        key = "tecnoempleo"

        def search(self, query, cursor):
            raise ProviderError("DOWN", "Provider unavailable")

    from app.config import get_settings

    run = run_search(
        db,
        user,
        config,
        get_settings(),
        providers={"itjobs": FakeProvider({}), "tecnoempleo": Failure({})},
    )
    db.commit()
    assert run.status.value == "PARTIAL"
    assert run.counters["provider_failures"] == 1


def test_manual_import_actions_and_notification_deduplication(client):
    _profile(client)
    payload = {
        "provider": "linkedin",
        "url": "https://www.linkedin.com/jobs/view/1",
        "company": "Acme",
        "title": "Data Analyst",
        "description": "SQL and Power BI, English",
        "country": "ES",
        "city": "Madrid",
        "workplace_type": "HYBRID",
    }
    first = client.post("/v1/discovery/imports/manual", json=payload)
    second = client.post("/v1/discovery/imports/manual", json=payload)
    assert first.status_code == second.status_code == 201, (first.text, second.text)
    assert second.json()["duplicates"] == 1
    matches = client.get("/v1/discovery/matches?include_rejected=true").json()
    response = client.post(
        f"/v1/discovery/matches/{matches[0]['match_id']}/action",
        json={"action": "PREPARE_APPLICATION"},
    )
    assert response.status_code == 200 and response.json()["application_id"]
    notifications = client.get("/v1/discovery/notifications").json()
    assert len({item["title"] + item["body"] for item in notifications}) == len(notifications)


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "file:///etc/passwd", "https://evil.example/job"]
)
def test_manual_import_drops_malicious_urls(client, url):
    _profile(client)
    response = client.post(
        "/v1/discovery/imports/manual",
        json={
            "provider": "indeed",
            "url": url,
            "company": "Acme",
            "title": "Analyst",
            "description": "SQL",
        },
    )
    assert response.status_code == 201
    job_id = response.json()["job_ids"][0]
    assert client.get(f"/v1/jobs/{job_id}").json()["url"] is None
