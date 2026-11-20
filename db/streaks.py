"""
Candidate Preparation Streaks & Activity Logging (db/streaks.py)
================================================================
Tracks student preparation streaks, unique daily activity, and monthly calendar matrices.
"""

from __future__ import annotations

import calendar
import datetime
import json
import logging
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from db.connection import get_connection, transaction

logger = logging.getLogger(__name__)


def record_preparation_activity(
    student_id: str,
    activity_type: str,
    metadata: Optional[Dict[str, Any]] = None,
    activity_date: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Logs a meaningful placement preparation activity for the student on a specific date (#236).
    Enforces that multiple activities on the same day do not falsely inflate the daily streak count.
    Updates the candidate's current streak, longest streak, and total active days atomically.
    """
    effective_student_id = (student_id or "default_student").strip()
    act_type = (activity_type or "general_practice").strip().lower()
    target_date = (activity_date or datetime.date.today().isoformat()).strip()
    meta_json = json.dumps(metadata or {})
    rec_id = f"act-{uuid.uuid4().hex[:12]}"

    try:
        with transaction(db_path) as cursor:
            cursor.execute(
                """
                INSERT OR IGNORE INTO preparation_activity_log (
                    id, student_id, activity_date, activity_type, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (rec_id, effective_student_id, target_date, act_type, meta_json),
            )
            streak_data = _recalculate_student_streak(cursor, effective_student_id)
            return streak_data
    except Exception as e:
        logger.error(f"Error recording preparation activity for {student_id}: {e}")
        return get_student_streak(student_id, db_path=db_path)


def _recalculate_student_streak(cursor: sqlite3.Cursor, student_id: str) -> Dict[str, Any]:
    """
    Internal calculation helper that computes current and longest streak across unique active days.
    Guarantees that multiple activities on the same day only count as 1 active day.
    """
    cursor.execute(
        """
        SELECT DISTINCT activity_date
        FROM preparation_activity_log
        WHERE student_id = ?
        ORDER BY activity_date ASC
        """,
        (student_id,),
    )
    rows = cursor.fetchall()
    active_dates = [r[0] for r in rows if r[0]]

    if not active_dates:
        cursor.execute(
            """
            INSERT INTO student_streaks (
                student_id, current_streak, longest_streak, last_activity_date, total_active_days, updated_at
            ) VALUES (?, 0, 0, NULL, 0, CURRENT_TIMESTAMP)
            ON CONFLICT(student_id) DO UPDATE SET
                current_streak = 0,
                longest_streak = 0,
                last_activity_date = NULL,
                total_active_days = 0,
                updated_at = CURRENT_TIMESTAMP
            """,
            (student_id,),
        )
        return {
            "student_id": student_id,
            "current_streak": 0,
            "longest_streak": 0,
            "last_activity_date": None,
            "total_active_days": 0,
            "active_today": False,
            "has_started": False,
        }

    date_objs = []
    for d_str in active_dates:
        try:
            date_objs.append(datetime.date.fromisoformat(d_str))
        except ValueError:
            continue
    date_objs = sorted(set(date_objs))
    dates_set = set(date_objs)

    longest = 0
    cur_run = 0
    prev_d = None
    for d in date_objs:
        if prev_d is None or (d - prev_d).days == 1:
            cur_run += 1
        else:
            cur_run = 1
        longest = max(longest, cur_run)
        prev_d = d

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    active_today = today in dates_set

    current_streak = 0
    if active_today:
        current_streak = 1
        check_d = yesterday
        while check_d in dates_set:
            current_streak += 1
            check_d -= datetime.timedelta(days=1)
    elif yesterday in dates_set:
        current_streak = 1
        check_d = yesterday - datetime.timedelta(days=1)
        while check_d in dates_set:
            current_streak += 1
            check_d -= datetime.timedelta(days=1)
    else:
        current_streak = 0

    longest = max(longest, current_streak)
    last_act_str = date_objs[-1].isoformat() if date_objs else None
    total_days = len(date_objs)

    cursor.execute(
        """
        INSERT INTO student_streaks (
            student_id, current_streak, longest_streak, last_activity_date, total_active_days, updated_at
        ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(student_id) DO UPDATE SET
            current_streak = excluded.current_streak,
            longest_streak = excluded.longest_streak,
            last_activity_date = excluded.last_activity_date,
            total_active_days = excluded.total_active_days,
            updated_at = CURRENT_TIMESTAMP
        """,
        (student_id, current_streak, longest, last_act_str, total_days),
    )

    return {
        "student_id": student_id,
        "current_streak": current_streak,
        "longest_streak": longest,
        "last_activity_date": last_act_str,
        "total_active_days": total_days,
        "active_today": active_today,
        "has_started": total_days > 0,
    }


def get_student_streak(
    student_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieves current streak stats for a student, dynamically evaluating if streak broke."""
    try:
        with transaction(db_path) as cursor:
            effective_student_id = (student_id or "default_student").strip()
            return _recalculate_student_streak(cursor, effective_student_id)
    except Exception as e:
        logger.error(f"Error fetching student streak for {student_id}: {e}")
        return {
            "student_id": student_id,
            "current_streak": 0,
            "longest_streak": 0,
            "last_activity_date": None,
            "total_active_days": 0,
            "active_today": False,
            "has_started": False,
        }


def get_streak_calendar(
    student_id: str,
    year: Optional[int] = None,
    month: Optional[int] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Returns monthly calendar matrix indicating active preparation days for tracker (#236)."""
    effective_student_id = (student_id or "default_student").strip()
    today = datetime.date.today()
    target_year = year if year and 2020 <= year <= 2035 else today.year
    target_month = month if month and 1 <= month <= 12 else today.month

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        month_prefix = f"{target_year:04d}-{target_month:02d}"
        cursor.execute(
            """
            SELECT activity_date, activity_type
            FROM preparation_activity_log
            WHERE student_id = ? AND activity_date LIKE ?
            ORDER BY activity_date ASC
            """,
            (effective_student_id, f"{month_prefix}%"),
        )
        rows = cursor.fetchall()

        date_activities: Dict[str, List[str]] = {}
        for r in rows:
            d = r[0]
            t = r[1]
            if d not in date_activities:
                date_activities[d] = []
            if t not in date_activities[d]:
                date_activities[d].append(t)

    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(target_year, target_month)

    calendar_weeks = []
    for week in weeks:
        week_days = []
        for d in week:
            d_str = d.isoformat()
            is_active = d_str in date_activities
            week_days.append({
                "date": d_str,
                "day_number": d.day,
                "is_current_month": d.month == target_month,
                "is_today": d == today,
                "is_active": is_active,
                "activities": date_activities.get(d_str, []),
                "activity_count": len(date_activities.get(d_str, [])),
            })
        calendar_weeks.append(week_days)

    month_name = calendar.month_name[target_month]

    return {
        "student_id": effective_student_id,
        "year": target_year,
        "month": target_month,
        "month_name": month_name,
        "active_days_in_month": len(date_activities),
        "calendar_weeks": calendar_weeks,
        "active_dates": list(date_activities.keys()),
    }


def get_recent_preparation_activities(
    student_id: str,
    limit: int = 10,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Returns the recent preparation activity records for a candidate (#236)."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            effective_student_id = (student_id or "default_student").strip()
            cursor.execute(
                """
                SELECT id, student_id, activity_date, activity_type, metadata_json, created_at
                FROM preparation_activity_log
                WHERE student_id = ?
                ORDER BY activity_date DESC, created_at DESC
                LIMIT ?
                """,
                (effective_student_id, limit),
            )
            activities = []
            for r in cursor.fetchall():
                rec = dict(r)
                try:
                    rec["metadata"] = json.loads(rec.get("metadata_json") or "{}")
                except Exception:
                    rec["metadata"] = {}
                activities.append(rec)
            return activities
    except Exception as e:
        logger.error(f"Error fetching recent preparation activities for {student_id}: {e}")
        return []


def get_student_preparation_summary_data(
    student_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Aggregates student placement readiness summary data (#200)."""
    from db.analyses import get_analysis, get_student_versions
    from db.coding_practice import get_coding_submissions, get_student_profile
    from db.interviews import (
        get_student_interview_history,
        get_student_interview_performance_analytics,
    )
    from db.tracker import get_company_checklist

    s_id = (student_id or "default_student").strip()
    profile = get_student_profile(s_id, db_path=db_path)
    history = get_student_versions(s_id)
    latest_analysis = history[0] if history else {}

    matched_skills = []
    skill_gaps = []
    ats_score = latest_analysis.get("ats_score", 0)
    match_percentage = latest_analysis.get("match_percentage", 0)
    target_role = latest_analysis.get("target_role", "Software Engineer")
    target_company = latest_analysis.get("company_name", "General")

    if latest_analysis.get("id"):
        full_record = get_analysis(latest_analysis["id"])
        if full_record and full_record.get("results"):
            res = full_record["results"]
            job_match = res.get("job_match") or {}
            matched_skills = job_match.get("matched_skills") or []
            skill_gap_items = res.get("skill_gap") or []
            skill_gaps = [
                g.get("missing_skill") if isinstance(g, dict) else str(g)
                for g in skill_gap_items if g
            ] or job_match.get("missing_skills", [])

    submissions = get_coding_submissions(student_id=s_id, db_path=db_path)
    total_submissions = len(submissions)
    passed_submissions = sum(1 for s in submissions if s.get("passed"))
    avg_coding_score = (
        round(sum(s.get("score", 0) for s in submissions) / total_submissions, 1)
        if total_submissions > 0
        else 0.0
    )

    interviews = get_student_interview_history(student_id=s_id, db_path=db_path)
    total_interviews = len(interviews)
    interview_analytics = get_student_interview_performance_analytics(student_id=s_id, db_path=db_path)
    avg_interview_score = (
        interview_analytics.get("overall_average_score", 90.0)
        if total_interviews > 0
        else 0.0
    )

    checklists = get_company_checklist(student_id=s_id, company_name=target_company, db_path=db_path)
    checklist_completion = checklists.get("overall_percentage", 0.0) if checklists else 0.0
    completed_tasks = checklists.get("completed_tasks", 1) if checklists else 1
    total_tasks = checklists.get("total_tasks", 1) if checklists else 1

    app_distribution = {}
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status, count(*) as count FROM job_applications WHERE student_id = ? GROUP BY status",
                (s_id,),
            )
            app_distribution = {r["status"]: r["count"] for r in cursor.fetchall()}
    except Exception:
        app_distribution = {}

    streak = get_student_streak(s_id, db_path=db_path)

    return {
        "student_id": s_id,
        "profile": profile,
        "target_role": target_role,
        "target_company": target_company,
        "ats_score": ats_score,
        "match_percentage": match_percentage,
        "matched_skills": matched_skills,
        "skill_gaps": skill_gaps,
        "coding": {
            "total_submissions": total_submissions,
            "passed_submissions": passed_submissions,
            "average_score": avg_coding_score,
        },
        "interviews": {
            "total_interviews": total_interviews,
            "average_score": avg_interview_score,
        },
        "checklist": {
            "completed_tasks": completed_tasks,
            "total_tasks": total_tasks,
            "completion_percentage": checklist_completion,
        },
        "application_pipeline": app_distribution,
        "streak": streak,
    }
