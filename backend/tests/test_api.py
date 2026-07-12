def sample_job() -> dict:
    return {
        "source": "manual",
        "external_job_id": "abc-1",
        "url": "https://careers.example.com/jobs/1?tracking=a",
        "company": "Example",
        "title": "Data Analyst",
        "country": "PT",
        "city": "Porto",
        "workplace_type": "HYBRID",
        "description": "Use Python and SQL to build reliable reports.",
        "requirements": ["Python", "SQL"],
    }


def test_health_and_profile_lifecycle(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/openapi.json").json()["info"]["version"] == "1.0.0"
    payload = {
        "full_name": "Ana Silva",
        "email": "ana@example.com",
        "citizenships": ["Brazil", "Portugal"],
        "eu_work_authorized": True,
        "requires_sponsorship": False,
        "skills": [{"name": "Python", "years_experience": 8}],
        "languages": [{"language": "English", "proficiency": "advanced"}],
    }
    created = client.post("/v1/profiles", json=payload)
    assert created.status_code == 201
    assert (
        client.patch("/v1/profiles/me", json={"relocation_available": True}).json()[
            "relocation_available"
        ]
        is True
    )


def test_duplicate_job_is_rejected(client):
    assert client.post("/v1/jobs", json=sample_job()).status_code == 201
    duplicate = sample_job() | {
        "external_job_id": "different-id",
        "url": "https://careers.example.com/jobs/1/",
    }
    response = client.post("/v1/jobs", json=duplicate)
    assert response.status_code == 409


def test_application_requires_explicit_approval_before_submission(client):
    job_id = client.post("/v1/jobs", json=sample_job()).json()["id"]
    app_id = client.post("/v1/applications", json={"job_id": job_id}).json()["id"]
    for target in ["ANALYZED", "SHORTLISTED", "DOCUMENTS_PREPARED", "AWAITING_REVIEW", "APPROVED"]:
        assert (
            client.post(
                f"/v1/applications/{app_id}/transition", json={"to_status": target}
            ).status_code
            == 200
        )
    assert (
        client.post(
            f"/v1/applications/{app_id}/transition", json={"to_status": "READY_TO_SUBMIT"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/v1/applications/{app_id}/transition",
            json={"to_status": "READY_TO_SUBMIT", "approved_by_user": True},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/v1/applications/{app_id}/transition", json={"to_status": "SUBMITTED"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/v1/applications/{app_id}/transition",
            json={"to_status": "SUBMITTED", "approved_by_user": True},
        ).status_code
        == 200
    )
    history = client.get(f"/v1/applications/{app_id}/history").json()
    assert history[-1]["to_status"] == "SUBMITTED"


def test_analysis_persists_explainable_score_and_advances_to_analyzed(client):
    profile = {
        "full_name": "Ana Silva",
        "email": "ana@example.com",
        "citizenships": ["Portugal"],
        "eu_work_authorized": True,
        "requires_sponsorship": False,
        "total_years_experience": 8,
        "preferred_titles": ["Data Analyst"],
        "preferred_locations": ["Porto"],
        "skills": [
            {"name": "Python", "years_experience": 8},
            {"name": "SQL", "years_experience": 8},
        ],
        "languages": [{"language": "English", "proficiency": "advanced"}],
    }
    assert client.post("/v1/profiles", json=profile).status_code == 201
    imported = sample_job() | {
        "requirements": ["Python", "SQL", "English"],
        "language": "English",
        "sponsorship_information": "No sponsorship. Right to work required.",
    }
    job_id = client.post("/v1/jobs", json=imported).json()["id"]
    application_id = client.post("/v1/applications", json={"job_id": job_id}).json()["id"]

    response = client.post(f"/v1/applications/{application_id}/analyze")

    assert response.status_code == 200
    assert response.json()["overall_score"] > 0
    assert response.json()["recommendation"] in {"STRONG_MATCH", "POSSIBLE_MATCH"}
    application = client.get("/v1/applications").json()[0]
    assert application["status"] == "ANALYZED"
    assert application["match_analysis"]["overall_score"] == response.json()["overall_score"]


def test_mock_generation_creates_a_valid_versioned_document(client):
    profile = {
        "full_name": "Ana Silva",
        "email": "ana@example.com",
        "eu_work_authorized": True,
        "requires_sponsorship": False,
        "preferred_titles": ["Data Analyst"],
        "preferred_locations": ["Porto"],
        "skills": [{"name": "Python", "years_experience": 8}],
        "languages": [{"language": "English", "proficiency": "advanced"}],
    }
    assert client.post("/v1/profiles", json=profile).status_code == 201
    job_id = client.post("/v1/jobs", json=sample_job()).json()["id"]
    application_id = client.post("/v1/applications", json={"job_id": job_id}).json()["id"]
    assert (
        client.post(
            f"/v1/applications/{application_id}/transition", json={"to_status": "ANALYZED"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/v1/applications/{application_id}/transition", json={"to_status": "SHORTLISTED"}
        ).status_code
        == 200
    )

    response = client.post(
        f"/v1/applications/{application_id}/documents/generate", json={"language": "en"}
    )

    assert response.status_code == 201
    document = response.json()
    assert document["version"] == 1
    assert document["status"] == "VALID"
    assert document["validation"]["valid"] is True
    assert document["content"]["professional_summary"]
    assert client.get("/v1/applications").json()[0]["status"] == "DOCUMENTS_PREPARED"

    second = client.post(
        f"/v1/applications/{application_id}/documents/generate", json={"language": "en"}
    )
    assert second.status_code == 201
    assert second.json()["version"] == 2
    assert len(client.get(f"/v1/applications/{application_id}/documents").json()) == 2
    latest = client.get(f"/v1/applications/{application_id}/documents?latest_valid=true").json()
    assert [item["version"] for item in latest] == [2]
