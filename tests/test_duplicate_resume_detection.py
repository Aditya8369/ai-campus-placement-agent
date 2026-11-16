import io
import pytest
from app import app
from utils.duplicate_resume_service import DuplicateResumeService, duplicate_resume_service


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_unique_then_exact_duplicate():
    service = DuplicateResumeService()
    student_id = "test_dup_student_1"
    file_bytes = b"Sample resume content for John Doe. Education: B.Tech Computer Science."

    # First upload: Should be unique
    first_check = service.check_for_duplicate(
        student_id=student_id,
        file_bytes=file_bytes,
        filename="john_doe_resume.pdf"
    )
    assert first_check["is_duplicate"] is False
    assert first_check["duplicate_type"] == "none"

    # Save fingerprint
    rec_id = service.record_upload_fingerprint(
        student_id=student_id,
        file_bytes=file_bytes,
        filename="john_doe_resume.pdf",
        extracted_text="Sample resume content for John Doe. Education: B.Tech Computer Science."
    )
    assert rec_id > 0

    # Second upload with identical bytes: Should detect exact duplicate
    second_check = service.check_for_duplicate(
        student_id=student_id,
        file_bytes=file_bytes,
        filename="john_doe_resume_copy.pdf"
    )
    assert second_check["is_duplicate"] is True
    assert second_check["duplicate_type"] == "exact_binary"
    assert second_check["can_proceed"] is True
    assert "john_doe_resume.pdf" in second_check["message"]


def test_content_match_duplicate():
    service = DuplicateResumeService()
    student_id = "test_dup_student_2"
    orig_text = "Experienced Python developer with skills in Flask, SQL, algorithms."
    orig_bytes = orig_text.encode("utf-8")

    service.record_upload_fingerprint(
        student_id=student_id,
        file_bytes=orig_bytes,
        filename="original.pdf",
        extracted_text=orig_text
    )

    # Different bytes (e.g. metadata/re-encoded), but identical text
    re_encoded_bytes = b"HeaderPadding..." + orig_bytes
    check = service.check_for_duplicate(
        student_id=student_id,
        file_bytes=re_encoded_bytes,
        filename="reencoded.pdf",
        extracted_text=orig_text
    )
    assert check["is_duplicate"] is True
    assert check["duplicate_type"] == "content_match"


def test_different_student_isolation():
    service = DuplicateResumeService()
    file_bytes = b"Unique student placement report resume text bytes."

    # Student A uploads
    service.record_upload_fingerprint(
        student_id="student_A",
        file_bytes=file_bytes,
        filename="resume_a.pdf"
    )

    # Student B uploads the same file bytes: should not be marked as duplicate
    # because duplicates are scoped per-student
    b_check = service.check_for_duplicate(
        student_id="student_B",
        file_bytes=file_bytes,
        filename="resume_b.pdf"
    )
    assert b_check["is_duplicate"] is False


def test_api_check_duplicate_json(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "session_user_dup"

    content = "Sample content for testing duplicate detection API endpoint."
    # 1. Record fingerprint
    rec_res = client.post("/api/resume/record-fingerprint", json={
        "content": content,
        "filename": "first_try.txt"
    })
    assert rec_res.status_code == 201

    # 2. Check duplicate
    chk_res = client.post("/api/resume/check-duplicate", json={
        "content": content,
        "filename": "second_try.txt"
    })
    assert chk_res.status_code == 200
    data = chk_res.get_json()
    assert data["success"] is True
    assert data["duplicate_check"]["is_duplicate"] is True


def test_api_check_duplicate_multipart(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "session_user_dup2"

    data = {
        "resume": (io.BytesIO(b"Multipart resume content binary"), "test.pdf")
    }
    res = client.post("/api/resume/check-duplicate", data=data, content_type="multipart/form-data")
    assert res.status_code == 200
    assert res.get_json()["success"] is True
