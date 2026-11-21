import pytest
from app import app
from utils.file_validation_service import FileValidationFeedbackService, file_validation_service


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_validate_supported_text_and_pdf():
    service = FileValidationFeedbackService()
    valid_txt = service.validate_file("my_resume.txt", b"Education: B.Tech Computer Science\nSkills: Python, SQL")
    assert valid_txt["is_valid"] is True
    assert valid_txt["status"] == "ACCEPTED"
    assert valid_txt["safe_to_continue"] is True
    assert "ready for AI placement analysis" in valid_txt["message"]
    assert len(valid_txt["tips"]) > 0


def test_validate_unsupported_file_extension():
    service = FileValidationFeedbackService()
    res = service.validate_file("resume.exe", b"binary executable payload")
    assert res["is_valid"] is False
    assert res["status"] == "UNSUPPORTED_TYPE"
    assert res["safe_to_continue"] is False
    assert "not a supported file type" in res["message"]
    assert ".pdf" in res["message"]
    assert any("PDF" in tip for tip in res["tips"])


def test_validate_empty_file():
    service = FileValidationFeedbackService()
    res = service.validate_file("empty_resume.pdf", b"")
    assert res["is_valid"] is False
    assert res["status"] == "EMPTY_FILE"
    assert res["safe_to_continue"] is False
    assert "completely empty" in res["message"]


def test_validate_file_too_large():
    service = FileValidationFeedbackService(max_size_bytes=1000)
    res = service.validate_file("large_resume.pdf", b"A" * 2000)
    assert res["is_valid"] is False
    assert res["status"] == "FILE_TOO_LARGE"
    assert res["safe_to_continue"] is False
    assert "exceeds the maximum allowed size" in res["message"]
    assert any("compress" in tip.lower() for tip in res["tips"])


def test_replacement_warning():
    service = FileValidationFeedbackService()
    res = service.validate_file(
        filename="new_resume.docx",
        file_bytes=b"PK\x03\x04sample word content",
        has_existing_file=True,
        existing_filename="old_resume.pdf"
    )
    assert res["is_valid"] is True
    assert res["will_replace"] is True
    assert "replace your previously uploaded resume ('old_resume.pdf')" in res["message"]


def test_magic_header_inspection():
    service = FileValidationFeedbackService()
    # Spoofed PDF (has txt content, not %PDF-)
    spoofed = service.validate_file("fake.pdf", b"Hello this is not binary pdf")
    assert spoofed["is_valid"] is True
    assert spoofed["magic_warning"] is not None


def test_api_validate_file_json(client):
    res = client.post("/api/upload/validate-file", json={
        "filename": "candidate_resume.pdf",
        "content": "Sample candidate resume content"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["feedback"]["status"] == "ACCEPTED"
    assert data["feedback"]["safe_to_continue"] is True


def test_api_validate_file_unsupported(client):
    res = client.post("/api/upload/validate-file", json={
        "filename": "archive.zip",
        "content": "PK\x03\x04zip contents"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is False
    assert data["feedback"]["status"] == "UNSUPPORTED_TYPE"
    assert data["feedback"]["safe_to_continue"] is False
