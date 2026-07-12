import pytest
from fastapi import HTTPException

from app.ai import AIProviderError
from app.main import app, get_ai_provider


def job_payload() -> dict:
    return {
        "source": "manual",
        "external_job_id": "errors-1",
        "url": "https://jobs.example.com/errors-1",
        "company": "Example",
        "title": "Engineer",
        "description": "Build reliable systems.",
    }


def test_missing_resources_and_duplicate_ownership_are_rejected(client):
    assert client.get("/v1/profiles/me").status_code == 404
    assert client.get("/v1/jobs/missing").status_code == 404
    assert client.post("/v1/applications", json={"job_id": "missing"}).status_code == 404
    assert client.post("/v1/applications/missing/analyze").status_code == 404
    assert client.get("/v1/applications/missing/documents").status_code == 404
    assert (
        client.post(
            "/v1/applications/missing/transition", json={"to_status": "ANALYZED"}
        ).status_code
        == 404
    )
    assert client.get("/v1/applications/missing/history").status_code == 404

    profile = {
        "full_name": "Ana Silva",
        "email": "ana@example.com",
        "employment": [{"company": "Example", "title": "Engineer"}],
    }
    assert client.post("/v1/profiles", json=profile).status_code == 201
    assert client.post("/v1/profiles", json=profile).status_code == 409

    job_id = client.post("/v1/jobs", json=job_payload()).json()["id"]
    assert client.post("/v1/applications", json={"job_id": job_id}).status_code == 201
    assert client.post("/v1/applications", json={"job_id": job_id}).status_code == 409


def test_analysis_and_generation_reject_ineligible_state(client):
    job_id = client.post("/v1/jobs", json=job_payload()).json()["id"]
    application_id = client.post("/v1/applications", json={"job_id": job_id}).json()["id"]

    assert client.post(f"/v1/applications/{application_id}/analyze").status_code == 409
    assert (
        client.post(
            f"/v1/applications/{application_id}/documents/generate",
            json={"language": "en"},
        ).status_code
        == 409
    )

    profile = {"full_name": "Ana Silva", "email": "ana@example.com"}
    assert client.post("/v1/profiles", json=profile).status_code == 201
    assert client.post(f"/v1/applications/{application_id}/analyze").status_code == 200
    assert (
        client.post(
            f"/v1/applications/{application_id}/transition",
            json={"to_status": "SHORTLISTED"},
        ).status_code
        == 200
    )
    assert client.post(f"/v1/applications/{application_id}/analyze").status_code == 409


def test_duplicate_job_messages_preserve_priority(client):
    assert client.post("/v1/jobs", json=job_payload()).status_code == 201

    source_duplicate = job_payload() | {
        "url": "https://jobs.example.com/source-duplicate",
        "description": "Different content.",
    }
    response = client.post("/v1/jobs", json=source_duplicate)
    assert response.status_code == 409
    assert response.json()["detail"] == "Duplicate source and external job ID"

    content_duplicate = job_payload() | {
        "source": "other",
        "external_job_id": "other-1",
        "url": "https://jobs.example.com/content-duplicate",
    }
    response = client.post("/v1/jobs", json=content_duplicate)
    assert response.status_code == 409
    assert response.json()["detail"] == "Duplicate job content"


def test_ai_provider_dependency_translates_configuration_error(monkeypatch):
    get_ai_provider.cache_clear()

    def fail_provider(_settings):
        raise ValueError("bad provider")

    monkeypatch.setattr("app.main.build_provider", fail_provider)

    with pytest.raises(HTTPException) as raised:
        get_ai_provider()

    assert raised.value.status_code == 503
    assert raised.value.detail == "bad provider"
    get_ai_provider.cache_clear()


def test_generation_translates_provider_failure_without_leaking_details(client):
    assert (
        client.post(
            "/v1/profiles", json={"full_name": "Ana Silva", "email": "ana@example.com"}
        ).status_code
        == 201
    )
    job_id = client.post("/v1/jobs", json=job_payload()).json()["id"]
    application_id = client.post("/v1/applications", json={"job_id": job_id}).json()["id"]
    for target in ["ANALYZED", "SHORTLISTED"]:
        assert (
            client.post(
                f"/v1/applications/{application_id}/transition", json={"to_status": target}
            ).status_code
            == 200
        )

    class FailingProvider:
        def select_plan(self, **_kwargs):
            raise AIProviderError("provider request contained sensitive details")

    app.dependency_overrides[get_ai_provider] = FailingProvider
    response = client.post(
        f"/v1/applications/{application_id}/documents/generate", json={"language": "en"}
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Document generation provider is temporarily unavailable"}
