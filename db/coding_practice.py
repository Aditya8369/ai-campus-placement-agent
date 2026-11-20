"""
Coding Practice & Technical Skills Repository (db/coding_practice.py)
===================================================================
Handles database operations for coding submissions, bookmarks, technical skill
self-assessments, student profiles, profile completeness calculations, and aptitude tests.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from db.connection import get_connection, transaction

logger = logging.getLogger(__name__)


def save_coding_submission(
    sub_id: str,
    student_id: str,
    question_title: str,
    language: str,
    code: str,
    passed: bool,
    score: int,
    tests_passed: int = 0,
    total_tests: int = 0,
    test_results: Optional[List[Dict[str, Any]]] = None,
    complexity_analysis: Optional[str] = None,
    feedback: Optional[str] = None,
    company_name: str = "General",
    analysis_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Persists a coding assessment submission attempt (#194)."""
    effective_student_id = (student_id or "default_student").strip()
    with transaction(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO coding_submissions (
                id, student_id, analysis_id, question_title, company_name,
                language, code, passed, score, tests_passed, total_tests,
                test_results_json, complexity_analysis, feedback
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sub_id,
                effective_student_id,
                analysis_id,
                question_title.strip(),
                company_name.strip(),
                language.strip().lower(),
                code,
                1 if passed else 0,
                int(score),
                int(tests_passed),
                int(total_tests),
                json.dumps(test_results or []),
                complexity_analysis or "",
                feedback or "",
            ),
        )
        logger.info(f"Saved coding submission {sub_id} for student {effective_student_id}")

    try:
        from db.streaks import record_preparation_activity
        record_preparation_activity(
            student_id=effective_student_id,
            activity_type="coding_practice",
            metadata={"submission_id": sub_id, "question_title": question_title, "score": score, "passed": passed},
            db_path=db_path,
        )
    except Exception as streak_err:
        logger.warning(f"Failed to record preparation activity on save_coding_submission: {streak_err}")

    return sub_id


def get_coding_submissions(
    student_id: str,
    question_title: Optional[str] = None,
    language_filter: Optional[str] = None,
    status_filter: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves all coding assessment submission attempts for a student."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            effective_student_id = (student_id or "default_student").strip()
            conditions = ["student_id = ?"]
            params: List[Any] = [effective_student_id]

            if question_title and question_title.strip():
                conditions.append("LOWER(question_title) = LOWER(?)")
                params.append(question_title.strip())

            if language_filter and language_filter.strip() and language_filter.strip().lower() not in ("all", "any"):
                conditions.append("LOWER(language) = LOWER(?)")
                params.append(language_filter.strip())

            if status_filter and status_filter.strip() and status_filter.strip().lower() not in ("all", "any"):
                if status_filter.strip().lower() == "passed":
                    conditions.append("passed = 1")
                elif status_filter.strip().lower() == "failed":
                    conditions.append("passed = 0")

            where_clause = f"WHERE {' AND '.join(conditions)}"
            query = f"SELECT * FROM coding_submissions {where_clause} ORDER BY submitted_at DESC, id DESC"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            submissions = []
            for r in rows:
                rec = dict(r)
                try:
                    rec["test_results"] = json.loads(rec.get("test_results_json", "[]"))
                except Exception:
                    rec["test_results"] = []
                rec["passed"] = bool(rec.get("passed", 0))
                submissions.append(rec)

            return submissions
    except Exception as e:
        logger.error(f"Error retrieving coding submissions for {student_id}: {e}")
        return []


def save_skill_self_assessment(
    student_id: str,
    skill_name: str,
    category: str,
    proficiency_level: str,
    years_experience: float = 0.0,
    notes: str = "",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Saves or updates a student's technical skill self-assessment."""
    record_id = str(uuid.uuid4())
    normalized_student_id = (student_id or "default_student").strip()
    normalized_skill = skill_name.strip()
    normalized_category = (category or "General").strip()
    valid_levels = ["Beginner", "Intermediate", "Advanced", "Expert"]
    level = proficiency_level if proficiency_level in valid_levels else "Intermediate"

    with transaction(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO technical_self_assessments (
                id, student_id, skill_name, category, proficiency_level, years_experience, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(student_id, skill_name) DO UPDATE SET
                category = excluded.category,
                proficiency_level = excluded.proficiency_level,
                years_experience = excluded.years_experience,
                notes = excluded.notes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                record_id,
                normalized_student_id,
                normalized_skill,
                normalized_category,
                level,
                float(years_experience or 0.0),
                notes.strip() if notes else "",
            ),
        )

        cursor.execute(
            "SELECT * FROM technical_self_assessments WHERE student_id = ? AND skill_name = ?",
            (normalized_student_id, normalized_skill),
        )
        row = cursor.fetchone()
        return dict(row) if row else {}


def get_student_skill_self_assessments(
    student_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves all technical skill self-assessments for a student."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        normalized_student_id = (student_id or "default_student").strip()
        cursor.execute(
            """
            SELECT * FROM technical_self_assessments
            WHERE student_id = ?
            ORDER BY category ASC, skill_name ASC
            """,
            (normalized_student_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def delete_skill_self_assessment(
    student_id: str,
    skill_name: str,
    db_path: Optional[str] = None,
) -> bool:
    """Deletes a student's self-assessment entry for a skill."""
    with transaction(db_path) as cursor:
        normalized_student_id = (student_id or "default_student").strip()
        cursor.execute(
            "DELETE FROM technical_self_assessments WHERE student_id = ? AND skill_name = ?",
            (normalized_student_id, skill_name.strip()),
        )
        return cursor.rowcount > 0


def get_default_technical_skills_catalog() -> Dict[str, List[str]]:
    """Returns curated placement technical skills catalog grouped by category."""
    return {
        "Programming Languages": ["Python", "Java", "C++", "JavaScript", "TypeScript", "Go"],
        "Web & Frameworks": ["React", "Node.js", "Flask", "Django", "Spring Boot", "HTML5/CSS3"],
        "Data & Databases": ["SQL", "PostgreSQL", "MongoDB", "Redis", "Data Structures & Algorithms"],
        "Cloud & DevOps": ["Git & GitHub", "Docker", "Kubernetes", "AWS", "CI/CD Pipelines", "Linux"],
        "Core CS Fundamentals": ["Operating Systems", "DBMS", "Computer Networks", "System Design", "OOP"],
    }


def save_student_profile(
    student_id: str,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    department: Optional[str] = None,
    grad_year: Optional[int] = None,
    cgpa: Optional[float] = None,
    target_role: Optional[str] = None,
    target_company: Optional[str] = None,
    skills: Optional[List[str]] = None,
    linkedin_url: Optional[str] = None,
    github_url: Optional[str] = None,
    has_resume_uploaded: Optional[bool] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Saves or updates a candidate's placement profile (#199)."""
    s_id = (student_id or "default_student").strip()
    skills_json = json.dumps(skills) if skills is not None else None

    with transaction(db_path) as cursor:
        cursor.execute("SELECT * FROM student_profiles WHERE student_id = ?", (s_id,))
        existing = cursor.fetchone()

        if existing:
            rec = dict(existing)
            u_name = full_name if full_name is not None else rec.get("full_name")
            u_email = email if email is not None else rec.get("email")
            u_phone = phone if phone is not None else rec.get("phone")
            u_dept = department if department is not None else rec.get("department")
            u_year = grad_year if grad_year is not None else rec.get("grad_year")
            u_cgpa = cgpa if cgpa is not None else rec.get("cgpa")
            u_role = target_role if target_role is not None else rec.get("target_role")
            u_comp = target_company if target_company is not None else rec.get("target_company")
            u_skills = skills_json if skills_json is not None else rec.get("skills_json")
            u_li = linkedin_url if linkedin_url is not None else rec.get("linkedin_url")
            u_gh = github_url if github_url is not None else rec.get("github_url")
            u_resume = (
                int(has_resume_uploaded)
                if has_resume_uploaded is not None
                else rec.get("has_resume_uploaded", 0)
            )

            cursor.execute(
                """
                UPDATE student_profiles SET
                    full_name = ?, email = ?, phone = ?, department = ?,
                    grad_year = ?, cgpa = ?, target_role = ?, target_company = ?,
                    skills_json = ?, linkedin_url = ?, github_url = ?,
                    has_resume_uploaded = ?, updated_at = CURRENT_TIMESTAMP
                WHERE student_id = ?
                """,
                (
                    u_name, u_email, u_phone, u_dept,
                    u_year, u_cgpa, u_role, u_comp,
                    u_skills, u_li, u_gh, u_resume, s_id,
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO student_profiles (
                    student_id, full_name, email, phone, department,
                    grad_year, cgpa, target_role, target_company,
                    skills_json, linkedin_url, github_url, has_resume_uploaded, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    s_id, full_name, email, phone, department,
                    grad_year, cgpa, target_role, target_company,
                    skills_json, linkedin_url, github_url,
                    int(has_resume_uploaded or 0),
                ),
            )

        cursor.execute("SELECT * FROM student_profiles WHERE student_id = ?", (s_id,))
        saved = dict(cursor.fetchone())
        if saved.get("skills_json"):
            try:
                saved["skills"] = json.loads(saved["skills_json"])
            except Exception:
                saved["skills"] = []
        else:
            saved["skills"] = []
        return saved


def get_student_profile(
    student_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieves student profile record by student_id (#199)."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        s_id = (student_id or "default_student").strip()
        cursor.execute("SELECT * FROM student_profiles WHERE student_id = ?", (s_id,))
        row = cursor.fetchone()
        if not row:
            cursor.execute("SELECT name, email FROM users WHERE id = ?", (s_id,))
            user_row = cursor.fetchone()
            return {
                "student_id": s_id,
                "full_name": user_row["name"] if user_row else "",
                "email": user_row["email"] if user_row else "",
                "phone": "",
                "department": "",
                "grad_year": None,
                "cgpa": None,
                "target_role": "",
                "target_company": "",
                "skills": [],
                "linkedin_url": "",
                "github_url": "",
                "has_resume_uploaded": 0,
            }

        data = dict(row)
        if data.get("skills_json"):
            try:
                data["skills"] = json.loads(data["skills_json"])
            except Exception:
                data["skills"] = []
        else:
            data["skills"] = []
        return data


def calculate_profile_completion(
    student_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluates profile completeness across key placement readiness criteria (#199)."""
    profile = get_student_profile(student_id, db_path=db_path)

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM analyses WHERE student_id = ?", (student_id.strip(),))
        has_analyses = cursor.fetchone()[0] > 0

    criteria = []

    has_name = bool((profile.get("full_name") or "").strip())
    has_email = bool((profile.get("email") or "").strip())
    has_phone = bool((profile.get("phone") or "").strip())
    basic_done = has_name and has_email
    criteria.append({
        "category": "Basic Contact Information",
        "title": "Full Name & Email",
        "weight": 15,
        "completed": basic_done,
        "missing_items": [f for f, ok in [("Full Name", has_name), ("Email Address", has_email)] if not ok],
    })

    criteria.append({
        "category": "Basic Contact Information",
        "title": "Contact Phone Number",
        "weight": 5,
        "completed": has_phone,
        "missing_items": [] if has_phone else ["Phone Number"],
    })

    has_dept = bool((profile.get("department") or "").strip())
    has_year = bool(profile.get("grad_year") and int(profile.get("grad_year")) >= 2020)
    has_cgpa = bool(profile.get("cgpa") and float(profile.get("cgpa")) > 0)
    criteria.append({
        "category": "Academic Background",
        "title": "Department & Graduation Year",
        "weight": 15,
        "completed": has_dept and has_year,
        "missing_items": [f for f, ok in [("Department", has_dept), ("Graduation Year", has_year)] if not ok],
    })

    criteria.append({
        "category": "Academic Background",
        "title": "Undergraduate CGPA",
        "weight": 10,
        "completed": has_cgpa,
        "missing_items": [] if has_cgpa else ["CGPA"],
    })

    has_role = bool((profile.get("target_role") or "").strip())
    has_comp = bool((profile.get("target_company") or "").strip())
    criteria.append({
        "category": "Placement Preferences",
        "title": "Target Role & Dream Company",
        "weight": 20,
        "completed": has_role and has_comp,
        "missing_items": [f for f, ok in [("Target Role", has_role), ("Target Company", has_comp)] if not ok],
    })

    skills_list = profile.get("skills", [])
    has_skills = len(skills_list) >= 3
    criteria.append({
        "category": "Technical Competencies",
        "title": "At least 3 Key Technical Skills",
        "weight": 15,
        "completed": has_skills,
        "missing_items": [] if has_skills else [f"Add at least {3 - len(skills_list)} more skill(s)"],
    })

    resume_ready = bool(profile.get("has_resume_uploaded")) or has_analyses
    has_social = bool((profile.get("linkedin_url") or "").strip()) or bool((profile.get("github_url") or "").strip())
    criteria.append({
        "category": "Placement Portfolio",
        "title": "Resume Upload & Developer Links",
        "weight": 20,
        "completed": resume_ready and has_social,
        "missing_items": [f for f, ok in [("Resume Upload", resume_ready), ("LinkedIn/GitHub URL", has_social)] if not ok],
    })

    total_weight = sum(c["weight"] for c in criteria)
    earned_weight = sum(c["weight"] for c in criteria if c["completed"])
    percentage = round((earned_weight / total_weight) * 100) if total_weight > 0 else 0

    all_missing = []
    for c in criteria:
        if not c["completed"]:
            all_missing.extend(c["missing_items"])

    return {
        "student_id": student_id,
        "completion_percentage": percentage,
        "is_complete": percentage >= 100,
        "criteria": criteria,
        "missing_fields": all_missing,
        "profile": profile,
    }


def save_coding_bookmark(
    student_id: str,
    problem_id: str,
    problem_data: Dict[str, Any],
    db_path: Optional[str] = None,
) -> bool:
    """Saves a recommended coding practice question to the candidate's bookmarked collection."""
    try:
        effective_student_id = (student_id or "default_student").strip()
        p_id = str(problem_id).strip()
        data_json = json.dumps(problem_data)
        bookmark_id = str(uuid.uuid4())

        with transaction(db_path) as cursor:
            cursor.execute(
                """
                INSERT INTO bookmarked_coding_questions (
                    id, student_id, problem_id, problem_data, created_at
                ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(student_id, problem_id) DO UPDATE SET
                    problem_data = excluded.problem_data,
                    created_at = CURRENT_TIMESTAMP
                """,
                (bookmark_id, effective_student_id, p_id, data_json),
            )
            logger.info(f"Saved coding bookmark for student {effective_student_id}, problem {p_id}")
            return True
    except Exception as e:
        logger.error(f"Error saving coding bookmark for problem {problem_id}: {e}")
        return False


def remove_coding_bookmark(
    student_id: str,
    problem_id: str,
    db_path: Optional[str] = None,
) -> bool:
    """Removes a bookmarked coding question for a candidate."""
    try:
        effective_student_id = (student_id or "default_student").strip()
        p_id = str(problem_id).strip()

        with transaction(db_path) as cursor:
            cursor.execute(
                """
                DELETE FROM bookmarked_coding_questions
                WHERE student_id = ? AND problem_id = ?
                """,
                (effective_student_id, p_id),
            )
            logger.info(f"Removed coding bookmark for student {effective_student_id}, problem {p_id}")
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error removing coding bookmark for problem {problem_id}: {e}")
        return False


def get_coding_bookmarks(
    student_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves all bookmarked coding questions for a student."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            effective_student_id = (student_id or "default_student").strip()

            cursor.execute(
                """
                SELECT id, student_id, problem_id, problem_data, created_at
                FROM bookmarked_coding_questions
                WHERE student_id = ?
                ORDER BY created_at DESC
                """,
                (effective_student_id,),
            )
            rows = cursor.fetchall()

            bookmarks = []
            for row in rows:
                rec = dict(row)
                try:
                    prob = json.loads(rec.get("problem_data", "{}"))
                except Exception:
                    prob = {}
                if "id" not in prob or not prob["id"]:
                    prob["id"] = rec.get("problem_id")
                prob["bookmark_id"] = rec.get("id")
                prob["bookmarked_at"] = rec.get("created_at")
                bookmarks.append(prob)
            return bookmarks
    except Exception as e:
        logger.error(f"Error fetching coding bookmarks for student {student_id}: {e}")
        return []


def is_coding_bookmarked(
    student_id: str,
    problem_id: str,
    db_path: Optional[str] = None,
) -> bool:
    """Checks if a coding practice question is bookmarked by the student."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            effective_student_id = (student_id or "default_student").strip()
            p_id = str(problem_id).strip()

            cursor.execute(
                """
                SELECT 1 FROM bookmarked_coding_questions
                WHERE student_id = ? AND problem_id = ?
                LIMIT 1
                """,
                (effective_student_id, p_id),
            )
            return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Error checking bookmark status for problem {problem_id}: {e}")
        return False


def save_aptitude_attempt(
    student_id: str,
    test_category: str,
    total_questions: int,
    correct_count: int,
    score_percentage: float,
    time_taken_seconds: int,
    time_limit_seconds: int,
    timed_out: bool,
    topic_accuracy_json: str,
    weak_topics_json: str,
    results_json: str,
    attempt_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Persists a timed aptitude practice attempt and per-topic accuracy scores."""
    attempt_uuid = attempt_id or str(uuid.uuid4())
    with transaction(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO aptitude_attempts (
                id, student_id, test_category, total_questions, correct_count,
                score_percentage, time_taken_seconds, time_limit_seconds, timed_out,
                topic_accuracy_json, weak_topics_json, results_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_uuid,
                student_id,
                test_category,
                total_questions,
                correct_count,
                round(float(score_percentage), 2),
                int(time_taken_seconds),
                int(time_limit_seconds),
                1 if timed_out else 0,
                topic_accuracy_json,
                weak_topics_json,
                results_json,
            ),
        )

        cursor.execute("SELECT * FROM aptitude_attempts WHERE id = ?", (attempt_uuid,))
        row = cursor.fetchone()
        return dict(row) if row else {"id": attempt_uuid, "student_id": student_id}


def get_student_aptitude_attempts(
    student_id: str,
    limit: int = 10,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves the most recent aptitude practice attempts for a student."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM aptitude_attempts
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
                if item.get("topic_accuracy_json"):
                    try:
                        item["topic_accuracy"] = json.loads(item["topic_accuracy_json"])
                    except Exception:
                        item["topic_accuracy"] = {}
                if item.get("weak_topics_json"):
                    try:
                        item["weak_topics"] = json.loads(item["weak_topics_json"])
                    except Exception:
                        item["weak_topics"] = []
                if item.get("results_json"):
                    try:
                        item["results"] = json.loads(item["results_json"])
                    except Exception:
                        item["results"] = {}
                result.append(item)
            return result
    except Exception as e:
        logger.error(f"Error fetching aptitude attempts for student {student_id}: {e}")
        return []


def get_aptitude_attempt_by_id(
    attempt_id: str,
    student_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves a single aptitude attempt record by its ID, optionally checking student ownership."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            if student_id:
                cursor.execute(
                    "SELECT * FROM aptitude_attempts WHERE id = ? AND student_id = ?",
                    (attempt_id, student_id),
                )
            else:
                cursor.execute("SELECT * FROM aptitude_attempts WHERE id = ?", (attempt_id,))
            row = cursor.fetchone()
            if not row:
                return None
            item = dict(row)
            if item.get("topic_accuracy_json"):
                try:
                    item["topic_accuracy"] = json.loads(item["topic_accuracy_json"])
                except Exception:
                    item["topic_accuracy"] = {}
            if item.get("weak_topics_json"):
                try:
                    item["weak_topics"] = json.loads(item["weak_topics_json"])
                except Exception:
                    item["weak_topics"] = []
            if item.get("results_json"):
                try:
                    item["results"] = json.loads(item["results_json"])
                except Exception:
                    item["results"] = {}
            return item
    except Exception as e:
        logger.error(f"Error retrieving aptitude attempt {attempt_id}: {e}")
        return None


def get_student_weak_aptitude_topics(
    student_id: str,
    threshold: float = 60.0,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Analyzes historical attempts of a student across aptitude tests for weak topics."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT topic_accuracy_json FROM aptitude_attempts
                WHERE student_id = ?
                ORDER BY created_at DESC
                LIMIT 20
                """,
                (student_id,),
            )
            rows = cursor.fetchall()
            if not rows:
                return []

            topic_stats: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                raw_acc = r["topic_accuracy_json"]
                if not raw_acc:
                    continue
                try:
                    parsed = json.loads(raw_acc)
                except Exception:
                    continue

                for topic_name, stats in parsed.items():
                    if topic_name not in topic_stats:
                        topic_stats[topic_name] = {
                            "topic": topic_name,
                            "category": stats.get("category", "general"),
                            "total": 0,
                            "correct": 0,
                        }
                    topic_stats[topic_name]["total"] += int(stats.get("total", 0))
                    topic_stats[topic_name]["correct"] += int(stats.get("correct", 0))

            weak_topics = []
            for topic_name, stats in topic_stats.items():
                tot = stats["total"]
                corr = stats["correct"]
                if tot > 0:
                    acc = round((corr / tot) * 100.0, 1)
                    if acc < threshold:
                        weak_topics.append({
                            "topic": topic_name,
                            "category": stats["category"],
                            "total_questions": tot,
                            "correct_answers": corr,
                            "accuracy_percentage": acc,
                            "recommendation": f"Accuracy in {topic_name} is {acc}%. Targeted practice recommended before campus drives.",
                        })

            weak_topics.sort(key=lambda x: (x["accuracy_percentage"], -x["total_questions"]))
            return weak_topics
    except Exception as e:
        logger.error(f"Error computing weak aptitude topics for student {student_id}: {e}")
        return []


def delete_student_aptitude_attempts(
    student_id: str,
    db_path: Optional[str] = None,
) -> int:
    """Deletes all aptitude practice attempts for a student."""
    try:
        with transaction(db_path) as cursor:
            cursor.execute("DELETE FROM aptitude_attempts WHERE student_id = ?", (student_id,))
            return cursor.rowcount
    except Exception as e:
        logger.error(f"Error clearing aptitude practice attempts for student {student_id}: {e}")
        return 0
