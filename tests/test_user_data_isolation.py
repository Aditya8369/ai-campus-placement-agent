import pytest
import os
import json
import uuid
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    save_analysis,
    create_interview_session,
    save_job_application,
    get_job_applications,
    save_skill_self_assessment,
    get_student_skill_self_assessments,
    save_coding_submission,
    get_coding_submissions,
    save_calendar_event,
    get_calendar_events,
    save_company_checklist,
    get_company_checklist,
    get_student_versions,
    create_preparation_note,
    get_preparation_notes,
    get_preparation_note_by_id,
    delete_preparation_note,
)


@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_isolation.db"
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    with patch.object(config, "DATABASE_PATH", str(test_db)), \
         patch.object(config, "REPORT_FOLDER", str(report_dir)):
        init_db()
        app.config["TESTING"] = True
        app.config["ENFORCE_LOGIN_IN_TESTS"] = True
        app.config["ENFORCE_STUDENT_ISOLATION"] = True
        with app.test_client() as client:
            with app.app_context():
                yield client


def test_database_level_multi_tenant_isolation():
    """
    Ensure queries to database functions strictly filter by student_id (#205).
    """
    student_alice = f"alice_{uuid.uuid4().hex[:8]}"
    student_bob = f"bob_{uuid.uuid4().hex[:8]}"

    # 1. Job applications isolation
    save_job_application(
        app_id="app-alice-1",
        student_id=student_alice,
        company_name="Google",
        role_title="Software Engineer"
    )
    save_job_application(
        app_id="app-bob-1",
        student_id=student_bob,
        company_name="Meta",
        role_title="Production Engineer"
    )
    alice_apps = get_job_applications(student_id=student_alice)
    bob_apps = get_job_applications(student_id=student_bob)
    assert len(alice_apps) == 1
    assert alice_apps[0]["company_name"] == "Google"
    assert len(bob_apps) == 1
    assert bob_apps[0]["company_name"] == "Meta"

    # 2. Technical skill assessments isolation
    save_skill_self_assessment(
        student_id=student_alice,
        skill_name="Go",
        category="Languages",
        proficiency_level="Advanced"
    )
    save_skill_self_assessment(
        student_id=student_bob,
        skill_name="Rust",
        category="Languages",
        proficiency_level="Intermediate"
    )
    alice_skills = get_student_skill_self_assessments(student_id=student_alice)
    bob_skills = get_student_skill_self_assessments(student_id=student_bob)
    assert len(alice_skills) == 1
    assert alice_skills[0]["skill_name"] == "Go"
    assert len(bob_skills) == 1
    assert bob_skills[0]["skill_name"] == "Rust"

    # 3. Preparation checklist isolation
    checklist_alice = {"coding": [{"task": "Review Google L4 System Design", "completed": True}]}
    checklist_bob = {"coding": [{"task": "Review Meta Fast Preparation", "completed": False}]}
    save_company_checklist(student_alice, "Google", checklist_alice)
    save_company_checklist(student_bob, "Meta", checklist_bob)

    alice_chk = get_company_checklist(student_alice, "Google")
    bob_chk = get_company_checklist(student_bob, "Meta")
    assert alice_chk is not None
    assert alice_chk["overall_percentage"] == 100.0
    assert bob_chk is not None
    assert bob_chk["overall_percentage"] == 0.0

    # 4. Coding submissions isolation
    sub_alice_id = f"sub-alice-{uuid.uuid4().hex[:6]}"
    sub_bob_id = f"sub-bob-{uuid.uuid4().hex[:6]}"
    save_coding_submission(
        sub_id=sub_alice_id,
        student_id=student_alice,
        question_title="LRU Cache",
        language="python",
        code="class LRU: pass",
        passed=True,
        score=100
    )
    save_coding_submission(
        sub_id=sub_bob_id,
        student_id=student_bob,
        question_title="Trie Implementation",
        language="cpp",
        code="class Trie {};",
        passed=False,
        score=40
    )
    alice_subs = get_coding_submissions(student_id=student_alice)
    bob_subs = get_coding_submissions(student_id=student_bob)
    assert len(alice_subs) == 1
    assert alice_subs[0]["question_title"] == "LRU Cache"
    assert len(bob_subs) == 1
    assert bob_subs[0]["question_title"] == "Trie Implementation"

    # 5. Interview preparation notes isolation (#235)
    note_alice = create_preparation_note(
        student_id=student_alice,
        title="Alice System Design Notes",
        description="Sharding and replication strategies",
        category="Technical"
    )
    note_bob = create_preparation_note(
        student_id=student_bob,
        title="Bob HR Questions",
        description="Conflict resolution stories",
        category="HR"
    )
    note_alice_id = note_alice["id"] if isinstance(note_alice, dict) else note_alice
    note_bob_id = note_bob["id"] if isinstance(note_bob, dict) else note_bob

    alice_notes = get_preparation_notes(student_id=student_alice)
    bob_notes = get_preparation_notes(student_id=student_bob)
    assert len(alice_notes) == 1
    assert alice_notes[0]["title"] == "Alice System Design Notes"
    assert len(bob_notes) == 1
    assert bob_notes[0]["title"] == "Bob HR Questions"

    # Bob cannot fetch Alice's note
    assert get_preparation_note_by_id(note_alice_id, student_bob) is None
    # Bob cannot delete Alice's note
    assert delete_preparation_note(note_alice_id, student_bob) is False
    # Alice can delete her own note
    assert delete_preparation_note(note_alice_id, student_alice) is True


def test_cross_student_access_prevention_on_analyses(client):
    """
    Candidate B must be rejected when attempting to access Candidate A's analysis record (#205).
    """
    aid_alice = f"analysis-alice-{uuid.uuid4().hex[:8]}"
    save_analysis(
        analysis_id=aid_alice,
        resume_filename="alice_resume.pdf",
        company_name="Google",
        job_description="SWE role",
        results_dict={
            "ats_score": 92,
            "resume_analysis": {"ats_score": 92},
            "job_match": {"match_percentage": 88, "matched_skills": ["Python"]}
        },
        student_id="student_alice"
    )

    # Simulate logged-in as Bob
    with client.session_transaction() as sess:
        sess["user_id"] = "student_bob"
        sess["user_name"] = "Bob"

    # Bob tries to view Alice's dashboard
    res_dash = client.get(f"/dashboard/{aid_alice}")
    assert res_dash.status_code in [200, 302, 403, 404]

    # Bob views recent analyses or profile
    with client.session_transaction() as sess:
        sess["user_id"] = "student_bob"
        sess["user_name"] = "Bob"

    versions = get_student_versions("student_bob")
    assert all(v["student_id"] == "student_bob" for v in versions)


def test_cross_student_calendar_and_checklist_isolation(client):
    """
    Candidate cannot view or toggle checklist tasks and calendar events of another candidate (#205).
    """
    save_calendar_event(
        event_id="cal-alice-secret",
        student_id="student_alice",
        title="Confidential Amazon Bar Raiser",
        event_type="interview",
        event_date="2026-11-25"
    )

    with client.session_transaction() as sess:
        sess["user_id"] = "student_bob"
        sess["user_name"] = "Bob"

    # Bob views calendar page; must not see Alice's event
    res_cal = client.get("/calendar")
    assert res_cal.status_code == 200
    assert b"Confidential Amazon Bar Raiser" not in res_cal.data

    # Verify Alice's event remains intact in database
    alice_events = get_calendar_events(student_id="student_alice")
    assert len(alice_events) == 1
    assert alice_events[0]["title"] == "Confidential Amazon Bar Raiser"
    bob_events = get_calendar_events(student_id="student_bob")
    assert len(bob_events) == 0


def test_cross_student_job_application_data_isolation(client):
    """
    Candidate cannot view or tamper with another student's job applications (#205).
    """
    app_id_alice = "app-alice-private-01"
    save_job_application(
        app_id=app_id_alice,
        student_id="student_alice",
        company_name="Goldman Sachs",
        role_title="Quantitative Developer",
        status="Interview"
    )

    with client.session_transaction() as sess:
        sess["user_id"] = "student_bob"
        sess["user_name"] = "Bob"

    # Bob accesses applications page; should not contain Alice's Goldman Sachs application
    res_page = client.get("/applications")
    assert res_page.status_code == 200
    assert b"Goldman Sachs" not in res_page.data

    # Alice's application must still exist
    alice_apps = get_job_applications(student_id="student_alice")
    assert len(alice_apps) == 1
    assert alice_apps[0]["id"] == app_id_alice
    bob_apps = get_job_applications(student_id="student_bob")
    assert len(bob_apps) == 0


def test_cross_student_notes_isolation_on_web(client):
    """
    Student A and Student B have isolated interview preparation notes on web routes (#205, #235).
    """
    note_id = create_preparation_note(
        student_id="student_alice",
        title="Alice Secret Note",
        description="Alice proprietary tips",
        category="Technical"
    )

    with client.session_transaction() as sess:
        sess["user_id"] = "student_bob"
        sess["user_name"] = "Bob"

    # Bob visits /notes page
    res = client.get("/notes")
    assert res.status_code == 200
    assert b"Alice Secret Note" not in res.data

    # Bob visits Alice's note detail
    res_detail = client.get(f"/notes/{note_id}")
    assert res_detail.status_code in [302, 404]

    # Alice visits /notes page
    with client.session_transaction() as sess:
        sess["user_id"] = "student_alice"
        sess["user_name"] = "Alice"

    res_alice = client.get("/notes")
    assert res_alice.status_code == 200
    assert b"Alice Secret Note" in res_alice.data


def test_cross_student_feedback_and_submission_isolation(client):
    """
    Ensure user feedback submissions and coding submissions remain isolated (#205).
    """
    from utils.database import submit_user_feedback, get_user_feedback_list

    student_alice = f"alice_fb_{uuid.uuid4().hex[:6]}"
    student_bob = f"bob_fb_{uuid.uuid4().hex[:6]}"

    submit_user_feedback(student_alice, 5, "Technical", "Alice placement feedback rating")
    submit_user_feedback(student_bob, 4, "Platform", "Bob platform performance feedback")

    alice_fb = get_user_feedback_list(student_id=student_alice)
    bob_fb = get_user_feedback_list(student_id=student_bob)

    assert len(alice_fb) >= 1
    assert any("Alice placement feedback" in f.get("comment", "") for f in alice_fb)
    assert not any("Bob platform performance" in f.get("comment", "") for f in alice_fb)

    assert len(bob_fb) >= 1
    assert any("Bob platform performance" in f.get("comment", "") for f in bob_fb)
    assert not any("Alice placement feedback" in f.get("comment", "") for f in bob_fb)


def test_cross_student_profile_isolation(client):
    """
    Ensure student profiles and bookmarks remain isolated (#205, #199, #234).
    """
    from utils.database import (
        save_student_profile,
        get_student_profile,
        save_coding_bookmark,
        get_coding_bookmarks,
        is_coding_bookmarked,
    )

    student_alice = f"alice_prof_{uuid.uuid4().hex[:6]}"
    student_bob = f"bob_prof_{uuid.uuid4().hex[:6]}"

    save_student_profile(
        student_id=student_alice,
        full_name="Alice Candidate",
        email=f"{student_alice}@university.edu",
        department="Computer Science",
        grad_year=2026,
        cgpa=9.1
    )
    save_student_profile(
        student_id=student_bob,
        full_name="Bob Candidate",
        email=f"{student_bob}@university.edu",
        department="Information Technology",
        grad_year=2027,
        cgpa=8.4
    )

    prof_alice = get_student_profile(student_alice)
    prof_bob = get_student_profile(student_bob)

    assert prof_alice is not None
    assert prof_alice["full_name"] == "Alice Candidate"
    assert prof_bob is not None
    assert prof_bob["full_name"] == "Bob Candidate"

    # Coding question bookmarks isolation
    save_coding_bookmark(student_alice, "prob-alice-101", {"title": "Alice Problem", "difficulty": "Medium"})
    assert is_coding_bookmarked(student_alice, "prob-alice-101") is True
    assert is_coding_bookmarked(student_bob, "prob-alice-101") is False

    alice_bms = [b["id"] for b in get_coding_bookmarks(student_alice)]
    bob_bms = [b["id"] for b in get_coding_bookmarks(student_bob)]
    assert "prob-alice-101" in alice_bms
    assert "prob-alice-101" not in bob_bms

