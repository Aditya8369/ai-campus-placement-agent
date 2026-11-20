"""
Application Offer Decision Notes Service (#515)

Provides a private, structured decision matrix and notes notebook for job offers:
- Fields for work location, bond duration/terms, probation period, and travel expectations
- Professional growth rating (1-5), team culture notes, and primary reservations/concerns
- HR contact point, offer expiry date, joining date, and final acceptance/rejection rationale
- Complete privacy isolation ensuring offer decision notes are private to the student and never exposed in shared resumes
- Exportable decision comparison sheet
"""

import os
import json
import sqlite3
import datetime
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "instance", "placement_agent.db")


def _get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_offer_decision_notes_table():
    """Initializes schema for student job offer decision notes."""
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS application_offer_decision_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    application_id INTEGER,
                    company_name TEXT NOT NULL,
                    role_title TEXT NOT NULL,
                    ctc_lpa REAL DEFAULT 0.0,
                    work_location TEXT DEFAULT 'Hybrid / Remote',
                    bond_terms TEXT DEFAULT 'None',
                    bond_duration_months INTEGER DEFAULT 0,
                    probation_period_months INTEGER DEFAULT 3,
                    travel_required_pct INTEGER DEFAULT 0,
                    growth_potential_rating INTEGER DEFAULT 3, -- 1-5
                    work_life_balance_rating INTEGER DEFAULT 3, -- 1-5
                    culture_and_team_notes TEXT DEFAULT '',
                    concerns_and_risks TEXT DEFAULT '',
                    hr_contact_info TEXT DEFAULT '',
                    offer_deadline TEXT,
                    joining_date TEXT,
                    decision_status TEXT DEFAULT 'under_review', -- 'under_review', 'accepted', 'declined', 'deferred'
                    decision_rationale TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_aodn_user ON application_offer_decision_notes(user_id)")
    finally:
        conn.close()


init_offer_decision_notes_table()


class OfferDecisionNotesService:
    """Manages private offer evaluations and decision criteria."""

    @classmethod
    def save_offer_notes(
        cls,
        user_id: str,
        company_name: str,
        role_title: str,
        ctc_lpa: float,
        work_location: str = "Hybrid",
        bond_terms: str = "None",
        bond_duration_months: int = 0,
        probation_period_months: int = 3,
        travel_required_pct: int = 0,
        growth_potential_rating: int = 3,
        work_life_balance_rating: int = 3,
        culture_and_team_notes: str = "",
        concerns_and_risks: str = "",
        hr_contact_info: str = "",
        offer_deadline: Optional[str] = None,
        joining_date: Optional[str] = None,
        decision_status: str = "under_review",
        decision_rationale: str = "",
        application_id: Optional[int] = None,
        note_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Creates or updates private offer decision notes."""
        if not company_name or not role_title:
            raise ValueError("Company name and role title are required.")

        conn = _get_db_connection()
        try:
            with conn:
                if note_id:
                    conn.execute("""
                        UPDATE application_offer_decision_notes
                        SET company_name = ?, role_title = ?, ctc_lpa = ?, work_location = ?,
                            bond_terms = ?, bond_duration_months = ?, probation_period_months = ?,
                            travel_required_pct = ?, growth_potential_rating = ?, work_life_balance_rating = ?,
                            culture_and_team_notes = ?, concerns_and_risks = ?, hr_contact_info = ?,
                            offer_deadline = ?, joining_date = ?, decision_status = ?, decision_rationale = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ? AND user_id = ?
                    """, (
                        company_name, role_title, ctc_lpa, work_location,
                        bond_terms, bond_duration_months, probation_period_months,
                        travel_required_pct, growth_potential_rating, work_life_balance_rating,
                        culture_and_team_notes, concerns_and_risks, hr_contact_info,
                        offer_deadline, joining_date, decision_status, decision_rationale,
                        note_id, user_id
                    ))
                    record_id = note_id
                else:
                    cursor = conn.execute("""
                        INSERT INTO application_offer_decision_notes (
                            user_id, application_id, company_name, role_title, ctc_lpa, work_location,
                            bond_terms, bond_duration_months, probation_period_months, travel_required_pct,
                            growth_potential_rating, work_life_balance_rating, culture_and_team_notes,
                            concerns_and_risks, hr_contact_info, offer_deadline, joining_date,
                            decision_status, decision_rationale
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_id, application_id, company_name, role_title, ctc_lpa, work_location,
                        bond_terms, bond_duration_months, probation_period_months, travel_required_pct,
                        growth_potential_rating, work_life_balance_rating, culture_and_team_notes,
                        concerns_and_risks, hr_contact_info, offer_deadline, joining_date,
                        decision_status, decision_rationale
                    ))
                    record_id = cursor.lastrowid
            return cls.get_offer_note(user_id, record_id)
        finally:
            conn.close()

    @classmethod
    def get_offer_note(cls, user_id: str, note_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a single offer decision record."""
        conn = _get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM application_offer_decision_notes WHERE id = ? AND user_id = ?",
                (note_id, user_id)
            ).fetchone()
            return cls._row_to_dict(row) if row else None
        finally:
            conn.close()

    @classmethod
    def list_offer_notes(cls, user_id: str) -> List[Dict[str, Any]]:
        """Lists all private offer decision records for the student."""
        conn = _get_db_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM application_offer_decision_notes WHERE user_id = ? ORDER BY ctc_lpa DESC",
                (user_id,)
            ).fetchall()
            return [cls._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    @classmethod
    def delete_offer_note(cls, user_id: str, note_id: int) -> bool:
        """Deletes an offer decision note."""
        conn = _get_db_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM application_offer_decision_notes WHERE id = ? AND user_id = ?",
                    (note_id, user_id)
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    @classmethod
    def _row_to_dict(cls, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "application_id": row["application_id"],
            "company_name": row["company_name"],
            "role_title": row["role_title"],
            "ctc_lpa": row["ctc_lpa"],
            "work_location": row["work_location"],
            "bond_terms": row["bond_terms"],
            "bond_duration_months": row["bond_duration_months"],
            "probation_period_months": row["probation_period_months"],
            "travel_required_pct": row["travel_required_pct"],
            "growth_potential_rating": row["growth_potential_rating"],
            "work_life_balance_rating": row["work_life_balance_rating"],
            "culture_and_team_notes": row["culture_and_team_notes"],
            "concerns_and_risks": row["concerns_and_risks"],
            "hr_contact_info": row["hr_contact_info"],
            "offer_deadline": row["offer_deadline"],
            "joining_date": row["joining_date"],
            "decision_status": row["decision_status"],
            "decision_rationale": row["decision_rationale"],
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"])
        }
