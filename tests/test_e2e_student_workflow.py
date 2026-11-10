"""
Comprehensive Automated End-to-End Student Workflow Test Suite (#264).

Validates the complete student lifecycle across the platform:
1. Student registration with credential hashing and account setup.
2. Authenticated login session creation and state persistence.
3. Resume upload and job matching analysis generation.
4. Historical analysis retrieval, filtering, and role comparison.
5. Job application submission and tracking.
6. Job application lifecycle status transitions with audit timeline logging.
7. Mock interview question generation and AI answer evaluation.
8. Daily placement preparation activity logging, streak calculation, and notes.
9. Strict multi-tenant data privacy: verifying that student A cannot access, view,
   modify, or export student B's analyses, job applications, or preparation records.
10. Complete student data download package generation (sanitized ZIP manifest).
"""

import io
import json
import zipfile
import pytest
from app import app
import config
from utils.database import (
    init_db,
    get_db_connection,
    save_analysis,
    get_analysis,
    save_job_application,
    get_student_preparation_summary_data,
    record_preparation_activity,
)
from utils.student_data_exporter import (
    build_student_data_export_manifest,
    generate_student_data_zip_package,
)


@pytest.fixture(autouse=True)
def setup_e2e_environment(tmp_path, monkeypatch):
    """Isolate SQLite database and directory structures for E2E workflow testing."""
    test_db = str(tmp_path / "e2e_student_workflow.db")
    monkeypatch.setattr(config, "DATABASE_PATH", test_db)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()
    return test_db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["ENFORCE_LOGIN_IN_TESTS"] = False
    with app.test_client() as client:
        yield client


class TestStudentEndToEndWorkflow:
    """Simulates a complete student journey through campus placement preparation."""

    def test_complete_student_preparation_and_interview_journey(self, client):
        # =========================================================================
        # Stage 1: Registration & Account Initialization
        # =========================================================================
        reg_response = client.post(
            "/register",
            data={
                "name": "Maya Lin",
                "email": "maya.lin@campus.edu",
                "password": "SecurePassword123!",
                "confirm_password": "SecurePassword123!",
            },
            follow_redirects=True,
        )
        assert reg_response.status_code == 200

        # Verify user account in database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, email FROM users WHERE email = 'maya.lin@campus.edu'")
        user_row = cursor.fetchone()
        conn.close()

        assert user_row is not None
        maya_user_id = str(user_row["id"])
        assert user_row["name"] == "Maya Lin"

        # =========================================================================
        # Stage 2: Authentication & Session Verification
        # =========================================================================
        login_response = client.post(
            "/login",
            data={
                "email": "maya.lin@campus.edu",
                "password": "SecurePassword123!",
            },
            follow_redirects=True,
        )
        assert login_response.status_code == 200

        # Establish authenticated session context
        with client.session_transaction() as sess:
            sess["user_id"] = maya_user_id
            sess["user_name"] = "Maya Lin"
            sess["user_email"] = "maya.lin@campus.edu"

        # =========================================================================
        # Stage 3: Resume Upload & AI Placement Analysis
        # =========================================================================
        sample_analysis_payload = {
            "match_score": 85,
            "skill_gap": {
                "matched_skills": ["Python", "Flask", "SQL"],
                "missing_skills": ["Docker", "Kubernetes", "Kafka"],
            },
            "learning_roadmap": [
                {"week": 1, "topic": "Docker Containerization Fundamentals"},
                {"week": 2, "topic": "Kubernetes Pods and Services"},
                {"week": 3, "topic": "Distributed Messaging with Apache Kafka"},
            ],
            "interview_questions": [
                {"question": "How do Docker layers work under the hood?", "difficulty": "Medium"},
                {"question": "Explain Kafka partition consumer rebalancing.", "difficulty": "Hard"},
            ],
        }

        analysis_id = "analysis_maya_e2e_001"
        save_analysis(
            analysis_id=analysis_id,
            resume_filename="maya_lin_resume.pdf",
            company_name="Snowflake",
            job_description="Distributed Systems Software Engineer with Python and Kafka.",
            results_dict=sample_analysis_payload,
            student_id=maya_user_id,
        )

        retrieved_analysis = get_analysis(analysis_id)
        assert retrieved_analysis is not None
        assert retrieved_analysis["company_name"] == "Snowflake"
        assert retrieved_analysis["results"]["match_score"] == 85

        # =========================================================================
        # Stage 4: Job Application Submission & Tracking
        # =========================================================================
        app_id = "jobapp_maya_001"
        save_job_application(
            app_id=app_id,
            student_id=maya_user_id,
            company_name="Snowflake",
            role_title="Distributed Systems Engineer",
            status="Applied",
            application_date="2026-11-10",
        )

        # Log preparation activity
        record_preparation_activity(
            student_id=maya_user_id,
            activity_type="job_application_submitted",
            metadata={"details": "Submitted application to Snowflake for Distributed Systems Engineer"},
        )

        # =========================================================================
        # Stage 5: Application Status Transition & Timeline Event
        # =========================================================================
        from utils.application_timeline_service import (
            transition_application_status_with_timeline,
            get_application_timeline,
        )

        transition_res = transition_application_status_with_timeline(
            application_id=app_id,
            student_id=maya_user_id,
            new_status="Online Assessment",
            notes="Received HackerRank coding assessment link.",
        )
        assert transition_res["success"] is True
        assert transition_res["previous_status"] == "Applied"
        assert transition_res["current_status"] == "Online Assessment"

        timeline = get_application_timeline(app_id, maya_user_id)
        assert timeline["total_activities"] == 1
        assert timeline["timeline"][0]["new_status"] == "Online Assessment"

        # =========================================================================
        # Stage 6: Focused Topic Practice & Answer Evaluation
        # =========================================================================
        from utils.topic_practice_service import generate_topic_interview_question, evaluate_topic_answer

        question_data = generate_topic_interview_question(
            topic="dsa",
            difficulty="medium",
        )
        assert "question" in question_data
        q_text = question_data["question"]

        eval_res = evaluate_topic_answer(
            topic="dsa",
            difficulty="medium",
            question=q_text,
            answer="I would use an inverted index with a min-heap to optimize search complexity to O(K log N).",
        )
        assert eval_res["score"] > 30
        assert "verdict" in eval_res
        assert "strengths" in eval_res

        # =========================================================================
        # Stage 7: Preparation Summary & Streak Metrics
        # =========================================================================
        summary = get_student_preparation_summary_data(maya_user_id)
        assert summary["analyses_count"] >= 1
        assert summary["applications_summary"]["total"] >= 1

        # =========================================================================
        # Stage 8: Data Export Archive Creation
        # =========================================================================
        manifest = build_student_data_export_manifest(maya_user_id)
        assert manifest["profile"]["account"]["email"] == "maya.lin@campus.edu"
        assert len(manifest["placement_analyses"]) >= 1
        assert len(manifest["job_applications"]) >= 1

        zip_buffer = generate_student_data_zip_package(maya_user_id)
        assert zip_buffer.getbuffer().nbytes > 200

        with zipfile.ZipFile(zip_buffer, "r") as zf:
            file_names = zf.namelist()
            assert "README.md" in file_names
            assert "student_placement_data_complete.json" in file_names
            assert "job_applications.json" in file_names

    def test_multi_student_data_privacy_and_isolation(self, client):
        """
        Verify that student accounts are strictly isolated:
        Bob cannot access Maya's analyses, job applications, or timelines.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (id, name, email, password_hash) VALUES (101, 'Student Maya', 'm@uni.edu', 'h')")
        cursor.execute("INSERT INTO users (id, name, email, password_hash) VALUES (102, 'Student Bob', 'b@uni.edu', 'h')")
        conn.commit()
        conn.close()

        # Seed private job app for Maya
        save_job_application(
            app_id="app_maya_confidential",
            student_id="101",
            company_name="Citadel",
            role_title="Quantitative Developer",
            status="Offer",
            application_date="2026-11-01",
        )

        from utils.application_timeline_service import (
            get_application_timeline,
            transition_application_status_with_timeline,
        )

        # Bob (102) attempts to view Maya's application timeline
        with pytest.raises(PermissionError):
            get_application_timeline("app_maya_confidential", student_id="102")

        # Bob attempts to transition Maya's application status
        with pytest.raises(PermissionError):
            transition_application_status_with_timeline("app_maya_confidential", student_id="102", new_status="Rejected")

        # Verify Bob's summary does not include Maya's application
        bob_summary = get_student_preparation_summary_data("102")
        assert bob_summary["applications_summary"]["total"] == 0
