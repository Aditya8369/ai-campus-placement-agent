"""
Interview Experience Multi-Dimensional Search & Filtering Service (#254)
========================================================================
Extends and empowers student community interview experience discovery with:
1. Multi-facet filtering:
   - Target Company (Google, Microsoft, Amazon, TCS, etc.)
   - Role / Job Title (Software Engineer, Data Scientist, Frontend Developer, etc.)
   - Year / Date range of interview (e.g. 2026, 2025, past 6 months)
   - Final Verdict (Offer, Rejected, Pending, Withdrawn)
   - Difficulty Level (Easy, Medium, Hard, Very Hard)
   - Round Category (Coding, System Design, HR / Behavioral, Managerial)
2. Configurable Sorting:
   - date_desc (newest interview first - default)
   - date_asc (oldest interview first)
   - difficulty_desc (hardest first)
   - difficulty_asc (easiest first)
   - company_asc (alphabetical by company)
3. Full-Text Search:
   - Scans company, role, tips, question summaries, and preparation guidance.
4. Aggregated Filter Metatags:
   - Returns unique company list, roles, verdict distribution, and difficulty levels
     for rich dynamic dropdowns in the frontend.
"""

import sqlite3
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

DIFFICULTY_WEIGHTS = {
    "easy": 1,
    "medium": 2,
    "hard": 3,
    "very hard": 4
}


def search_and_filter_interview_experiences(
    company_name: Optional[str] = None,
    role_title: Optional[str] = None,
    verdict: Optional[str] = None,
    difficulty: Optional[str] = None,
    category_filter: Optional[str] = None,
    year_filter: Optional[str] = None,
    search_query: Optional[str] = None,
    sort_by: str = "date_desc",
    page: int = 1,
    page_size: int = 20,
    include_reported: bool = False
) -> Dict[str, Any]:
    """
    Executes a multi-parameter search and filter query over peer interview experiences.
    Returns paginated list of experiences, total matching count, and metadata facet options.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        conditions = []
        params: List[Any] = []

        if not include_reported:
            conditions.append("reported_flag = 0")

        # Company filter
        if company_name and company_name.strip() and company_name.strip().lower() not in ("all", "any"):
            conditions.append("LOWER(company_name) = LOWER(?)")
            params.append(company_name.strip())

        # Role filter
        if role_title and role_title.strip() and role_title.strip().lower() not in ("all", "any"):
            conditions.append("LOWER(role_title) LIKE ?")
            params.append(f"%{role_title.strip().lower()}%")

        # Verdict filter
        if verdict and verdict.strip() and verdict.strip().lower() not in ("all", "any"):
            conditions.append("LOWER(overall_verdict) = LOWER(?)")
            params.append(verdict.strip())

        # Difficulty filter
        if difficulty and difficulty.strip() and difficulty.strip().lower() not in ("all", "any"):
            conditions.append("LOWER(difficulty_level) = LOWER(?)")
            params.append(difficulty.strip())

        # Year filter
        if year_filter and year_filter.strip() and year_filter.strip().lower() not in ("all", "any"):
            conditions.append("interview_date LIKE ?")
            params.append(f"{year_filter.strip()}%")

        # Text search (company, role, tips)
        if search_query and search_query.strip():
            sq = f"%{search_query.strip().lower()}%"
            conditions.append("(LOWER(company_name) LIKE ? OR LOWER(role_title) LIKE ? OR LOWER(tips_and_preparation) LIKE ? OR rounds_json LIKE ?)")
            params.extend([sq, sq, sq, sq])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Sorting logic
        order_by = "ORDER BY interview_date DESC, created_at DESC"
        if sort_by == "date_asc":
            order_by = "ORDER BY interview_date ASC, created_at ASC"
        elif sort_by == "company_asc":
            order_by = "ORDER BY company_name ASC, interview_date DESC"
        elif sort_by == "difficulty_desc":
            order_by = "ORDER BY CASE LOWER(difficulty_level) WHEN 'very hard' THEN 4 WHEN 'hard' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC, interview_date DESC"
        elif sort_by == "difficulty_asc":
            order_by = "ORDER BY CASE LOWER(difficulty_level) WHEN 'easy' THEN 1 WHEN 'medium' THEN 2 WHEN 'hard' THEN 3 ELSE 4 END ASC, interview_date DESC"

        query = f"SELECT * FROM interview_experiences {where_clause} {order_by}"
        cursor.execute(query, params)
        all_matching_rows = cursor.fetchall()

        # Parse JSON and post-filter by round category if requested
        experiences = []
        for row in all_matching_rows:
            rec = dict(row)
            try:
                rec["rounds"] = json.loads(rec.get("rounds_json") or "[]")
            except Exception:
                rec["rounds"] = []

            if category_filter and category_filter.strip() and category_filter.strip().lower() not in ("all", "any"):
                target_cat = category_filter.strip().lower()
                has_cat = any(
                    target_cat in r.get("round_type", "").lower() or
                    target_cat in r.get("round_name", "").lower() or
                    target_cat in r.get("category", "").lower()
                    for r in rec["rounds"]
                )
                if not has_cat:
                    continue

            experiences.append(rec)

        total_count = len(experiences)

        # Pagination
        p = max(1, page)
        ps = max(1, min(page_size, 100))
        start_idx = (p - 1) * ps
        end_idx = start_idx + ps
        paginated_items = experiences[start_idx:end_idx]

        return {
            "total_matches": total_count,
            "page": p,
            "page_size": ps,
            "total_pages": (total_count + ps - 1) // ps if total_count > 0 else 1,
            "experiences": paginated_items
        }


def get_interview_filter_facets() -> Dict[str, Any]:
    """
    Returns unique aggregations across all published experiences
    to populate dynamic dropdowns and search facets.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Distinct companies
        cursor.execute("""
            SELECT DISTINCT company_name, COUNT(*) as count
            FROM interview_experiences
            WHERE reported_flag = 0
            GROUP BY company_name
            ORDER BY count DESC, company_name ASC
        """)
        companies = [{"name": r["company_name"], "count": r["count"]} for r in cursor.fetchall()]

        # Distinct verdicts
        cursor.execute("""
            SELECT DISTINCT overall_verdict, COUNT(*) as count
            FROM interview_experiences
            WHERE reported_flag = 0
            GROUP BY overall_verdict
            ORDER BY count DESC
        """)
        verdicts = [{"verdict": r["overall_verdict"], "count": r["count"]} for r in cursor.fetchall()]

        # Distinct difficulties
        cursor.execute("""
            SELECT DISTINCT difficulty_level, COUNT(*) as count
            FROM interview_experiences
            WHERE reported_flag = 0
            GROUP BY difficulty_level
            ORDER BY count DESC
        """)
        difficulties = [{"difficulty": r["difficulty_level"], "count": r["count"]} for r in cursor.fetchall()]

        # Distinct roles
        cursor.execute("""
            SELECT DISTINCT role_title, COUNT(*) as count
            FROM interview_experiences
            WHERE reported_flag = 0
            GROUP BY role_title
            ORDER BY count DESC
            LIMIT 25
        """)
        roles = [{"role": r["role_title"], "count": r["count"]} for r in cursor.fetchall()]

        return {
            "companies": companies,
            "verdicts": verdicts,
            "difficulties": difficulties,
            "roles": roles,
            "sort_options": [
                {"key": "date_desc", "label": "Newest Interviews First"},
                {"key": "date_asc", "label": "Oldest Interviews First"},
                {"key": "difficulty_desc", "label": "Highest Difficulty First"},
                {"key": "difficulty_asc", "label": "Lowest Difficulty First"},
                {"key": "company_asc", "label": "Company (A-Z)"}
            ]
        }
