"""
Mock Interview & GD Repository (db/interviews.py)
=================================================
Handles database operations for mock interview sessions, questions, evaluations,
bookmarks, interview experiences, preparation notes, and group discussions.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from db.connection import get_connection, transaction

logger = logging.getLogger(__name__)


def save_interview_session(
    session_id: str,
    student_id: str,
    company_name: str,
    role_title: str,
    interview_type: str,
    overall_score: float,
    strengths: Optional[List[str]] = None,
    improvements: Optional[List[str]] = None,
    rounds: Optional[List[Dict[str, Any]]] = None,
    analysis_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    """Creates an interview-history record and linked analysis if absent."""
    effective_analysis_id = analysis_id or session_id
    effective_student_id = (student_id or "default_student").strip()

    with transaction(db_path) as cursor:
        cursor.execute(
            "SELECT 1 FROM analyses WHERE id = ? AND student_id = ?",
            (effective_analysis_id, effective_student_id),
        )
        if cursor.fetchone() is None:
            cursor.execute(
                """
                INSERT INTO analyses (
                    id, resume_filename, company_name, job_description, results_json, student_id, version_number
                ) VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    effective_analysis_id,
                    f"{company_name or 'Interview'}_{effective_analysis_id}.pdf",
                    company_name or "General",
                    role_title or "Interview",
                    json.dumps({
                        "summary": {
                            "interview_type": interview_type or "Technical",
                            "overall_score": float(overall_score or 0.0),
                            "strengths": strengths or [],
                            "improvements": improvements or [],
                            "rounds": rounds or [],
                        }
                    }),
                    effective_student_id,
                ),
            )

        questions_payload = []
        if rounds:
            for idx, round_info in enumerate(rounds):
                entry = {"index": idx, "type": interview_type or "Technical"}
                if isinstance(round_info, dict):
                    entry.update(round_info)
                questions_payload.append(entry)
        if not questions_payload:
            questions_payload = [{
                "index": 0,
                "type": interview_type or "Technical",
                "question": f"{role_title or 'Interview'} review",
            }]

        cursor.execute(
            """
            INSERT OR REPLACE INTO interviews (
                id, analysis_id, current_question_index, questions_json, answers_json, completed
            ) VALUES (?, ?, 0, ?, ?, 1)
            """,
            (session_id, effective_analysis_id, json.dumps(questions_payload), json.dumps([])),
        )


def create_interview_session(
    interview_id: str,
    analysis_id: str,
    questions_list: list,
    db_path: Optional[str] = None,
) -> None:
    """Creates a new mock interview session referencing an analysis."""
    with transaction(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO interviews (id, analysis_id, current_question_index, questions_json, answers_json, completed)
            VALUES (?, ?, 0, ?, ?, 0)
            """,
            (interview_id, analysis_id, json.dumps(questions_list), json.dumps([])),
        )
        logger.info(f"Interview session initialized with ID: {interview_id}")


def get_interview_session(interview_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieves and returns an interview session record by ID."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM interviews WHERE id = ?", (interview_id,))
        row = cursor.fetchone()
        if row:
            record = dict(row)
            record["questions"] = json.loads(record["questions_json"])
            record["answers"] = json.loads(record["answers_json"])
            return record
        return None


def update_interview_session(
    interview_id: str,
    current_question_index: int,
    answers_list: list,
    completed: bool,
    db_path: Optional[str] = None,
) -> None:
    """Updates the progress, answer list, and completion status of an active interview session."""
    with transaction(db_path) as cursor:
        cursor.execute(
            """
            UPDATE interviews
            SET current_question_index = ?, answers_json = ?, completed = ?
            WHERE id = ?
            """,
            (current_question_index, json.dumps(answers_list), 1 if completed else 0, interview_id),
        )
        logger.info(
            f"Interview session {interview_id} updated. "
            f"Current index: {current_question_index}. Completed: {completed}"
        )


def get_student_interview_history(
    student_id: str = "default_student",
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves full mock interview session history for a student across all attempts.
    Calculates completion rates and score averages per question type.
    """
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                i.id AS session_id,
                i.analysis_id,
                i.current_question_index,
                i.questions_json,
                i.answers_json,
                i.completed,
                a.company_name,
                a.created_at AS analysis_date
            FROM interviews i
            JOIN analyses a ON i.analysis_id = a.id
            WHERE a.student_id = ?
            ORDER BY a.created_at DESC, i.id DESC
            """,
            (student_id,),
        )
        rows = cursor.fetchall()

        history = []
        for r in rows:
            rec = dict(r)
            questions = json.loads(rec.get("questions_json", "[]") or "[]")
            answers = json.loads(rec.get("answers_json", "[]") or "[]")

            scores = []
            type_scores: Dict[str, List[float]] = {"Technical": [], "HR": [], "Behavioral": []}
            for ans in answers:
                eval_data = ans.get("evaluation", {})
                score = eval_data.get("score")
                if score is not None:
                    try:
                        score_val = float(score)
                        scores.append(score_val)
                        q_type = ans.get("type", "General")
                        if q_type in type_scores:
                            type_scores[q_type].append(score_val)
                    except (ValueError, TypeError):
                        pass

            avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0
            technical_avg = (
                round(sum(type_scores["Technical"]) / len(type_scores["Technical"]), 1)
                if type_scores["Technical"]
                else 0.0
            )
            hr_avg = (
                round(sum(type_scores["HR"]) / len(type_scores["HR"]), 1)
                if type_scores["HR"]
                else 0.0
            )
            behavioral_avg = (
                round(sum(type_scores["Behavioral"]) / len(type_scores["Behavioral"]), 1)
                if type_scores["Behavioral"]
                else 0.0
            )

            from utils.interviewer_style_service import get_style_config
            detected_style = None
            if questions and isinstance(questions, list) and len(questions) > 0:
                detected_style = questions[0].get("interviewer_style")
            if not detected_style and answers and isinstance(answers, list) and len(answers) > 0:
                detected_style = answers[0].get("interviewer_style") or answers[0].get("evaluation", {}).get("interviewer_style")
            style_cfg = get_style_config(detected_style)

            history.append({
                "session_id": rec["session_id"],
                "analysis_id": rec["analysis_id"],
                "company_name": rec.get("company_name", "General"),
                "total_questions": len(questions),
                "answered_questions": len(answers),
                "completed": bool(rec.get("completed", 0)),
                "average_score": avg_score,
                "technical_score": technical_avg,
                "hr_score": hr_avg,
                "behavioral_score": behavioral_avg,
                "date": rec.get("analysis_date", ""),
                "questions": questions,
                "answers": answers,
                "interviewer_style": style_cfg["id"],
                "interviewer_style_name": style_cfg["name"],
                "interviewer_style_badge": style_cfg["badge_class"],
                "interviewer_style_icon": style_cfg["icon"],
            })
        return history


def get_student_interview_performance_analytics(
    student_id: str = "default_student",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Computes performance analytics, score trends, and strengths/weaknesses for mock interviews."""
    history = get_student_interview_history(student_id=student_id, db_path=db_path)
    if not history:
        return {
            "total_sessions": 0,
            "completed_sessions": 0,
            "total_questions_answered": 0,
            "overall_average_score": 0.0,
            "technical_average": 0.0,
            "hr_average": 0.0,
            "behavioral_average": 0.0,
            "score_trend": [],
            "strengths": [],
            "weaknesses": [],
            "sessions": [],
        }

    total_sessions = len(history)
    completed_sessions = sum(1 for s in history if s["completed"])
    total_answered = sum(s["answered_questions"] for s in history)

    all_scores = [s["average_score"] for s in history if s["average_score"] > 0]
    overall_avg = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0.0

    tech_scores = [s["technical_score"] for s in history if s["technical_score"] > 0]
    hr_scores = [s["hr_score"] for s in history if s["hr_score"] > 0]
    behav_scores = [s["behavioral_score"] for s in history if s["behavioral_score"] > 0]

    tech_avg = round(sum(tech_scores) / len(tech_scores), 1) if tech_scores else 0.0
    hr_avg = round(sum(hr_scores) / len(hr_scores), 1) if hr_scores else 0.0
    behav_avg = round(sum(behav_scores) / len(behav_scores), 1) if behav_scores else 0.0

    score_trend = [
        {
            "date": s.get("date", "")[:10],
            "company": s["company_name"],
            "score": s["average_score"],
            "session_id": s["session_id"],
        }
        for s in reversed(history)
        if s["average_score"] > 0
    ]

    strengths = []
    weaknesses = []

    domain_eval = [
        ("Technical Concepts", tech_avg),
        ("HR and Culture Fit", hr_avg),
        ("Behavioral and STAR Structure", behav_avg),
    ]

    for name, avg in domain_eval:
        if avg >= 75.0:
            strengths.append(f"{name} ({avg}/100) - Strong grasp of core concepts and structured communication")
        elif avg > 0:
            weaknesses.append(f"{name} ({avg}/100) - Needs further practice with concise articulation and situational examples")

    if not strengths and overall_avg >= 70.0:
        strengths.append("Consistent practice and willingness to complete structured multi-round interviews.")
    if not weaknesses:
        weaknesses.append("Practice speaking with greater conciseness and quantifiable impact metrics.")

    return {
        "total_sessions": total_sessions,
        "completed_sessions": completed_sessions,
        "total_questions_answered": total_answered,
        "overall_average_score": overall_avg,
        "technical_average": tech_avg,
        "hr_average": hr_avg,
        "behavioral_average": behav_avg,
        "score_trend": score_trend,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "sessions": history,
    }


MAX_BOOKMARKS_PER_STUDENT = 50
GOOD_SCORE_THRESHOLD = 75.0
MASTERY_GOOD_SCORE_COUNT = 2


def save_interview_bookmark(
    student_id: str,
    question_id: str,
    question_text: str,
    category: str = "Technical",
    company_name: str = "General",
    notes: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    last_score: Optional[float] = None,
    db_path: Optional[str] = None,
) -> bool:
    """Saves an interview practice question to the candidate's bookmarked collection (#358, #846)."""
    try:
        effective_student_id = (student_id or "default_student").strip()
        q_id = str(question_id).strip()
        q_text = str(question_text).strip()
        if not q_text:
            return False
        if not q_id:
            import hashlib
            q_id = f"iq-{hashlib.sha256(q_text.encode('utf-8')).hexdigest()[:12]}"
        cat = (category or "Technical").strip()
        comp = (company_name or "General").strip()
        user_notes = (notes or "").strip()
        meta_json = json.dumps(metadata or {})
        b_id = str(uuid.uuid4())

        with transaction(db_path) as cursor:
            # Check if this bookmark already exists for this student
            cursor.execute(
                "SELECT id FROM bookmarked_interview_questions WHERE student_id = ? AND question_id = ?",
                (effective_student_id, q_id),
            )
            exists = cursor.fetchone() is not None

            # If not an existing bookmark, enforce per-user bookmark limit (#846)
            if not exists:
                cursor.execute(
                    "SELECT COUNT(*) FROM bookmarked_interview_questions WHERE student_id = ?",
                    (effective_student_id,),
                )
                cnt = cursor.fetchone()[0]
                if cnt >= MAX_BOOKMARKS_PER_STUDENT:
                    logger.warning(
                        f"Student {effective_student_id} reached bookmark limit of {MAX_BOOKMARKS_PER_STUDENT} questions"
                    )
                    return False

            cursor.execute(
                """
                INSERT INTO bookmarked_interview_questions (
                    id, student_id, question_id, question_text, category, company_name, notes, metadata_json, last_score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(student_id, question_id) DO UPDATE SET
                    question_text = excluded.question_text,
                    category = excluded.category,
                    company_name = excluded.company_name,
                    notes = excluded.notes,
                    metadata_json = excluded.metadata_json,
                    last_score = COALESCE(excluded.last_score, bookmarked_interview_questions.last_score),
                    created_at = CURRENT_TIMESTAMP
                """,
                (b_id, effective_student_id, q_id, q_text, cat, comp, user_notes, meta_json, last_score),
            )
            logger.info(f"Saved interview bookmark for student {effective_student_id}, question {q_id}")
            return True
    except Exception as e:
        logger.error(f"Error saving interview bookmark for question {question_id}: {e}")
        return False


bookmark_interview_question = save_interview_bookmark


def remove_interview_bookmark(
    student_id: str,
    question_id: str,
    db_path: Optional[str] = None,
) -> bool:
    """Removes a bookmarked interview question for a candidate."""
    try:
        effective_student_id = (student_id or "default_student").strip()
        q_id = str(question_id).strip()

        with transaction(db_path) as cursor:
            cursor.execute(
                """
                DELETE FROM bookmarked_interview_questions
                WHERE student_id = ? AND question_id = ?
                """,
                (effective_student_id, q_id),
            )
            logger.info(f"Removed interview bookmark for student {effective_student_id}, question {q_id}")
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error removing interview bookmark for question {question_id}: {e}")
        return False


def get_interview_bookmarks(
    student_id: str,
    category: Optional[str] = None,
    practiced_only: Optional[bool] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves all bookmarked interview questions for a student."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            effective_student_id = (student_id or "default_student").strip()

            conditions = ["student_id = ?"]
            params: List[Any] = [effective_student_id]

            if category and category.strip().lower() not in ("all", ""):
                conditions.append("LOWER(category) = LOWER(?)")
                params.append(category.strip())

            if practiced_only is True:
                conditions.append("is_practiced = 1")
            elif practiced_only is False:
                conditions.append("is_practiced = 0")

            query = f"""
                SELECT id, student_id, question_id, question_text, category, company_name, notes, metadata_json,
                       is_practiced, last_practiced_at, practice_answer, practice_evaluation_json,
                       last_score, good_score_count, created_at
                FROM bookmarked_interview_questions
                WHERE {" AND ".join(conditions)}
                ORDER BY created_at DESC
            """
            cursor.execute(query, tuple(params))

            rows = cursor.fetchall()
            bookmarks = []
            for row in rows:
                rec = dict(row)
                try:
                    rec["metadata"] = json.loads(rec.get("metadata_json", "{}"))
                except Exception:
                    rec["metadata"] = {}
                try:
                    rec["practice_evaluation"] = json.loads(rec.get("practice_evaluation_json", "{}"))
                except Exception:
                    rec["practice_evaluation"] = {}
                rec["is_practiced"] = bool(rec.get("is_practiced", 0))
                rec["last_score"] = rec.get("last_score")
                rec["good_score_count"] = int(rec.get("good_score_count") or 0)
                bookmarks.append(rec)
            return bookmarks
    except Exception as e:
        logger.error(f"Error retrieving interview bookmarks for student {student_id}: {e}")
        return []


def get_interview_bookmark_by_id(
    student_id: str,
    question_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves a single bookmarked interview question for a candidate."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            effective_student_id = (student_id or "default_student").strip()
            q_id = str(question_id).strip()

            cursor.execute(
                """
                SELECT id, student_id, question_id, question_text, category, company_name, notes, metadata_json,
                       is_practiced, last_practiced_at, practice_answer, practice_evaluation_json,
                       last_score, good_score_count, created_at
                FROM bookmarked_interview_questions
                WHERE student_id = ? AND question_id = ?
                LIMIT 1
                """,
                (effective_student_id, q_id),
            )

            row = cursor.fetchone()
            if not row:
                return None
            rec = dict(row)
            try:
                rec["metadata"] = json.loads(rec.get("metadata_json", "{}"))
            except Exception:
                rec["metadata"] = {}
            try:
                rec["practice_evaluation"] = json.loads(rec.get("practice_evaluation_json", "{}"))
            except Exception:
                rec["practice_evaluation"] = {}
            rec["is_practiced"] = bool(rec.get("is_practiced", 0))
            rec["last_score"] = rec.get("last_score")
            rec["good_score_count"] = int(rec.get("good_score_count") or 0)
            return rec
    except Exception as e:
        logger.error(f"Error fetching bookmark {question_id} for student {student_id}: {e}")
        return None


def record_bookmark_score(
    student_id: str,
    question_id: str,
    score: float,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Records student's latest score for a bookmarked interview question (#846).
    If score >= 75.0, increments good_score_count.
    Once good_score_count >= 2, automatically removes the question from the saved list.
    """
    try:
        effective_student_id = (student_id or "default_student").strip()
        q_id = str(question_id).strip()
        clean_score = max(0.0, min(100.0, float(score)))

        with transaction(db_path) as cursor:
            # Try to locate by question_id first, then fallback to question_text
            cursor.execute(
                """
                SELECT question_id, question_text, good_score_count
                FROM bookmarked_interview_questions
                WHERE student_id = ? AND (question_id = ? OR LOWER(question_text) = LOWER(?))
                LIMIT 1
                """,
                (effective_student_id, q_id, q_id),
            )
            row = cursor.fetchone()
            if not row:
                return {
                    "found": False,
                    "removed": False,
                    "mastered": False,
                    "mastery": False,
                    "good_score_count": 0,
                    "last_score": clean_score,
                    "message": "Question not currently bookmarked.",
                }

            matched_q_id = row["question_id"]
            current_good = int(row["good_score_count"] or 0)
            is_good = clean_score >= GOOD_SCORE_THRESHOLD
            new_good = current_good + (1 if is_good else 0)
            mastered = new_good >= MASTERY_GOOD_SCORE_COUNT

            if mastered:
                cursor.execute(
                    "DELETE FROM bookmarked_interview_questions WHERE student_id = ? AND question_id = ?",
                    (effective_student_id, matched_q_id),
                )
                logger.info(
                    f"Auto-removed bookmarked question {matched_q_id} for student {effective_student_id} after {new_good} good scores"
                )
                return {
                    "found": True,
                    "question_id": matched_q_id,
                    "last_score": clean_score,
                    "good_score_count": new_good,
                    "mastered": True,
                    "mastery": True,
                    "removed": True,
                    "message": f"Mastered! You scored {clean_score:.0f}/100. This question was removed from your saved list after 2 strong scores.",
                }
            else:
                cursor.execute(
                    """
                    UPDATE bookmarked_interview_questions
                    SET last_score = ?,
                        good_score_count = ?,
                        is_practiced = 1,
                        last_practiced_at = CURRENT_TIMESTAMP
                    WHERE student_id = ? AND question_id = ?
                    """,
                    (clean_score, new_good, effective_student_id, matched_q_id),
                )
                rem = MASTERY_GOOD_SCORE_COUNT - new_good
                return {
                    "found": True,
                    "question_id": matched_q_id,
                    "last_score": clean_score,
                    "good_score_count": new_good,
                    "mastered": False,
                    "mastery": False,
                    "removed": False,
                    "message": (
                        f"Score {clean_score:.0f}/100 recorded. "
                        f"({new_good}/{MASTERY_GOOD_SCORE_COUNT} strong scores; {rem} more to master and remove)"
                        if is_good
                        else f"Score {clean_score:.0f}/100 recorded. (Score >= 75 to build towards mastery)"
                    ),
                }
    except Exception as e:
        logger.error(f"Error recording score for bookmark {question_id}: {e}")
        return {
            "found": False,
            "removed": False,
            "mastered": False,
            "mastery": False,
            "good_score_count": 0,
            "last_score": float(score or 0),
            "error": str(e),
        }


def update_interview_bookmark_practice(
    student_id: str,
    question_id: str,
    is_practiced: bool = True,
    answer: str = "",
    evaluation: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> bool:
    """Updates the practice status and optionally stores practice answer and evaluation."""
    try:
        effective_student_id = (student_id or "default_student").strip()
        q_id = str(question_id).strip()
        practiced_int = 1 if is_practiced else 0
        eval_json = json.dumps(evaluation or {})

        with transaction(db_path) as cursor:
            cursor.execute(
                """
                UPDATE bookmarked_interview_questions
                SET is_practiced = ?,
                    last_practiced_at = CURRENT_TIMESTAMP,
                    practice_answer = COALESCE(NULLIF(?, ''), practice_answer),
                    practice_evaluation_json = CASE WHEN ? != '{}' THEN ? ELSE practice_evaluation_json END
                WHERE student_id = ? AND question_id = ?
                """,
                (practiced_int, answer or "", eval_json, eval_json, effective_student_id, q_id),
            )
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating practice state for question {question_id}: {e}")
        return False


def reset_interview_bookmarks_practice(
    student_id: str,
    question_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> bool:
    """Resets practice progress for a specific question or all questions for a student."""
    try:
        effective_student_id = (student_id or "default_student").strip()
        with transaction(db_path) as cursor:
            if question_id:
                cursor.execute(
                    """
                    UPDATE bookmarked_interview_questions
                    SET is_practiced = 0,
                        practice_answer = '',
                        practice_evaluation_json = '{}'
                    WHERE student_id = ? AND question_id = ?
                    """,
                    (effective_student_id, str(question_id).strip()),
                )
            else:
                cursor.execute(
                    """
                    UPDATE bookmarked_interview_questions
                    SET is_practiced = 0,
                        practice_answer = '',
                        practice_evaluation_json = '{}'
                    WHERE student_id = ?
                    """,
                    (effective_student_id,),
                )
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error resetting practice progress for student {student_id}: {e}")
        return False


def get_interview_bookmark_practice_stats(
    student_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Calculates practice progress metrics across bookmarked questions."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            effective_student_id = (student_id or "default_student").strip()

            cursor.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN is_practiced = 1 THEN 1 ELSE 0 END) as practiced,
                    SUM(CASE WHEN is_practiced = 0 THEN 1 ELSE 0 END) as unpracticed
                FROM bookmarked_interview_questions
                WHERE student_id = ?
                """,
                (effective_student_id,),
            )
            row = cursor.fetchone()
            total = row["total"] if row and row["total"] else 0
            practiced = row["practiced"] if row and row["practiced"] else 0
            unpracticed = row["unpracticed"] if row and row["unpracticed"] else 0
            pct = round((practiced / total) * 100, 1) if total > 0 else 0.0

            return {
                "total": total,
                "practiced": practiced,
                "unpracticed": unpracticed,
                "percentage": pct,
            }
    except Exception as e:
        logger.error(f"Error calculating practice stats for student {student_id}: {e}")
        return {"total": 0, "practiced": 0, "unpracticed": 0, "percentage": 0.0}


def is_interview_bookmarked(
    student_id: str,
    question_id: str,
    db_path: Optional[str] = None,
) -> bool:
    """Checks if an interview question is bookmarked by the student."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            effective_student_id = (student_id or "default_student").strip()
            q_id = str(question_id).strip()

            cursor.execute(
                """
                SELECT 1 FROM bookmarked_interview_questions
                WHERE student_id = ? AND question_id = ?
                LIMIT 1
                """,
                (effective_student_id, q_id),
            )
            return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Error checking interview bookmark status for question {question_id}: {e}")
        return False


def save_interview_experience(
    exp_id: str,
    student_id: str,
    candidate_name: str,
    company_name: str,
    role_title: str,
    interview_date: str,
    rounds: List[Dict[str, Any]],
    overall_verdict: str = "Offer",
    difficulty_level: str = "Medium",
    tips_and_preparation: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Saves a student-submitted company interview experience."""
    effective_name = (candidate_name or "").strip() or "Anonymous Candidate"
    if "@" in effective_name or re.search(r"\d{7,}", effective_name):
        effective_name = "Anonymous Candidate"

    with transaction(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO interview_experiences (
                id, student_id, candidate_name, company_name, role_title,
                interview_date, rounds_json, overall_verdict, difficulty_level,
                tips_and_preparation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exp_id,
                student_id.strip() if student_id else "default_student",
                effective_name,
                company_name.strip(),
                role_title.strip(),
                interview_date.strip(),
                json.dumps(rounds),
                overall_verdict.strip(),
                difficulty_level.strip(),
                (tips_and_preparation or "").strip(),
            ),
        )
        logger.info(f"Saved interview experience {exp_id} for company {company_name}")
        return exp_id


def get_interview_experiences(
    company_name: Optional[str] = None,
    category_filter: Optional[str] = None,
    search_query: Optional[str] = None,
    sort_by: str = "date_desc",
    include_reported: bool = False,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves company interview experiences with search, sorting, and round filtering (#693)."""
    try:
        from utils.interview_helpful_service import ensure_helpful_votes_schema
        with get_connection(db_path) as conn:
            ensure_helpful_votes_schema(conn)
            cursor = conn.cursor()
            conditions = []
            params = []

            if not include_reported:
                conditions.append("reported_flag = 0")

            if company_name and company_name.strip() and company_name.strip().lower() not in ("all", "any"):
                conditions.append("LOWER(company_name) = LOWER(?)")
                params.append(company_name.strip())

            if search_query and search_query.strip():
                kw = f"%{search_query.strip().lower()}%"
                conditions.append(
                    "(LOWER(company_name) LIKE ? OR LOWER(role_title) LIKE ? OR LOWER(tips_and_preparation) LIKE ?)"
                )
                params.extend([kw, kw, kw])

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            order_by = "ORDER BY interview_date DESC, created_at DESC"
            if sort_by in ("helpful_desc", "most_helpful"):
                order_by = "ORDER BY helpful_count DESC, interview_date DESC, created_at DESC"
            elif sort_by == "date_asc":
                order_by = "ORDER BY interview_date ASC, created_at ASC"

            query = f"SELECT * FROM interview_experiences {where_clause} {order_by}"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            experiences = []
            for r in rows:
                rec = dict(r)
                try:
                    rec["rounds"] = json.loads(rec.get("rounds_json", "[]"))
                except Exception:
                    rec["rounds"] = []

                if category_filter and category_filter.strip() and category_filter.strip().lower() not in ("all", "any"):
                    target_cat = category_filter.strip().lower()
                    has_cat = any(
                        target_cat in round_info.get("category", "").lower()
                        for round_info in rec["rounds"]
                    )
                    if not has_cat:
                        continue

                experiences.append(rec)

            return experiences
    except Exception as e:
        logger.error(f"Error fetching interview experiences: {e}")
        return []


def report_interview_experience(
    exp_id: str,
    reason: str,
    db_path: Optional[str] = None,
) -> bool:
    """Flags an interview experience as reported for moderation review."""
    try:
        with transaction(db_path) as cursor:
            cursor.execute(
                """
                UPDATE interview_experiences
                SET reported_flag = 1, report_reason = ?
                WHERE id = ?
                """,
                (reason.strip() if reason else "Inappropriate content", exp_id),
            )
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error reporting interview experience {exp_id}: {e}")
        return False


def create_preparation_note(
    student_id: str,
    title: str,
    description: str,
    category: str = "Technical",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates a new private interview preparation note for a student."""
    effective_student_id = (student_id or "default_student").strip()
    note_id = f"note-{uuid.uuid4().hex[:12]}"
    valid_categories = ["Technical", "HR", "DSA", "Company Preparation"]
    clean_category = category.strip() if category and category.strip() in valid_categories else "Technical"
    clean_title = (title or "Untitled Note").strip()
    clean_desc = (description or "").strip()

    with transaction(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO interview_preparation_notes (
                id, student_id, title, description, category, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (note_id, effective_student_id, clean_title, clean_desc, clean_category),
        )

        cursor.execute("SELECT * FROM interview_preparation_notes WHERE id = ?", (note_id,))
        row = cursor.fetchone()
        logger.info(f"Created interview note {note_id} for student {effective_student_id}")

    # Record activity for streak tracking if available
    try:
        from db.streaks import record_preparation_activity
        record_preparation_activity(
            student_id=effective_student_id,
            activity_type="prep_note",
            metadata={"note_id": note_id, "title": clean_title, "category": clean_category},
            db_path=db_path,
        )
    except Exception as streak_err:
        logger.warning(f"Failed to record preparation activity on create_preparation_note: {streak_err}")

    return dict(row) if row else {}


def get_preparation_notes(
    student_id: str,
    category_filter: Optional[str] = None,
    search_query: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves all interview preparation notes belonging exclusively to the student."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            effective_student_id = (student_id or "default_student").strip()

            conditions = ["student_id = ?"]
            params: List[Any] = [effective_student_id]

            if category_filter and category_filter.strip() and category_filter.strip().lower() not in ("all", "any"):
                conditions.append("LOWER(category) = LOWER(?)")
                params.append(category_filter.strip())

            if search_query and search_query.strip():
                kw = f"%{search_query.strip().lower()}%"
                conditions.append("(LOWER(title) LIKE ? OR LOWER(description) LIKE ?)")
                params.extend([kw, kw])

            where_clause = f"WHERE {' AND '.join(conditions)}"
            query = f"SELECT * FROM interview_preparation_notes {where_clause} ORDER BY updated_at DESC"

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Error fetching preparation notes: {e}")
        return []


def get_preparation_note_by_id(
    note_id: str,
    student_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves a single preparation note by its ID, enforcing strict student ownership."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            effective_student_id = (student_id or "default_student").strip()
            cursor.execute(
                """
                SELECT id, student_id, title, description, category, created_at, updated_at
                FROM interview_preparation_notes
                WHERE id = ? AND student_id = ?
                """,
                (note_id.strip(), effective_student_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Error fetching preparation note {note_id}: {e}")
        return None


def update_preparation_note(
    note_id: str,
    student_id: str,
    title: str,
    description: str,
    category: str,
    db_path: Optional[str] = None,
) -> bool:
    """Updates an existing preparation note after validating student ownership."""
    try:
        effective_student_id = (student_id or "default_student").strip()
        valid_categories = ["Technical", "HR", "DSA", "Company Preparation"]
        clean_category = category.strip() if category and category.strip() in valid_categories else "Technical"
        clean_title = (title or "Untitled Note").strip()
        clean_desc = (description or "").strip()

        with transaction(db_path) as cursor:
            cursor.execute(
                """
                UPDATE interview_preparation_notes
                SET title = ?, description = ?, category = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND student_id = ?
                """,
                (clean_title, clean_desc, clean_category, note_id.strip(), effective_student_id),
            )
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating preparation note {note_id}: {e}")
        return False


def delete_preparation_note(
    note_id: str,
    student_id: str,
    db_path: Optional[str] = None,
) -> bool:
    """Permanently deletes a preparation note after validating student ownership."""
    try:
        effective_student_id = (student_id or "default_student").strip()
        with transaction(db_path) as cursor:
            cursor.execute(
                """
                DELETE FROM interview_preparation_notes
                WHERE id = ? AND student_id = ?
                """,
                (note_id.strip(), effective_student_id),
            )
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting preparation note {note_id}: {e}")
        return False


def get_note_category_counts(
    student_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, int]:
    """Returns aggregated note counts per category for the student."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            effective_student_id = (student_id or "default_student").strip()
            cursor.execute(
                """
                SELECT category, COUNT(*) as cnt
                FROM interview_preparation_notes
                WHERE student_id = ?
                GROUP BY category
                """,
                (effective_student_id,),
            )
            counts = {"All": 0, "Technical": 0, "HR": 0, "DSA": 0, "Company Preparation": 0}
            total = 0
            for row in cursor.fetchall():
                cat = row["category"]
                cnt = row["cnt"]
                total += cnt
                counts[cat] = cnt
            counts["All"] = total
            return counts
    except Exception as e:
        logger.error(f"Error getting note category counts: {e}")
        return {"All": 0, "Technical": 0, "HR": 0, "DSA": 0, "Company Preparation": 0}


def save_gd_attempt(
    student_id: str,
    topic_title: str,
    category: str,
    contribution_type: str,
    contribution_text: str,
    word_count: int,
    overall_score: int,
    content_score: int,
    structure_score: int,
    balance_score: int,
    clarity_score: int,
    stronger_opening: str,
    missed_counterpoint: str,
    feedback_json: str,
    topic_id: Optional[str] = None,
    attempt_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Persists a group discussion practice submission and evaluation into SQLite."""
    attempt_uuid = attempt_id or str(uuid.uuid4())
    with transaction(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO gd_practice_attempts (
                id, student_id, topic_id, topic_title, category,
                contribution_type, contribution_text, word_count,
                overall_score, content_score, structure_score, balance_score, clarity_score,
                stronger_opening, missed_counterpoint, feedback_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_uuid,
                student_id,
                topic_id,
                topic_title,
                category,
                contribution_type,
                contribution_text,
                word_count,
                overall_score,
                content_score,
                structure_score,
                balance_score,
                clarity_score,
                stronger_opening,
                missed_counterpoint,
                feedback_json,
            ),
        )

        cursor.execute("SELECT * FROM gd_practice_attempts WHERE id = ?", (attempt_uuid,))
        row = cursor.fetchone()
        return dict(row) if row else {"id": attempt_uuid, "student_id": student_id}


def get_student_gd_attempts(
    student_id: str,
    limit: int = 10,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves the most recent group discussion attempts for a student."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM gd_practice_attempts
                WHERE student_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (student_id, max(1, limit)),
            )
            rows = cursor.fetchall()
            result = []
            for r in rows:
                item = dict(r)
                if item.get("feedback_json"):
                    try:
                        item["feedback"] = json.loads(item["feedback_json"])
                    except Exception:
                        item["feedback"] = {}
                result.append(item)
            return result
    except Exception as e:
        logger.error(f"Error fetching GD practice attempts for student {student_id}: {e}")
        return []


def get_gd_attempt_by_id(
    attempt_id: str,
    student_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves a single GD attempt record by its ID, optionally enforcing student ownership."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            if student_id:
                cursor.execute(
                    "SELECT * FROM gd_practice_attempts WHERE id = ? AND student_id = ?",
                    (attempt_id, student_id),
                )
            else:
                cursor.execute("SELECT * FROM gd_practice_attempts WHERE id = ?", (attempt_id,))
            row = cursor.fetchone()
            if not row:
                return None
            item = dict(row)
            if item.get("feedback_json"):
                try:
                    item["feedback"] = json.loads(item["feedback_json"])
                except Exception:
                    item["feedback"] = {}
            return item
    except Exception as e:
        logger.error(f"Error retrieving GD attempt {attempt_id}: {e}")
        return None


def delete_student_gd_attempts(
    student_id: str,
    db_path: Optional[str] = None,
) -> int:
    """Deletes all GD practice attempts for a student."""
    try:
        with transaction(db_path) as cursor:
            cursor.execute("DELETE FROM gd_practice_attempts WHERE student_id = ?", (student_id,))
            return cursor.rowcount
    except Exception as e:
        logger.error(f"Error clearing GD practice attempts for student {student_id}: {e}")
        return 0
