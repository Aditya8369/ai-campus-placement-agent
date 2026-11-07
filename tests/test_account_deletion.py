import pytest
import uuid
from app import app
from utils.database import (
    init_db,
    create_user,
    get_user_by_id,
    save_analysis,
    create_interview_session,
    save_job_application,
    save_calendar_event,
    save_coding_submission,
    save_skill_self_assessment,
    submit_user_feedback,
    get_user_data_export_manifest,
    delete_user_account_and_personal_data
)
from werkzeug.security import generate_password_hash


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    yield


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestAccountDeletionDatabase:
    """Unit tests for complete cascading erasure of personal data (#207)."""

    def test_cascading_account_and_data_deletion(self):
        student_id = f"purge_student_{uuid.uuid4().hex[:8]}"
        email = f"{student_id}@university.edu"
        password = "secret_password_123"

        # 1. Create student account
        create_user(student_id, "Purge Candidate", email, generate_password_hash(password))

        # 2. Populate personal data across diverse placement modules
        # Analysis
        analysis_id = f"analysis_{uuid.uuid4().hex[:8]}"
        save_analysis(analysis_id, "resume.pdf", "Google", "SWE", {"score": 85}, student_id=student_id)

        # Mock interview
        interview_id = f"int_{uuid.uuid4().hex[:8]}"
        create_interview_session(interview_id, analysis_id, [{"q": "Explain binary search"}])

        # Job application
        app_id = f"app_{uuid.uuid4().hex[:8]}"
        save_job_application(app_id, student_id, "Google", "SWE Intern", "Applied", "2026-05-01")

        # Calendar event
        cal_id = f"cal_{uuid.uuid4().hex[:8]}"
        save_calendar_event(cal_id, student_id, "Technical Round", "interview", "2026-05-10")

        # Coding submission
        sub_id = f"sub_{uuid.uuid4().hex[:8]}"
        save_coding_submission(
            sub_id, student_id, "Two Sum", "Amazon", "python",
            "def two_sum(): pass", True, 100, 5, 5, "{}", "O(N)", "Great!"
        )

        # Technical skill
        save_skill_self_assessment(student_id, "Python", "Programming", "Advanced", 3.0)

        # Feedback
        submit_user_feedback(student_id, 5, "General", "Excellent platform!")

        # 3. Check manifest before deletion
        manifest = get_user_data_export_manifest(student_id)
        assert manifest["total_records"] >= 7
        assert manifest["tables"]["analyses"] >= 1
        assert manifest["tables"]["interviews"] >= 1
        assert manifest["tables"]["job_applications"] >= 1
        assert manifest["tables"]["users"] == 1

        # 4. Perform complete account erasure
        result = delete_user_account_and_personal_data(student_id)
        assert result["status"] == "purged"
        assert result["total_deleted"] >= 7

        # 5. Check manifest after deletion
        post_manifest = get_user_data_export_manifest(student_id)
        assert post_manifest["total_records"] == 0
        assert get_user_by_id(student_id) is None

    def test_delete_nonexistent_or_invalid_id_raises_value_error(self):
        with pytest.raises(ValueError):
            delete_user_account_and_personal_data("")
        with pytest.raises(ValueError):
            delete_user_account_and_personal_data("   ")


class TestAccountDeletionRoutes:
    """Integration tests for web account deletion endpoints and security safeguards (#207)."""

    def test_account_delete_page_renders_manifest(self, client):
        student_id = f"del_view_{uuid.uuid4().hex[:8]}"
        with client.session_transaction() as sess:
            sess["user_id"] = student_id
            sess["user_name"] = "Deletable User"

        response = client.get("/account/delete")
        assert response.status_code == 200
        assert b"Permanent Account Deletion" in response.data
        assert b"Personal Data Footprint Summary" in response.data

    def test_delete_aborts_without_correct_phrase(self, client):
        student_id = f"del_phrase_{uuid.uuid4().hex[:8]}"
        with client.session_transaction() as sess:
            sess["user_id"] = student_id

        response = client.post("/account/delete", data={
            "confirm_phrase": "delete account",  # lowercase/wrong phrase
            "password": "any"
        })

        assert response.status_code == 200
        assert b"Please type &#39;DELETE MY ACCOUNT&#39; exactly as shown" in response.data or b"Please type 'DELETE MY ACCOUNT' exactly as shown" in response.data

    def test_delete_aborts_with_wrong_password(self, client):
        student_id = f"pw_del_{uuid.uuid4().hex[:8]}"
        create_user(student_id, "User With Password", f"{student_id}@uni.edu", generate_password_hash("correct_password"))

        with client.session_transaction() as sess:
            sess["user_id"] = student_id

        response = client.post("/account/delete", data={
            "confirm_phrase": "DELETE MY ACCOUNT",
            "password": "wrong_password"
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b"Incorrect password" in response.data
        assert get_user_by_id(student_id) is not None

    def test_successful_delete_logs_out_and_redirects(self, client):
        student_id = f"success_del_{uuid.uuid4().hex[:8]}"
        create_user(student_id, "Successful Deletion", f"{student_id}@uni.edu", generate_password_hash("mypassword123"))

        with client.session_transaction() as sess:
            sess["user_id"] = student_id

        response = client.post("/account/delete", data={
            "confirm_phrase": "DELETE MY ACCOUNT",
            "password": "mypassword123"
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b"permanently removed" in response.data
        assert get_user_by_id(student_id) is None

    def test_api_account_export_manifest_endpoint(self, client):
        student_id = f"manifest_test_{uuid.uuid4().hex[:8]}"
        with client.session_transaction() as sess:
            sess["user_id"] = student_id

        response = client.get("/api/account/export-manifest")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert "manifest" in data
        assert "tables" in data["manifest"]
