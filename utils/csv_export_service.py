"""
CSV Export Service for Student Placement Preparation Data (#274).

Enables students to export their preparation data into CSV format:
1. Job Applications:
   - Company, role, applied date, stage/status, location, notes.
2. Mock Interview Performance:
   - Session ID, analysis target company, question index, question text, answer length, score, feedback.
3. Preparation / Study Notes:
   - Title, category/topic, content, tags, created timestamp.
4. Coding Challenge Submissions:
   - Problem title, topic/difficulty, language, status, execution time, submitted timestamp.

Security & Multi-Tenancy:
- Strict student isolation: only records belonging to the authenticated student are retrieved and exported.
- Sanitizes formula injection (e.g. cells starting with '=', '+', '-', '@' are prepended with single quotes).
"""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any, Dict, List, Tuple

from utils.database import get_db_connection

logger = logging.getLogger(__name__)


def sanitize_csv_cell(value: Any) -> str:
    """
    Prevents CSV Formula Injection / DDE vulnerabilities by escaping leading formula triggers.
    """
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{text}"
    return text


def export_job_applications_to_csv(student_id: str) -> str:
    """
    Exports a student's tracked job applications as a CSV string.
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "Application ID",
        "Company Name",
        "Job Title / Role",
        "Application Status",
        "Applied Date",
        "Location",
        "Job Type",
        "Notes",
        "Created At"
    ])

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, company_name, role_title, status, application_date, location, job_type, notes, created_at
            FROM job_applications
            WHERE student_id = ?
            ORDER BY application_date DESC
            """,
            (student_id,)
        )
        rows = cursor.fetchall()
        for r in rows:
            writer.writerow([
                sanitize_csv_cell(r["id"]),
                sanitize_csv_cell(r["company_name"]),
                sanitize_csv_cell(r["role_title"]),
                sanitize_csv_cell(r["status"]),
                sanitize_csv_cell(r["application_date"]),
                sanitize_csv_cell(r["location"]),
                sanitize_csv_cell(r["job_type"]),
                sanitize_csv_cell(r["notes"]),
                sanitize_csv_cell(r["created_at"])
            ])
    except Exception as e:
        logger.warning(f"Error querying job_applications for export: {e}")
    finally:
        conn.close()

    return output.getvalue()


def export_mock_interviews_to_csv(student_id: str) -> str:
    """
    Exports detailed questions and answer evaluations from a student's mock interviews.
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "Interview ID",
        "Target Company",
        "Question Index",
        "Question Type",
        "Question",
        "Student Answer",
        "Score",
        "Evaluator Feedback",
        "Completed"
    ])

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT i.id, i.questions_json, i.answers_json, i.completed, a.company_name
            FROM interviews i
            JOIN analyses a ON i.analysis_id = a.id
            WHERE a.student_id = ?
            ORDER BY a.created_at DESC
            """,
            (student_id,)
        )
        rows = cursor.fetchall()
        for r in rows:
            interview_id = r["id"]
            company = r["company_name"] or "General Mock"
            completed = "Yes" if r["completed"] else "In Progress"
            
            try:
                questions = json.loads(r["questions_json"] or "[]")
            except Exception:
                questions = []

            try:
                answers = json.loads(r["answers_json"] or "[]")
            except Exception:
                answers = []

            for idx, q in enumerate(questions):
                q_text = q if isinstance(q, str) else q.get("question", "")
                q_type = q.get("type", "Technical") if isinstance(q, dict) else "Technical"
                
                ans_data = answers[idx] if idx < len(answers) else {}
                ans_text = ans_data.get("answer", "") if isinstance(ans_data, dict) else ""
                eval_data = ans_data.get("evaluation", {}) if isinstance(ans_data, dict) else {}
                score = eval_data.get("score") or eval_data.get("technical_accuracy") or ""
                feedback = eval_data.get("feedback") or eval_data.get("general_feedback") or ""

                writer.writerow([
                    sanitize_csv_cell(interview_id),
                    sanitize_csv_cell(company),
                    sanitize_csv_cell(idx + 1),
                    sanitize_csv_cell(q_type),
                    sanitize_csv_cell(q_text),
                    sanitize_csv_cell(ans_text),
                    sanitize_csv_cell(score),
                    sanitize_csv_cell(feedback),
                    sanitize_csv_cell(completed)
                ])
    finally:
        conn.close()

    return output.getvalue()


def export_preparation_notes_to_csv(student_id: str) -> str:
    """
    Exports a student's personal placement preparation and review notes.
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "Note ID",
        "Topic / Title",
        "Category",
        "Tags",
        "Note Content",
        "Created At"
    ])

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, category, tags, content, created_at
            FROM preparation_notes
            WHERE student_id = ?
            ORDER BY created_at DESC
            """,
            (student_id,)
        )
        rows = cursor.fetchall()
        for r in rows:
            writer.writerow([
                sanitize_csv_cell(r["id"]),
                sanitize_csv_cell(r["title"]),
                sanitize_csv_cell(r["category"]),
                sanitize_csv_cell(r["tags"]),
                sanitize_csv_cell(r["content"]),
                sanitize_csv_cell(r["created_at"])
            ])
    except Exception as e:
        logger.warning(f"Error querying preparation_notes for export: {e}")
    finally:
        conn.close()

    return output.getvalue()


def export_coding_practice_to_csv(student_id: str) -> str:
    """
    Exports a student's coding practice problem submissions.
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "Submission ID",
        "Problem Title",
        "Target Company",
        "Language",
        "Status",
        "Score",
        "Tests Passed",
        "Total Tests",
        "Submitted At"
    ])

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, question_title, company_name, language, passed, score, tests_passed, total_tests, submitted_at
            FROM coding_submissions
            WHERE student_id = ?
            ORDER BY submitted_at DESC
            """,
            (student_id,)
        )
        rows = cursor.fetchall()
        for r in rows:
            passed_status = "Passed" if r["passed"] else "Failed"
            writer.writerow([
                sanitize_csv_cell(r["id"]),
                sanitize_csv_cell(r["question_title"]),
                sanitize_csv_cell(r["company_name"]),
                sanitize_csv_cell(r["language"]),
                sanitize_csv_cell(passed_status),
                sanitize_csv_cell(r["score"]),
                sanitize_csv_cell(r["tests_passed"]),
                sanitize_csv_cell(r["total_tests"]),
                sanitize_csv_cell(r["submitted_at"])
            ])
    except Exception as e:
        logger.warning(f"Error querying coding_submissions for export: {e}")
    finally:
        conn.close()

    return output.getvalue()


SUPPORTED_EXPORT_TYPES = {
    "applications": (export_job_applications_to_csv, "job_applications.csv"),
    "interviews": (export_mock_interviews_to_csv, "mock_interviews.csv"),
    "notes": (export_preparation_notes_to_csv, "preparation_notes.csv"),
    "coding": (export_coding_practice_to_csv, "coding_practice.csv")
}


def get_csv_export(data_type: str, student_id: str) -> Tuple[str, str]:
    """
    Retrieves the CSV content and filename for a specified data export type.
    """
    normalized_type = str(data_type).strip().lower()
    if normalized_type not in SUPPORTED_EXPORT_TYPES:
        raise ValueError(f"Unsupported export type '{data_type}'. Supported: {list(SUPPORTED_EXPORT_TYPES.keys())}")
    
    exporter_fn, filename = SUPPORTED_EXPORT_TYPES[normalized_type]
    csv_content = exporter_fn(student_id)
    return csv_content, f"{student_id}_{filename}"
