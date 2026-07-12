def profile_payload() -> dict:
    return {"full_name": "Ana Silva", "email": "ana@example.com"}


def job_payload() -> dict:
    return {
        "source": "manual",
        "company": "Example",
        "title": "Engineer",
        "description": "Build reliable systems.",
    }


def test_unknown_request_fields_are_rejected(client):
    response = client.post("/v1/profiles", json=profile_payload() | {"is_admin": True})

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


def test_profile_patch_rejects_null_for_required_database_field(client):
    assert client.post("/v1/profiles", json=profile_payload()).status_code == 201

    response = client.patch("/v1/profiles/me", json={"full_name": None})

    assert response.status_code == 422


def test_nested_input_length_is_bounded(client):
    response = client.post("/v1/jobs", json=job_payload() | {"requirements": ["x" * 501]})

    assert response.status_code == 422


def test_non_http_job_url_is_rejected(client):
    response = client.post("/v1/jobs", json=job_payload() | {"url": "file:///etc/passwd"})

    assert response.status_code == 422


def test_sql_metacharacters_are_stored_as_data(client):
    malicious_title = "Engineer'); DROP TABLE jobs; --"
    created = client.post("/v1/jobs", json=job_payload() | {"title": malicious_title})

    assert created.status_code == 201
    assert created.json()["title"] == malicious_title
    jobs = client.get("/v1/jobs")
    assert jobs.status_code == 200
    assert jobs.json()[0]["title"] == malicious_title


def test_invalid_employment_date_range_is_rejected(client):
    response = client.post(
        "/v1/profiles",
        json=profile_payload()
        | {
            "employment": [
                {
                    "company": "Example",
                    "title": "Engineer",
                    "start_date": "2025-01-01",
                    "end_date": "2024-01-01",
                }
            ]
        },
    )

    assert response.status_code == 422


def test_strings_are_trimmed_and_whitespace_only_names_are_rejected(client):
    created = client.post(
        "/v1/profiles", json={"full_name": "  Ana Silva  ", "email": "ana@example.com"}
    )

    assert created.status_code == 201
    assert created.json()["full_name"] == "Ana Silva"

    other_client_response = client.post(
        "/v1/jobs",
        json=job_payload() | {"source": "   ", "title": "Another role"},
    )
    assert other_client_response.status_code == 422


def test_duplicate_profile_facts_are_rejected_case_insensitively(client):
    response = client.post(
        "/v1/profiles",
        json=profile_payload() | {"skills": [{"name": "Python"}, {"name": " python "}]},
    )

    assert response.status_code == 422
    assert "Duplicate skill entries" in response.text


def test_country_and_currency_codes_must_be_alphabetic(client):
    response = client.post(
        "/v1/jobs", json=job_payload() | {"country": "12", "salary_currency": "1$3"}
    )

    assert response.status_code == 422
