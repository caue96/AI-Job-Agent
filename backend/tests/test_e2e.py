def candidate_profile() -> dict:
    return {
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


def job() -> dict:
    return {
        "source": "manual",
        "external_job_id": "e2e-1",
        "url": "https://jobs.example.com/data-analyst",
        "company": "Example Logistics",
        "title": "Data Analyst",
        "country": "PT",
        "city": "Porto",
        "workplace_type": "HYBRID",
        "description": "Analyze logistics operations with Python and SQL.",
        "requirements": ["Python", "SQL", "English"],
        "sponsorship_information": "No sponsorship. Right to work required.",
    }


def transition(client, application_id: str, target: str, approved_by_user: bool = False):
    response = client.post(
        f"/v1/applications/{application_id}/transition",
        json={"to_status": target, "approved_by_user": approved_by_user},
    )
    assert response.status_code == 200, response.text


def test_manual_approval_happy_path(client):
    assert client.post("/v1/profiles", json=candidate_profile()).status_code == 201
    job_id = client.post("/v1/jobs", json=job()).json()["id"]
    application_id = client.post("/v1/applications", json={"job_id": job_id}).json()["id"]

    assert client.post(f"/v1/applications/{application_id}/analyze").status_code == 200
    transition(client, application_id, "SHORTLISTED")
    generated = client.post(
        f"/v1/applications/{application_id}/documents/generate", json={"language": "en"}
    )
    assert generated.status_code == 201
    assert generated.json()["validation"]["valid"] is True
    transition(client, application_id, "AWAITING_REVIEW")
    transition(client, application_id, "APPROVED")
    transition(client, application_id, "READY_TO_SUBMIT", approved_by_user=True)
    transition(client, application_id, "SUBMITTED", approved_by_user=True)

    application = client.get("/v1/applications").json()[0]
    assert application["status"] == "SUBMITTED"
    history = client.get(f"/v1/applications/{application_id}/history").json()
    assert history[-1]["to_status"] == "SUBMITTED"


def test_invalid_state_jump_is_rejected(client):
    job_id = client.post("/v1/jobs", json=job()).json()["id"]
    application_id = client.post("/v1/applications", json={"job_id": job_id}).json()["id"]

    response = client.post(
        f"/v1/applications/{application_id}/transition", json={"to_status": "SHORTLISTED"}
    )

    assert response.status_code == 409
