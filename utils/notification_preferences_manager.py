"""
Notification preferences management service.
Handles student communication preferences across placement activity categories,
default fallbacks, channel preferences (email, in-app), frequency toggles,
and multi-tenant isolation.
"""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from typing import Any, Dict, List, Optional

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

# Canonical notification categories and descriptions
NOTIFICATION_CATEGORIES = {
    "application_status_updates": {
        "title": "Application Status Updates",
        "description": "Receive immediate alerts when your job application advances, changes stage, or is reviewed.",
        "default_enabled": True,
        "default_email": True,
        "default_in_app": True,
    },
    "interview_reminders": {
        "title": "Interview Reminders & Schedule Alerts",
        "description": "Get upcoming reminders 24h and 1h prior to scheduled mock or company placement interviews.",
        "default_enabled": True,
        "default_email": True,
        "default_in_app": True,
    },
    "placement_drive_alerts": {
        "title": "Campus Placement Drive Alerts",
        "description": "Notifications when new hiring drives or company listings matching your profile are posted.",
        "default_enabled": True,
        "default_email": True,
        "default_in_app": True,
    },
    "weekly_digest": {
        "title": "Weekly Preparation & Progress Digest",
        "description": "Weekly roundup summarizing your resume scores, mock interview drills, and preparation tasks.",
        "default_enabled": False,
        "default_email": True,
        "default_in_app": False,
    },
    "skill_gap_recommendations": {
        "title": "Skill Gap & Learning Recommendations",
        "description": "Periodic AI recommendations tailored to close skills missing from your target applications.",
        "default_enabled": True,
        "default_email": False,
        "default_in_app": True,
    },
}

VALID_FREQUENCIES = {"realtime", "daily_digest", "weekly_digest"}


def init_notification_preferences_table() -> None:
    """Initialize notification preferences table if it doesn't already exist."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS student_notification_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                category TEXT NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                email_enabled BOOLEAN NOT NULL DEFAULT 1,
                in_app_enabled BOOLEAN NOT NULL DEFAULT 1,
                frequency TEXT NOT NULL DEFAULT 'realtime',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, category)
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_notif_pref_user ON student_notification_preferences(user_id)"
        )
        conn.commit()
    finally:
        conn.close()


def get_student_preferences(user_id: Any) -> Dict[str, Any]:
    """
    Retrieve full notification preference configuration for a student.
    Merges stored preferences with defaults for any missing categories.
    """
    init_notification_preferences_table()
    user_str = str(user_id)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT category, enabled, email_enabled, in_app_enabled, frequency, updated_at
            FROM student_notification_preferences
            WHERE user_id = ?
            """,
            (user_str,),
        )
        rows = cursor.fetchall()
        stored: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            stored[row["category"]] = {
                "category": row["category"],
                "enabled": bool(row["enabled"]),
                "email_enabled": bool(row["email_enabled"]),
                "in_app_enabled": bool(row["in_app_enabled"]),
                "frequency": row["frequency"],
                "updated_at": row["updated_at"],
            }

        categories_out = []
        global_enabled = True
        has_any_disabled = False

        for cat_id, meta in NOTIFICATION_CATEGORIES.items():
            if cat_id in stored:
                cat_data = stored[cat_id]
                item = {
                    "category_id": cat_id,
                    "title": meta["title"],
                    "description": meta["description"],
                    "enabled": cat_data["enabled"],
                    "email_enabled": cat_data["email_enabled"],
                    "in_app_enabled": cat_data["in_app_enabled"],
                    "frequency": cat_data["frequency"],
                    "updated_at": cat_data["updated_at"],
                    "is_customized": True,
                }
            else:
                item = {
                    "category_id": cat_id,
                    "title": meta["title"],
                    "description": meta["description"],
                    "enabled": meta["default_enabled"],
                    "email_enabled": meta["default_email"],
                    "in_app_enabled": meta["default_in_app"],
                    "frequency": "realtime" if cat_id != "weekly_digest" else "weekly_digest",
                    "updated_at": None,
                    "is_customized": False,
                }
            if not item["enabled"]:
                has_any_disabled = True
            categories_out.append(item)

        return {
            "user_id": user_str,
            "preferences": categories_out,
            "master_toggle_all": not has_any_disabled,
            "available_frequencies": sorted(list(VALID_FREQUENCIES)),
            "total_categories": len(NOTIFICATION_CATEGORIES),
        }
    finally:
        conn.close()


def update_student_preferences(
    user_id: Any,
    preferences_payload: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Update or insert notification preferences for a student.
    Validates categories and frequency enums.
    """
    init_notification_preferences_table()
    if not isinstance(preferences_payload, list):
        raise ValueError("preferences must be a list of preference configurations")

    user_str = str(user_id)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        now_str = dt.datetime.utcnow().isoformat()

        for item in preferences_payload:
            category = item.get("category_id") or item.get("category")
            if not category or category not in NOTIFICATION_CATEGORIES:
                continue

            enabled = bool(item.get("enabled", True))
            email_enabled = bool(item.get("email_enabled", True))
            in_app_enabled = bool(item.get("in_app_enabled", True))
            frequency = item.get("frequency", "realtime")
            if frequency not in VALID_FREQUENCIES:
                frequency = "realtime"

            cursor.execute(
                """
                INSERT INTO student_notification_preferences 
                    (user_id, category, enabled, email_enabled, in_app_enabled, frequency, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, category) DO UPDATE SET
                    enabled = excluded.enabled,
                    email_enabled = excluded.email_enabled,
                    in_app_enabled = excluded.in_app_enabled,
                    frequency = excluded.frequency,
                    updated_at = excluded.updated_at
                """,
                (
                    user_str,
                    category,
                    1 if enabled else 0,
                    1 if email_enabled else 0,
                    1 if in_app_enabled else 0,
                    frequency,
                    now_str,
                ),
            )

        conn.commit()
    finally:
        conn.close()

    return get_student_preferences(user_str)


def set_master_notification_toggle(user_id: Any, enabled: bool) -> Dict[str, Any]:
    """Toggle all notifications on or off simultaneously."""
    init_notification_preferences_table()
    user_str = str(user_id)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        now_str = dt.datetime.utcnow().isoformat()
        flag = 1 if enabled else 0

        for cat_id in NOTIFICATION_CATEGORIES:
            cursor.execute(
                """
                INSERT INTO student_notification_preferences 
                    (user_id, category, enabled, email_enabled, in_app_enabled, frequency, updated_at)
                VALUES (?, ?, ?, ?, ?, 'realtime', ?)
                ON CONFLICT(user_id, category) DO UPDATE SET
                    enabled = excluded.enabled,
                    email_enabled = excluded.email_enabled,
                    in_app_enabled = excluded.in_app_enabled,
                    updated_at = excluded.updated_at
                """,
                (user_str, cat_id, flag, flag, flag, now_str),
            )
        conn.commit()
    finally:
        conn.close()

    return get_student_preferences(user_str)


def is_notification_allowed(
    user_id: Any,
    category: str,
    channel: str = "email",
) -> bool:
    """
    Check if a notification of a given category and channel should be sent to the user.
    """
    if category not in NOTIFICATION_CATEGORIES:
        return True

    init_notification_preferences_table()
    user_str = str(user_id)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT enabled, email_enabled, in_app_enabled
            FROM student_notification_preferences
            WHERE user_id = ? AND category = ?
            """,
            (user_str, category),
        )
        row = cursor.fetchone()
        if not row:
            # Fallback to category defaults
            default_meta = NOTIFICATION_CATEGORIES[category]
            if not default_meta["default_enabled"]:
                return False
            if channel == "email":
                return default_meta["default_email"]
            elif channel == "in_app":
                return default_meta["default_in_app"]
            return True

        if not bool(row["enabled"]):
            return False

        if channel == "email":
            return bool(row["email_enabled"])
        elif channel == "in_app":
            return bool(row["in_app_enabled"])

        return True
    finally:
        conn.close()
