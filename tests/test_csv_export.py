"""
Unit tests for CSV Export Service (#274).
"""

import csv
import io
import json
import pytest
from app import app
from utils.database import get_db_connection, init_db
from utils.csv_export_service import sanitize_csv_cell, get_csv_export


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def setup_test_records():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS preparation_notes (
            id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT,
            tags TEXT,
            content TEXT,
            created_at TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS coding_submissions (
            id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            problem_title TEXT NOT NULL,
            topic TEXT,
            difficulty TEXT,
            language TEXT,
            status TEXT,
            score REAL,
            submitted_at TEXT
        )
        """
    )

    # Clean up test rows
    cursor.execute("DELETE FROM interviews WHERE id LIKE 'int-exp-%'")
    cursor.execute("DELETE FROM analyses WHERE student_id LIKE 'test-exp-%'")
    cursor.execute("DELETE FROM job_applications WHERE student_id LIKE 'test-exp-%'")
    cursor.execute("DELETE FROM preparation_notes WHERE student_id LIKE 'test-exp-%'")
    cursor.execute("DELETE FROM coding_submissions WHERE student_id LIKE 'test-exp-%'")

    # Insert sample records for student A
    cursor.execute(
        """
        INSERT INTO job_applications (id, student_id, company_name, role_title, status, application_date, location, notes)
        VALUES ('app-1', 'test-exp-student-a', 'Google', 'SRE', 'Interviewing', '2026-11-01', 'Remote', 'Round 2 scheduled')
        """
    )
    cursor.execute(
        """
        INSERT INTO preparation_notes (id, student_id, title, category, tags, content, created_at)
        VALUES ('note-1', 'test-exp-student-a', 'OS Concurrency', 'OS', 'mutex,semaphores', 'Deadlock 4 conditions: mutual exclusion, hold and wait...', '2026-11-02')
        """
    )
    cursor.execute(
        """
        INSERT INTO coding_submissions (id, student_id, question_title, company_name, language, code, passed, score, tests_passed, total_tests)
        VALUES ('sub-1', 'test-exp-student-a', 'LRU Cache', 'Google', 'python', 'def lru(): pass', 1, 100, 5, 5)
        """
    )
    cursor.execute(
        """
        INSERT INTO analyses (id, student_id, resume_filename, company_name, job_description, results_json)
        VALUES ('ana-exp-1', 'test-exp-student-a', 'r.pdf', 'Stripe', 'Backend Engineer', '{}')
        """
    )
    cursor.execute(
        """
        INSERT INTO interviews (id, analysis_id, current_question_index, questions_json, answers_json, completed)
        VALUES ('int-exp-1', 'ana-exp-1', 1, '["What is idempotency?"]', '[{"answer": "An operation with no side-effects on repetition", "evaluation": {"score": 90, "feedback": "Accurate."}}]', 1)
        """
    )

    # Insert sample records for student B to verify isolation
    cursor.execute(
        """
        INSERT INTO job_applications (id, student_id, company_name, role_title, status, application_date, location, notes)
        VALUES ('app-b', 'test-exp-student-b', 'PrivateCorp', 'TopSecret', 'Applied', '2026-11-01', 'NY', 'Private notes')
        """
    )
    conn.commit()
    conn.close()

    yield

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM interviews WHERE id LIKE 'int-exp-%'")
    cursor.execute("DELETE FROM analyses WHERE student_id LIKE 'test-exp-%'")
    cursor.execute("DELETE FROM job_applications WHERE student_id LIKE 'test-exp-%'")
    cursor.execute("DELETE FROM preparation_notes WHERE student_id LIKE 'test-exp-%'")
    cursor.execute("DELETE FROM coding_submissions WHERE student_id LIKE 'test-exp-%'")
    conn.commit()
    conn.close()


def test_sanitize_csv_cell():
    assert sanitize_csv_cell("=1+1") == "'=1+1"
    assert sanitize_csv_cell("@SUM(A1:A5)") == "'@SUM(A1:A5)"
    assert sanitize_csv_cell("-10") == "'-10"
    assert sanitize_csv_cell("+44") == "'+44"
    assert sanitize_csv_cell("Normal Text") == "Normal Text"
    assert sanitize_csv_cell(None) == ""


def test_export_applications_endpoint(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "test-exp-student-a"

    res = client.get("/api/export/csv/applications")
    assert res.status_code == 200
    assert res.mimetype == "text/csv"
    assert 'attachment; filename="test-exp-student-a_job_applications.csv"' in res.headers["Content-Disposition"]

    csv_text = res.data.decode("utf-8")
    assert "Google" in csv_text
    assert "SRE" in csv_text
    # Ensure isolation: Student B data must not appear
    assert "PrivateCorp" not in csv_text


def test_export_interviews_endpoint(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "test-exp-student-a"

    res = client.get("/api/export/csv/interviews")
    assert res.status_code == 200
    csv_text = res.data.decode("utf-8")
    assert "Stripe" in csv_text
    assert "What is idempotency?" in csv_text
    assert "Accurate." in csv_text


def test_export_notes_endpoint(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "test-exp-student-a"

    res = client.get("/api/export/csv/notes")
    assert res.status_code == 200
    csv_text = res.data.decode("utf-8")
    assert "OS Concurrency" in csv_text
    assert "Deadlock" in csv_text


def test_export_coding_endpoint(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "test-exp-student-a"

    res = client.get("/api/export/csv/coding")
    assert res.status_code == 200
    csv_text = res.data.decode("utf-8")
    assert "LRU Cache" in csv_text
    assert "Google" in csv_text
    assert "Passed" in csv_text


def test_export_invalid_type_endpoint(client):
    res = client.get("/api/export/csv/unknown_type")
    assert res.status_code == 400
    assert "Unsupported export type" in res.get_json()["error"]
