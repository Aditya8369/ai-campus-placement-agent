"""
Comprehensive Automated Tests for Roadmap iCalendar (.ics) Export (#647).
========================================================================

Acceptance Criteria:
1. The downloaded file imports correctly into Google Calendar and Apple Calendar (RFC 5545 compliance).
2. Re-importing the same file does not create duplicate events (deterministic stable UIDs).
3. Special characters in task titles are escaped correctly (RFC 5545 §3.3.11).
4. Unit tests validate the generated iCalendar structure.
5. Privacy: No personal student data is included beyond task titles and links.
"""

import datetime as dt
import json
import re
import tempfile
from pathlib import Path
import pytest

import config
from app import app
from utils.database import init_db, save_analysis
from utils.roadmap_calendar import (
    escape_ics_text,
    fold_ics_line,
    extract_week_tasks,
    generate_stable_task_uid,
    parse_start_date,
    parse_study_time,
    generate_roadmap_ics,
)


@pytest.fixture
def test_client(monkeypatch):
    """Provides a Flask test client with an isolated SQLite database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_roadmap_calendar.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db)
        monkeypatch.setattr(config, "UPLOAD_FOLDER", Path(tmpdir) / "uploads")
        monkeypatch.setattr(config, "REPORT_FOLDER", Path(tmpdir) / "reports")
        config.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
        config.REPORT_FOLDER.mkdir(parents=True, exist_ok=True)
        init_db()

        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        with app.test_client() as client:
            yield client


# ==============================================================================
# 1. Unit Tests: RFC 5545 Escaping & Line Folding
# ==============================================================================

def test_escape_ics_text_special_characters():
    """
    Acceptance criterion: Special characters in task titles are escaped correctly
    according to RFC 5545 §3.3.11 (commas, semicolons, backslashes, line breaks).
    """
    raw_text = "Master C++, STL; practice 'Binary Search, Trees' \\ graphs\r\nSecond Line\nThird Line"
    escaped = escape_ics_text(raw_text)

    # Commas must be escaped
    assert r"\," in escaped
    # Semicolons must be escaped
    assert r"\;" in escaped
    # Backslashes must be double-escaped
    assert r"\\" in escaped
    # CRLF and LF must be converted to literal \n
    assert "\r" not in escaped
    assert "\n" not in escaped
    assert r"\nSecond Line\nThird Line" in escaped


def test_escape_ics_text_handles_none_and_numbers():
    """Ensures None returns empty string and numbers are converted cleanly."""
    assert escape_ics_text(None) == ""
    assert escape_ics_text(12345) == "12345"
    assert escape_ics_text("") == ""


def test_fold_ics_line_strict_75_octets():
    """
    RFC 5545 §3.1 requires lines to not exceed 75 octets.
    Continuation lines must begin with a single ASCII space (byte 32).
    """
    # Short line: no folding
    short_line = "SUMMARY:Short study task"
    assert fold_ics_line(short_line) == short_line

    # Long line: > 75 octets
    long_line = "DESCRIPTION:This is an extremely detailed and thorough preparation task intended to verify strict line folding according to RFC 5545 specification without splitting multibyte UTF-8 characters."
    folded = fold_ics_line(long_line, max_octets=75)

    # Must contain CRLF folding
    assert "\r\n " in folded

    # Every physical line in the folded output must be <= 75 octets
    lines = folded.split("\r\n")
    for idx, l in enumerate(lines):
        line_bytes = l.encode("utf-8")
        assert len(line_bytes) <= 75, f"Line {idx} exceeds 75 octets: {len(line_bytes)}"
        if idx > 0:
            assert l.startswith(" "), f"Continuation line {idx} does not start with space"


# ==============================================================================
# 2. Unit Tests: Stable Deterministic UIDs & Deduplication
# ==============================================================================

def test_stable_uid_identical_on_rerun():
    """
    Acceptance criterion: Re-importing the same file does not create duplicate events.
    Verifies that calling generate_stable_task_uid with identical inputs generates
    the EXACT same deterministic UID.
    """
    uid1 = generate_stable_task_uid(
        analysis_id="analysis-uuid-1234",
        week_number=1,
        task_code="top",
        task_index=2,
        task_title="Docker Containerization Basics",
    )
    uid2 = generate_stable_task_uid(
        analysis_id="analysis-uuid-1234",
        week_number=1,
        task_code="top",
        task_index=2,
        task_title="Docker Containerization Basics",
    )
    assert uid1 == uid2
    assert uid1.startswith("roadmap-analysis-uuid-1234-w1-top2-")
    assert uid1.endswith("@ai-campus-placement-agent")


def test_stable_uid_distinguishes_different_tasks():
    """Verifies that different weeks, indexes, or task titles yield distinct UIDs."""
    uid_a = generate_stable_task_uid("aid", 1, "top", 1, "Python Basics")
    uid_b = generate_stable_task_uid("aid", 1, "top", 2, "Python Data Structures")
    uid_c = generate_stable_task_uid("aid", 2, "top", 1, "Python Basics")

    assert uid_a != uid_b
    assert uid_a != uid_c
    assert uid_b != uid_c


# ==============================================================================
# 3. Unit Tests: Task Extraction & Spreading
# ==============================================================================

def test_extract_week_tasks_categories():
    """Extracts topics, coding practice, weekly task, projects, and interview questions."""
    week_data = {
        "week": "Week 1",
        "week_number": 1,
        "skills": ["Docker", "Linux"],
        "topics": ["Linux File Permissions", "Shell Scripting"],
        "coding_practice": ["Write a bash backup script"],
        "practice_task": "Build and run a multi-stage Dockerfile",
        "mini_projects": ["Containerized Flask API"],
        "interview_questions": ["Explain Linux fork vs exec"],
        "revision_tasks": ["Review process states"],
    }
    tasks = extract_week_tasks(week_data)
    assert len(tasks) == 7

    categories = [t["category"] for t in tasks]
    assert "Topic to Learn" in categories
    assert "Coding Practice" in categories
    assert "Weekly Practice Task" in categories
    assert "Micro Project" in categories
    assert "Interview Prep Question" in categories
    assert "Revision Task" in categories


# ==============================================================================
# 4. Unit Tests: Calendar Generation & RFC 5545 Compliance
# ==============================================================================

def test_generate_roadmap_ics_timed_events_structure():
    """
    Acceptance criterion: Generates valid iCalendar text with timed events.
    Verifies VCALENDAR, VEVENT, CRLF, DTSTART, DTEND, and study time default 19:00.
    """
    sample_plan = [
        {
            "week": "Week 1",
            "week_number": 1,
            "skills": ["SQL", "PostgreSQL"],
            "topics": ["Indexing Strategies", "Query Optimization"],
            "practice_task": "Optimize slow JOIN queries with EXPLAIN ANALYZE",
        },
        {
            "week": "Week 2",
            "week_number": 2,
            "skills": ["Docker"],
            "topics": ["Multi-stage builds", "Docker Compose"],
            "practice_task": "Compose PostgreSQL and Redis services",
        },
    ]

    ics_output = generate_roadmap_ics(
        roadmap_data={"plan": sample_plan, "company_name": "Google", "target_role": "Backend Engineer"},
        start_date="2026-12-01",
        daily_study_time="19:00",
        duration_minutes=60,
        all_day=False,
        analysis_id="test-analysis-101",
        company_name="Google",
        target_role="Backend Engineer",
    )

    # 1. Structure checks
    assert ics_output.startswith("BEGIN:VCALENDAR\r\n")
    assert ics_output.endswith("END:VCALENDAR\r\n")
    assert "VERSION:2.0\r\n" in ics_output
    assert "PRODID:-//AI Campus Placement Agent//Roadmap Calendar Export//EN\r\n" in ics_output
    assert "METHOD:PUBLISH\r\n" in ics_output
    assert "X-WR-CALNAME:Google Study Roadmap\r\n" in ics_output

    # 2. Strict CRLF compliance across all lines
    raw_lines = ics_output.split("\r\n")
    for l in raw_lines:
        assert "\n" not in l
        assert "\r" not in l
        # Line length constraint
        assert len(l.encode("utf-8")) <= 75

    # 3. Timed event checks (19:00 study time and 1-hour duration -> 20:00 end)
    assert "DTSTART:20261201T190000\r\n" in ics_output
    assert "DTEND:20261201T200000\r\n" in ics_output

    # 4. Week 2 events must be spread 7 days later
    assert "DTSTART:20261208T190000\r\n" in ics_output


def test_generate_roadmap_ics_allday_mode():
    """Acceptance criterion: Generates valid all-day events when all_day=True."""
    sample_plan = [
        {
            "week": "Week 1",
            "week_number": 1,
            "skills": ["Git"],
            "topics": ["Interactive Rebase"],
        }
    ]

    ics_output = generate_roadmap_ics(
        roadmap_data={"plan": sample_plan},
        start_date="2026-12-05",
        all_day=True,
        analysis_id="aid-allday",
    )

    # VALUE=DATE format for all-day events
    assert "DTSTART;VALUE=DATE:20261205\r\n" in ics_output
    assert "DTEND;VALUE=DATE:20261206\r\n" in ics_output
    # No time component in all-day mode
    assert "T190000" not in ics_output


def test_generate_roadmap_ics_privacy_guarantee():
    """
    Acceptance criterion: Privacy - Do not include personal student data
    beyond the task titles and links.
    """
    sample_plan = [
        {
            "week": "Week 1",
            "week_number": 1,
            "skills": ["Python"],
            "topics": ["Decorators and Generators"],
            "practice_task": "Implement an LRU Cache decorator",
        }
    ]

    ics_output = generate_roadmap_ics(
        roadmap_data={"plan": sample_plan},
        start_date="2026-12-01",
        analysis_id="analysis-pvt-999",
        company_name="Microsoft",
        target_role="Software Engineer",
    )

    # Must contain task titles and links
    assert "LRU Cache" in ics_output
    assert "/dashboard/analysis-pvt-999#roadmapSection" in ics_output

    # Must NOT contain personal identifiers
    assert "email" not in ics_output.lower()
    assert "student_id" not in ics_output.lower()
    assert "phone" not in ics_output.lower()
    assert "@gmail.com" not in ics_output
    assert "@example.com" not in ics_output


def test_calendar_reimport_uids_are_deterministic():
    """
    Verifies that generating the .ics twice with the same roadmap produces
    identical UIDs across all events, allowing calendars to update seamlessly.
    """
    plan = [
        {"week": "Week 1", "week_number": 1, "topics": ["Trees", "Graphs"]},
        {"week": "Week 2", "week_number": 2, "topics": ["Dynamic Programming"]},
    ]

    ics1 = generate_roadmap_ics(roadmap_data={"plan": plan}, analysis_id="sync-test-id", start_date="2026-12-01")
    ics2 = generate_roadmap_ics(roadmap_data={"plan": plan}, analysis_id="sync-test-id", start_date="2026-12-01")

    uids1 = re.findall(r"UID:(.+?)\r\n", ics1)
    uids2 = re.findall(r"UID:(.+?)\r\n", ics2)

    assert len(uids1) == 3
    assert uids1 == uids2


# ==============================================================================
# 5. Integration Tests: REST API Endpoints
# ==============================================================================

def test_api_analysis_roadmap_calendar_export_get(test_client):
    """GET /api/analysis/<analysis_id>/roadmap/calendar.ics returns .ics attachment."""
    analysis_record = {
        "analysis_id": "test-cal-export-647",
        "company_name": "Amazon",
        "target_role": "SDE 1",
        "job_description": "Proficiency in Java, Spring Boot, and AWS.",
        "resume_filename": "candidate.pdf",
        "results": {
            "job_match": {
                "matched_skills": ["Java"],
                "missing_skills": ["Spring Boot", "AWS"],
            },
            "skill_gap": [
                {"skill": "Spring Boot", "importance": "High"},
                {"skill": "AWS", "importance": "High"},
            ],
        },
    }
    save_analysis(
        analysis_id=analysis_record["analysis_id"],
        resume_filename=analysis_record["resume_filename"],
        company_name=analysis_record["company_name"],
        job_description=analysis_record["job_description"],
        results_dict=analysis_record["results"],
    )

    resp = test_client.get(
        "/api/analysis/test-cal-export-647/roadmap/calendar.ics?start_date=2026-12-01&study_time=19:00&duration=60"
    )
    assert resp.status_code == 200
    assert "text/calendar" in resp.headers["Content-Type"]
    assert "attachment" in resp.headers["Content-Disposition"]
    assert "placement-roadmap-Amazon.ics" in resp.headers["Content-Disposition"]

    ics_content = resp.get_data(as_text=True)
    assert "BEGIN:VCALENDAR" in ics_content
    assert "END:VCALENDAR" in ics_content
    assert "Spring Boot" in ics_content or "AWS" in ics_content
    assert "UID:roadmap-test-cal-export-647" in ics_content


def test_api_analysis_roadmap_calendar_export_post_custom_plan(test_client):
    """POST /api/analysis/<analysis_id>/roadmap/calendar.ics exports customized plan."""
    analysis_record = {
        "analysis_id": "test-cal-custom-647",
        "company_name": "Netflix",
        "target_role": "Backend Engineer",
        "job_description": "Distributed systems",
        "resume_filename": "cv.pdf",
        "results": {
            "job_match": {"matched_skills": ["Python"], "missing_skills": ["Kafka"]},
            "skill_gap": [{"skill": "Kafka", "importance": "High"}],
        },
    }
    save_analysis(
        analysis_id=analysis_record["analysis_id"],
        resume_filename=analysis_record["resume_filename"],
        company_name=analysis_record["company_name"],
        job_description=analysis_record["job_description"],
        results_dict=analysis_record["results"],
    )

    custom_plan = [
        {
            "week": "Week 1",
            "week_number": 1,
            "skills": ["Kafka"],
            "topics": ["Kafka Architecture", "Partitioning & Consumer Groups"],
            "practice_task": "Spin up a Kafka broker with Docker Compose",
        }
    ]

    resp = test_client.post(
        "/api/analysis/test-cal-custom-647/roadmap/calendar.ics",
        data=json.dumps({
            "custom_roadmap": {"plan": custom_plan},
            "start_date": "2026-12-10",
            "study_time": "20:30",
            "duration": 45,
            "all_day": False,
        }),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert "text/calendar" in resp.headers["Content-Type"]
    ics_text = resp.get_data(as_text=True)
    assert "Kafka Architecture" in ics_text
    assert "DTSTART:20261210T203000\r\n" in ics_text
    assert "DTEND:20261210T211500\r\n" in ics_text


def test_api_roadmap_calendar_standalone(test_client):
    """POST /api/roadmap/calendar.ics exports standalone roadmap calendar without analysis ID."""
    resp = test_client.post(
        "/api/roadmap/calendar.ics",
        data=json.dumps({
            "missing_skills": ["Kubernetes", "Helm"],
            "weeks": 2,
            "hours_per_week": 10,
            "company_name": "Stripe",
            "target_role": "DevOps Engineer",
            "start_date": "2026-12-15",
            "study_time": "18:00",
            "duration": 60,
        }),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert "text/calendar" in resp.headers["Content-Type"]
    ics_text = resp.get_data(as_text=True)
    assert "BEGIN:VCALENDAR" in ics_text
    assert "Stripe Study Roadmap" in ics_text
    assert "DTSTART:20261215T180000\r\n" in ics_text


def test_dashboard_renders_calendar_modal_and_button(test_client):
    """GET /dashboard/<analysis_id> renders Add to Calendar button and modal."""
    analysis_record = {
        "analysis_id": "test-dash-cal-button",
        "company_name": "Apple",
        "job_description": "iOS Developer",
        "resume_filename": "resume.pdf",
        "results": {
            "job_match": {"matched_skills": ["Swift"], "missing_skills": ["SwiftUI"]},
            "skill_gap": [{"skill": "SwiftUI", "importance": "High"}],
        },
    }
    save_analysis(
        analysis_id=analysis_record["analysis_id"],
        resume_filename=analysis_record["resume_filename"],
        company_name=analysis_record["company_name"],
        job_description=analysis_record["job_description"],
        results_dict=analysis_record["results"],
    )

    resp = test_client.get("/dashboard/test-dash-cal-button")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Button & Modal elements
    assert "btnOpenCalendarModal" in html
    assert "roadmapCalendarModal" in html
    assert "btnDownloadRoadmapCalendar" in html
    assert "calendarStartDate" in html
    assert "calendarStudyTime" in html
    assert "calendarDurationSelect" in html
    assert "calendarTypeTimed" in html
    assert "calendarTypeAllDay" in html
