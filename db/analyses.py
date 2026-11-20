"""
Analyses Repository (db/analyses.py)
===================================
Handles placement analyses, versions, batch comparisons, annotations,
and section feedback.
"""

import csv
from io import StringIO
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

from db.connection import get_connection, transaction

logger = logging.getLogger(__name__)


def save_analysis(
    analysis_id: str,
    resume_filename: str,
    company_name: str,
    job_description: str,
    results_dict: dict,
    student_id: Optional[str] = None,
    version_number: Optional[int] = None,
    target_role: Optional[str] = None,
    **kwargs
) -> None:
    """Inserts a newly generated analysis record into the database."""
    if (
        student_id == "demo_visitor"
        or analysis_id in ("demo-sample-analysis", "demo_sample_analysis", "demo")
        or (isinstance(results_dict, dict) and results_dict.get("is_demo"))
    ):
        logger.info(f"Demo mode analysis {analysis_id} intercepted; skipping real persistence.")
        return

    effective_student_id = (student_id or "default_student").strip()

    if not target_role:
        res = results_dict if isinstance(results_dict, dict) else {}
        target_role = (
            res.get("target_role")
            or res.get("job_match", {}).get("target_role")
            or res.get("role_preparation", {}).get("target_role")
            or "Software Engineer"
        )
    target_role = (target_role or "Software Engineer").strip()

    # Persist resume_text and ats_breakdown in results_dict if passed via kwargs (#494)
    if isinstance(results_dict, dict):
        if "resume_text" in kwargs and not results_dict.get("resume_text") and not results_dict.get("extracted_resume_text"):
            results_dict["resume_text"] = kwargs["resume_text"]
        if "ats_breakdown" in kwargs and not results_dict.get("ats_breakdown"):
            results_dict["ats_breakdown"] = kwargs["ats_breakdown"]

    with transaction() as cursor:
        if version_number is None or version_number <= 0:
            cursor.execute(
                "SELECT COALESCE(MAX(version_number), 0) + 1 FROM analyses WHERE student_id = ?",
                (effective_student_id,)
            )
            version_number = cursor.fetchone()[0]

        cursor.execute("PRAGMA table_info(analyses)")
        col_names = [c[1] for c in cursor.fetchall()]
        if "target_role" in col_names:
            cursor.execute("""
                INSERT INTO analyses (id, resume_filename, company_name, job_description, results_json, student_id, version_number, target_role)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                analysis_id,
                resume_filename,
                company_name,
                job_description,
                json.dumps(results_dict),
                effective_student_id,
                version_number,
                target_role
            ))
        else:
            cursor.execute("""
                INSERT INTO analyses (id, resume_filename, company_name, job_description, results_json, student_id, version_number)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                analysis_id,
                resume_filename,
                company_name,
                job_description,
                json.dumps(results_dict),
                effective_student_id,
                version_number
            ))

    logger.info(f"Analysis saved: {analysis_id} (Student: {effective_student_id}, Version: v{version_number})")

    # Automatically register cohort benchmark & activity
    try:
        from utils.database import record_or_update_cohort_benchmark
        res_analysis = results_dict.get("resume_analysis", {}) if isinstance(results_dict, dict) else {}
        job_match = results_dict.get("job_match", {}) if isinstance(results_dict, dict) else {}
        ats_val = int(res_analysis.get("ats_score", 70))
        match_val = int(job_match.get("match_percentage", 65))
        skills_cnt = len(job_match.get("matched_skills", [])) if isinstance(job_match.get("matched_skills"), list) else 0

        handle_suffix = abs(hash(analysis_id)) % 100
        anon_handle = f"Candidate_{handle_suffix:02d}"

        record_or_update_cohort_benchmark(
            analysis_id=analysis_id,
            student_handle=anon_handle,
            department="Computer Science",
            grad_year=2026,
            ats_score=ats_val,
            job_match_score=match_val,
            target_company=company_name or "General",
            skills_count=skills_cnt
        )
    except Exception as bench_err:
        logger.warning(f"Failed to record cohort benchmark on save_analysis: {bench_err}")

    try:
        from utils.database import record_preparation_activity
        record_preparation_activity(
            student_id=effective_student_id,
            activity_type="resume_analysis",
            metadata={"analysis_id": analysis_id, "company": company_name}
        )
    except Exception as streak_err:
        logger.warning(f"Failed to record preparation activity on save_analysis: {streak_err}")


def get_analysis(analysis_id: str) -> Optional[dict]:
    """Retrieves and returns an analysis record by ID."""
    if analysis_id in ("demo-sample-analysis", "demo_sample_analysis", "demo"):
        from utils.demo_mode import get_synthetic_sample_analysis
        return get_synthetic_sample_analysis()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,))
        row = cursor.fetchone()
        if row:
            record = dict(row)
            record["results"] = json.loads(record["results_json"])
            if not record.get("resume_text") and isinstance(record.get("results"), dict):
                record["resume_text"] = record["results"].get("extracted_resume_text") or record["results"].get("resume_text")
            return record
        return None


def get_student_versions(
    student_id: str,
    company_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Retrieves all resume analysis versions for a student."""
    if student_id == "demo_visitor":
        from utils.demo_mode import get_synthetic_sample_analysis
        return [get_synthetic_sample_analysis()]

    effective_student_id = (student_id or "default_student").strip()
    with get_connection() as conn:
        cursor = conn.cursor()
        if company_name:
            cursor.execute("""
                SELECT * FROM analyses
                WHERE student_id = ? AND company_name = ?
                ORDER BY version_number ASC, created_at ASC
            """, (effective_student_id, company_name.strip()))
        else:
            cursor.execute("""
                SELECT * FROM analyses
                WHERE student_id = ?
                ORDER BY version_number ASC, created_at ASC
            """, (effective_student_id,))

        rows = cursor.fetchall()
        versions = []
        for row in rows:
            rec = dict(row)
            try:
                rec["results"] = json.loads(rec.get("results_json", "{}"))
                res_analysis = rec["results"].get("resume_analysis", {})
                job_match = rec["results"].get("job_match", {})
                rec["ats_score"] = res_analysis.get("ats_score", 0)
                rec["match_percentage"] = job_match.get("match_percentage", 0)
            except Exception:
                rec["results"] = {}
                rec["ats_score"] = 0
                rec["match_percentage"] = 0
            versions.append(rec)
        return versions


def get_previous_analysis(
    student_id: str,
    current_version: int,
    company_name: Optional[str] = None,
    target_role: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Retrieves the immediately preceding analysis record for a candidate."""
    if student_id == "demo_visitor":
        return None

    effective_student_id = (student_id or "default_student").strip()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(analyses)")
        col_names = {c[1] for c in cursor.fetchall()}
        has_role_col = "target_role" in col_names

        query = ["SELECT * FROM analyses WHERE student_id = ? AND version_number < ?"]
        params: List[Any] = [effective_student_id, current_version]

        norm_company = company_name.strip() if company_name else ""
        norm_role = target_role.strip() if target_role else ""

        if norm_company and norm_role and has_role_col:
            query.append("AND (LOWER(company_name) = LOWER(?) OR LOWER(target_role) = LOWER(?))")
            params.extend([norm_company, norm_role])
        elif norm_company:
            query.append("AND LOWER(company_name) = LOWER(?)")
            params.append(norm_company)
        elif norm_role and has_role_col:
            query.append("AND LOWER(target_role) = LOWER(?)")
            params.append(norm_role)

        query.append("ORDER BY version_number DESC, created_at DESC LIMIT 1")
        cursor.execute(" ".join(query), tuple(params))
        row = cursor.fetchone()
        if row:
            rec = dict(row)
            try:
                rec["results"] = json.loads(rec.get("results_json", "{}"))
            except Exception:
                rec["results"] = {}
            return rec
        return None


def get_previous_analysis_for_target(
    student_id: str,
    current_analysis_id: Optional[str] = None,
    current_version: Optional[int] = None,
    company_name: Optional[str] = None,
    target_role: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Finds the most recent preceding analysis for the SAME target role or company."""
    if student_id == "demo_visitor":
        return None

    effective_student_id = (student_id or "default_student").strip()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(analyses)")
        cols = {c[1] for c in cursor.fetchall()}
        has_role_col = "target_role" in cols

        query = ["SELECT * FROM analyses WHERE student_id = ?"]
        params: List[Any] = [effective_student_id]

        if current_analysis_id:
            query.append("AND id != ?")
            params.append(current_analysis_id)

        if current_version is not None and current_version > 1:
            query.append("AND version_number < ?")
            params.append(current_version)

        norm_company = company_name.strip() if company_name else ""
        norm_role = target_role.strip() if target_role else ""

        if norm_company and norm_role and has_role_col:
            query.append("AND (LOWER(company_name) = LOWER(?) OR LOWER(target_role) = LOWER(?))")
            params.extend([norm_company, norm_role])
        elif norm_company:
            query.append("AND LOWER(company_name) = LOWER(?)")
            params.append(norm_company)
        elif norm_role and has_role_col:
            query.append("AND LOWER(target_role) = LOWER(?)")
            params.append(norm_role)

        query.append("ORDER BY version_number DESC, created_at DESC LIMIT 1")
        cursor.execute(" ".join(query), tuple(params))
        row = cursor.fetchone()
        if not row:
            return None
        rec = dict(row)
        try:
            rec["results"] = json.loads(rec.get("results_json", "{}"))
        except Exception:
            rec["results"] = {}
        return rec


def get_student_versions_for_target(
    student_id: str,
    company_name: Optional[str] = None,
    target_role: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Retrieves all resume analysis versions matching the target role OR company."""
    if student_id == "demo_visitor":
        from utils.demo_mode import get_synthetic_sample_analysis
        return [get_synthetic_sample_analysis()]

    effective_student_id = (student_id or "default_student").strip()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(analyses)")
        cols = {c[1] for c in cursor.fetchall()}
        has_role_col = "target_role" in cols

        query = ["SELECT * FROM analyses WHERE student_id = ?"]
        params: List[Any] = [effective_student_id]

        norm_company = company_name.strip() if company_name else ""
        norm_role = target_role.strip() if target_role else ""

        if norm_company and norm_role and has_role_col:
            query.append("AND (LOWER(company_name) = LOWER(?) OR LOWER(target_role) = LOWER(?))")
            params.extend([norm_company, norm_role])
        elif norm_company:
            query.append("AND LOWER(company_name) = LOWER(?)")
            params.append(norm_company)
        elif norm_role and has_role_col:
            query.append("AND LOWER(target_role) = LOWER(?)")
            params.append(norm_role)

        query.append("ORDER BY version_number ASC, created_at ASC")
        cursor.execute(" ".join(query), tuple(params))
        rows = cursor.fetchall()

        versions = []
        for row in rows:
            rec = dict(row)
            try:
                rec["results"] = json.loads(rec.get("results_json", "{}"))
                res_analysis = rec["results"].get("resume_analysis", {})
                job_match = rec["results"].get("job_match", {})
                rec["ats_score"] = res_analysis.get("ats_score", 0)
                rec["match_percentage"] = job_match.get("match_percentage", 0)
            except Exception:
                rec["results"] = {}
                rec["ats_score"] = 0
                rec["match_percentage"] = 0
            versions.append(rec)
        return versions


def get_recent_analyses(limit: int = 10) -> list:
    """Retrieves recent analyses ordered by created_at DESC."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, resume_filename, company_name, job_description, results_json, created_at
            FROM analyses
            ORDER BY created_at DESC
            LIMIT ?
        """, (max(1, min(limit, 50)),))
        rows = cursor.fetchall()
        recent = []
        for row in rows:
            record = dict(row)
            try:
                parsed_results = json.loads(record.pop("results_json", "{}"))
                resume_analysis = parsed_results.get("resume_analysis", {})
                job_match = parsed_results.get("job_match", {})
                record["ats_score"] = resume_analysis.get("ats_score", 0)
                record["match_percentage"] = job_match.get("match_percentage", 0)
            except Exception:
                record["ats_score"] = 0
                record["match_percentage"] = 0
            recent.append(record)
        return recent


def delete_analysis(analysis_id: str) -> bool:
    """Deletes an analysis record and associated interviews, bookmarks, and cache."""
    if analysis_id in ("demo-sample-analysis", "demo_sample_analysis", "demo"):
        return True

    with transaction() as cursor:
        cursor.execute("DELETE FROM interviews WHERE analysis_id = ?", (analysis_id,))
        cursor.execute("DELETE FROM cohort_benchmarks WHERE analysis_id = ?", (analysis_id,))
        cursor.execute("DELETE FROM analysis_cache WHERE analysis_id = ?", (analysis_id,))
        cursor.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
        return cursor.rowcount > 0


def get_analyses_history(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Retrieves past placement analysis sessions ordered by created_at DESC."""
    with get_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT id, resume_filename, company_name, job_description, results_json,
                   student_id, version_number, created_at
            FROM analyses
            WHERE student_id != 'demo_visitor' AND id NOT IN ('demo-sample-analysis', 'demo_sample_analysis', 'demo')
            ORDER BY created_at DESC, rowid DESC
        """
        params: List[Any] = []
        if limit is not None and limit > 0:
            query += " LIMIT ?"
            params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        history = []
        for row in rows:
            record = dict(row)
            raw_json = record.pop("results_json", "{}")
            try:
                parsed = json.loads(raw_json)
                job_match = parsed.get("job_match", {})
                res_analysis = parsed.get("resume_analysis", {})
                record["ats_score"] = int(res_analysis.get("ats_score", 0))
                record["match_percentage"] = int(job_match.get("match_percentage", 0))
                record["target_role"] = (
                    parsed.get("target_role")
                    or job_match.get("target_role")
                    or "Software Engineer"
                )
            except Exception:
                record["ats_score"] = 0
                record["match_percentage"] = 0
                record["target_role"] = "Software Engineer"
            history.append(record)
        return history


def save_batch_comparison(
    student_id: str,
    resume_filename: str,
    companies: List[str],
    results: Dict[str, Any]
) -> str:
    """Saves multi-company batch comparison results."""
    batch_id = str(uuid.uuid4())
    effective_student_id = (student_id or "default_student").strip()
    with transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO batch_comparisons (id, student_id, resume_filename, companies_json, results_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (batch_id, effective_student_id, resume_filename, json.dumps(companies), json.dumps(results))
        )
    return batch_id


def get_batch_comparison(batch_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a saved batch comparison by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM batch_comparisons WHERE id = ?", (batch_id,))
        row = cursor.fetchone()
        if row:
            rec = dict(row)
            try:
                rec["companies"] = json.loads(rec.get("companies_json", "[]"))
                rec["results"] = json.loads(rec.get("results_json", "{}"))
            except Exception:
                rec["companies"] = []
                rec["results"] = {}
            return rec
        return None


def create_analysis_annotation(
    student_id: str,
    analysis_id: str,
    annotation_type: str,
    section: str,
    content: str
) -> Dict[str, Any]:
    """Creates a new private annotation on an analysis."""
    annotation_id = str(uuid.uuid4())
    effective_student = (student_id or "default_student").strip()
    clean_type = annotation_type if annotation_type in ("note", "highlight") else "note"
    clean_sec = section.strip() if section else "General"
    clean_content = content.strip()
    with transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO analysis_annotations (id, analysis_id, student_id, annotation_type, section, content)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (annotation_id, analysis_id, effective_student, clean_type, clean_sec, clean_content)
        )
    return {
        "id": annotation_id,
        "analysis_id": analysis_id,
        "student_id": effective_student,
        "annotation_type": clean_type,
        "section": clean_sec,
        "content": clean_content
    }


def get_analysis_annotations(
    student_id: str,
    analysis_id: str
) -> List[Dict[str, Any]]:
    """Retrieves all private annotations for an analysis owned by student."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM analysis_annotations
            WHERE analysis_id = ? AND student_id = ?
            ORDER BY updated_at DESC, created_at DESC
            """,
            (analysis_id, student_id)
        )
        return [dict(r) for r in cursor.fetchall()]


def get_analysis_annotation(
    student_id: str,
    analysis_id: str,
    annotation_id: str
) -> Optional[Dict[str, Any]]:
    """Retrieves a single annotation by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM analysis_annotations
            WHERE id = ? AND analysis_id = ? AND student_id = ?
            """,
            (annotation_id, analysis_id, student_id)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def update_analysis_annotation(
    student_id: str,
    analysis_id: str,
    annotation_id: str,
    content: str,
    tag: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Updates the content or tag of an existing annotation."""
    with transaction() as cursor:
        if tag is not None:
            cursor.execute(
                """
                UPDATE analysis_annotations
                SET content = ?, section = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND analysis_id = ? AND student_id = ?
                """,
                (content.strip(), tag.strip(), annotation_id, analysis_id, student_id)
            )
        else:
            cursor.execute(
                """
                UPDATE analysis_annotations
                SET content = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND analysis_id = ? AND student_id = ?
                """,
                (content.strip(), annotation_id, analysis_id, student_id)
            )
        if cursor.rowcount == 0:
            return None
    return get_analysis_annotation(student_id, analysis_id, annotation_id)


def delete_analysis_annotation(
    student_id: str,
    analysis_id: str,
    annotation_id: str
) -> bool:
    """Deletes an annotation record owned by student."""
    with transaction() as cursor:
        cursor.execute(
            """
            DELETE FROM analysis_annotations
            WHERE id = ? AND analysis_id = ? AND student_id = ?
            """,
            (annotation_id, analysis_id, student_id)
        )
        return cursor.rowcount > 0


def save_analysis_section_feedback(
    student_id: str,
    analysis_id: str,
    section: str,
    rating: str,
    comment: Optional[str] = None
) -> Dict[str, Any]:
    """Saves or updates feedback on an individual analysis section."""
    clean_user = (student_id or "default_student").strip()
    clean_sec = section.strip()
    clean_rating = "up" if rating.strip().lower() in ("up", "helpful", "1") else "down"
    clean_comment = comment.strip() if comment else None

    with transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO analysis_section_feedback (analysis_id, user_id, section, rating, comment, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(analysis_id, user_id, section) DO UPDATE SET
                rating = excluded.rating,
                comment = COALESCE(excluded.comment, analysis_section_feedback.comment),
                updated_at = CURRENT_TIMESTAMP
            """,
            (analysis_id, clean_user, clean_sec, clean_rating, clean_comment)
        )
    return {
        "analysis_id": analysis_id,
        "user_id": clean_user,
        "section": clean_sec,
        "rating": clean_rating,
        "comment": clean_comment
    }


def get_analysis_section_feedback(
    student_id: str,
    analysis_id: str,
    section: str
) -> Optional[Dict[str, Any]]:
    """Retrieves feedback for a specific section."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM analysis_section_feedback
            WHERE analysis_id = ? AND user_id = ? AND section = ?
            """,
            (analysis_id, student_id, section)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_analysis_section_feedback_summary(days: int = 30) -> Dict[str, Any]:
    """Aggregates section feedback metrics over the specified days."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT section, rating, COUNT(*) as cnt
            FROM analysis_section_feedback
            WHERE created_at >= datetime('now', '-' || ? || ' days')
            GROUP BY section, rating
        """, (days,))
        rows = cursor.fetchall()

        by_section: Dict[str, Any] = {}
        total_up = 0
        total_down = 0

        for r in rows:
            sec = r["section"]
            rat = r["rating"]
            count = r["cnt"]
            if sec not in by_section:
                by_section[sec] = {"up": 0, "down": 0, "total": 0, "helpful_pct": 0.0}
            by_section[sec][rat] += count
            by_section[sec]["total"] += count
            if rat == "up":
                total_up += count
            else:
                total_down += count

        for sec, stats in by_section.items():
            if stats["total"] > 0:
                stats["helpful_pct"] = round((stats["up"] / stats["total"]) * 100, 1)

        total_feedbacks = total_up + total_down
        return {
            "period_days": days,
            "total_feedbacks": total_feedbacks,
            "overall_helpful_pct": round((total_up / total_feedbacks) * 100, 1) if total_feedbacks > 0 else 0.0,
            "sections": by_section
        }


def export_analysis_section_feedback_csv() -> str:
    """Exports all section feedback records as CSV."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, analysis_id, user_id, section, rating, comment, created_at, updated_at
            FROM analysis_section_feedback
            ORDER BY created_at DESC
        """)
        rows = cursor.fetchall()
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "analysis_id", "user_id", "section", "rating", "comment", "created_at", "updated_at"])
        for r in rows:
            writer.writerow([r["id"], r["analysis_id"], r["user_id"], r["section"], r["rating"], r["comment"], r["created_at"], r["updated_at"]])
        return output.getvalue()
