"""
Saved Internships Service (#357).

Allows students to save internships for later review, attach personal notes,
filter/browse saved opportunities, and optionally convert a saved internship
into an active job application without automatic creation.
Guarantees strict multi-tenant student privacy.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from utils.database import get_db_connection

logger = logging.getLogger(__name__)


def init_saved_internships_table():
    """Initializes the saved internships table if missing."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_internships (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                internship_id TEXT,
                company_name TEXT NOT NULL,
                title TEXT NOT NULL,
                location TEXT,
                stipend TEXT,
                deadline TEXT,
                url TEXT,
                notes TEXT,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def save_internship(
    student_id: str,
    company_name: str,
    title: str,
    internship_id: Optional[str] = None,
    location: Optional[str] = "Remote",
    stipend: Optional[str] = None,
    deadline: Optional[str] = None,
    url: Optional[str] = None,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Saves an internship for the student with optional personal note.
    """
    if not student_id:
        raise PermissionError("Authentication required to save internships.")
    if not company_name or not title:
        raise ValueError("Company name and internship title are required.")

    init_saved_internships_table()
    saved_id = f"si-{uuid.uuid4().hex[:12]}"

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Check if already saved by this student
        if internship_id:
            cursor.execute(
                """
                SELECT id FROM saved_internships
                WHERE student_id = ? AND internship_id = ?
                """,
                (student_id, str(internship_id))
            )
            existing = cursor.fetchone()
            if existing:
                # Update existing note if provided
                if notes is not None:
                    cursor.execute(
                        """
                        UPDATE saved_internships
                        SET notes = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (notes.strip(), existing["id"])
                    )
                    conn.commit()
                return {
                    "success": True,
                    "saved_id": existing["id"],
                    "message": "Internship already saved; updated notes."
                }

        cursor.execute(
            """
            INSERT INTO saved_internships (
                id, student_id, internship_id, company_name, title,
                location, stipend, deadline, url, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                saved_id,
                student_id,
                internship_id,
                company_name.strip(),
                title.strip(),
                (location or "Remote").strip(),
                (stipend or "").strip(),
                (deadline or "").strip(),
                (url or "").strip(),
                (notes or "").strip()
            )
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "success": True,
        "saved_id": saved_id,
        "message": "Internship saved successfully for later review."
    }


def get_saved_internships(student_id: str) -> List[Dict[str, Any]]:
    """
    Retrieves all internships saved by the authenticated student.
    """
    if not student_id:
        return []

    init_saved_internships_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM saved_internships
            WHERE student_id = ?
            ORDER BY saved_at DESC
            """,
            (student_id,)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def remove_saved_internship(student_id: str, saved_id: str) -> bool:
    """
    Removes a saved internship record owned by the student.
    """
    init_saved_internships_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM saved_internships
            WHERE id = ? AND student_id = ?
            """,
            (saved_id, student_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def update_saved_internship_note(student_id: str, saved_id: str, notes: str) -> bool:
    """
    Updates the personal note attached to a saved internship.
    """
    init_saved_internships_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE saved_internships
            SET notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND student_id = ?
            """,
            (notes.strip(), saved_id, student_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def convert_saved_internship_to_application(
    student_id: str,
    saved_id: str,
    status: str = "Applied"
) -> Dict[str, Any]:
    """
    Allows a user to explicitly convert a saved internship into an active tracked job application.
    Does NOT automatically delete the saved item unless requested.
    """
    init_saved_internships_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM saved_internships WHERE id = ? AND student_id = ?",
            (saved_id, student_id)
        )
        item = cursor.fetchone()
        if not item:
            raise KeyError("Saved internship not found or access denied.")

        app_id = f"app-from-int-{uuid.uuid4().hex[:8]}"
        cursor.execute(
            """
            INSERT INTO job_applications (
                id, student_id, company_name, role_title, status,
                application_date, location, job_url, notes
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_DATE, ?, ?, ?)
            """,
            (
                app_id,
                student_id,
                item["company_name"],
                item["title"],
                status,
                item["location"],
                item["url"],
                f"Converted from saved internship. Personal notes: {item['notes'] or 'None'}"
            )
        )
        conn.commit()
        return {
            "success": True,
            "application_id": app_id,
            "company_name": item["company_name"],
            "role_title": item["title"]
        }
    finally:
        conn.close()
