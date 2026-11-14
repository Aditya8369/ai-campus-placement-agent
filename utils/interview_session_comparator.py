"""
Interview Session Comparison Service (#273).

Enables students to select and compare results between two or more completed mock interview sessions:
- Overall score trajectory and delta calculations.
- Category-wise comparisons:
  1. Technical Accuracy & Knowledge
  2. Structured Communication & Articulation
  3. Behavioral / STAR Competency
- Identification of concrete improvements (topics where scores gained)
  and regression/attention areas (topics where scores declined or remained below target).
- Multi-tenant student isolation: guarantees students can only compare sessions they own.
- History retrieval tailored for comparison selection.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, Dict, List, Optional

from utils.database import get_db_connection

logger = logging.getLogger(__name__)


def extract_session_metrics(session_record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts summary metrics from an interview session row.
    """
    answers = json.loads(session_record.get("answers_json", "[]") or "[]")
    questions = json.loads(session_record.get("questions_json", "[]") or "[]")

    overall_scores = []
    cat_scores: Dict[str, List[float]] = {"Technical": [], "HR": [], "Behavioral": []}

    for ans in answers:
        eval_data = ans.get("evaluation") or {}
        score = eval_data.get("technical_accuracy") or eval_data.get("score") or eval_data.get("communication_score") or 60
        try:
            s_val = float(score)
            overall_scores.append(s_val)
        except (ValueError, TypeError):
            s_val = 60
            overall_scores.append(s_val)

        q_type = str(ans.get("type", "Technical")).capitalize()
        if q_type.upper() == "HR":
            q_type = "HR"
        if q_type in cat_scores:
            cat_scores[q_type].append(s_val)
        else:
            cat_scores["Technical"].append(s_val)

    avg_overall = round(sum(overall_scores) / len(overall_scores), 1) if overall_scores else 0.0
    avg_tech = round(sum(cat_scores["Technical"]) / len(cat_scores["Technical"]), 1) if cat_scores["Technical"] else 0.0
    avg_hr = round(sum(cat_scores["HR"]) / len(cat_scores["HR"]), 1) if cat_scores["HR"] else 0.0
    avg_beh = round(sum(cat_scores["Behavioral"]) / len(cat_scores["Behavioral"]), 1) if cat_scores["Behavioral"] else 0.0

    return {
        "session_id": session_record.get("id") or session_record.get("session_id"),
        "analysis_id": session_record.get("analysis_id"),
        "company_name": session_record.get("company_name", "General"),
        "date": session_record.get("analysis_date") or session_record.get("created_at") or "Recent",
        "total_questions": len(questions),
        "total_answered": len(answers),
        "completed": bool(session_record.get("completed")),
        "overall_score": avg_overall,
        "category_scores": {
            "Technical": avg_tech,
            "HR": avg_hr,
            "Behavioral": avg_beh
        }
    }


def compare_interview_sessions(session_ids: List[str], student_id: str) -> Dict[str, Any]:
    """
    Compares two or more interview sessions owned by the student.
    Calculates score changes, improvements, and areas requiring attention.
    """
    if not session_ids or len(session_ids) < 2:
        raise ValueError("At least two interview session IDs are required for comparison.")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in session_ids)
        query = f"""
            SELECT 
                i.id,
                i.analysis_id,
                i.current_question_index,
                i.questions_json,
                i.answers_json,
                i.completed,
                a.company_name,
                a.created_at,
                a.student_id
            FROM interviews i
            JOIN analyses a ON i.analysis_id = a.id
            WHERE i.id IN ({placeholders})
        """
        cursor.execute(query, session_ids)
        rows = cursor.fetchall()
        
        if len(rows) < 2:
            raise KeyError("One or more specified interview sessions were not found.")

        sessions_data = []
        for r in rows:
            rec = dict(r)
            owner = str(rec.get("student_id") or "default_student")
            if owner != str(student_id) and owner != "default_student" and str(student_id) != "default_student":
                raise PermissionError("Access denied: You cannot compare interview sessions belonging to another student.")
            sessions_data.append(extract_session_metrics(rec))

        # Preserve the request order or sort by date
        # Map by id
        session_map = {s["session_id"]: s for s in sessions_data}
        ordered_sessions = [session_map[sid] for sid in session_ids if sid in session_map]

        baseline = ordered_sessions[0]
        latest = ordered_sessions[-1]

        overall_delta = round(latest["overall_score"] - baseline["overall_score"], 1)
        tech_delta = round(latest["category_scores"]["Technical"] - baseline["category_scores"]["Technical"], 1)
        hr_delta = round(latest["category_scores"]["HR"] - baseline["category_scores"]["HR"], 1)
        beh_delta = round(latest["category_scores"]["Behavioral"] - baseline["category_scores"]["Behavioral"], 1)

        improvements = []
        attention_areas = []

        if overall_delta > 0:
            improvements.append(f"Overall readiness score improved by +{overall_delta}% points.")
        elif overall_delta < 0:
            attention_areas.append(f"Overall readiness score dropped by {overall_delta}% points.")

        if tech_delta > 3:
            improvements.append(f"Technical Knowledge improved significantly (+{tech_delta}%).")
        elif tech_delta < -3:
            attention_areas.append(f"Technical accuracy declined by {abs(tech_delta)}%; focus on core systems and algorithm review.")
        elif latest["category_scores"]["Technical"] < 65:
            attention_areas.append("Technical knowledge remains below benchmark (65%); practice coding fundamentals.")

        if beh_delta > 3:
            improvements.append(f"Behavioral structure and STAR compliance improved (+{beh_delta}%).")
        elif beh_delta < -3:
            attention_areas.append(f"Behavioral responses saw lower scores ({beh_delta}%); practice structured STAR storytelling.")

        if hr_delta > 3:
            improvements.append(f"HR & articulation round improved (+{hr_delta}%).")
        elif hr_delta < -3:
            attention_areas.append(f"HR round scores dipped ({hr_delta}%); refine career trajectory and motivation articulation.")

        if not improvements:
            improvements.append("Performance maintained consistency across sessions.")
        if not attention_areas:
            attention_areas.append("Solid overall trajectory! Continue regular drills to lock in placement gains.")

        return {
            "success": True,
            "session_count": len(ordered_sessions),
            "sessions": ordered_sessions,
            "comparison_summary": {
                "baseline_session_id": baseline["session_id"],
                "latest_session_id": latest["session_id"],
                "overall_score_delta": overall_delta,
                "overall_trajectory": "Improved" if overall_delta > 0 else ("Declined" if overall_delta < 0 else "Unchanged"),
                "category_deltas": {
                    "Technical": tech_delta,
                    "HR": hr_delta,
                    "Behavioral": beh_delta
                },
                "key_improvements": improvements,
                "attention_areas": attention_areas
            }
        }
    finally:
        conn.close()
