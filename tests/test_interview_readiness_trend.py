"""
Unit and Integration Tests for Interview Readiness Trend Predictions (#787).
=============================================================================
Validates:
1. Candidate trajectory projections: Improving, Stable, and At Risk.
2. Sensitivity to recent practice drill scores and completed task activity.
3. Explicit Planning Estimate labeling and placement guarantee disclaimers.
4. Graceful handling of candidates with zero or sparse initial records.
5. REST API endpoint (/api/interview/readiness-trend) and web history view.
"""

import json
from datetime import datetime, timedelta, timezone
import pytest

from app import app
from db.connection import transaction
from utils.interview_readiness_trend_service import (
    PLANNING_ESTIMATE_DISCLAIMER,
    GUARANTEE_WARNING,
    TREND_AT_RISK,
    TREND_IMPROVING,
    TREND_STABLE,
    calculate_trend_prediction,
    predict_interview_readiness_trend,
)


@pytest.fixture
def trend_test_db(tmp_path):
    """Sets up an isolated SQLite test database with schema initialized."""
    db_file = tmp_path / "test_readiness_trend.db"
    db_path = str(db_file)

    from db.migrations import init_db
    init_db(db_path)

    return db_path


def test_calculate_trend_prediction_improving():
    """Verify that rising practice scores and completed tasks trigger 'improving' trend."""
    # Scores increasing from 55 to 85 across sessions
    result = calculate_trend_prediction(
        interview_scores=[55.0, 68.0, 78.0, 85.0],
        completed_tasks_count=4,
        practice_scores=[70.0, 80.0],
        days_since_last_activity=1,
        current_streak=5,
    )

    assert result["status"] == TREND_IMPROVING
    assert result["status_label"] == "Improving"
    assert result["score_delta"] > 0
    assert result["estimated_readiness_score"] >= 75
    assert result["is_planning_estimate"] is True
    assert "Planning Estimate" in result["disclaimer"]
    assert "not a guaranteed probability" in result["disclaimer"].lower() or "not represent an official assessment" in result["disclaimer"].lower()
    assert result["guarantee_warning"] == GUARANTEE_WARNING


def test_calculate_trend_prediction_stable():
    """Verify consistent scores meeting baseline with steady tasks trigger 'stable' trend."""
    result = calculate_trend_prediction(
        interview_scores=[72.0, 70.0, 74.0],
        completed_tasks_count=2,
        practice_scores=[70.0, 75.0],
        days_since_last_activity=2,
        current_streak=3,
    )

    assert result["status"] == TREND_STABLE
    assert result["status_label"] == "Stable"
    assert abs(result["score_delta"]) <= 3.5
    assert result["is_planning_estimate"] is True
    assert result["disclaimer"] == PLANNING_ESTIMATE_DISCLAIMER


def test_calculate_trend_prediction_at_risk_declining():
    """Verify declining evaluation scores trigger 'at_risk' trend."""
    # Scores dropping from 80 down to 48
    result = calculate_trend_prediction(
        interview_scores=[80.0, 65.0, 52.0, 48.0],
        completed_tasks_count=1,
        practice_scores=[55.0, 50.0],
        days_since_last_activity=3,
        current_streak=1,
    )

    assert result["status"] == TREND_AT_RISK
    assert result["status_label"] == "At Risk"
    assert result["score_delta"] < 0
    assert result["is_planning_estimate"] is True
    assert len(result["actionable_recommendations"]) > 0


def test_calculate_trend_prediction_at_risk_low_scores():
    """Verify scores below 55% trigger 'at_risk' trend."""
    result = calculate_trend_prediction(
        interview_scores=[42.0, 46.0],
        completed_tasks_count=1,
        practice_scores=[50.0],
        days_since_last_activity=2,
    )

    assert result["status"] == TREND_AT_RISK
    assert result["recent_average_score"] < 55.0


def test_calculate_trend_prediction_at_risk_inactivity():
    """Verify 14+ days of lapsed activity triggers 'at_risk' trend regardless of prior score."""
    result = calculate_trend_prediction(
        interview_scores=[85.0],
        completed_tasks_count=0,
        days_since_last_activity=18,
    )

    assert result["status"] == TREND_AT_RISK
    assert any("18 days" in d for d in result["drivers"])


def test_planning_estimate_labeling_and_no_guarantee_guarantee():
    """Acceptance Criteria: Clearly label the result as a planning estimate and do not present it as a guaranteed placement probability."""
    for trend_type in (TREND_IMPROVING, TREND_STABLE, TREND_AT_RISK):
        dummy_scores = [85.0, 90.0] if trend_type == TREND_IMPROVING else ([70.0] if trend_type == TREND_STABLE else [40.0])
        res = calculate_trend_prediction(interview_scores=dummy_scores)

        # 1. Must be flagged as planning estimate
        assert res["is_planning_estimate"] is True
        assert res["estimate_classification"] == "Directional Planning Estimate"

        # 2. Disclaimer must be explicitly provided
        assert res["disclaimer"] == PLANNING_ESTIMATE_DISCLAIMER
        assert "Planning Estimate Only" in res["disclaimer"]

        # 3. Must warn that it is NOT a guaranteed placement probability
        assert "not a guaranteed probability" in res["disclaimer"].lower() or "not represent an official assessment" in res["disclaimer"].lower()
        assert "Do not interpret as a guaranteed placement probability" in res["guarantee_warning"]


def test_candidate_with_zero_data_fallback():
    """Verify a new candidate with 0 interviews or drills receives a graceful baseline."""
    res = calculate_trend_prediction(
        interview_scores=[],
        completed_tasks_count=0,
        practice_scores=[],
        days_since_last_activity=None,
    )

    assert res["status"] in (TREND_STABLE, TREND_AT_RISK)
    assert res["confidence"] == "low"
    assert res["is_planning_estimate"] is True
    assert res["estimated_readiness_score"] >= 15
    assert res["total_evaluations_analyzed"] == 0


def test_predict_interview_readiness_trend_db_integration(trend_test_db):
    """Verify end-to-end telemetry retrieval from database across mock interviews, aptitude, coding, and streaks."""
    sid = "student_trend_e2e"

    with transaction(trend_test_db) as cursor:
        # Create student profile
        cursor.execute("""
            INSERT INTO users (id, name, email, password_hash)
            VALUES (?, 'Trend Candidate', 'trend@campus.edu', 'hash')
        """, (sid,))

        # 1. Mock interviews
        cursor.execute("""
            INSERT INTO analyses (id, resume_filename, company_name, student_id, results_json, created_at)
            VALUES ('an_t1', 'res.pdf', 'AcmeCorp', ?, '{}', '2026-11-10 10:00:00')
        """, (sid,))
        ans_1 = json.dumps([{"question": "Q1", "evaluation": {"score": 60}}])
        cursor.execute("""
            INSERT INTO interviews (id, analysis_id, questions_json, answers_json, completed)
            VALUES ('int_t1', 'an_t1', '[]', ?, 1)
        """, (ans_1,))

        cursor.execute("""
            INSERT INTO analyses (id, resume_filename, company_name, student_id, results_json, created_at)
            VALUES ('an_t2', 'res.pdf', 'AcmeCorp', ?, '{}', '2026-11-18 10:00:00')
        """, (sid,))
        ans_2 = json.dumps([{"question": "Q1", "evaluation": {"score": 85}}])
        cursor.execute("""
            INSERT INTO interviews (id, analysis_id, questions_json, answers_json, completed)
            VALUES ('int_t2', 'an_t2', '[]', ?, 1)
        """, (ans_2,))

        # 2. Aptitude attempt
        cursor.execute("""
            INSERT INTO aptitude_attempts (id, student_id, test_category, total_questions, correct_count, score_percentage, time_taken_seconds, time_limit_seconds, topic_accuracy_json, weak_topics_json, results_json, created_at)
            VALUES ('apt_t1', ?, 'Quantitative', 10, 8, 80.0, 300, 600, '{}', '{}', '{}', '2026-11-19 12:00:00')
        """, (sid,))

        # 3. Coding submission
        cursor.execute("""
            INSERT INTO coding_submissions (id, student_id, question_title, code, passed, score, tests_passed, total_tests, submitted_at)
            VALUES ('code_t1', ?, 'Two Sum', 'code', 1, 100, 5, 5, '2026-11-20 14:00:00')
        """, (sid,))

        # 4. Activity log
        cursor.execute("""
            INSERT INTO preparation_activity_log (id, student_id, activity_date, activity_type)
            VALUES ('act_t1', ?, '2026-11-20', 'mock_interview')
        """, (sid,))

        # 5. Streak
        cursor.execute("""
            INSERT INTO student_streaks (student_id, current_streak, longest_streak, last_activity_date, total_active_days)
            VALUES (?, 4, 10, '2026-11-20', 12)
        """, (sid,))

    result = predict_interview_readiness_trend(student_id=sid, db_path=trend_test_db)

    assert result["total_evaluations_analyzed"] >= 3
    assert result["status"] == TREND_IMPROVING
    assert result["score_delta"] > 0
    assert result["current_streak"] == 4
    assert result["is_planning_estimate"] is True
    assert "Planning Estimate Only" in result["disclaimer"]


def test_api_readiness_trend_endpoint():
    """Verify REST API endpoint /api/interview/readiness-trend returns valid payload and planning estimate disclaimers."""
    client = app.test_client()

    response = client.get("/api/interview/readiness-trend?student_id=test_api_candidate")
    assert response.status_code == 200

    data = response.get_json()
    assert data["success"] is True
    assert "readiness_trend" in data

    trend = data["readiness_trend"]
    assert trend["status"] in (TREND_IMPROVING, TREND_STABLE, TREND_AT_RISK)
    assert trend["is_planning_estimate"] is True
    assert "Planning Estimate" in trend["disclaimer"]
    assert trend["guarantee_warning"] == GUARANTEE_WARNING


def test_interview_history_view_renders_readiness_trend():
    """Verify HTML template view /interview-history displays the readiness trend prediction card."""
    client = app.test_client()

    response = client.get("/interview-history?student_id=default_student")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    assert "readinessTrendCard" in html
    assert "Planning Estimate Only" in html
    assert "Trajectory:" in html
    assert "Planning Estimate Notice" in html
    assert "not a placement guarantee" in html.lower() or "not a guaranteed placement probability" in html.lower() or "planning estimate" in html.lower()
