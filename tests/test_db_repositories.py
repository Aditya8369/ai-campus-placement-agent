"""
Comprehensive Unit Tests for Domain Repositories (tests/test_db_repositories.py)
==============================================================================
Validates db/ connection, migrations, and each domain repository module
(users, analyses, interviews, tracker, coding_practice, reports, streaks, cohorts, system)
using an isolated temporary SQLite database for each test.
"""

import hashlib
import json
import os
import sqlite3
import time
import pytest

from db.connection import create_connection, get_connection, transaction
from db.migrations import init_db, run_migrations, get_applied_migrations, MIGRATIONS

from db.users import (
    create_user, get_user_by_email, get_user_by_id, change_user_password,
    create_auth_session, get_active_auth_session, touch_auth_session,
    get_active_auth_sessions, revoke_auth_session, revoke_other_auth_sessions,
    revoke_all_auth_sessions, enable_user_two_factor, get_user_two_factor_status,
    update_user_backup_codes, disable_user_two_factor,
    generate_email_verification_token, verify_user_email_token, is_user_email_verified,
    create_password_reset_token, get_valid_password_reset_token, reset_user_password,
    invalidate_password_reset_token, update_email_notification_preferences,
    get_email_notification_preferences, save_email_notification_preferences,
    get_user_data_export_manifest, delete_user_account_and_personal_data
)

from db.analyses import (
    save_analysis, get_analysis, get_student_versions, get_previous_analysis,
    get_previous_analysis_for_target, get_student_versions_for_target,
    get_recent_analyses, delete_analysis, get_analyses_history,
    save_batch_comparison, get_batch_comparison,
    create_analysis_annotation, get_analysis_annotations, get_analysis_annotation,
    update_analysis_annotation, delete_analysis_annotation,
    save_analysis_section_feedback, get_analysis_section_feedback,
    get_analysis_section_feedback_summary, export_analysis_section_feedback_csv
)

from db.interviews import (
    create_interview_session, get_interview_session, update_interview_session,
    save_interview_session, get_student_interview_history,
    get_student_interview_performance_analytics, save_interview_bookmark,
    bookmark_interview_question, get_interview_bookmarks, get_interview_bookmark_by_id,
    update_interview_bookmark_practice, reset_interview_bookmarks_practice,
    get_interview_bookmark_practice_stats, is_interview_bookmarked,
    remove_interview_bookmark, save_interview_experience, get_interview_experiences,
    report_interview_experience, create_preparation_note, get_preparation_notes,
    get_preparation_note_by_id, update_preparation_note, delete_preparation_note,
    get_note_category_counts, save_gd_attempt, get_student_gd_attempts,
    get_gd_attempt_by_id, delete_student_gd_attempts
)

from db.tracker import (
    save_job_application, get_job_applications, get_job_application_by_id,
    update_job_application, update_job_application_status, delete_job_application,
    get_application_stage_counts, get_application_funnel_analytics,
    export_job_applications_csv, export_job_applications_json,
    export_job_applications_markdown, get_job_applications_export_summary,
    save_calendar_event, get_calendar_events, update_calendar_event, delete_calendar_event,
    get_default_company_checklist, get_company_checklist, save_company_checklist,
    reset_company_checklist, record_viewed_job, get_recently_viewed_jobs,
    remove_recently_viewed_job, clear_recently_viewed_jobs,
    create_saved_job_description, get_saved_job_descriptions,
    get_saved_job_description_by_id, update_saved_job_description,
    delete_saved_job_description, save_job_contact, get_job_contacts, delete_job_contact
)

from db.coding_practice import (
    save_coding_submission, get_coding_submissions, save_skill_self_assessment,
    get_student_skill_self_assessments, delete_skill_self_assessment,
    get_default_technical_skills_catalog, save_student_profile, get_student_profile,
    calculate_profile_completion, save_coding_bookmark, remove_coding_bookmark,
    get_coding_bookmarks, is_coding_bookmarked, save_aptitude_attempt,
    get_student_aptitude_attempts, get_aptitude_attempt_by_id,
    get_student_weak_aptitude_topics, delete_student_aptitude_attempts
)

from db.reports import (
    create_shared_report, get_shared_report, record_shared_report_view,
    get_active_shares_for_analysis, revoke_shared_report, get_shared_report_views,
    create_secure_share_link, get_secure_shared_report, revoke_secure_share_link,
    list_student_secure_shares
)

from db.streaks import (
    record_preparation_activity, get_student_streak, get_streak_calendar,
    get_recent_preparation_activities, get_student_preparation_summary_data
)

from db.cohorts import (
    get_user_leaderboard_opt_in, set_user_leaderboard_opt_in,
    record_or_update_cohort_benchmark, get_cohort_benchmark_by_analysis_id,
    get_cohort_benchmarks, get_cohort_stats, get_user_placement_history,
    get_student_top_skill_gaps_for_company
)

from db.system import (
    create_database_backup, verify_database_integrity,
    calculate_gemini_call_cost, log_gemini_api_call, get_gemini_usage_summary,
    submit_user_feedback, get_user_feedback_list, get_feedback_metrics_summary
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Provides a fresh temporary SQLite database initialized with all migrations."""
    db_file = str(tmp_path / "test_repo.db")
    import config
    monkeypatch.setattr(config, "DATABASE_PATH", db_file)
    init_db(db_file)
    return db_file


def test_connection_and_transaction(tmp_path):
    """Verifies connection creation, sqlite3.Row row factory, and atomic transactions."""
    db_file = str(tmp_path / "conn_test.db")

    # 1. Connection creation and pragmas
    conn = create_connection(db_file)
    assert isinstance(conn, sqlite3.Connection)
    assert conn.row_factory == sqlite3.Row
    conn.close()

    # 2. Context manager get_connection
    with get_connection(db_file) as c:
        c.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")
        c.commit()

    # 3. Transaction commit on success
    with transaction(db_file) as cur:
        cur.execute("INSERT INTO test_table (name) VALUES ('Alice')")

    with get_connection(db_file) as c:
        row = c.execute("SELECT * FROM test_table WHERE name = 'Alice'").fetchone()
        assert row is not None
        assert row["name"] == "Alice"

    # 4. Transaction rollback on exception
    with pytest.raises(ValueError):
        with transaction(db_file) as cur:
            cur.execute("INSERT INTO test_table (name) VALUES ('Bob')")
            raise ValueError("Deliberate failure to test rollback")

    with get_connection(db_file) as c:
        row = c.execute("SELECT * FROM test_table WHERE name = 'Bob'").fetchone()
        assert row is None


def test_migrations_runner(tmp_path):
    """Verifies versioned schema migration tracking, execution, and idempotence."""
    db_file = str(tmp_path / "mig_test.db")

    applied = run_migrations(db_file)
    assert applied == len(MIGRATIONS)
    assert applied >= 8

    # Verify versions are stored in schema_migrations
    with get_connection(db_file) as conn:
        cur = conn.cursor()
        versions = get_applied_migrations(cur)
        assert len(versions) == len(MIGRATIONS)
        assert "001_core_schema" in versions
        assert "008_reports_and_sharing" in versions

    # Idempotence: subsequent call applies 0 migrations
    second_run = run_migrations(db_file)
    assert second_run == 0


def test_users_repository(temp_db):
    """Verifies all user authentication, session, 2FA, token, and GDPR functions."""
    # 1. User creation and lookup
    user_id = "user-alice-1"
    assert create_user(user_id, "Alice", "alice@example.com", "hashed_pwd")
    by_email = get_user_by_email("alice@example.com")
    assert by_email is not None
    assert by_email["id"] == user_id
    assert by_email["name"] == "Alice"
    by_id = get_user_by_id(user_id)
    assert by_id["email"] == "alice@example.com"

    # 2. Password change
    assert change_user_password(user_id, "new_hashed_pwd")
    updated = get_user_by_id(user_id)
    assert updated["password_hash"] == "new_hashed_pwd"

    # 3. Auth sessions
    sess = create_auth_session(user_id, "Chrome")
    assert sess["id"]
    active = get_active_auth_session(sess["id"], sess["token"], user_id)
    assert active is not None
    assert active["user_id"] == user_id
    touch_auth_session(sess["id"], user_id)
    all_sessions = get_active_auth_sessions(user_id)
    assert len(all_sessions) == 1
    sess2 = create_auth_session(user_id, "Firefox")
    assert len(get_active_auth_sessions(user_id)) == 2
    assert revoke_other_auth_sessions(user_id, sess["id"]) == 1
    assert len(get_active_auth_sessions(user_id)) == 1
    assert revoke_auth_session(user_id, sess["id"])
    assert len(get_active_auth_sessions(user_id)) == 0

    # 4. Two-factor authentication
    assert enable_user_two_factor(user_id, "SECRET_KEY", ["B1", "B2"])
    status_2fa = get_user_two_factor_status(user_id)
    assert status_2fa["enabled"] is True
    assert status_2fa["backup_codes_count"] == 2
    assert update_user_backup_codes(user_id, ["B3"])
    assert get_user_two_factor_status(user_id)["backup_codes_count"] == 1
    assert disable_user_two_factor(user_id)
    assert get_user_two_factor_status(user_id)["enabled"] is False

    # 5. Email verification tokens
    token = generate_email_verification_token(user_id)
    assert token
    assert not is_user_email_verified(user_id)
    res = verify_user_email_token(token)
    assert res is not None
    assert res["user_id"] == user_id
    assert is_user_email_verified(user_id)

    # 6. Password reset tokens
    raw_tok = "alice-secret-token"
    token_hash = hashlib.sha256(raw_tok.encode("utf-8")).hexdigest()
    expires_at = int(time.time()) + 1800
    assert create_password_reset_token(user_id, token_hash, expires_at)
    valid = get_valid_password_reset_token(token_hash)
    assert valid is not None
    assert valid["user_id"] == user_id
    assert reset_user_password(token_hash, "reset_hash")
    assert get_user_by_id(user_id)["password_hash"] == "reset_hash"

    # 7. Notification preferences
    assert update_email_notification_preferences(user_id, email="alice@test.com")
    prefs = get_email_notification_preferences(user_id)
    assert prefs["email"] == "alice@test.com"
    assert save_email_notification_preferences(user_id, {"output_language": "fr"})

    # 8. GDPR export and account deletion
    manifest = get_user_data_export_manifest(user_id)
    assert manifest["student_id"] == user_id
    assert delete_user_account_and_personal_data(user_id)
    assert get_user_by_id(user_id) is None


def test_analyses_repository(temp_db):
    """Verifies resume analyses, versioning, annotations, batch comparisons, and section feedback."""
    student = "student-123"
    results = {
        "ats_score": 85,
        "job_match": {"match_percentage": 90, "matched_skills": ["Python", "SQL"]},
        "summary": {"score": 85}
    }

    # 1. Save and get analysis
    save_analysis("analysis-1", "resume.pdf", "Google", "JD text", results, student_id=student)
    rec = get_analysis("analysis-1")
    assert rec is not None
    assert rec["company_name"] == "Google"
    assert rec["results"]["ats_score"] == 85

    # 2. Version history
    save_analysis("analysis-2", "resume_v2.pdf", "Google", "JD text", results, student_id=student, version_number=2)
    versions = get_student_versions(student)
    assert len(versions) == 2

    prev = get_previous_analysis(student, current_version=2, company_name="Google")
    assert prev is not None
    assert prev["id"] == "analysis-1"

    prev_target = get_previous_analysis_for_target(student, current_analysis_id="analysis-2", current_version=2, company_name="Google")
    assert prev_target is not None

    versions_target = get_student_versions_for_target(student, "Google")
    assert len(versions_target) == 2

    recent = get_recent_analyses(limit=5)
    assert len(recent) == 2

    history = get_analyses_history()
    assert len(history) == 2

    # 3. Batch comparison
    batch_id = save_batch_comparison(student, "resume.pdf", ["Google", "Amazon"], {"Google": 85, "Amazon": 80})
    batch = get_batch_comparison(batch_id)
    assert batch is not None
    assert "Google" in batch["companies"]

    # 4. Annotations
    anno = create_analysis_annotation(student, "analysis-1", "note", "work_experience", "Highlight leadership metrics")
    assert anno["id"]
    annos = get_analysis_annotations(student, "analysis-1")
    assert len(annos) == 1
    single_anno = get_analysis_annotation(student, "analysis-1", anno["id"])
    assert single_anno is not None
    assert update_analysis_annotation(student, "analysis-1", anno["id"], "Updated note")
    assert delete_analysis_annotation(student, "analysis-1", anno["id"])
    assert len(get_analysis_annotations(student, "analysis-1")) == 0

    # 5. Section feedback
    save_analysis_section_feedback(student, "analysis-1", "skills", "up", "Very accurate")
    fb = get_analysis_section_feedback(student, "analysis-1", "skills")
    assert fb is not None
    assert fb["rating"] == "up"
    summary = get_analysis_section_feedback_summary()
    assert summary["total_feedbacks"] == 1
    csv_data = export_analysis_section_feedback_csv()
    assert "skills" in csv_data

    # 6. Delete analysis
    assert delete_analysis("analysis-1")
    assert get_analysis("analysis-1") is None


def test_interviews_repository(temp_db):
    """Verifies interview sessions, bookmarks, experiences, prep notes, and GD attempts."""
    student = "student-int-1"

    # Seed an analysis for foreign key
    save_analysis("analysis-int", "resume.pdf", "Amazon", "JD", {"ats_score": 80}, student_id=student)

    # 1. Sessions
    create_interview_session("int-1", "analysis-int", [{"q": "Explain polymorphism"}])
    session = get_interview_session("int-1")
    assert session is not None
    assert len(session["questions"]) == 1

    update_interview_session("int-1", 1, [{"q": "Explain polymorphism", "a": "OOP concept"}], completed=True)
    updated_session = get_interview_session("int-1")
    assert updated_session["completed"] == 1
    assert len(updated_session["answers"]) == 1

    save_interview_session("int-2", student, "Amazon", "SDE", "Technical", 88.0, analysis_id="analysis-int")
    history = get_student_interview_history(student)
    assert len(history) >= 1
    analytics = get_student_interview_performance_analytics(student)
    assert analytics["total_sessions"] >= 1

    # 2. Bookmarks
    assert save_interview_bookmark(student, "q-1", "Explain indexing in SQL", category="Technical", company_name="Amazon")
    assert is_interview_bookmarked(student, "q-1")
    b_item = get_interview_bookmark_by_id(student, "q-1")
    assert b_item is not None
    assert b_item["category"] == "Technical"

    assert update_interview_bookmark_practice(student, "q-1", is_practiced=True, answer="B-tree")
    stats = get_interview_bookmark_practice_stats(student)
    assert stats["practiced"] == 1
    assert reset_interview_bookmarks_practice(student)
    assert get_interview_bookmark_practice_stats(student)["practiced"] == 0

    assert remove_interview_bookmark(student, "q-1")
    assert not is_interview_bookmarked(student, "q-1")

    # 3. Experiences
    exp_id = save_interview_experience(
        "exp-1", student, "Bob", "Microsoft", "SDE-1", "2026-11-01",
        rounds=[{"round_name": "Technical Round", "category": "Technical"}],

    )
    assert exp_id == "exp-1"
    exps = get_interview_experiences(company_name="Microsoft")
    assert len(exps) == 1
    assert report_interview_experience("exp-1", "Needs update")

    # 4. Preparation Notes
    note = create_preparation_note(student, "System Design Basics", "Load balancers & caching", category="Technical")
    assert note["id"]
    notes = get_preparation_notes(student)
    assert len(notes) == 1
    assert get_preparation_note_by_id(note["id"], student) is not None
    assert update_preparation_note(note["id"], student, "Updated Title", "New content", "Technical")
    counts = get_note_category_counts(student)
    assert counts["Technical"] == 1
    assert delete_preparation_note(note["id"], student)
    assert len(get_preparation_notes(student)) == 0

    # 5. GD Attempts
    gd = save_gd_attempt(
        student, "AI Ethics in Recruitment", "Tech Ethics", "Opening statement", "Good arguments",
        150, 85, 80, 85, 90, 85, "Clear hook", "Economic counterpoint", json.dumps({"clarity": "strong"}),

    )
    assert gd["id"]
    gd_list = get_student_gd_attempts(student)
    assert len(gd_list) == 1
    assert get_gd_attempt_by_id(gd["id"], student) is not None
    assert delete_student_gd_attempts(student) == 1


def test_tracker_repository_and_deadline_date(temp_db):
    """
    Verifies job application tracker operations, specifically ensuring deadline_date
    is persisted and updated reliably (#477), along with exports, calendar, and checklists.
    """
    student = "student-track-1"

    # 1. Save application with deadline_date (verifying Issue #477 fix)
    save_job_application(
        "app-1", student, "Google", "SWE Intern", status="Applied",
        application_date="2026-11-10", deadline_date="2026-12-01",
        notes="First interview soon"
    )
    app = get_job_application_by_id("app-1", student)
    assert app is not None
    assert app["company_name"] == "Google"
    assert app["deadline_date"] == "2026-12-01"  # Verification for #477

    # 2. Update application with new deadline_date
    assert update_job_application(
        "app-1", student, "Google", "SWE Intern", status="Interview",
        deadline_date="2026-12-15", notes="Round 2 scheduled"
    )
    app_updated = get_job_application_by_id("app-1", student)
    assert app_updated["status"] == "Interview"
    assert app_updated["deadline_date"] == "2026-12-15"  # Verification for #477

    # 3. Stages, status, funnel
    assert update_job_application_status("app-1", student, "Selected")
    stage_counts = get_application_stage_counts(student)
    assert stage_counts["Selected"] == 1
    funnel = get_application_funnel_analytics(student)
    assert funnel["total_applications"] == 1

    # 4. Exports
    csv_content = export_job_applications_csv(student)
    assert "Google" in csv_content
    json_data = export_job_applications_json(student)
    assert json_data["total_applications"] == 1
    md_content = export_job_applications_markdown(student)
    assert "SWE Intern" in md_content
    summary = get_job_applications_export_summary(student)
    assert summary["total_records"] == 1

    # 5. Contacts
    cnt_id = save_job_contact("cnt-1", "app-1", student, "Recruiter Sarah", role="Lead Recruiter", email="sarah@google.com")
    assert cnt_id == "cnt-1"
    contacts = get_job_contacts("app-1", student)
    assert len(contacts) == 1
    assert delete_job_contact("cnt-1", student)

    # 6. Delete application
    assert delete_job_application("app-1", student)
    assert get_job_application_by_id("app-1", student) is None

    # 7. Calendar events
    save_calendar_event("ev-1", student, "Mock Test", "preparation", "2026-11-25")
    events = get_calendar_events(student)
    assert len(events) == 1
    assert update_calendar_event("ev-1", student, "Mock Test 2", "preparation", "2026-11-26", completed=True)
    assert delete_calendar_event("ev-1", student)

    # 8. Checklists
    checklist = get_company_checklist(student, "Google")
    assert checklist["company_name"] == "Google"
    assert checklist["total_tasks"] > 0
    assert reset_company_checklist(student, "Google")

    # 9. Viewed jobs
    record_viewed_job(student, "job-99", "Netflix", "Data Engineer")
    viewed = get_recently_viewed_jobs(student)
    assert len(viewed) == 1
    assert remove_recently_viewed_job(student, "job-99")
    assert clear_recently_viewed_jobs(student) == 0

    # 10. Saved job descriptions
    saved_jd = create_saved_job_description(student, "Apple", "iOS Dev", "LinkedIn", "Build swift apps")
    assert saved_jd["id"]
    jds = get_saved_job_descriptions(student)
    assert len(jds) == 1
    assert get_saved_job_description_by_id(saved_jd["id"], student) is not None
    assert update_saved_job_description(saved_jd["id"], student, "Apple", "iOS Lead", "LinkedIn", "New text")
    assert delete_saved_job_description(saved_jd["id"], student)


def test_coding_practice_repository(temp_db):
    """Verifies coding submissions, skills assessment, bookmarks, profiles, and aptitude tests."""
    student = "student-code-1"

    # 1. Submissions
    sub_id = save_coding_submission(
        "sub-1", student, "Two Sum", "python", "def two_sum(): pass",
        passed=True, score=100, tests_passed=5, total_tests=5
    )
    assert sub_id == "sub-1"
    subs = get_coding_submissions(student)
    assert len(subs) == 1
    assert subs[0]["passed"] is True

    # 2. Skill self-assessments
    save_skill_self_assessment(student, "Python", "Programming Languages", "Advanced", years_experience=3.0)
    assessments = get_student_skill_self_assessments(student)
    assert len(assessments) == 1
    assert assessments[0]["proficiency_level"] == "Advanced"
    catalog = get_default_technical_skills_catalog()
    assert "Programming Languages" in catalog
    assert delete_skill_self_assessment(student, "Python")
    assert len(get_student_skill_self_assessments(student)) == 0

    # 3. Student profile & completion
    save_student_profile(
        student, full_name="John Doe", email="john@example.com", department="Computer Science",
        grad_year=2026, cgpa=8.5, target_role="Backend Developer", target_company="Amazon",
        skills=["Python", "SQL", "Docker"]
    )
    profile = get_student_profile(student)
    assert profile["full_name"] == "John Doe"
    completion = calculate_profile_completion(student)
    assert completion["completion_percentage"] > 50

    # 4. Coding bookmarks
    assert save_coding_bookmark(student, "p-101", {"id": "p-101", "title": "Merge K Sorted Lists"})
    assert is_coding_bookmarked(student, "p-101")
    bookmarks = get_coding_bookmarks(student)
    assert len(bookmarks) == 1
    assert remove_coding_bookmark(student, "p-101")
    assert not is_coding_bookmarked(student, "p-101")

    # 5. Aptitude attempts & weak topics
    apt = save_aptitude_attempt(
        student, "Quantitative", 10, 4, 40.0, 300, 600, False,
        topic_accuracy_json=json.dumps({"Probability": {"total": 5, "correct": 1, "category": "Math"}}),
        weak_topics_json=json.dumps(["Probability"]),
        results_json=json.dumps({"details": "needs practice"}),

    )
    assert apt["id"]
    attempts = get_student_aptitude_attempts(student)
    assert len(attempts) == 1
    assert get_aptitude_attempt_by_id(apt["id"], student) is not None
    weak = get_student_weak_aptitude_topics(student, threshold=60.0)
    assert len(weak) == 1
    assert weak[0]["topic"] == "Probability"
    assert delete_student_aptitude_attempts(student) == 1


def test_reports_repository(temp_db):
    """Verifies mentor report sharing, secure links, view tracking, and revocation."""
    student = "student-rep-1"
    save_analysis("analysis-rep", "resume.pdf", "Microsoft", "JD", {"ats_score": 90}, student_id=student)

    # 1. Standard mentor shared reports
    share = create_shared_report("analysis-rep", student, expires_hours=24, access_code="1234")
    assert share["id"]
    retrieved = get_shared_report(share["id"])
    assert retrieved is not None
    assert retrieved["company_name"] == "Microsoft"

    assert record_shared_report_view(share["id"], viewer_ip="192.168.1.1", user_agent="Mozilla")
    views = get_shared_report_views(share["id"], student)
    assert len(views) == 1

    active_shares = get_active_shares_for_analysis("analysis-rep", student)
    assert len(active_shares) == 1
    assert revoke_shared_report(share["id"], student)
    assert get_shared_report(share["id"]) is None

    # 2. Secure token shared report links
    sec_share = create_secure_share_link("analysis-rep", student, expiration_choice="24h")
    assert sec_share["token"]
    ok, rep_data, err = get_secure_shared_report(sec_share["token"])
    assert ok is True
    assert rep_data["company_name"] == "Microsoft"
    assert rep_data["view_count"] == 1

    shares_list = list_student_secure_shares(student)
    assert len(shares_list) == 1
    assert revoke_secure_share_link(student, sec_share["share_id"])
    ok_revoked, _, msg = get_secure_shared_report(sec_share["token"])
    assert ok_revoked is False
    assert "revoked" in msg.lower()


def test_streaks_cohorts_system(temp_db, tmp_path):
    """Verifies streaks, cohort benchmarking, telemetry, feedback, and database integrity."""
    student = "student-sys-1"

    # 1. Streaks
    record_preparation_activity(student, "resume_review", activity_date="2026-11-20")
    streak = get_student_streak(student)
    assert streak["total_active_days"] == 1
    calendar = get_streak_calendar(student, year=2026, month=11)
    assert calendar["active_days_in_month"] == 1
    activities = get_recent_preparation_activities(student)
    assert len(activities) == 1
    prep_summary = get_student_preparation_summary_data(student)
    assert prep_summary["student_id"] == student

    # 2. Cohorts and Leaderboard
    assert set_user_leaderboard_opt_in(student, True)
    assert get_user_leaderboard_opt_in(student) is True
    save_analysis("analysis-coh", "resume.pdf", "Meta", "JD", {"ats_score": 92, "job_match": {"match_percentage": 88}}, student_id=student)
    bid = record_or_update_cohort_benchmark("analysis-coh", "MetaHero", "Computer Science", 2026, 92, 88)
    assert bid
    assert get_cohort_benchmark_by_analysis_id("analysis-coh") is not None
    benchmarks = get_cohort_benchmarks(department="Computer Science")
    assert len(benchmarks) >= 1
    stats = get_cohort_stats(department="Computer Science")
    assert stats["total_students"] >= 1
    placement_history = get_user_placement_history(student)
    assert placement_history["total_analyses"] == 1
    gaps = get_student_top_skill_gaps_for_company(student, "Meta")
    assert isinstance(gaps, list)

    # 3. System & Feedback
    cost = calculate_gemini_call_cost(1000, 500)
    assert cost > 0
    log_id = log_gemini_api_call("/api/analyze", "gemini-1.5-flash", 100, 200)
    assert log_id
    usage = get_gemini_usage_summary(days=30)
    assert usage["total_calls"] >= 1

    feedback = submit_user_feedback(student, 5, "Resume ATS", "Great insights!")
    assert feedback["id"]
    f_list = get_user_feedback_list(student)
    assert len(f_list) == 1
    fb_summary = get_feedback_metrics_summary()
    assert fb_summary["total_feedback"] >= 1

    integrity = verify_database_integrity()
    assert integrity["healthy"] is True

    backup_path = str(tmp_path / "backup.db")
    res = create_database_backup(backup_path)
    assert os.path.exists(res)
