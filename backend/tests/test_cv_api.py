from __future__ import annotations

from io import BytesIO

from pypdf import PdfWriter
from sqlalchemy import select

from app.models import CandidateProfile, CvImport, User


def text_pdf(*lines: str) -> bytes:
    escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
    content = (
        "BT /F1 12 Tf 72 750 Td 15 TL " + " ".join(f"({line}) Tj T*" for line in escaped) + " ET"
    )
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content.encode('latin-1'))} >>\nstream\n{content}\nendstream",
    ]
    result = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(result))
        result.extend(f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(result)


def upload(
    client, content: bytes, filename: str = "resume.pdf", media_type: str = "application/pdf"
):
    return client.post("/v1/cv-imports", files={"file": (filename, content, media_type)})


def test_successful_upload_review_edit_confirm_export_and_delete(client):
    response = upload(
        client,
        text_pdf(
            "Jane Candidate",
            "Senior Python Engineer",
            "jane@example.com",
            "+351 912 345 678",
            "SKILLS",
            "Python, FastAPI, PostgreSQL, Docker",
        ),
    )
    assert response.status_code == 201, response.text
    imported = response.json()
    assert imported["status"] == "AWAITING_REVIEW"
    assert imported["draft"]["personal"]["email"]["value"] == "jane@example.com"
    assert imported["file_available"] is True
    assert "extracted_pages" not in imported
    import_id = imported["id"]

    listing = client.get("/v1/cv-imports").json()
    assert [item["id"] for item in listing] == [import_id]
    comparison = client.get(f"/v1/cv-imports/{import_id}/compare").json()
    assert comparison == {"profile_exists": False, "conflicts": [], "additions": []}

    draft = imported["draft"]
    draft["personal"]["full_name"]["value"] = "Jane A. Candidate"
    edited = client.patch(f"/v1/cv-imports/{import_id}", json={"draft": draft})
    assert edited.status_code == 200
    assert edited.json()["validation"]["user_edited"] is True
    assert "personal.full_name" in edited.json()["validation"]["user_confirmed_fields"]
    assert edited.json()["draft"]["personal"]["full_name"]["evidence"][0]["method"] == "user"

    confirmed = client.post(
        f"/v1/cv-imports/{import_id}/confirm",
        json={"strategy": "replace", "accept_conflicts": False},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["version"] == 1
    assert client.get(f"/v1/cv-imports/{import_id}").json()["status"] == "PROFILE_SAVED"
    profile = client.get("/v1/profiles/me").json()
    assert profile["full_name"] == "Jane A. Candidate"
    assert {skill["name"] for skill in profile["skills"]} >= {"Python", "Fastapi", "Postgresql"}
    assert len(client.get(f"/v1/cv-imports/{import_id}/export").json()["versions"]) == 1

    assert client.delete(f"/v1/cv-imports/{import_id}/file").status_code == 204
    assert client.get(f"/v1/cv-imports/{import_id}").json()["file_available"] is False
    assert client.delete(f"/v1/cv-imports/{import_id}").status_code == 204
    assert client.get(f"/v1/cv-imports/{import_id}").status_code == 404


def test_confirmation_rejects_invalid_reviewed_email_and_profile_can_be_deleted(client):
    imported = upload(
        client,
        text_pdf(
            "Jane Candidate",
            "jane@example.com",
            "Python developer with extensive platform and distributed systems experience",
        ),
    ).json()
    draft = imported["draft"]
    draft["personal"]["email"]["value"] = "not-an-email"
    assert (
        client.patch(f"/v1/cv-imports/{imported['id']}", json={"draft": draft}).status_code == 200
    )
    blocked = client.post(
        f"/v1/cv-imports/{imported['id']}/confirm",
        json={"strategy": "replace", "accept_conflicts": False},
    )
    assert blocked.status_code == 409
    assert "valid email" in blocked.json()["detail"]

    profile = client.post(
        "/v1/profiles", json={"full_name": "Delete Me", "email": "delete@example.com"}
    )
    assert profile.status_code == 201
    assert client.delete("/v1/profiles/me").status_code == 204
    assert client.get("/v1/profiles/me").status_code == 404


def test_rejects_non_pdf_extension_mime_signature_empty_and_corrupt(client):
    cases = [
        ("resume.txt", b"%PDF-1.4", "application/pdf", ".pdf extension"),
        ("resume.pdf", b"%PDF-1.4", "text/plain", "PDF media type"),
        ("resume.pdf", b"not a pdf", "application/pdf", "signature"),
        ("resume.pdf", b"", "application/pdf", "empty"),
        ("resume.pdf", b"%PDF-1.4 invalid", "application/pdf", "corrupt or unreadable"),
    ]
    for filename, content, media_type, message in cases:
        response = upload(client, content, filename, media_type)
        assert response.status_code == 422
        assert message in response.json()["detail"]


def test_detects_password_protected_and_scanned_pdfs(client):
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    encrypted = BytesIO()
    writer.write(encrypted)
    response = upload(client, encrypted.getvalue(), "protected.pdf")
    assert response.status_code == 422
    assert "Password-protected" in response.json()["detail"]

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    scanned = BytesIO()
    writer.write(scanned)
    response = upload(client, scanned.getvalue(), "scan.pdf")
    assert response.status_code == 201
    assert response.json()["status"] == "TEXT_EXTRACTED"
    assert response.json()["validation"]["scanned_likely"] is True
    assert response.json()["draft"] is None


def test_same_original_filename_uses_distinct_private_storage_keys(client):
    content = text_pdf("Jane Candidate", "jane@example.com", "Python developer with experience")
    first = upload(client, content).json()
    second = upload(client, content).json()
    db = client.app.state.test_session
    records = list(db.scalars(select(CvImport).order_by(CvImport.created_at)))
    assert first["original_filename"] == second["original_filename"] == "resume.pdf"
    assert records[0].storage_key != records[1].storage_key
    assert all(record.storage_key != record.original_filename for record in records)


def test_merge_requires_explicit_conflict_confirmation(client):
    profile = client.post(
        "/v1/profiles",
        json={"full_name": "Existing Name", "email": "existing@example.com"},
    )
    assert profile.status_code == 201
    imported = upload(
        client,
        text_pdf(
            "Imported Name",
            "imported@example.com",
            "Python developer with extensive distributed systems and platform "
            "engineering experience",
        ),
    ).json()
    import_id = imported["id"]
    comparison = client.get(f"/v1/cv-imports/{import_id}/compare").json()
    assert {item["field"] for item in comparison["conflicts"]} == {"full_name", "email"}

    rejected = client.post(
        f"/v1/cv-imports/{import_id}/confirm",
        json={"strategy": "merge", "accept_conflicts": False},
    )
    assert rejected.status_code == 409
    accepted = client.post(
        f"/v1/cv-imports/{import_id}/confirm",
        json={"strategy": "merge", "accept_conflicts": True},
    )
    assert accepted.status_code == 200
    db = client.app.state.test_session
    saved = db.scalar(select(CandidateProfile))
    assert saved.full_name == "Existing Name"


def test_cv_import_is_scoped_to_current_user(client):
    imported = upload(
        client, text_pdf("Jane Candidate", "jane@example.com", "Python developer with experience")
    ).json()
    db = client.app.state.test_session
    record = db.get(CvImport, imported["id"])
    other = User(email="other@example.invalid")
    db.add(other)
    db.flush()
    record.user_id = other.id
    db.commit()
    assert client.get(f"/v1/cv-imports/{record.id}").status_code == 404
