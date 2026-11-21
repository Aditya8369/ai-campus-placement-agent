"""
Recruiter Contact & Follow-Up Tracking Service (#516)

Tracks communications, outreach touchpoints, and scheduled follow-ups with corporate recruiters:
- Stores recruiter identity: name, corporate email, phone, LinkedIn profile URL, and company affiliation
- Tracks interaction touchpoints: channel (Email, LinkedIn InMail, On-campus talk, Phone call)
- Follow-up scheduling with automatic overdue alerts and reminder dates
- Status states: 'initial_outreach', 'awaiting_reply', 'interview_scheduled', 'offer_stage', 'closed'
- Multi-tenant student isolation with SQLite persistence
"""

import os
import re
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


def init_recruiter_contacts_table():
    """Initializes schema for recruiter tracking."""
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recruiter_contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    recruiter_name TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    email TEXT,
                    phone TEXT,
                    linkedin_url TEXT,
                    role_or_department TEXT DEFAULT 'Talent Acquisition',
                    last_contacted_date TEXT,
                    next_followup_date TEXT,
                    interaction_channel TEXT DEFAULT 'LinkedIn', -- 'Email', 'LinkedIn', 'Campus', 'Call'
                    status TEXT DEFAULT 'awaiting_reply', -- 'initial_outreach', 'awaiting_reply', 'in_discussion', 'closed'
                    notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_user ON recruiter_contacts(user_id, next_followup_date)")
    finally:
        conn.close()


init_recruiter_contacts_table()


class RecruiterContactService:
    """Manages recruiter directory and scheduled follow-ups."""

    @classmethod
    def save_contact(
        cls,
        user_id: str,
        recruiter_name: str,
        company_name: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        linkedin_url: Optional[str] = None,
        role_or_department: str = "Talent Acquisition",
        last_contacted_date: Optional[str] = None,
        next_followup_date: Optional[str] = None,
        interaction_channel: str = "LinkedIn",
        status: str = "awaiting_reply",
        notes: str = "",
        contact_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Creates or updates a recruiter contact record."""
        name = recruiter_name.strip()
        comp = company_name.strip()
        if not name or not comp:
            raise ValueError("Recruiter name and company name are required.")

        # Email format validation if provided
        if email and email.strip():
            email = email.strip()
            if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
                raise ValueError("Invalid email format.")

        conn = _get_db_connection()
        try:
            with conn:
                if contact_id:
                    conn.execute("""
                        UPDATE recruiter_contacts
                        SET recruiter_name = ?, company_name = ?, email = ?, phone = ?,
                            linkedin_url = ?, role_or_department = ?, last_contacted_date = ?,
                            next_followup_date = ?, interaction_channel = ?, status = ?,
                            notes = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ? AND user_id = ?
                    """, (
                        name, comp, email, phone, linkedin_url, role_or_department,
                        last_contacted_date, next_followup_date, interaction_channel,
                        status, notes, contact_id, user_id
                    ))
                    record_id = contact_id
                else:
                    cursor = conn.execute("""
                        INSERT INTO recruiter_contacts (
                            user_id, recruiter_name, company_name, email, phone, linkedin_url,
                            role_or_department, last_contacted_date, next_followup_date,
                            interaction_channel, status, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_id, name, comp, email, phone, linkedin_url,
                        role_or_department, last_contacted_date, next_followup_date,
                        interaction_channel, status, notes
                    ))
                    record_id = cursor.lastrowid
            return cls.get_contact(user_id, record_id)
        finally:
            conn.close()

    @classmethod
    def get_contact(cls, user_id: str, contact_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a single recruiter record."""
        conn = _get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM recruiter_contacts WHERE id = ? AND user_id = ?",
                (contact_id, user_id)
            ).fetchone()
            return cls._row_to_dict(row) if row else None
        finally:
            conn.close()

    @classmethod
    def list_contacts(cls, user_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists contacts for student, optionally filtered by status."""
        conn = _get_db_connection()
        try:
            if status and status.lower() != "all":
                rows = conn.execute(
                    "SELECT * FROM recruiter_contacts WHERE user_id = ? AND status = ? ORDER BY next_followup_date ASC",
                    (user_id, status)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM recruiter_contacts WHERE user_id = ? ORDER BY next_followup_date ASC",
                    (user_id,)
                ).fetchall()
            return [cls._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    @classmethod
    def get_followup_reminders(cls, user_id: str) -> List[Dict[str, Any]]:
        """Returns recruiter contacts that have a follow-up due today or overdue."""
        today_str = datetime.date.today().isoformat()
        conn = _get_db_connection()
        try:
            rows = conn.execute("""
                SELECT * FROM recruiter_contacts
                WHERE user_id = ? AND next_followup_date IS NOT NULL AND next_followup_date <= ?
                AND status NOT IN ('closed', 'offer_stage')
                ORDER BY next_followup_date ASC
            """, (user_id, today_str)).fetchall()
            return [cls._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    @classmethod
    def delete_contact(cls, user_id: str, contact_id: int) -> bool:
        """Deletes a recruiter contact."""
        conn = _get_db_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM recruiter_contacts WHERE id = ? AND user_id = ?",
                    (contact_id, user_id)
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    @classmethod
    def _row_to_dict(cls, row: sqlite3.Row) -> Dict[str, Any]:
        today_str = datetime.date.today().isoformat()
        is_overdue = False
        if row["next_followup_date"] and row["next_followup_date"] < today_str and row["status"] not in ["closed", "offer_stage"]:
            is_overdue = True

        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "recruiter_name": row["recruiter_name"],
            "company_name": row["company_name"],
            "email": row["email"],
            "phone": row["phone"],
            "linkedin_url": row["linkedin_url"],
            "role_or_department": row["role_or_department"],
            "last_contacted_date": row["last_contacted_date"],
            "next_followup_date": row["next_followup_date"],
            "interaction_channel": row["interaction_channel"],
            "status": row["status"],
            "notes": row["notes"],
            "is_overdue": is_overdue,
            "created_at": str(row["created_at"])
        }
