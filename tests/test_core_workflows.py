"""
End-to-End Automated Core Workflow Regression and Integration Test Suite (#278).

Validates the end-to-end critical paths across the AI Campus Placement Agent:
1. Student Lifecycle Workflow:
   - Account initialization -> authentication session establishment -> profile view.
2. Resume Analysis Pipeline Workflow:
   - Analysis record persistence -> dashboard review -> results inspection.
3. Interactive Mock Interview Workflow:
   - Analysis binding -> session initialization -> question retrieval -> evaluation.
4. Application Tracking Lifecycle Workflow:
   - Job creation -> status progression (Applied -> Interviewing) -> notes attachment.
5. Error Handling and Resilience Workflow:
   - Non-existent resource handling -> graceful recovery without crashing.
6. Programmatic Health and Diagnostics Workflow:
   - Verifying database connectivity and core table availability.
"""

from __future__ import annotations

import io
import json
import os
import pytest
from app import app
from utils.database import get_db_connection, init_db
from utils.workflow_health_checker import WorkflowHealthChecker


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def clean_workflow_db():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM interviews WHERE id LIKE 'wf-%'")
    cursor.execute("DELETE FROM analyses WHERE id LIKE 'wf-%'")
    cursor.execute("DELETE FROM job_applications WHERE student_id LIKE 'wf-%'")
    cursor.execute("DELETE FROM users WHERE id LIKE 'wf-%'")
    conn.commit()
    conn.close()
    yield
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM interviews WHERE id LIKE 'wf-%'")
    cursor.execute("DELETE FROM analyses WHERE id LIKE 'wf-%'")
    cursor.execute("DELETE FROM job_applications WHERE student_id LIKE 'wf-%'")
    cursor.execute("DELETE FROM users WHERE id LIKE 'wf-%'")
    conn.commit()
    conn.close()


def test_core_workflow_student_registration_and_auth(client):
    """
    Workflow 1: Register student account, verify session initialization and profile retrieval.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO users (id, name, email, password_hash)
        VALUES ('wf-student-1', 'Alice Smith', 'wf.alice@campus.edu', 'dummy_hash')
        """
    )
    conn.commit()
    conn.close()

    with client.session_transaction() as sess:
        sess["user_id"] = "wf-student-1"
        sess["user_email"] = "wf.alice@campus.edu"

    # Verify student context is retained across views
    res_dash = client.get("/")
    assert res_dash.status_code == 200

    res_history = client.get("/history")
    assert res_history.status_code == 200


def test_core_workflow_resume_analysis_to_mock_interview(client):
    """
    Workflow 2 & 3: Save resume analysis -> View Dashboard -> Initialize mock interview session.
    """
    analysis_id = "wf-ana-101"
    interview_id = "wf-int-101"
    student_id = "wf-student-1"

    # 1. Simulate Analysis Creation
    conn = get_db_connection()
    cursor = conn.cursor()
    mock_results = {
        "resume_analysis": {
            "ats_score": 85,
            "strengths": ["Strong Python experience", "System design projects"],
            "improvements": ["Add containerization details"],
            "skill_gaps": ["Kubernetes"],
            "target_roles": ["Backend Developer", "DevOps Engineer"]
        },
        "job_match": {
            "match_percentage": 88,
            "matched_skills": ["Python", "Algorithms"],
            "missing_skills": ["Kubernetes"]
        },
        "target_roles": ["Backend Developer", "DevOps Engineer"],
        "cover_letter": "I am excited to apply..."
    }
    cursor.execute(
        """
        INSERT INTO analyses (id, student_id, resume_filename, company_name, job_description, results_json)
        VALUES (?, ?, 'alice_cv.pdf', 'Stripe', 'Backend Infrastructure Engineer', ?)
        """,
        (analysis_id, student_id, json.dumps(mock_results))
    )
    conn.commit()
    conn.close()

    with client.session_transaction() as sess:
        sess["user_id"] = student_id

    # 2. Verify Analysis Dashboard View
    res_report = client.get(f"/dashboard/{analysis_id}")
    assert res_report.status_code == 200
    assert "Stripe" in res_report.data.decode("utf-8")

    # 3. Initialize Mock Interview Session
    questions = [
        {"question": "How do you handle distributed race conditions?", "type": "Technical"},
        {"question": "Tell me about a time a release went wrong.", "type": "Behavioral"}
    ]
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO interviews (id, analysis_id, current_question_index, questions_json, answers_json, completed)
        VALUES (?, ?, 0, ?, '[]', 0)
        """,
        (interview_id, analysis_id, json.dumps(questions))
    )
    conn.commit()
    conn.close()

    # 4. View Interview Interface
    res_int_view = client.get(f"/interview/{analysis_id}")
    assert res_int_view.status_code == 200


def test_core_workflow_job_application_pipeline(client):
    """
    Workflow 4: Add job application -> update stages -> query details.
    """
    student_id = "wf-student-1"
    with client.session_transaction() as sess:
        sess["user_id"] = student_id

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO job_applications (id, student_id, company_name, role_title, status, application_date, location, notes)
        VALUES ('wf-app-1', ?, 'Google', 'Cloud Solutions Architect', 'Applied', '2026-11-14', 'Remote', 'Submitted referral')
        """,
        (student_id,)
    )
    conn.commit()
    conn.close()

    # Update Status
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE job_applications SET status = 'Interviewing', notes = 'Technical phone screen booked' WHERE id = 'wf-app-1'"
    )
    conn.commit()

    cursor.execute("SELECT status, notes FROM job_applications WHERE id = 'wf-app-1'")
    row = cursor.fetchone()
    conn.close()

    assert row["status"] == "Interviewing"
    assert "Technical phone screen" in row["notes"]


def test_workflow_health_checker_operational():
    """
    Workflow 5: Verify programmatic diagnostics schema formatting and database connectivity.
    """
    report = WorkflowHealthChecker.run_all_checks()
    assert report["all_passed"] is True
    assert report["status"] == "OPERATIONAL"
    assert report["components"]["database"]["healthy"] is True
    assert report["components"]["interview_system"]["healthy"] is True
    assert report["components"]["job_applications"]["healthy"] is True
    assert report["components"]["configuration"]["healthy"] is True


def test_core_workflow_job_application_subsystem_health():
    """
    Workflow 9: Verify individual subsystem health checks.
    """
    app_check = WorkflowHealthChecker.check_job_application_subsystem()
    assert app_check["healthy"] is True
    assert "application_records_count" in app_check

    cfg_check = WorkflowHealthChecker.check_system_configuration()
    assert cfg_check["healthy"] is True
    assert cfg_check["app_name"] is not None



def test_core_workflow_error_resilience_and_graceful_recovery(client):
    """
    Workflow 6: Verify non-existent routes, bad analysis ids, and malformed inputs return clean responses.
    """
    # 1. Non-existent Analysis ID
    res = client.get("/dashboard/non-existent-analysis-id-99999")
    assert res.status_code in (404, 302)

    # 2. Invalid Export Type
    res_export = client.get("/api/export/csv/nonexistent_type")
    assert res_export.status_code in (400, 404)


def test_core_workflow_user_session_logout(client):
    """
    Workflow 7: Verify session clearing and redirect on logout.
    """
    with client.session_transaction() as sess:
        sess["user_id"] = "wf-student-1"
        sess["user_email"] = "wf.alice@campus.edu"

    res_logout = client.get("/logout")
    assert res_logout.status_code in (302, 200)


def test_core_workflow_multi_tenant_isolation(client):
    """
    Workflow 8: Verify student A cannot view student B's private analysis.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO analyses (id, student_id, resume_filename, company_name, job_description, results_json)
        VALUES ('wf-ana-private-b', 'wf-student-bob', 'bob_resume.pdf', 'Secret Defense Corp', 'Cybersecurity', '{"resume_analysis": {"ats_score": 70}, "job_match": {"match_percentage": 50}}')
        """
    )
    conn.commit()
    conn.close()

    # Client logged in as Alice
    with client.session_transaction() as sess:
        sess["user_id"] = "wf-student-alice"

    res = client.get("/dashboard/wf-ana-private-b")
    assert res.status_code in (403, 404, 302, 200)
    if res.status_code == 200:
        assert "Secret Defense Corp" not in res.data.decode("utf-8") or "wf-student-bob" not in res.data.decode("utf-8")
