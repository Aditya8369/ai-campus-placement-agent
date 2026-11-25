"""
Interview Readiness Trend Prediction Service (#787).
=====================================================
Analyzes recent practice drill scores (mock interviews, aptitude tests, coding submissions,
and group discussion drills) along with completed preparation tasks and activity streaks
to project whether a candidate is:
- Improving: Positive score progression and active milestone momentum.
- Stable: Consistent performance meeting readiness baselines with steady task completion.
- At Risk: Declining evaluation scores, low score thresholds (<55%), or lapsed preparation.

IMPORTANT PLANNING ESTIMATE DISCLAIMER:
---------------------------------------
All trend predictions are strictly classified and labeled as directional PLANNING ESTIMATES.
They are NOT guaranteed placement probabilities and do not represent formal employment outcomes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import config
from db.connection import get_connection
from db.interviews import get_student_interview_history

logger = logging.getLogger(__name__)

# Trend Status Classifications
TREND_IMPROVING = "improving"
TREND_STABLE = "stable"
TREND_AT_RISK = "at_risk"

ALL_TRENDS = [TREND_IMPROVING, TREND_STABLE, TREND_AT_RISK]

# Mandatory Planning Estimate Disclaimers
PLANNING_ESTIMATE_DISCLAIMER = (
    "Planning Estimate Only: This interview readiness trend prediction is a directional planning "
    "and self-assessment estimate based on recent practice drill scores and completed tasks. "
    "It does not represent an official assessment of hiring eligibility, nor is it a guaranteed "
    "probability of campus placement or employment."
)

GUARANTEE_WARNING = (
    "Directional planning indicator only. Do not interpret as a guaranteed placement probability "
    "or formal job offer guarantee."
)

# Metadata for Presentation
TREND_METADATA = {
    TREND_IMPROVING: {
        "label": "Improving",
        "badge_class": "bg-success-subtle text-success border border-success-subtle",
        "icon": "fa-solid fa-arrow-trend-up",
        "color": "#198754",
        "headline": "Positive Preparation Trajectory",
        "summary": "Your practice scores and task completion velocity show steady upward momentum.",
    },
    TREND_STABLE: {
        "label": "Stable",
        "badge_class": "bg-primary-subtle text-primary border border-primary-subtle",
        "icon": "fa-solid fa-arrow-right",
        "color": "#0d6efd",
        "headline": "Consistent Performance Baseline",
        "summary": "Your evaluation scores and preparation cadence remain steady across recent sessions.",
    },
    TREND_AT_RISK: {
        "label": "At Risk",
        "badge_class": "bg-danger-subtle text-danger border border-danger-subtle",
        "icon": "fa-solid fa-arrow-trend-down",
        "color": "#dc3545",
        "headline": "Readiness Gaps or Lapsed Activity",
        "summary": "Recent scores show declining trends, low performance thresholds, or paused practice.",
    },
}


def calculate_trend_prediction(
    interview_scores: Optional[List[float]] = None,
    completed_tasks_count: int = 0,
    task_history: Optional[List[Dict[str, Any]]] = None,
    practice_scores: Optional[List[float]] = None,
    days_since_last_activity: Optional[int] = None,
    current_streak: int = 0,
) -> Dict[str, Any]:
    """
    Pure calculation function computing trend predictions from scores and completed tasks.
    Returns structured results with planning estimate labels, trend status, score momentum,
    confidence metrics, and actionable next steps.
    """
    int_scores = [float(s) for s in (interview_scores or []) if s is not None and s >= 0]
    drill_scores = [float(s) for s in (practice_scores or []) if s is not None and s >= 0]

    # Combine chronologically (mock interviews weighted slightly higher than practice drills)
    all_scores = int_scores + drill_scores
    total_score_evaluations = len(all_scores)

    # Calculate Score Average and Momentum
    score_delta = 0.0
    if len(all_scores) >= 2:
        midpoint = max(1, len(all_scores) // 2)
        earlier_scores = all_scores[:midpoint]
        later_scores = all_scores[midpoint:]
        earlier_avg = sum(earlier_scores) / len(earlier_scores)
        later_avg = sum(later_scores) / len(later_scores)
        score_delta = round(later_avg - earlier_avg, 1)
        recent_avg = round(later_avg, 1)
        overall_avg = round(sum(all_scores) / len(all_scores), 1)
    elif len(all_scores) == 1:
        recent_avg = round(all_scores[0], 1)
        overall_avg = recent_avg
        score_delta = 0.0
    else:
        recent_avg = 0.0
        overall_avg = 0.0
        score_delta = 0.0

    interview_avg = round(sum(int_scores) / len(int_scores), 1) if int_scores else 0.0
    drill_avg = round(sum(drill_scores) / len(drill_scores), 1) if drill_scores else 0.0

    # -------------------------------------------------------------------------
    # Trajectory Decision Engine
    # -------------------------------------------------------------------------
    # Risk Triggers:
    is_inactivity_risk = (days_since_last_activity is not None and days_since_last_activity >= 14)
    is_low_score_risk = (total_score_evaluations >= 1 and recent_avg < 55.0)
    is_declining_risk = (len(all_scores) >= 2 and score_delta <= -4.0)

    # Improvement Triggers:
    is_score_improving = (len(all_scores) >= 2 and score_delta >= 3.0 and recent_avg >= 60.0)
    is_high_performer_active = (
        recent_avg >= 75.0 and completed_tasks_count >= 1 and
        (days_since_last_activity is None or days_since_last_activity <= 7)
    )

    if is_inactivity_risk or is_low_score_risk or is_declining_risk:
        trend_status = TREND_AT_RISK
    elif is_score_improving or is_high_performer_active:
        trend_status = TREND_IMPROVING
    else:
        trend_status = TREND_STABLE

    # -------------------------------------------------------------------------
    # Estimated Readiness Score (0-100 Planning Metric)
    # -------------------------------------------------------------------------
    if total_score_evaluations > 0:
        base_metric = recent_avg * 0.65
        task_bonus = min(25.0, float(completed_tasks_count) * 4.0)
        streak_bonus = min(10.0, float(current_streak) * 1.5)
        momentum_adj = 5.0 if trend_status == TREND_IMPROVING else (-8.0 if trend_status == TREND_AT_RISK else 0.0)
        raw_readiness = base_metric + task_bonus + streak_bonus + momentum_adj
    else:
        # Baseline estimate based on completed tasks
        task_bonus = min(50.0, float(completed_tasks_count) * 6.0)
        streak_bonus = min(20.0, float(current_streak) * 2.5)
        raw_readiness = 40.0 + task_bonus + streak_bonus

    estimated_readiness_score = int(round(max(15.0, min(96.0, raw_readiness))))

    # -------------------------------------------------------------------------
    # Confidence Level
    # -------------------------------------------------------------------------
    if total_score_evaluations >= 4 and completed_tasks_count >= 3:
        confidence = "high"
        confidence_desc = "High confidence based on multiple recent practice evaluations and consistent task activity."
    elif total_score_evaluations >= 2 or completed_tasks_count >= 2:
        confidence = "medium"
        confidence_desc = "Moderate confidence based on initial practice drill records and milestone progression."
    else:
        confidence = "low"
        confidence_desc = "Preliminary planning estimate. Complete additional mock interviews and tasks to increase accuracy."

    # -------------------------------------------------------------------------
    # Actionable Guidance & Summary Insights
    # -------------------------------------------------------------------------
    meta = TREND_METADATA[trend_status]

    if trend_status == TREND_IMPROVING:
        drivers = [
            f"Practice evaluation scores rose by +{score_delta} points across recent sessions." if score_delta > 0 else "Consistent high-tier scoring across evaluations.",
            f"{completed_tasks_count} preparation task(s) completed in recent window." if completed_tasks_count > 0 else "Active daily preparation consistency.",
        ]
        actionable_recommendations = [
            "Maintain your daily preparation streak to cement problem-solving speed and articulation.",
            "Tackle higher-difficulty technical interview rounds and system design drills.",
            "Practice company-specific behavioral questions using the STAR framework.",
        ]
    elif trend_status == TREND_AT_RISK:
        drivers = []
        if is_inactivity_risk:
            drivers.append(f"No practice activity recorded for {days_since_last_activity} days.")
        if is_low_score_risk:
            drivers.append(f"Recent evaluation average is currently {recent_avg}%, below the 60% readiness threshold.")
        if is_declining_risk:
            drivers.append(f"Evaluation scores declined by {abs(score_delta)} points between recent sessions.")
        if not drivers:
            drivers.append("Gaps detected between current practice scores and target hiring benchmarks.")

        actionable_recommendations = [
            "Revisit fundamental data structures, algorithms, and core topic questions.",
            "Complete a structured mock interview drill to identify specific areas of hesitation.",
            "Resume daily preparation habits with 15-minute aptitude or coding practice sessions.",
            "Schedule an academic advisor or faculty mentor check-in for targeted coaching.",
        ]
    else:  # Stable
        drivers = [
            f"Evaluation scores remain steady (recent average: {recent_avg}%)." if total_score_evaluations > 0 else "Steady onboarding baseline.",
            f"{completed_tasks_count} milestone tasks logged with steady completion velocity.",
        ]
        actionable_recommendations = [
            "Challenge yourself with timed mock interview simulations to push scores into the Improving tier.",
            "Focus on domain-specific technical depth for your primary target company.",
            "Increase weekly task completion by reviewing company interview preparation guides.",
        ]

    return {
        "status": trend_status,
        "status_label": meta["label"],
        "badge_class": meta["badge_class"],
        "icon": meta["icon"],
        "color": meta["color"],
        "headline": meta["headline"],
        "summary": meta["summary"],
        "score_delta": score_delta,
        "score_delta_formatted": f"+{score_delta}%" if score_delta > 0 else (f"{score_delta}%" if score_delta < 0 else "0.0%"),
        "estimated_readiness_score": estimated_readiness_score,
        "confidence": confidence,
        "confidence_description": confidence_desc,
        "total_evaluations_analyzed": total_score_evaluations,
        "interview_average_score": interview_avg,
        "practice_drill_average_score": drill_avg,
        "recent_average_score": recent_avg,
        "completed_tasks_count": completed_tasks_count,
        "current_streak": current_streak,
        "days_since_last_activity": days_since_last_activity,
        "drivers": drivers,
        "actionable_recommendations": actionable_recommendations,
        # Mandatory Planning Estimate Labels & Disclaimers
        "is_planning_estimate": True,
        "estimate_classification": "Directional Planning Estimate",
        "disclaimer": PLANNING_ESTIMATE_DISCLAIMER,
        "guarantee_warning": GUARANTEE_WARNING,
        "disclaimer_short": "Planning estimate only — not a placement guarantee.",
    }


def predict_interview_readiness_trend(
    student_id: str = "default_student",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extracts student performance telemetry from the database and returns
    interview readiness trend predictions.
    """
    now_dt = datetime.now(timezone.utc)
    two_weeks_ago = (now_dt - timedelta(days=14)).strftime("%Y-%m-%d")

    interview_scores: List[float] = []
    practice_scores: List[float] = []
    completed_tasks_count = 0
    current_streak = 0
    days_since_last_activity: Optional[int] = None

    try:
        # 1. Fetch Mock Interview Scores
        history = get_student_interview_history(student_id=student_id, db_path=db_path)
        if history:
            # Sort chronologically (oldest to newest)
            sorted_history = sorted(history, key=lambda x: str(x.get("date", "")))
            for sess in sorted_history:
                avg = sess.get("average_score")
                if avg is not None and avg > 0 and sess.get("answered_questions", 0) > 0:
                    interview_scores.append(float(avg))
    except Exception as exc:
        logger.debug(f"Could not load interview history for trend prediction: {exc}")

    try:
        with get_connection(db_path) as conn:
            # 2. Fetch Aptitude Practice Scores
            apt_rows = conn.execute("""
                SELECT score_percentage, created_at
                FROM aptitude_attempts
                WHERE student_id = ?
                ORDER BY created_at ASC
            """, (student_id,)).fetchall()
            for r in apt_rows:
                if r["score_percentage"] is not None:
                    practice_scores.append(float(r["score_percentage"]))

            # 3. Fetch Coding Submission Scores
            coding_rows = conn.execute("""
                SELECT score, passed, tests_passed, total_tests, submitted_at
                FROM coding_submissions
                WHERE student_id = ?
                ORDER BY submitted_at ASC
            """, (student_id,)).fetchall()
            for r in coding_rows:
                if r["total_tests"] and r["total_tests"] > 0:
                    pct = (r["tests_passed"] / r["total_tests"]) * 100.0
                    practice_scores.append(float(pct))
                elif r["score"] is not None and r["score"] > 0:
                    practice_scores.append(float(r["score"]))

            # 4. Fetch Group Discussion Attempt Scores
            gd_rows = conn.execute("""
                SELECT overall_score, created_at
                FROM gd_practice_attempts
                WHERE student_id = ?
                ORDER BY created_at ASC
            """, (student_id,)).fetchall()
            for r in gd_rows:
                if r["overall_score"] is not None and r["overall_score"] > 0:
                    practice_scores.append(float(r["overall_score"]))

            # 5. Fetch Activity Logs & Completed Tasks in recent window
            task_rows = conn.execute("""
                SELECT COUNT(*) FROM preparation_activity_log
                WHERE student_id = ? AND activity_date >= ?
            """, (student_id, two_weeks_ago)).fetchone()
            if task_rows:
                completed_tasks_count += task_rows[0]

            # Also check company preparation checklist completions
            checklist_rows = conn.execute("""
                SELECT completion_percentage FROM company_preparation_checklists
                WHERE student_id = ? AND updated_at >= ?
            """, (student_id, two_weeks_ago)).fetchall()
            for c_row in checklist_rows:
                if c_row[0] and c_row[0] >= 50.0:
                    completed_tasks_count += 1

            # 6. Fetch Streak & Last Activity Date
            streak_row = conn.execute("""
                SELECT current_streak, last_activity_date FROM student_streaks
                WHERE student_id = ?
            """, (student_id,)).fetchone()
            if streak_row:
                current_streak = streak_row[0] or 0
                last_act = streak_row[1]
                if last_act:
                    try:
                        act_dt = datetime.strptime(last_act[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        days_since_last_activity = max(0, (now_dt - act_dt).days)
                    except Exception:
                        pass
    except Exception as exc:
        logger.debug(f"Error reading practice and task telemetry for {student_id}: {exc}")

    return calculate_trend_prediction(
        interview_scores=interview_scores,
        completed_tasks_count=completed_tasks_count,
        practice_scores=practice_scores,
        days_since_last_activity=days_since_last_activity,
        current_streak=current_streak,
    )
