"""
Private Job Offers Comparison Service (#330).

Allows students to record, manage, and privately compare job offers side-by-side:
- Key parameters:
  1. Base Salary & Guaranteed Annual Compensation
  2. Signing Bonus & Performance Bonuses
  3. Equity / Stock Options / RSUs
  4. Work Arrangement (Remote, Hybrid, On-site) & Location
  5. Benefits (Health Insurance, Relocation, Learning Stipend, 401k/PF match)
  6. Response / Offer Acceptance Deadline
  7. Personal Notes & Tradeoffs

Privacy & Multi-Tenancy:
- Strictly private: Offers are tied to student_id and never visible to other candidates or campus recruiters.
- Side-by-side metric comparison, annualized total compensation calculator, and deadline alerts.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from utils.database import get_db_connection

logger = logging.getLogger(__name__)


def init_job_offers_table():
    """Initializes the job offers table if missing."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS student_job_offers (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                company_name TEXT NOT NULL,
                role_title TEXT NOT NULL,
                location TEXT,
                work_mode TEXT DEFAULT 'Hybrid',
                base_salary REAL NOT NULL,
                bonus REAL DEFAULT 0,
                equity_annual REAL DEFAULT 0,
                benefits_summary TEXT,
                deadline_date TEXT,
                status TEXT DEFAULT 'Pending Decision',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def create_job_offer(
    student_id: str,
    company_name: str,
    role_title: str,
    base_salary: float,
    bonus: float = 0.0,
    equity_annual: float = 0.0,
    location: str = "Remote",
    work_mode: str = "Hybrid",
    benefits_summary: str = "",
    deadline_date: Optional[str] = None,
    notes: str = ""
) -> Dict[str, Any]:
    """Creates a new private job offer record."""
    if not student_id:
        raise PermissionError("Authentication required.")
    if not company_name or not role_title:
        raise ValueError("Company name and role title are required.")

    init_job_offers_table()
    offer_id = f"off-{uuid.uuid4().hex[:12]}"
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO student_job_offers (
                id, student_id, company_name, role_title, location, work_mode,
                base_salary, bonus, equity_annual, benefits_summary, deadline_date, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                offer_id,
                student_id,
                company_name.strip(),
                role_title.strip(),
                (location or "Remote").strip(),
                (work_mode or "Hybrid").strip(),
                float(base_salary),
                float(bonus),
                float(equity_annual),
                (benefits_summary or "").strip(),
                (deadline_date or "").strip() or None,
                (notes or "").strip()
            )
        )
        conn.commit()
    finally:
        conn.close()

    return {"success": True, "offer_id": offer_id, "message": "Offer saved successfully."}


def get_student_offers(student_id: str) -> List[Dict[str, Any]]:
    """Retrieves all offers owned by the student."""
    init_job_offers_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM student_job_offers
            WHERE student_id = ?
            ORDER BY created_at DESC
            """,
            (student_id,)
        )
        rows = cursor.fetchall()
        offers = []
        for r in rows:
            rec = dict(r)
            total_comp = round(rec["base_salary"] + rec["bonus"] + rec["equity_annual"], 2)
            rec["total_compensation"] = total_comp
            offers.append(rec)
        return offers
    finally:
        conn.close()


def compare_job_offers(student_id: str, offer_ids: List[str]) -> Dict[str, Any]:
    """
    Generates a side-by-side comparison of selected job offers.
    """
    if not offer_ids or len(offer_ids) < 2:
        raise ValueError("At least two offers are required for comparison.")

    all_offers = get_student_offers(student_id)
    offer_map = {o["id"]: o for o in all_offers}

    selected = []
    for oid in offer_ids:
        if oid in offer_map:
            selected.append(offer_map[oid])
        else:
            raise KeyError(f"Offer '{oid}' not found or access denied.")

    # Calculate metrics
    highest_comp = max(selected, key=lambda x: x["total_compensation"])
    highest_base = max(selected, key=lambda x: x["base_salary"])

    comparison_matrix = {
        "attributes": [
            {"label": "Company", "key": "company_name"},
            {"label": "Role", "key": "role_title"},
            {"label": "Work Mode", "key": "work_mode"},
            {"label": "Location", "key": "location"},
            {"label": "Base Salary", "key": "base_salary", "format": "currency"},
            {"label": "Bonus", "key": "bonus", "format": "currency"},
            {"label": "Equity / RSUs", "key": "equity_annual", "format": "currency"},
            {"label": "Total Compensation", "key": "total_compensation", "format": "currency"},
            {"label": "Decision Deadline", "key": "deadline_date"},
            {"label": "Benefits & Perks", "key": "benefits_summary"},
            {"label": "Notes", "key": "notes"}
        ],
        "offers": selected,
        "insights": {
            "top_total_comp": highest_comp["company_name"],
            "top_base_salary": highest_base["company_name"],
            "count": len(selected)
        }
    }

    return {"success": True, "comparison": comparison_matrix}
