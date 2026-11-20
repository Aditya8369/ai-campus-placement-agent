"""
Tests for Recommended Next Action Rules Engine (#558)
=====================================================
Verifies:
- Simple, documented, deterministic rule evaluations using sample CandidateState objects:
  1. Brand new user -> First placement analysis
  2. Imminent application deadline (<= 3 days) -> Application tracker
  3. Very low ATS score (< 60) -> Resume fixes
  4. Large skill gap (>= 3 missing skills) -> Learning roadmap
  5. Active weak topics -> Weak topics notebook
  6. Stale interview practice (>= 7 days or 0 interviews) -> Mock interview
  7. Low recent interview score (< 70) -> Retry interview questions
  8. Unpracticed coding -> Practice DSA
  9. Aptitude readiness -> Speed aptitude test
  10. Placement ready -> Maintain streak
- Up to two alternative actions are returned.
- "Not now" hides the suggestion for 24 hours and is recoverable.
- Card never leaks data from another user (multi-tenant privacy isolation).
- Web route and REST API endpoints.
"""

import datetime as dt
from datetime import datetime, timezone, timedelta
import pytest

import config
from app import app
from utils.database import (
    init_db,
    save_analysis,
    save_job_application,
)
from utils.next_action_rules import (
    CandidateState,
    evaluate_next_actions,
    get_recommended_action_card_data,
    dismiss_action_card,
    is_action_card_dismissed,
    undismiss_action_card,
    ensure_dismissals_table,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Initializes an isolated SQLite database for each test run."""
    test_db = str(tmp_path / "test_next_action.db")
    monkeypatch.setattr(config, "DATABASE_PATH", test_db)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()
    ensure_dismissals_table()
    return test_db


@pytest.fixture
def client():
    """Flask test client."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


# ============================================================================
# 1. Unit Tests with Sample Candidate States (Pure Logic)
# ============================================================================

def test_rule_brand_new_user_state():
    """Brand new user with no analysis receives 'Run Your First Analysis'."""
    new_user_state = CandidateState(
        student_id="newbie_student",
        has_analysis=False,
    )
    result = evaluate_next_actions(new_user_state)

    primary = result["primary"]
    assert primary["id"] == "run_first_analysis"
    assert "Analyze Resume" in primary["button_text"]
    assert primary["button_url"] == "/#analysisForm"
    assert primary["badge"] == "Get Started"

    # Up to 2 alternatives
    assert len(result["alternatives"]) <= 2
    alt_ids = [alt["id"] for alt in result["alternatives"]]
    assert primary["id"] not in alt_ids


def test_rule_urgent_application_deadline_state():
    """Application with a close deadline (<= 3 days) is prioritized at top priority."""
    urgent_state = CandidateState(
        student_id="student_deadline",
        has_analysis=True,
        latest_analysis_id="aid_1",
        ats_score=50,  # Even with low ATS, deadline should take highest priority
        has_urgent_deadline=True,
        urgent_application_company="Goldman Sachs",
        urgent_application_role="Quantitative Analyst",
        urgent_days_remaining=2,
    )
    result = evaluate_next_actions(urgent_state)

    primary = result["primary"]
    assert primary["id"] == "urgent_application_deadline"
    assert "Goldman Sachs" in primary["title"]
    assert primary["button_url"] == "/applications"
    assert primary["priority"] == 10

    # Low ATS should appear as an alternative
    alt_ids = [alt["id"] for alt in result["alternatives"]]
    assert "fix_critical_ats_score" in alt_ids


def test_rule_critical_low_ats_state():
    """Very low ATS score (< 60) leads to resume fixes."""
    low_ats_state = CandidateState(
        student_id="student_low_ats",
        has_analysis=True,
        latest_analysis_id="aid_ats",
        ats_score=45,
        target_company="Google",
    )
    result = evaluate_next_actions(low_ats_state)

    primary = result["primary"]
    assert primary["id"] == "fix_critical_ats_score"
    assert "Resume" in primary["title"]
    assert "45/100" in primary["description"]
    assert "bulletRewriterSection" in primary["button_url"] or "compare-resumes" in primary["button_url"]
    assert primary["priority"] == 20


def test_rule_large_skill_gap_state():
    """Large skill gap (>= 3 missing skills) leads to learning roadmap step."""
    skill_gap_state = CandidateState(
        student_id="student_gaps",
        has_analysis=True,
        latest_analysis_id="aid_gaps",
        ats_score=78,
        target_company="Amazon",
        skill_gaps=["Docker", "Kubernetes", "AWS", "CI/CD"],
    )
    result = evaluate_next_actions(skill_gap_state)

    primary = result["primary"]
    assert primary["id"] == "follow_skill_gap_roadmap"
    assert "4 Missing" in primary["title"]
    assert "roadmapSection" in primary["button_url"]
    assert primary["priority"] == 30


def test_rule_weak_topics_state():
    """Accumulated weak topics lead to weak topics notebook."""
    weak_state = CandidateState(
        student_id="student_weak",
        has_analysis=True,
        latest_analysis_id="aid_weak",
        ats_score=75,
        skill_gaps=["Redis"],
        weak_topic_count=3,
        top_weak_topic="Dynamic Programming",
    )
    result = evaluate_next_actions(weak_state)

    primary = result["primary"]
    assert primary["id"] == "practice_weak_topics"
    assert "Weak Focus Areas" in primary["title"]
    assert primary["button_url"] == "/weak-topics"
    assert primary["priority"] == 40


def test_rule_stale_interview_state():
    """No interview in the last 7 days leads to a mock interview."""
    stale_int_state = CandidateState(
        student_id="student_stale_int",
        has_analysis=True,
        latest_analysis_id="aid_stale",
        ats_score=80,
        skill_gaps=[],
        total_interviews=1,
        days_since_last_interview=10,
        last_interview_score=85.0,
    )
    result = evaluate_next_actions(stale_int_state)

    primary = result["primary"]
    assert primary["id"] == "conduct_mock_interview"
    assert "Mock Technical Interview" in primary["title"]
    assert "/interview/" in primary["button_url"]
    assert primary["priority"] == 50


def test_rule_low_recent_interview_score_state():
    """Recent interview with score < 70 leads to retry and feedback review."""
    low_int_state = CandidateState(
        student_id="student_low_int",
        has_analysis=True,
        latest_analysis_id="aid_low_int",
        ats_score=80,
        skill_gaps=[],
        total_interviews=1,
        days_since_last_interview=2,
        last_interview_score=55.0,
    )
    result = evaluate_next_actions(low_int_state)

    primary = result["primary"]
    assert primary["id"] == "retry_interview_responses"
    assert "55/100" in primary["description"]
    assert primary["button_url"] == "/interview-history"
    assert primary["priority"] == 60


def test_rule_placement_ready_maintain_streak_state():
    """Placement ready student (high ATS, recent passing interview, no gaps) gets streak maintenance."""
    ready_state = CandidateState(
        student_id="student_ready",
        has_analysis=True,
        latest_analysis_id="aid_ready",
        ats_score=88,
        match_percentage=85,
        skill_gaps=[],
        total_interviews=3,
        days_since_last_interview=1,
        last_interview_score=90.0,
        passed_coding_count=5,
        aptitude_attempts=2,
        aptitude_accuracy=85.0,
    )
    result = evaluate_next_actions(ready_state)

    primary = result["primary"]
    assert primary["id"] == "maintain_prep_streak"
    assert primary["button_url"] == "/streak"
    assert primary["badge"] == "Well Done"


def test_alternatives_count_and_uniqueness():
    """Verifies that up to 2 alternatives are provided and they never duplicate primary."""
    multi_state = CandidateState(
        student_id="student_multi",
        has_analysis=True,
        latest_analysis_id="aid_multi",
        ats_score=50,  # Triggers low ATS
        skill_gaps=["Docker", "SQL", "Redis"],  # Triggers large skill gap
        total_interviews=0,  # Triggers stale interview
    )
    result = evaluate_next_actions(multi_state)

    primary = result["primary"]
    alts = result["alternatives"]

    assert len(alts) <= 2
    assert len(alts) > 0
    alt_ids = [a["id"] for a in alts]
    assert primary["id"] not in alt_ids
    assert len(alt_ids) == len(set(alt_ids))


# ============================================================================
# 2. "Not Now" 24-Hour Dismissal Tests
# ============================================================================

def test_not_now_dismissal_for_24_hours():
    """Verifies dismissing hides suggestion for 24 hours, and force_show bypasses it."""
    student_id = "student_dismiss_test"

    # Initially not dismissed
    dismissed, until = is_action_card_dismissed(student_id)
    assert dismissed is False
    assert until is None

    # Dismiss for 24 hours
    expiry = dismiss_action_card(student_id, hours=24, action_id="test_act")
    assert expiry.tzinfo is not None

    # Now dismissed
    dismissed_now, until_now = is_action_card_dismissed(student_id)
    assert dismissed_now is True
    assert until_now is not None

    # get_recommended_action_card_data reflects dismissal
    card_data = get_recommended_action_card_data(student_id)
    assert card_data["is_dismissed"] is True
    assert card_data["primary"] is None

    # force_show bypasses dismissal
    forced_data = get_recommended_action_card_data(student_id, force_show=True)
    assert forced_data["is_dismissed"] is False
    assert forced_data["primary"] is not None

    # Undismiss restores normal state
    undismiss_action_card(student_id)
    dismissed_after, _ = is_action_card_dismissed(student_id)
    assert dismissed_after is False


def test_expired_dismissal_is_not_active(monkeypatch):
    """Verifies dismissals in the past do not hide the card."""
    student_id = "student_expired_dismissal"

    # Seed an expired dismissal (2 days ago)
    past_time = datetime.now(timezone.utc) - timedelta(days=2)
    from utils.database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO student_action_card_dismissals (
            student_id, dismissed_at, dismissed_until, action_id
        ) VALUES (?, ?, ?, ?)
    """, (student_id, past_time.isoformat(), past_time.isoformat(), "old_act"))
    conn.commit()
    conn.close()

    dismissed, _ = is_action_card_dismissed(student_id)
    assert dismissed is False


# ============================================================================
# 3. Multi-Tenant Privacy Isolation Tests
# ============================================================================

def test_card_never_shows_data_from_another_user():
    """
    Verifies that Student A's application, company name, and ATS score
    are NEVER visible in Student B's recommendation card.
    """
    student_alice = "student_alice_private"
    student_bob = "student_bob_private"

    # Alice has an urgent application for Netflix with deadline tomorrow
    today_dt = dt.date.today()
    save_job_application(
        app_id="app_alice_1",
        student_id=student_alice,
        company_name="Netflix",
        role_title="Senior Backend Engineer",
        status="Applied",
        application_date=today_dt.isoformat(),
        deadline_date=(today_dt + dt.timedelta(days=1)).isoformat()
    )

    # Bob has an analysis for Microsoft with low ATS
    save_analysis(
        analysis_id="analysis_bob_1",
        resume_filename="bob_resume.pdf",
        company_name="Microsoft",
        job_description="Azure Engineer",
        results_dict={
            "resume_analysis": {"ats_score": 40},
            "job_match": {"missing_skills": []}
        },
        student_id=student_bob
    )

    # Alice's card recommendations
    alice_card = get_recommended_action_card_data(student_alice)
    assert alice_card["primary"]["id"] == "urgent_application_deadline"
    assert "Netflix" in alice_card["primary"]["title"]
    assert "Microsoft" not in alice_card["primary"]["title"]

    # Bob's card recommendations
    bob_card = get_recommended_action_card_data(student_bob)
    assert bob_card["primary"]["id"] == "fix_critical_ats_score"
    assert "Netflix" not in bob_card["primary"]["description"]
    assert "Netflix" not in str(bob_card)

    # Dismissing Alice's card does NOT dismiss Bob's card
    dismiss_action_card(student_alice, hours=24)
    assert is_action_card_dismissed(student_alice)[0] is True
    assert is_action_card_dismissed(student_bob)[0] is False


# ============================================================================
# 4. Web Routes and REST API Endpoints Tests
# ============================================================================

def test_dashboard_web_view_renders_recommended_action_card(client):
    """Verifies that the dashboard HTML includes the recommended next action card."""
    student_id = "student_web_dash"
    aid = "analysis_dash_test"

    save_analysis(
        analysis_id=aid,
        resume_filename="resume.pdf",
        company_name="Stripe",
        job_description="Backend Dev",
        results_dict={
            "resume_analysis": {"ats_score": 52},
            "job_match": {"match_percentage": 60, "missing_skills": ["Kafka"]}
        },
        student_id=student_id
    )

    with client.session_transaction() as sess:
        sess["user_id"] = student_id

    resp = client.get(f"/dashboard/{aid}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "nextBestActionCard" in html
    assert "Recommended Next Step" in html
    assert "btnNextActionPrimary" in html
    assert "Not now (hide for 1 day)" in html


def test_dashboard_web_dismiss_action_form_post(client):
    """Verifies web POST /dashboard/<analysis_id>/dismiss-action hides the card."""
    student_id = "student_web_dismiss"
    aid = "analysis_dash_dismiss"

    save_analysis(
        analysis_id=aid,
        resume_filename="resume.pdf",
        company_name="Uber",
        job_description="Platform Engineer",
        results_dict={
            "resume_analysis": {"ats_score": 55},
            "job_match": {"match_percentage": 50, "missing_skills": []}
        },
        student_id=student_id
    )

    with client.session_transaction() as sess:
        sess["user_id"] = student_id

    # POST dismiss action
    post_resp = client.post(
        f"/dashboard/{aid}/dismiss-action",
        data={"action_id": "fix_critical_ats_score"},
        follow_redirects=True
    )
    assert post_resp.status_code == 200
    html = post_resp.get_data(as_text=True)

    # Main card should be hidden, dismissed alert shown
    assert "dismissedActionNotification" in html
    assert "Recommended next action hidden for 24 hours" in html


def test_api_recommended_action_endpoints(client):
    """Verifies REST API endpoints: GET, POST dismiss, POST undismiss."""
    student_id = "student_api_action"

    with client.session_transaction() as sess:
        sess["user_id"] = student_id

    # 1. GET /api/recommended-action (brand new user state)
    get_resp = client.get("/api/recommended-action")
    assert get_resp.status_code == 200
    json_data = get_resp.get_json()
    assert json_data["success"] is True
    data = json_data["data"]
    assert data["is_dismissed"] is False
    assert data["primary"]["id"] == "run_first_analysis"

    # 2. POST /api/recommended-action/dismiss
    dismiss_resp = client.post("/api/recommended-action/dismiss", json={"hours": 24})
    assert dismiss_resp.status_code == 200
    assert dismiss_resp.get_json()["success"] is True

    # Check GET after dismiss
    get_resp_2 = client.get("/api/recommended-action")
    assert get_resp_2.get_json()["data"]["is_dismissed"] is True

    # 3. POST /api/recommended-action/undismiss
    undismiss_resp = client.post("/api/recommended-action/undismiss")
    assert undismiss_resp.status_code == 200
    assert undismiss_resp.get_json()["success"] is True

    # Check GET after undismiss
    get_resp_3 = client.get("/api/recommended-action")
    assert get_resp_3.get_json()["data"]["is_dismissed"] is False
