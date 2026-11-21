"""
Custom Resume Comparison Labels Service (#523)

Enables students to assign custom nicknames, revision tags, and comparison labels to uploaded resumes:
- Friendly identifiers (e.g. "Google Tailored v2", "Fintech Quant Edition", "Pre-Review Draft")
- Change notes explaining what was altered between versions (e.g. "Added distributed systems metrics")
- Color badge coding (blue, green, purple, amber, rose)
- Isolation from AI prompts: custom label notes are kept local to comparison views and never contaminate raw text sent to Gemini ATS analyzers
- Multi-tenant student isolation with SQLite persistence
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


def init_resume_comparison_labels_table():
    """Initializes schema for custom resume version labels."""
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS resume_version_custom_labels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    resume_id TEXT NOT NULL,
                    custom_label TEXT NOT NULL, -- e.g. 'Google Tailored v2'
                    color_tag TEXT DEFAULT 'primary', -- 'primary', 'success', 'warning', 'info', 'dark'
                    change_notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, resume_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rvcl_user ON resume_version_custom_labels(user_id, resume_id)")
    finally:
        conn.close()


init_resume_comparison_labels_table()


class ResumeComparisonLabelsService:
    """Manages custom nicknames and change notes for resume versions."""

    VALID_COLOR_TAGS = ["primary", "success", "warning", "info", "secondary", "danger", "dark"]

    @classmethod
    def set_label(
        cls,
        user_id: str,
        resume_id: str,
        custom_label: str,
        color_tag: str = "primary",
        change_notes: str = ""
    ) -> Dict[str, Any]:
        """Assigns or updates a custom label and change notes for a resume version."""
        lbl = custom_label.strip()
        if not lbl:
            raise ValueError("Custom label cannot be empty.")

        c_tag = color_tag.lower().strip() if color_tag else "primary"
        if c_tag not in cls.VALID_COLOR_TAGS:
            c_tag = "primary"

        conn = _get_db_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO resume_version_custom_labels (
                        user_id, resume_id, custom_label, color_tag, change_notes, updated_at
                    ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id, resume_id) DO UPDATE SET
                        custom_label = excluded.custom_label,
                        color_tag = excluded.color_tag,
                        change_notes = excluded.change_notes,
                        updated_at = CURRENT_TIMESTAMP
                """, (user_id, resume_id, lbl, c_tag, change_notes.strip()))

            return cls.get_label(user_id, resume_id)
        finally:
            conn.close()

    @classmethod
    def get_label(cls, user_id: str, resume_id: str) -> Dict[str, Any]:
        """Retrieves custom label for a resume, falling back to default identifier if unset."""
        conn = _get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM resume_version_custom_labels WHERE user_id = ? AND resume_id = ?",
                (user_id, resume_id)
            ).fetchone()

            if row:
                return {
                    "resume_id": row["resume_id"],
                    "custom_label": row["custom_label"],
                    "color_tag": row["color_tag"],
                    "change_notes": row["change_notes"],
                    "is_custom": True,
                    "updated_at": str(row["updated_at"])
                }

            return {
                "resume_id": resume_id,
                "custom_label": f"Resume ({resume_id[:8]})" if len(resume_id) > 8 else f"Resume {resume_id}",
                "color_tag": "secondary",
                "change_notes": "",
                "is_custom": False,
                "updated_at": None
            }
        finally:
            conn.close()

    @classmethod
    def list_user_labels(cls, user_id: str) -> List[Dict[str, Any]]:
        """Lists all custom labels defined by student."""
        conn = _get_db_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM resume_version_custom_labels WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,)
            ).fetchall()
            return [
                {
                    "resume_id": r["resume_id"],
                    "custom_label": r["custom_label"],
                    "color_tag": r["color_tag"],
                    "change_notes": r["change_notes"],
                    "is_custom": True,
                    "updated_at": str(r["updated_at"])
                }
                for r in rows
            ]
        finally:
            conn.close()

    @classmethod
    def delete_label(cls, user_id: str, resume_id: str) -> bool:
        """Removes custom label, reverting to default filename/identifier."""
        conn = _get_db_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM resume_version_custom_labels WHERE user_id = ? AND resume_id = ?",
                    (user_id, resume_id)
                )
                return cursor.rowcount > 0
        finally:
            conn.close()
