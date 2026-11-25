"""
Unit and Integration Tests for Faculty Intervention Queue (#786).
==================================================================
Validates:
1. Detection of students who have not logged in for >= 14 days (Inactivity).
2. Detection of students with expired job application deadlines (Missed Deadlines).
3. Detection of students with halted daily drills / practice (Stopped Preparation).
4. Detection of students with repeated low mock interview scores (< 60%) (Repeated Low Scores).
5. Privacy preservation: Explanations summarize metrics and timelines without leaking
   confidential resume contents, private interview transcripts, or personal notes.
6. Suggested follow-up actions provide actionable, category-specific faculty guidance.
7. Coordinator workflow operations: status transitions (In Progress, Resolved, Snooze),
   audit action notes, and summary metric aggregations.
8. Access control and REST API endpoints (/api/admin/interventions).
"""

import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from flask import session

from app import app
from db.connection import transaction
from utils.faculty_intervention_service import (
    CATEGORY_INACTIVITY,
    CATEGORY_MISSED_DEADLINES,
    CATEGORY_REPEATED_LOW_SCORES,
    CATEGORY_STOPPED_PREP,
    STATUS_DISMISSED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_RESOLVED,
    STATUS_SNOOZED,
    URGENCY_HIGH,
    URGENCY_MEDIUM,
    FacultyInterventionService,
    init_intervention_tables,
)


@pytest.fixture
def test_db(tmp_path):
    """Sets up an isolated SQLite database with migrations and schema initialized."""
    db_file = tmp_path / "test_placement.db"
    db_path = str(db_file)

    # Initialize complete schema
    from db.migrations import init_db
    init_db(db_path)
    init_intervention_tables(db_path)

    return db_path


def test_inactivity_detection(test_db):
    """Verify students with no login or last seen >= 14 days ago are flagged for inactivity."""
    now_ts = time.time()
    twenty_days_ago_ts = now_ts - (20 * 86400)

    with transaction(test_db) as cursor:
        # Create an inactive student
        cursor.execute("""
            INSERT INTO users (id, name, email, password_hash, created_at)
            VALUES ('inactive_student_1', 'John Inactive', 'john@campus.edu', 'hash', '2026-10-01 10:00:00')
        """)
        # Recorded login 20 days ago
        cursor.execute("""
            INSERT INTO auth_sessions (id, user_id, token_hash, client_label, created_at, last_seen_at)
            VALUES ('sess_1', 'inactive_student_1', 'token1', 'Chrome', ?, ?)
        """, (twenty_days_ago_ts, twenty_days_ago_ts))

        # Create an active student (logged in today)
        cursor.execute("""
            INSERT INTO users (id, name, email, password_hash, created_at)
            VALUES ('active_student_1', 'Alice Active', 'alice@campus.edu', 'hash', '2026-11-01 10:00:00')
        """)
        cursor.execute("""
            INSERT INTO auth_sessions (id, user_id, token_hash, client_label, created_at, last_seen_at)
            VALUES ('sess_2', 'active_student_1', 'token2', 'Firefox', ?, ?)
        """, (now_ts, now_ts))

    # Run intervention scan
    stats = FacultyInterventionService.scan_students_for_interventions(db_path=test_db)
    assert stats["scanned_students"] >= 2

    # Query intervention queue
    queue = FacultyInterventionService.get_intervention_queue(category=CATEGORY_INACTIVITY, db_path=test_db)
    flagged_ids = [item["student_id"] for item in queue]

    assert "inactive_student_1" in flagged_ids
    assert "active_student_1" not in flagged_ids

    inactive_item = next(item for item in queue if item["student_id"] == "inactive_student_1")
    assert "No login activity recorded" in inactive_item["explanation"]
    assert "re-engagement" in inactive_item["suggested_action"].lower()
    assert inactive_item["urgency_level"] in (URGENCY_MEDIUM, URGENCY_HIGH)


def test_missed_deadlines_detection(test_db):
    """Verify students with expired job application deadlines are flagged."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")

    with transaction(test_db) as cursor:
        cursor.execute("""
            INSERT INTO users (id, name, email, password_hash)
            VALUES ('student_deadlines', 'Bob Deadline', 'bob@campus.edu', 'hash')
        """)
        # Overdue application
        cursor.execute("""
            INSERT INTO job_applications (id, student_id, company_name, role_title, status, application_date, deadline_date)
            VALUES ('app_overdue', 'student_deadlines', 'SecretCorp', 'SDE Intern', 'Applied', '2026-11-01', ?)
        """, (yesterday,))

        # Active student with future deadline
        cursor.execute("""
            INSERT INTO users (id, name, email, password_hash)
            VALUES ('student_ontime', 'Carol Ontime', 'carol@campus.edu', 'hash')
        """)
        cursor.execute("""
            INSERT INTO job_applications (id, student_id, company_name, role_title, status, application_date, deadline_date)
            VALUES ('app_future', 'student_ontime', 'FutureCorp', 'Full Stack', 'Applied', '2026-11-20', ?)
        """, (tomorrow,))

    FacultyInterventionService.scan_students_for_interventions(db_path=test_db)
    queue = FacultyInterventionService.get_intervention_queue(category=CATEGORY_MISSED_DEADLINES, db_path=test_db)
    flagged_ids = [item["student_id"] for item in queue]

    assert "student_deadlines" in flagged_ids
    assert "student_ontime" not in flagged_ids

    item = next(i for i in queue if i["student_id"] == "student_deadlines")
    assert "deadline(s) passed" in item["explanation"].lower()
    assert "advisory check-in" in item["suggested_action"].lower()
    # Sensitive company name should NOT be exposed in privacy-preserving explanation
    assert "SecretCorp" not in item["explanation"]


def test_stopped_preparation_detection(test_db):
    """Verify students who had preparation activity in the past but stopped for >= 14 days are flagged."""
    twenty_days_ago = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    with transaction(test_db) as cursor:
        # Student who stopped prep
        cursor.execute("""
            INSERT INTO users (id, name, email, password_hash)
            VALUES ('student_stopped_prep', 'David Stalled', 'david@campus.edu', 'hash')
        """)
        cursor.execute("""
            INSERT INTO student_streaks (student_id, current_streak, longest_streak, last_activity_date, total_active_days)
            VALUES ('student_stopped_prep', 0, 15, ?, 25)
        """, (twenty_days_ago,))

        # Student with active prep yesterday
        cursor.execute("""
            INSERT INTO users (id, name, email, password_hash)
            VALUES ('student_active_prep', 'Eve Consistent', 'eve@campus.edu', 'hash')
        """)
        cursor.execute("""
            INSERT INTO student_streaks (student_id, current_streak, longest_streak, last_activity_date, total_active_days)
            VALUES ('student_active_prep', 5, 20, ?, 30)
        """, (yesterday,))

    FacultyInterventionService.scan_students_for_interventions(db_path=test_db)
    queue = FacultyInterventionService.get_intervention_queue(category=CATEGORY_STOPPED_PREP, db_path=test_db)
    flagged_ids = [item["student_id"] for item in queue]

    assert "student_stopped_prep" in flagged_ids
    assert "student_active_prep" not in flagged_ids

    item = next(i for i in queue if i["student_id"] == "student_stopped_prep")
    assert "Preparation halted" in item["explanation"]
    assert "aptitude and dsa" in item["suggested_action"].lower()


def test_repeated_low_interview_scores_detection(test_db):
    """Verify students with >= 2 mock interviews scoring < 60% are flagged."""
    with transaction(test_db) as cursor:
        cursor.execute("""
            INSERT INTO users (id, name, email, password_hash)
            VALUES ('student_low_interviews', 'Frank Struggling', 'frank@campus.edu', 'hash')
        """)
        # First low interview analysis and session
        cursor.execute("""
            INSERT INTO analyses (id, resume_filename, company_name, student_id, results_json, created_at)
            VALUES ('an_1', 'resume.pdf', 'Acme', 'student_low_interviews', '{}', '2026-11-10 10:00:00')
        """)
        answers_low_1 = json.dumps([
            {"question": "Tell me about yourself", "type": "HR", "evaluation": {"score": 45}},
            {"question": "Explain QuickSort", "type": "Technical", "evaluation": {"score": 50}},
        ])
        cursor.execute("""
            INSERT INTO interviews (id, analysis_id, questions_json, answers_json, completed)
            VALUES ('int_1', 'an_1', '[]', ?, 1)
        """, (answers_low_1,))

        # Second low interview analysis and session
        cursor.execute("""
            INSERT INTO analyses (id, resume_filename, company_name, student_id, results_json, created_at)
            VALUES ('an_2', 'resume.pdf', 'BetaCorp', 'student_low_interviews', '{}', '2026-11-15 10:00:00')
        """)
        answers_low_2 = json.dumps([
            {"question": "Describe a difficult bug", "type": "Behavioral", "evaluation": {"score": 40}},
            {"question": "System Design Basics", "type": "Technical", "evaluation": {"score": 55}},
        ])
        cursor.execute("""
            INSERT INTO interviews (id, analysis_id, questions_json, answers_json, completed)
            VALUES ('int_2', 'an_2', '[]', ?, 1)
        """, (answers_low_2,))

        # High scoring student (control)
        cursor.execute("""
            INSERT INTO users (id, name, email, password_hash)
            VALUES ('student_high_interviews', 'Grace High', 'grace@campus.edu', 'hash')
        """)
        cursor.execute("""
            INSERT INTO analyses (id, resume_filename, company_name, student_id, results_json, created_at)
            VALUES ('an_3', 'resume.pdf', 'GammaCorp', 'student_high_interviews', '{}', '2026-11-16 10:00:00')
        """)
        answers_high = json.dumps([
            {"question": "Explain BST", "type": "Technical", "evaluation": {"score": 85}},
            {"question": "Why our company?", "type": "HR", "evaluation": {"score": 90}},
        ])
        cursor.execute("""
            INSERT INTO interviews (id, analysis_id, questions_json, answers_json, completed)
            VALUES ('int_3', 'an_3', '[]', ?, 1)
        """, (answers_high,))

    FacultyInterventionService.scan_students_for_interventions(db_path=test_db)
    queue = FacultyInterventionService.get_intervention_queue(category=CATEGORY_REPEATED_LOW_SCORES, db_path=test_db)
    flagged_ids = [item["student_id"] for item in queue]

    assert "student_low_interviews" in flagged_ids
    assert "student_high_interviews" not in flagged_ids

    item = next(i for i in queue if i["student_id"] == "student_low_interviews")
    assert "Multiple low mock interview evaluations" in item["explanation"]
    assert "1-on-1 faculty coaching" in item["suggested_action"].lower() or "star" in item["suggested_action"].lower()
    # Question text should NOT leak in explanation
    assert "Tell me about yourself" not in item["explanation"]
    assert "Explain QuickSort" not in item["explanation"]


def test_coordinator_workflow_status_transitions_and_action_notes(test_db):
    """Verify coordinator actions (In Progress, Resolved, Snoozed, Action Notes) function accurately."""
    res = FacultyInterventionService.create_manual_intervention(
        student_id="test_student_workflow",
        category=CATEGORY_INACTIVITY,
        explanation="Student has not accessed the placement portal for 25 days.",
        suggested_action="Call student or parent to discuss placement opt-in.",
        urgency_level=URGENCY_HIGH,
        student_name="Workflow Candidate",
        db_path=test_db,
    )
    assert res["success"] is True
    int_id = res["id"]

    # 1. Update status to in_progress with notes
    action_1 = FacultyInterventionService.record_faculty_action(
        intervention_id=int_id,
        new_status=STATUS_IN_PROGRESS,
        notes="Contacted via email on Monday. Waiting for response.",
        resolved_by="Prof. Sharma",
        db_path=test_db,
    )
    assert action_1["success"] is True
    item_1 = FacultyInterventionService.get_intervention_by_id(int_id, db_path=test_db)
    assert item_1["status"] == STATUS_IN_PROGRESS
    assert "Waiting for response" in item_1["action_notes"]
    assert "Prof. Sharma" in item_1["action_notes"]

    # 2. Snooze for 7 days
    action_2 = FacultyInterventionService.record_faculty_action(
        intervention_id=int_id,
        new_status=STATUS_SNOOZED,
        notes="Snoozing while student completes medical leave.",
        resolved_by="Prof. Sharma",
        snooze_days=7,
        db_path=test_db,
    )
    assert action_2["success"] is True
    assert action_2["snoozed_until"] is not None
    item_2 = FacultyInterventionService.get_intervention_by_id(int_id, db_path=test_db)
    assert item_2["status"] == STATUS_SNOOZED
    assert item_2["snoozed_until"] == action_2["snoozed_until"]

    # 3. Resolve the intervention
    action_3 = FacultyInterventionService.record_faculty_action(
        intervention_id=int_id,
        new_status=STATUS_RESOLVED,
        notes="Student attended counseling and resumed practice.",
        resolved_by="Prof. Sharma",
        db_path=test_db,
    )
    assert action_3["success"] is True
    item_3 = FacultyInterventionService.get_intervention_by_id(int_id, db_path=test_db)
    assert item_3["status"] == STATUS_RESOLVED


def test_intervention_queue_filtering_and_metrics(test_db):
    """Verify queue filtering by category, status, urgency, and summary metric counters."""
    # Create several interventions across categories
    FacultyInterventionService.create_manual_intervention(
        student_id="st_1",
        category=CATEGORY_INACTIVITY,
        explanation="Inactive account",
        suggested_action="Outreach",
        urgency_level=URGENCY_HIGH,
        department="Computer Science",
        db_path=test_db,
    )
    FacultyInterventionService.create_manual_intervention(
        student_id="st_2",
        category=CATEGORY_MISSED_DEADLINES,
        explanation="Missed deadline",
        suggested_action="Review",
        urgency_level=URGENCY_MEDIUM,
        department="Information Technology",
        db_path=test_db,
    )
    FacultyInterventionService.create_manual_intervention(
        student_id="st_3",
        category=CATEGORY_STOPPED_PREP,
        explanation="Stopped prep",
        suggested_action="Assign modules",
        urgency_level=URGENCY_LOW,
        department="Computer Science",
        db_path=test_db,
    )

    # Summary metrics
    metrics = FacultyInterventionService.get_intervention_summary_metrics(db_path=test_db)
    assert metrics["total_active"] >= 3
    assert metrics["high_urgency"] >= 1
    assert metrics["inactivity_count"] >= 1
    assert metrics["missed_deadlines_count"] >= 1
    assert metrics["stopped_prep_count"] >= 1

    # Filter by category
    cs_inactive = FacultyInterventionService.get_intervention_queue(
        category=CATEGORY_INACTIVITY,
        department="Computer Science",
        db_path=test_db,
    )
    assert len(cs_inactive) >= 1
    assert all(i["category"] == CATEGORY_INACTIVITY for i in cs_inactive)

    # Filter by urgency
    high_items = FacultyInterventionService.get_intervention_queue(
        urgency=URGENCY_HIGH,
        db_path=test_db,
    )
    assert len(high_items) >= 1
    assert all(i["urgency_level"] == URGENCY_HIGH for i in high_items)


def test_intervention_queue_access_control_and_api(test_db):
    """Verify route authentication guards and REST API functionality."""
    client = app.test_client()

    # 1. Unauthorized request without coordinator/admin credentials returns 403 or redirect
    unauth_resp = client.get("/api/admin/interventions")
    assert unauth_resp.status_code == 403

    unauth_view = client.get("/admin/intervention-queue")
    assert unauth_view.status_code in (302, 403)

    # 2. Authorized coordinator session
    with client.session_transaction() as sess:
        sess["user_id"] = "placement_coordinator_1"
        sess["user_role"] = "coordinator"
        sess["is_admin"] = True

    # 3. GET /admin/intervention-queue view returns 200 with HTML
    view_resp = client.get("/admin/intervention-queue")
    assert view_resp.status_code == 200
    assert b"Faculty Intervention Queue" in view_resp.data
    assert b"Privacy Protected" in view_resp.data

    # 4. GET /api/admin/interventions returns 200 with JSON payload
    api_resp = client.get("/api/admin/interventions")
    assert api_resp.status_code == 200
    payload = api_resp.get_json()
    assert payload["success"] is True
    assert "interventions" in payload
    assert "summary" in payload

    # 5. POST /api/admin/interventions/scan triggers student scan
    scan_resp = client.post("/api/admin/interventions/scan")
    assert scan_resp.status_code == 200
    scan_payload = scan_resp.get_json()
    assert scan_payload["success"] is True
    assert "stats" in scan_payload
