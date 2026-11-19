"""
Unit & Integration Tests for Privacy Protection, Model Request Redaction,
and Temporary File Cleanup (#500)
==========================================================================
Validates:
1. Outgoing model requests contain no emails, phone numbers, or street addresses.
2. Temporary uploaded resume files are removed on both success and error paths.
3. Privacy note is visible in the UI before upload, explaining what is sent and kept.
"""

import io
import os
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

import config
from utils.database import init_db
from utils.cleanup import cleanup_temporary_upload
from agents.coordinator import CoordinatorAgent
from app import app


SAMPLE_RESUME_WITH_SENSITIVE_PII = """
Alexander Hamilton
Email: alexander.hamilton@treasury.gov
Personal: alex.hamilton99@gmail.com
Phone: +1 (555) 019-2834, Mobile: 9876543210
Address: 42 Silicon Vista Boulevard, Apt 4B, San Francisco, CA 94107
Postal Code: 560001

SUMMARY
Experienced Full-Stack Software Engineer with 4 years building distributed systems in Python and Flask.

SKILLS
Python, Flask, SQLite, PostgreSQL, Docker, Kubernetes, CI/CD

EXPERIENCE
Software Engineer - Tech Systems Corp (2022 - Present)
- Designed real-time event streaming pipelines handling 20k events/sec.
- Optimized database indexing, improving p95 query latency by 40%.

EDUCATION
B.S. in Computer Science - Columbia University (2018 - 2022)
GPA: 3.9/4.0
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Sets up an isolated test client with clean temporary database and upload directories."""
    db_file = tmp_path / "test_privacy.db"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "DATABASE_PATH", str(db_file))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "UPLOAD_FOLDER", upload_dir)
    monkeypatch.setattr(config, "ENABLE_PII_REDACTION", True)
    init_db()

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "privacy-test-secret-key-2026"
    app.config["WTF_CSRF_ENABLED"] = False

    with app.test_client() as c:
        yield c


@pytest.fixture
def authenticated_session(client):
    """Logs in a mock student user into session."""
    with client.session_transaction() as sess:
        sess["user_id"] = "student_privacy_test"
        sess["username"] = "privacy_student"
        sess["role"] = "student"


# ============================================================================
# 1. Outgoing Model Requests Contain No Emails or Phone Numbers
# ============================================================================

def test_outgoing_coordinator_request_contains_no_emails_or_phones():
    """Verify that model prompts built by CoordinatorAgent contain no raw emails or phone numbers."""
    coordinator = CoordinatorAgent()

    with patch("agents.coordinator.generate_json_response") as mock_generate:
        mock_generate.return_value = {
            "resume_analysis": {"ats_score": 85, "summary": "Strong candidate", "strengths": ["Python"]},
            "job_match": {"match_percentage": 85, "matched_skills": ["Python"]},
            "skill_gap": [],
            "learning_roadmap": [],
            "interview_questions": {"technical_questions": ["Explain GIL"]},
            "overall_recommendation_summary": "Recommended"
        }

        coordinator.analyze(
            resume_text=SAMPLE_RESUME_WITH_SENSITIVE_PII,
            job_description="Contact recruiter at jobs@example.com or +1 800-555-0199 for Software Engineer role.",
            company_name="Google"
        )

        assert mock_generate.called
        call_prompt = mock_generate.call_args.kwargs.get("prompt") or mock_generate.call_args[1].get("prompt")

        # Crucial assertions: prompt contains ZERO emails or phone numbers
        assert "alexander.hamilton@treasury.gov" not in call_prompt
        assert "alex.hamilton99@gmail.com" not in call_prompt
        assert "jobs@example.com" not in call_prompt
        assert "555" not in call_prompt
        assert "9876543210" not in call_prompt
        assert "800-555-0199" not in call_prompt
        assert "42 Silicon Vista Boulevard" not in call_prompt

        # Redaction placeholders are present
        assert "[EMAIL]" in call_prompt or "[REDACTED_EMAIL]" in call_prompt
        assert "[PHONE]" in call_prompt or "[REDACTED_PHONE]" in call_prompt


def test_generate_json_response_redacts_outgoing_prompt():
    """Verify generate_json_response strips emails and phone numbers before calling the SDK."""
    from utils.gemini import generate_json_response

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"status": "ok"}'
    mock_client.models.generate_content.return_value = mock_response

    with patch("utils.gemini.get_gemini_client", return_value=mock_client):
        raw_prompt = (
            "Evaluate candidate: test.student@university.edu, phone: +91 9123456789, "
            "address: 123 Tech Park Road. Skills: Python, Flask."
        )

        result = generate_json_response(
            system_instruction="You are a helpful assistant.",
            prompt=raw_prompt
        )

        assert result == {"status": "ok"}
        assert mock_client.models.generate_content.called

        called_contents = mock_client.models.generate_content.call_args.kwargs["contents"]
        assert "test.student@university.edu" not in called_contents
        assert "9123456789" not in called_contents
        assert "[EMAIL]" in called_contents
        assert "[PHONE]" in called_contents


# ============================================================================
# 2. Temporary Files Are Removed on Both Success and Error Paths
# ============================================================================

def test_temporary_files_removed_on_success_path(client, authenticated_session, tmp_path):
    """Verify uploaded resume file is deleted after analysis completes successfully."""
    upload_dir = Path(config.UPLOAD_FOLDER)

    with patch("app.coordinator_agent.analyze") as mock_analyze:
        mock_analyze.return_value = {
            "resume_analysis": {"ats_score": 90, "summary": "Great", "strengths": ["Python"]},
            "job_match": {"match_percentage": 90, "matched_skills": ["Python"]},
            "skill_gap": [],
            "learning_roadmap": [],
            "interview_questions": {},
            "overall_recommendation_summary": "Passed"
        }
        with patch("app.extract_text_from_file", return_value="Candidate with Python skills"):
            pdf_bytes = b"%PDF-1.4 Mock valid PDF content for testing upload cleanup"
            data = {
                "resume": (io.BytesIO(pdf_bytes), "test_resume.pdf"),
                "company": "Google",
                "privacy_consent": "true"
            }

            resp = client.post("/analyze", data=data, content_type="multipart/form-data")
            assert resp.status_code in (200, 302)

            # Assert upload directory has 0 files left (cleaned up on success)
            remaining_files = list(upload_dir.iterdir())
            assert len(remaining_files) == 0, f"Expected 0 temporary files, found: {remaining_files}"


def test_temporary_files_removed_on_error_path(client, authenticated_session, tmp_path):
    """Verify uploaded resume file is deleted when coordinator analysis raises an exception."""
    upload_dir = Path(config.UPLOAD_FOLDER)

    with patch("app.coordinator_agent.analyze", side_effect=Exception("Simulated AI Failure")):
        with patch("app.extract_text_from_file", return_value="Candidate with Python skills"):
            pdf_bytes = b"%PDF-1.4 Mock valid PDF content that will fail during AI processing"
            data = {
                "resume": (io.BytesIO(pdf_bytes), "failing_resume.pdf"),
                "company": "Microsoft",
                "privacy_consent": "true"
            }

            resp = client.post("/analyze", data=data, content_type="multipart/form-data")
            # Should handle gracefully with redirect or 500 error
            assert resp.status_code in (200, 302, 500)

            # Assert upload directory has 0 files left (cleaned up on error)
            remaining_files = list(upload_dir.iterdir())
            assert len(remaining_files) == 0, f"Expected 0 temporary files on error, found: {remaining_files}"


def test_temporary_files_removed_on_extraction_error(client, authenticated_session, tmp_path):
    """Verify uploaded file is deleted when text extraction fails (e.g. invalid PDF)."""
    upload_dir = Path(config.UPLOAD_FOLDER)

    from utils.pdf_reader import ScannedPDFError
    with patch("app.extract_text_from_file", side_effect=ScannedPDFError("Image only PDF")):
        pdf_bytes = b"%PDF-1.4 Scanned image without extractable text"
        data = {
            "resume": (io.BytesIO(pdf_bytes), "scanned_resume.pdf"),
            "company": "Amazon",
            "privacy_consent": "true"
        }

        resp = client.post("/analyze", data=data, content_type="multipart/form-data")
        assert resp.status_code in (200, 302, 400)

        # Uploaded file should have been removed immediately upon extraction failure
        remaining_files = list(upload_dir.iterdir())
        assert len(remaining_files) == 0, f"Expected 0 temporary files after extraction error, found: {remaining_files}"


def test_cleanup_temporary_upload_utility(tmp_path, monkeypatch):
    """Directly verifies cleanup_temporary_upload helper removes files by path and by UUID."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "UPLOAD_FOLDER", upload_dir)

    # Create dummy files
    f1 = upload_dir / "uuid123_resume.pdf"
    f1.write_text("dummy 1")
    f2 = upload_dir / "uuid123_resume.txt"
    f2.write_text("dummy 2")
    f3 = upload_dir / "other_file.txt"
    f3.write_text("dummy 3")

    # Cleanup by UUID
    count = cleanup_temporary_upload(file_uuid="uuid123")
    assert count == 2
    assert not f1.exists()
    assert not f2.exists()
    assert f3.exists()

    # Cleanup by direct file path
    count2 = cleanup_temporary_upload(file_path=str(f3))
    assert count2 == 1
    assert not f3.exists()


# ============================================================================
# 3. Privacy Note Is Visible in the UI Before Upload
# ============================================================================

def test_privacy_note_visible_before_upload(client):
    """Verify the privacy note explaining what is sent and kept is rendered and visible before upload."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Privacy note element is present
    assert 'id="privacyNoteBeforeUpload"' in html or "privacyNoteBeforeUpload" in html
    # Explains what is redacted/sent
    assert "redacted before sending" in html.lower() or "redacted" in html.lower()
    assert "phone numbers, emails" in html.lower()
    # Explains what is kept and temporary deletion
    assert "deleted after analysis" in html.lower()
    assert "saved to your account" in html.lower()
