"""
Private Multi-Domain Saved Data Search Service (#324).

Allows students to privately search across all their saved placement preparation information:
1. Resume Analyses (target roles, company names, matching skills, gaps).
2. Mock Interview Q&As (question text, student answers, feedback).
3. Tracked Job Applications (company, role title, status, notes, location).
4. Personal Preparation Notes (title, category, tags, markdown contents).
5. Coding Practice Submissions (question title, language, feedback).

Security & Privacy:
- Strict student isolation: search is parameterized by student_id and never accesses or leaks another user's saved data.
- SQL injection safe parameterized queries with sanitized substring matching.
- Highlights matching snippets for responsive, fast discovery.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from utils.database import get_db_connection

logger = logging.getLogger(__name__)


def highlight_snippet(text: str, query: str, max_chars: int = 150) -> str:
    """
    Extracts a contextual snippet containing the search query with HTML highlighting.
    """
    if not text:
        return ""
    clean_text = str(text)
    if not query:
        return clean_text[:max_chars]

    pattern = re.compile(re.escape(query), re.IGNORECASE)
    match = pattern.search(clean_text)
    if not match:
        return clean_text[:max_chars] + ("..." if len(clean_text) > max_chars else "")

    start = max(0, match.start() - 40)
    end = min(len(clean_text), match.end() + 80)
    snippet = clean_text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(clean_text):
        snippet = snippet + "..."

    return pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", snippet)


def search_student_saved_data(
    student_id: str,
    query: str,
    filter_category: Optional[str] = None,
    limit: int = 30
) -> Dict[str, Any]:
    """
    Executes a private cross-domain search across the student's personal saved records.
    """
    if not student_id:
        return {"success": False, "error": "Authentication required to search personal data.", "results": []}

    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return {"success": True, "query": "", "total_count": 0, "results": []}

    search_param = f"%{cleaned_query}%"
    results: List[Dict[str, Any]] = []

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 1. Search Resume Analyses
        if not filter_category or filter_category.lower() in ("all", "analyses", "resumes"):
            cursor.execute(
                """
                SELECT id, company_name, job_description, resume_filename, results_json, created_at
                FROM analyses
                WHERE student_id = ?
                  AND (company_name LIKE ? OR job_description LIKE ? OR results_json LIKE ?)
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (student_id, search_param, search_param, search_param, limit)
            )
            for r in cursor.fetchall():
                results.append({
                    "id": r["id"],
                    "category": "Analysis",
                    "title": f"Resume Analysis: {r['company_name'] or 'Target Role'}",
                    "date": r["created_at"],
                    "url": f"/dashboard/{r['id']}",
                    "snippet": highlight_snippet(r["job_description"] or r["results_json"], cleaned_query)
                })

        # 2. Search Job Applications
        if not filter_category or filter_category.lower() in ("all", "applications", "jobs"):
            cursor.execute(
                """
                SELECT id, company_name, role_title, status, location, notes, application_date
                FROM job_applications
                WHERE student_id = ?
                  AND (company_name LIKE ? OR role_title LIKE ? OR notes LIKE ? OR location LIKE ?)
                ORDER BY application_date DESC
                LIMIT ?
                """,
                (student_id, search_param, search_param, search_param, search_param, limit)
            )
            for r in cursor.fetchall():
                results.append({
                    "id": r["id"],
                    "category": "Application",
                    "title": f"{r['role_title']} at {r['company_name']}",
                    "date": r["application_date"] or "Recent",
                    "url": "/applications",
                    "snippet": highlight_snippet(f"Status: {r['status']} | Notes: {r['notes']}", cleaned_query)
                })

        # 3. Search Mock Interviews
        if not filter_category or filter_category.lower() in ("all", "interviews", "mock"):
            cursor.execute(
                """
                SELECT i.id, i.analysis_id, i.questions_json, i.answers_json, a.company_name, a.created_at
                FROM interviews i
                JOIN analyses a ON i.analysis_id = a.id
                WHERE a.student_id = ?
                  AND (i.questions_json LIKE ? OR i.answers_json LIKE ? OR a.company_name LIKE ?)
                ORDER BY a.created_at DESC
                LIMIT ?
                """,
                (student_id, search_param, search_param, search_param, limit)
            )
            for r in cursor.fetchall():
                match_text = (r["questions_json"] or "") + " " + (r["answers_json"] or "")
                results.append({
                    "id": r["id"],
                    "category": "Interview",
                    "title": f"Mock Interview: {r['company_name'] or 'General'}",
                    "date": r["created_at"] or "Recent",
                    "url": f"/interview/{r['analysis_id']}",
                    "snippet": highlight_snippet(match_text, cleaned_query)
                })

        # 4. Search Preparation Notes
        if not filter_category or filter_category.lower() in ("all", "notes"):
            try:
                cursor.execute(
                    """
                    SELECT id, title, category, tags, content, created_at
                    FROM preparation_notes
                    WHERE student_id = ?
                      AND (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (student_id, search_param, search_param, search_param, limit)
                )
                for r in cursor.fetchall():
                    results.append({
                        "id": r["id"],
                        "category": "Note",
                        "title": f"Note: {r['title']}",
                        "date": r["created_at"],
                        "url": "/notes",
                        "snippet": highlight_snippet(r["content"], cleaned_query)
                    })
            except Exception as e:
                logger.debug(f"Notes search skipped: {e}")

        # 5. Search Coding Submissions
        if not filter_category or filter_category.lower() in ("all", "coding"):
            try:
                cursor.execute(
                    """
                    SELECT id, question_title, company_name, language, feedback, submitted_at
                    FROM coding_submissions
                    WHERE student_id = ?
                      AND (question_title LIKE ? OR feedback LIKE ? OR company_name LIKE ?)
                    ORDER BY submitted_at DESC
                    LIMIT ?
                    """,
                    (student_id, search_param, search_param, search_param, limit)
                )
                for r in cursor.fetchall():
                    results.append({
                        "id": r["id"],
                        "category": "Coding",
                        "title": f"Code Solution: {r['question_title']} ({r['language']})",
                        "date": r["submitted_at"],
                        "url": "/coding-practice",
                        "snippet": highlight_snippet(r["feedback"] or r["question_title"], cleaned_query)
                    })
            except Exception as e:
                logger.debug(f"Coding search skipped: {e}")

    finally:
        conn.close()

    return {
        "success": True,
        "query": cleaned_query,
        "filter": filter_category or "all",
        "total_count": len(results),
        "results": results[:limit]
    }
