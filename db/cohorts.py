"""
Cohort Benchmarks, Leaderboard & Placement History Repository (db/cohorts.py)
=============================================================================
Handles database operations for peer cohort benchmarking, university leaderboard
participation preferences (#360), composite score rankings, placement history (#149),
and target company skill gaps (#433).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional

from db.connection import get_connection, transaction

logger = logging.getLogger(__name__)


def _seed_cohort_benchmarks(cursor: sqlite3.Cursor) -> None:
    """Populates default cohort records representing diverse university branch peers."""
    seed_peers = [
        ("peer-01", "AlgoMaster_99", "Computer Science", 2026, 95, 94, 94.4, "Google", 9, "Platinum"),
        ("peer-02", "CloudArchitect_42", "Information Technology", 2026, 92, 91, 91.4, "Microsoft", 8, "Platinum"),
        ("peer-03", "SystemSurgeon_18", "Computer Science", 2026, 90, 89, 89.4, "Amazon", 8, "Platinum"),
        ("peer-04", "DataVoyager_77", "Data Science & AI", 2026, 88, 86, 86.9, "Adobe", 7, "Gold"),
        ("peer-05", "DevScholar_12", "Computer Science", 2026, 86, 84, 84.9, "Uber", 7, "Gold"),
        ("peer-06", "BinaryMonk_33", "Electronics & Comm", 2026, 85, 82, 83.3, "Cisco", 6, "Gold"),
        ("peer-07", "PixelCraft_29", "Information Technology", 2026, 84, 83, 83.4, "Swiggy", 6, "Gold"),
        ("peer-08", "CodeCrafter_05", "Computer Science", 2026, 83, 80, 81.3, "Razorpay", 6, "Gold"),
        ("peer-09", "NeuralNomad_64", "Data Science & AI", 2025, 82, 79, 80.3, "Oracle", 6, "Gold"),
        ("peer-10", "SyntaxSamurai_81", "Computer Science", 2025, 81, 78, 79.3, "Goldman Sachs", 6, "Gold"),
        ("peer-11", "KernelKnight_56", "Electronics & Comm", 2026, 80, 77, 78.3, "Qualcomm", 5, "Gold"),
        ("peer-12", "StackWizard_21", "Information Technology", 2026, 78, 76, 76.9, "Flipkart", 5, "Silver"),
        ("peer-13", "LogicWhiz_44", "Computer Science", 2026, 77, 75, 75.9, "TCS", 5, "Silver"),
        ("peer-14", "CyberFalcon_87", "Computer Science", 2025, 76, 74, 74.9, "Infosys", 5, "Silver"),
        ("peer-15", "QuantumCoder_19", "Electronics & Comm", 2027, 75, 72, 73.3, "Accenture", 4, "Silver"),
        ("peer-16", "ByteSurgeon_63", "Information Technology", 2026, 74, 71, 72.3, "Capgemini", 4, "Silver"),
        ("peer-17", "MatrixMaster_38", "Electrical Engineering", 2026, 73, 70, 71.3, "Wipro", 4, "Silver"),
        ("peer-18", "PromptArchitect_90", "Data Science & AI", 2026, 72, 69, 70.3, "Cognizant", 4, "Silver"),
        ("peer-19", "GitGuru_08", "Computer Science", 2027, 70, 68, 68.9, "General", 4, "Silver"),
        ("peer-20", "ScriptSage_52", "Electronics & Comm", 2025, 69, 66, 67.3, "General", 4, "Silver"),
        ("peer-21", "SiliconPioneer_35", "Electrical Engineering", 2026, 67, 65, 65.9, "General", 3, "Silver"),
        ("peer-22", "TurboCoder_14", "Mechanical Engineering", 2026, 64, 62, 62.9, "General", 3, "Bronze"),
        ("peer-23", "ApexDev_93", "Computer Science", 2027, 62, 60, 60.9, "General", 3, "Bronze"),
        ("peer-24", "VeloceBytes_41", "Civil Engineering", 2026, 58, 55, 56.3, "General", 2, "Bronze"),
    ]
    cursor.executemany(
        """
        INSERT OR IGNORE INTO cohort_benchmarks
        (id, student_handle, department, grad_year, ats_score, job_match_score, overall_score, target_company, skills_count, tier)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        seed_peers,
    )
    logger.info(f"Seeded {len(seed_peers)} default peer cohort benchmark records.")


def get_user_leaderboard_opt_in(
    user_id: Optional[str],
    db_path: Optional[str] = None,
) -> bool:
    """Retrieves the leaderboard participation preference for a user (#360)."""
    if not user_id:
        return True
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT leaderboard_opt_in FROM users WHERE id = ?", (str(user_id),))
            row = cursor.fetchone()
            if row and row[0] is not None:
                return bool(row[0])
            return True
    except Exception as e:
        logger.error(f"Error fetching leaderboard opt-in for user {user_id}: {e}")
        return True


def set_user_leaderboard_opt_in(
    user_id: str,
    opt_in: bool,
    db_path: Optional[str] = None,
) -> bool:
    """Updates the leaderboard participation preference for a user (#360)."""
    if not user_id:
        return False
    try:
        val = 1 if opt_in else 0
        with transaction(db_path) as cursor:
            cursor.execute("UPDATE users SET leaderboard_opt_in = ? WHERE id = ?", (val, str(user_id)))
            if cursor.rowcount == 0:
                cursor.execute(
                    """
                    INSERT INTO users (id, name, email, password_hash, leaderboard_opt_in)
                    VALUES (?, ?, ?, '', ?)
                    ON CONFLICT(id) DO UPDATE SET leaderboard_opt_in = excluded.leaderboard_opt_in
                    """,
                    (str(user_id), f"Student_{user_id}", f"{user_id}@campus.local", val),
                )
            return True
    except Exception as e:
        logger.error(f"Error updating leaderboard opt-in for user {user_id}: {e}")
        return False


def record_or_update_cohort_benchmark(
    analysis_id: str,
    student_handle: str,
    department: str = "Computer Science",
    grad_year: int = 2026,
    ats_score: int = 70,
    job_match_score: int = 65,
    overall_score: Optional[float] = None,
    target_company: str = "General",
    skills_count: int = 0,
    tier: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Inserts or updates an anonymized student evaluation in the cohort_benchmarks table."""
    if overall_score is None:
        overall_score = round((ats_score * 0.45) + (job_match_score * 0.55), 1)

    if not tier:
        if overall_score >= 88.0:
            tier = "Platinum"
        elif overall_score >= 78.0:
            tier = "Gold"
        elif overall_score >= 65.0:
            tier = "Silver"
        else:
            tier = "Bronze"

    with transaction(db_path) as cursor:
        cursor.execute("SELECT id FROM cohort_benchmarks WHERE analysis_id = ?", (analysis_id,))
        existing = cursor.fetchone()

        if existing:
            benchmark_id = existing[0]
            cursor.execute(
                """
                UPDATE cohort_benchmarks
                SET student_handle = ?, department = ?, grad_year = ?,
                    ats_score = ?, job_match_score = ?, overall_score = ?,
                    target_company = ?, skills_count = ?, tier = ?
                WHERE id = ?
                """,
                (
                    student_handle, department, grad_year,
                    ats_score, job_match_score, overall_score,
                    target_company, skills_count, tier,
                    benchmark_id,
                ),
            )
        else:
            benchmark_id = f"cohort-{analysis_id}"
            cursor.execute(
                """
                INSERT INTO cohort_benchmarks
                (id, analysis_id, student_handle, department, grad_year, ats_score, job_match_score, overall_score, target_company, skills_count, tier)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    benchmark_id, analysis_id, student_handle, department, grad_year,
                    ats_score, job_match_score, overall_score, target_company, skills_count, tier,
                ),
            )

        return benchmark_id


def get_cohort_benchmark_by_analysis_id(
    analysis_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves the cohort benchmark record for a specific analysis ID."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM cohort_benchmarks WHERE analysis_id = ?", (analysis_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Error fetching cohort benchmark for {analysis_id}: {e}")
        return None


def get_cohort_benchmarks(
    department: Optional[str] = None,
    grad_year: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    include_opted_out: bool = False,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves sorted cohort benchmark entries ordered by overall_score DESC."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            conditions = []
            params = []

            if not include_opted_out:
                conditions.append("COALESCE(u.leaderboard_opt_in, 1) = 1")

            if department and department.strip() and department.strip().lower() not in ("all", "any"):
                conditions.append("LOWER(cb.department) = LOWER(?)")
                params.append(department.strip())

            if grad_year and int(grad_year) > 0:
                conditions.append("cb.grad_year = ?")
                params.append(int(grad_year))

            if search and search.strip():
                kw = f"%{search.strip().lower()}%"
                conditions.append(
                    "(LOWER(cb.student_handle) LIKE ? OR LOWER(cb.target_company) LIKE ? OR LOWER(cb.department) LIKE ?)"
                )
                params.extend([kw, kw, kw])

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            query = f"""
                SELECT cb.* FROM cohort_benchmarks cb
                LEFT JOIN analyses a ON cb.analysis_id = a.id
                LEFT JOIN users u ON a.student_id = u.id
                {where_clause}
                ORDER BY cb.overall_score DESC, cb.ats_score DESC, cb.job_match_score DESC
                LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()

            benchmarks = []
            for idx, row in enumerate(rows):
                rec = dict(row)
                rec["rank"] = offset + idx + 1
                benchmarks.append(rec)

            return benchmarks
    except Exception as e:
        logger.error(f"Error fetching cohort benchmarks: {e}")
        return []


def get_cohort_stats(
    department: Optional[str] = None,
    grad_year: Optional[int] = None,
    include_opted_out: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Computes aggregate metrics across the specified cohort segment."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            conditions = []
            params = []

            if not include_opted_out:
                conditions.append("COALESCE(u.leaderboard_opt_in, 1) = 1")

            if department and department.strip() and department.strip().lower() not in ("all", "any"):
                conditions.append("LOWER(cb.department) = LOWER(?)")
                params.append(department.strip())

            if grad_year and int(grad_year) > 0:
                conditions.append("cb.grad_year = ?")
                params.append(int(grad_year))

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            cursor.execute(
                f"""
                SELECT
                    COUNT(*) as total_students,
                    COALESCE(AVG(cb.ats_score), 0) as avg_ats,
                    COALESCE(AVG(cb.job_match_score), 0) as avg_match,
                    COALESCE(AVG(cb.overall_score), 0) as avg_overall,
                    COALESCE(MAX(cb.overall_score), 0) as max_overall,
                    COALESCE(SUM(CASE WHEN cb.tier = 'Platinum' THEN 1 ELSE 0 END), 0) as platinum_count,
                    COALESCE(SUM(CASE WHEN cb.tier = 'Gold' THEN 1 ELSE 0 END), 0) as gold_count,
                    COALESCE(SUM(CASE WHEN cb.tier = 'Silver' THEN 1 ELSE 0 END), 0) as silver_count,
                    COALESCE(SUM(CASE WHEN cb.tier = 'Bronze' THEN 1 ELSE 0 END), 0) as bronze_count
                FROM cohort_benchmarks cb
                LEFT JOIN analyses a ON cb.analysis_id = a.id
                LEFT JOIN users u ON a.student_id = u.id
                {where_clause}
                """,
                params,
            )

            stats = dict(cursor.fetchone())
            stats["avg_ats"] = round(float(stats.get("avg_ats", 0)), 1)
            stats["avg_match"] = round(float(stats.get("avg_match", 0)), 1)
            stats["avg_overall"] = round(float(stats.get("avg_overall", 0)), 1)
            stats["max_overall"] = round(float(stats.get("max_overall", 0)), 1)

            cursor.execute(
                f"""
                SELECT cb.department, COUNT(*) as count
                FROM cohort_benchmarks cb
                LEFT JOIN analyses a ON cb.analysis_id = a.id
                LEFT JOIN users u ON a.student_id = u.id
                {where_clause}
                GROUP BY cb.department
                ORDER BY count DESC
                """,
                params,
            )
            stats["department_breakdown"] = [dict(r) for r in cursor.fetchall()]

            return stats
    except Exception as e:
        logger.error(f"Error computing cohort statistics: {e}")
        return {
            "total_students": 0,
            "avg_ats": 0.0,
            "avg_match": 0.0,
            "avg_overall": 0.0,
            "max_overall": 0.0,
            "platinum_count": 0,
            "gold_count": 0,
            "silver_count": 0,
            "bronze_count": 0,
            "department_breakdown": [],
        }


def get_user_placement_history(
    student_id: str = "default_student",
    company_filter: Optional[str] = None,
    sort_by: str = "date_desc",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieves previous placement analysis history for a specific student (#149)."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            effective_student_id = (student_id or "default_student").strip()

            query = """
                SELECT id, resume_filename, company_name, job_description, results_json,
                       student_id, version_number, created_at
                FROM analyses
                WHERE student_id = ?
            """
            params: List[Any] = [effective_student_id]

            if company_filter and company_filter.strip() and company_filter.strip().lower() not in ("all", "any"):
                query += " AND LOWER(company_name) LIKE ?"
                params.append(f"%{company_filter.strip().lower()}%")

            if sort_by == "score_desc":
                query += " ORDER BY created_at DESC"
            elif sort_by == "date_asc":
                query += " ORDER BY created_at ASC"
            else:
                query += " ORDER BY created_at DESC"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            records = []
            ats_scores = []
            match_scores = []
            company_counts: Dict[str, int] = {}

            for row in rows:
                rec = dict(row)
                try:
                    raw_json = rec.pop("results_json", "{}")
                    parsed = json.loads(raw_json)
                    rec["results"] = parsed

                    ats = parsed.get("ats_score") or parsed.get("resume_analysis", {}).get("ats_score", 0)
                    match = parsed.get("job_match_score") or parsed.get("job_match", {}).get("match_percentage", 0)

                    rec["ats_score"] = int(ats)
                    rec["match_percentage"] = int(match)
                    ats_scores.append(rec["ats_score"])
                    match_scores.append(rec["match_percentage"])

                    rec["matched_skills_count"] = len(
                        parsed.get("matched_skills")
                        or parsed.get("job_match", {}).get("matched_skills", [])
                    )
                    rec["missing_skills_count"] = len(
                        parsed.get("missing_skills")
                        or parsed.get("job_match", {}).get("missing_skills", [])
                    )

                    comp = rec.get("company_name", "General")
                    company_counts[comp] = company_counts.get(comp, 0) + 1

                except Exception as parse_err:
                    logger.warning(f"Failed to parse analysis payload for record {rec.get('id')}: {parse_err}")
                    rec["results"] = {}
                    rec["ats_score"] = 0
                    rec["match_percentage"] = 0
                    rec["matched_skills_count"] = 0
                    rec["missing_skills_count"] = 0

                records.append(rec)

            if sort_by == "score_desc":
                records.sort(key=lambda x: x["ats_score"], reverse=True)

            avg_ats = round(sum(ats_scores) / len(ats_scores), 1) if ats_scores else 0.0
            avg_match = round(sum(match_scores) / len(match_scores), 1) if match_scores else 0.0
            highest_ats = max(ats_scores) if ats_scores else 0

            return {
                "student_id": effective_student_id,
                "total_analyses": len(records),
                "average_ats_score": avg_ats,
                "average_match_percentage": avg_match,
                "highest_ats_score": highest_ats,
                "company_counts": company_counts,
                "analyses": records,
            }

    except Exception as e:
        logger.error(f"Error fetching placement analysis history for {student_id}: {e}")
        return {
            "student_id": student_id,
            "total_analyses": 0,
            "average_ats_score": 0.0,
            "average_match_percentage": 0.0,
            "highest_ats_score": 0,
            "company_counts": {},
            "analyses": [],
        }


def get_student_top_skill_gaps_for_company(
    student_id: str,
    company_name: str,
    limit: int = 3,
    db_path: Optional[str] = None,
) -> List[str]:
    """Retrieves top identified skill gaps for a student targeted at a company (#433)."""
    if not student_id:
        return []

    effective_student_id = str(student_id).strip()
    norm_comp = (company_name or "").strip()

    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            target_analysis = None

            if norm_comp:
                cursor.execute(
                    """
                    SELECT id, results_json FROM analyses
                    WHERE student_id = ? AND LOWER(company_name) = LOWER(?)
                    ORDER BY created_at DESC, version_number DESC
                    LIMIT 1
                    """,
                    (effective_student_id, norm_comp),
                )
                row = cursor.fetchone()
                if row:
                    target_analysis = row

            if not target_analysis:
                cursor.execute(
                    """
                    SELECT id, results_json FROM analyses
                    WHERE student_id = ?
                    ORDER BY created_at DESC, version_number DESC
                    LIMIT 1
                    """,
                    (effective_student_id,),
                )
                row = cursor.fetchone()
                if row:
                    target_analysis = row

            if not target_analysis:
                return []

            raw_json = target_analysis["results_json"]
            if not raw_json:
                return []

            parsed = json.loads(raw_json) if isinstance(raw_json, str) else (raw_json or {})
            results = parsed.get("results") or parsed

            gaps: List[str] = []
            raw_skill_gaps = results.get("skill_gap") or []
            for g in raw_skill_gaps:
                if isinstance(g, dict):
                    skill_name = g.get("skill") or g.get("missing_skill") or g.get("name")
                else:
                    skill_name = str(g)
                if skill_name and str(skill_name).strip() and str(skill_name).strip() not in gaps:
                    gaps.append(str(skill_name).strip())

            if not gaps:
                job_match = results.get("job_match") or {}
                missing_skills = job_match.get("missing_skills") or []
                for ms in missing_skills:
                    ms_clean = str(ms).strip()
                    if ms_clean and ms_clean not in gaps:
                        gaps.append(ms_clean)

            return gaps[:limit]
    except Exception as e:
        logger.warning(f"Error fetching top skill gaps for student {student_id} and company {company_name}: {e}")
        return []
