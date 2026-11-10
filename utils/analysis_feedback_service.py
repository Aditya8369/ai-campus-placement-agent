"""
AI Analysis Feedback and Correction Reporting Service (#262).
Allows students to flag inaccuracies or provide corrections on AI analysis outputs
(e.g., inaccurate skill gap, wrong match score, irrelevant question, poor roadmap, hallucinated skills).
Provides:
- Database schema initialization for feedback and correction reports.
- Category validation against canonical inaccuracy taxonomy.
- Ownership and privacy verification (students can only report feedback on their own analyses).
- Resolution status lifecycle management (pending, under_review, resolved, rejected).
- Reporting analytics / summary retrieval for administrators and quality audit pipelines.
"""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Tuple

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

# Valid feedback categories
FEEDBACK_CATEGORIES = {
    "inaccurate_skill_gap": {
        "title": "Inaccurate Skill Gap Identification",
        "description": "The AI claimed a skill was missing, but it is explicitly demonstrated in the resume or background.",
    },
    "wrong_match_score": {
        "title": "Mismatched or Unfair Role Match Score",
        "description": "The calculated role match score seems severely inaccurate compared to provided qualifications.",
    },
    "irrelevant_interview_questions": {
        "title": "Irrelevant Technical Interview Questions",
        "description": "Generated interview questions do not align with the target role seniority or job description stack.",
    },
    "poor_learning_roadmap": {
        "title": "Impractical or Misaligned Learning Roadmap",
        "description": "Suggested roadmap topics or milestones lack practical alignment with the required competencies.",
    },
    "hallucinated_qualifications": {
        "title": "Hallucinated or Misread Resume Details",
        "description": "The AI misattributed experience, institutions, or technical stacks not present in the candidate text.",
    },
    "other_ai_inaccuracy": {
        "title": "Other AI Analysis Inaccuracy",
        "description": "General feedback regarding analysis output clarity, formatting, or erroneous deductions.",
    },
}

VALID_STATUSES = {"pending", "under_review", "resolved", "rejected"}


def init_feedback_reports_table() -> None:
    """Initialize table storing AI analysis feedback and correction reports."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_analysis_feedback_reports (
                report_id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                category TEXT NOT NULL,
                field_affected TEXT NOT NULL DEFAULT 'general',
                claim_detail TEXT NOT NULL,
                proposed_correction TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                admin_notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP,
                FOREIGN KEY (analysis_id) REFERENCES analyses(id)
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_fb_analysis ON ai_analysis_feedback_reports(analysis_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_fb_student ON ai_analysis_feedback_reports(student_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_fb_status ON ai_analysis_feedback_reports(status)"
        )
        conn.commit()
    finally:
        conn.close()


def submit_analysis_feedback(
    analysis_id: str,
    student_id: str,
    category: str,
    claim_detail: str,
    field_affected: str = "general",
    proposed_correction: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Submit a new correction/feedback report for an AI analysis.
    Validates category and verifies ownership of the analysis.
    """
    init_feedback_reports_table()

    if not analysis_id or not str(analysis_id).strip():
        raise ValueError("analysis_id is required")
    if not claim_detail or len(claim_detail.strip()) < 10:
        raise ValueError("claim_detail must provide a descriptive explanation (minimum 10 characters)")

    cat_clean = category.strip().lower() if category else ""
    if cat_clean not in FEEDBACK_CATEGORIES:
        raise ValueError(
            f"Invalid feedback category '{category}'. Must be one of: {', '.join(sorted(FEEDBACK_CATEGORIES.keys()))}"
        )

    # Verify ownership of analysis
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT student_id FROM analyses WHERE id = ?",
            (str(analysis_id),),
        )
        row = cursor.fetchone()
        if not row:
            raise KeyError(f"Analysis '{analysis_id}' not found")
        
        owner_id = str(row["student_id"])
        # Check authorization (match or allow default_student in dev)
        if owner_id and owner_id != str(student_id) and owner_id != "default_student":
            raise PermissionError(f"Unauthorized: You cannot submit feedback on analysis '{analysis_id}'")

        report_id = f"fb_{uuid.uuid4().hex[:12]}"
        now_str = dt.datetime.utcnow().isoformat()

        cursor.execute(
            """
            INSERT INTO ai_analysis_feedback_reports
                (report_id, analysis_id, student_id, category, field_affected, claim_detail, proposed_correction, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                report_id,
                str(analysis_id),
                str(student_id),
                cat_clean,
                (field_affected or "general").strip()[:50],
                claim_detail.strip(),
                proposed_correction.strip() if proposed_correction else None,
                now_str,
            ),
        )
        conn.commit()

        return {
            "report_id": report_id,
            "analysis_id": str(analysis_id),
            "student_id": str(student_id),
            "category": cat_clean,
            "category_title": FEEDBACK_CATEGORIES[cat_clean]["title"],
            "field_affected": field_affected,
            "claim_detail": claim_detail.strip(),
            "proposed_correction": proposed_correction.strip() if proposed_correction else None,
            "status": "pending",
            "created_at": now_str,
        }
    finally:
        conn.close()


def get_analysis_feedback_reports(
    analysis_id: str,
    student_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieve feedback reports associated with an analysis.
    Filters by student_id if provided.
    """
    init_feedback_reports_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if student_id:
            cursor.execute(
                """
                SELECT report_id, analysis_id, student_id, category, field_affected,
                       claim_detail, proposed_correction, status, admin_notes, created_at, resolved_at
                FROM ai_analysis_feedback_reports
                WHERE analysis_id = ? AND student_id = ?
                ORDER BY created_at DESC
                """,
                (str(analysis_id), str(student_id)),
            )
        else:
            cursor.execute(
                """
                SELECT report_id, analysis_id, student_id, category, field_affected,
                       claim_detail, proposed_correction, status, admin_notes, created_at, resolved_at
                FROM ai_analysis_feedback_reports
                WHERE analysis_id = ?
                ORDER BY created_at DESC
                """,
                (str(analysis_id),),
            )
        rows = cursor.fetchall()
        reports = []
        for r in rows:
            cat = r["category"]
            cat_title = FEEDBACK_CATEGORIES.get(cat, {}).get("title", cat)
            reports.append({
                "report_id": r["report_id"],
                "analysis_id": r["analysis_id"],
                "student_id": r["student_id"],
                "category": cat,
                "category_title": cat_title,
                "field_affected": r["field_affected"],
                "claim_detail": r["claim_detail"],
                "proposed_correction": r["proposed_correction"],
                "status": r["status"],
                "admin_notes": r["admin_notes"],
                "created_at": r["created_at"],
                "resolved_at": r["resolved_at"],
            })
        return reports
    finally:
        conn.close()


def update_feedback_report_status(
    report_id: str,
    status: str,
    admin_notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update lifecycle status of a feedback report (admin action).
    """
    init_feedback_reports_table()
    st_clean = status.strip().lower()
    if st_clean not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        now_str = dt.datetime.utcnow().isoformat()
        resolved_at = now_str if st_clean in {"resolved", "rejected"} else None

        cursor.execute(
            """
            UPDATE ai_analysis_feedback_reports
            SET status = ?, admin_notes = COALESCE(?, admin_notes), resolved_at = ?
            WHERE report_id = ?
            """,
            (st_clean, admin_notes, resolved_at, str(report_id)),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"Feedback report '{report_id}' not found")
        conn.commit()

        cursor.execute(
            "SELECT * FROM ai_analysis_feedback_reports WHERE report_id = ?",
            (str(report_id),),
        )
        row = cursor.fetchone()
        return dict(row)
    finally:
        conn.close()


def get_feedback_summary_statistics() -> Dict[str, Any]:
    """
    Aggregate feedback statistics across all reports for quality monitoring.
    """
    init_feedback_reports_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM ai_analysis_feedback_reports")
        total = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT category, COUNT(*) as cnt
            FROM ai_analysis_feedback_reports
            GROUP BY category
            """
        )
        by_category = {row["category"]: row["cnt"] for row in cursor.fetchall()}

        cursor.execute(
            """
            SELECT status, COUNT(*) as cnt
            FROM ai_analysis_feedback_reports
            GROUP BY status
            """
        )
        by_status = {row["status"]: row["cnt"] for row in cursor.fetchall()}

        return {
            "total_reports": total,
            "reports_by_category": by_category,
            "reports_by_status": by_status,
        }
    finally:
        conn.close()
