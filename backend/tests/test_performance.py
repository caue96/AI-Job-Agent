from sqlalchemy import event

from app.ai import MockAIProvider
from app.main import app, get_ai_provider


def job_payload() -> dict:
    return {
        "source": "manual",
        "external_job_id": "performance-1",
        "url": "https://jobs.example.com/performance-1",
        "company": "Example",
        "title": "Performance Engineer",
        "description": "Build fast and reliable services.",
    }


def test_job_duplicate_detection_uses_one_lookup_query(client):
    statements: list[str] = []
    engine = client.app.state.test_engine

    def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        response = client.post("/v1/jobs", json=job_payload())
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    assert response.status_code == 201
    job_reads = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT") and "FROM jobs" in statement
    ]
    assert len(job_reads) == 1


def test_large_api_responses_are_compressed(client):
    payload = job_payload() | {"external_job_id": "large-1", "description": "x" * 4000}
    assert client.post("/v1/jobs", json=payload).status_code == 201

    response = client.get("/v1/jobs", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"


def test_ai_provider_runs_without_an_open_database_transaction(client):
    class ObservingProvider(MockAIProvider):
        transaction_was_open: bool | None = None

        def select_plan(self, **kwargs):
            self.transaction_was_open = app.state.test_session.in_transaction()
            return super().select_plan(**kwargs)

    provider = ObservingProvider()
    app.dependency_overrides[get_ai_provider] = lambda: provider
    profile = {
        "full_name": "Ana Silva",
        "email": "ana@example.com",
        "eu_work_authorized": True,
        "requires_sponsorship": False,
        "skills": [{"name": "Python", "years_experience": 8}],
    }
    assert client.post("/v1/profiles", json=profile).status_code == 201
    job_id = client.post("/v1/jobs", json=job_payload()).json()["id"]
    application_id = client.post("/v1/applications", json={"job_id": job_id}).json()["id"]
    for target in ("ANALYZED", "SHORTLISTED"):
        assert (
            client.post(
                f"/v1/applications/{application_id}/transition",
                json={"to_status": target},
            ).status_code
            == 200
        )

    response = client.post(
        f"/v1/applications/{application_id}/documents/generate",
        json={"language": "en"},
    )

    assert response.status_code == 201
    assert provider.transaction_was_open is False
