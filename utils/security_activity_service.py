"""
Security Activity & Audit Logging Service (#407).

Provides audit history for key account security events:
- Successful sign-ins
- Password changes / resets
- Email address modifications
- Account deletion requests
- Two-factor authentication (2FA) changes
- Session revocations

Security & Privacy Guarantees:
- Never stores or displays passwords, cleartext secrets, auth tokens, or private resume content.
- Anonymizes / masks IP addresses (e.g. 192.168.*** or 2001:db8:***) to prevent tracking.
- Captures general client device/browser family safely.
- Multi-tenant student isolation: users can only view their own account security events.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

VALID_EVENT_TYPES = [
    "SIGN_IN",
    "SIGN_OUT",
    "PASSWORD_CHANGE",
    "PASSWORD_RESET_REQUEST",
    "EMAIL_CHANGE",
    "ACCOUNT_DELETION_REQUEST",
    "TWO_FACTOR_CHANGE",
    "SESSION_REVOKE"
]


def init_security_activity_table():
    """Initializes the security activity log store."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS security_activity_log (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                description TEXT NOT NULL,
                ip_masked TEXT,
                user_agent_safe TEXT,
                status TEXT DEFAULT 'Success',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def mask_ip_address(ip_str: Optional[str]) -> str:
    """
    Masks IP address for user privacy (e.g. 192.168.1.42 -> 192.168.1.***).
    """
    if not ip_str or not isinstance(ip_str, str):
        return "Unknown"

    ip_clean = ip_str.strip()
    if ":" in ip_clean:
        # IPv6
        parts = ip_clean.split(":")
        if len(parts) > 2:
            return ":".join(parts[:2]) + ":****:****"
        return ip_clean[:8] + ":****"

    # IPv4
    parts = ip_clean.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.{parts[2]}.***"
    return "Masked"


def extract_safe_device(user_agent: Optional[str]) -> str:
    """
    Parses user-agent into high-level browser and platform without leaking unique fingerprints.
    """
    if not user_agent:
        return "Browser / Web Client"

    ua = str(user_agent)
    browser = "Browser"
    if "Firefox" in ua:
        browser = "Firefox"
    elif "Chrome" in ua or "CriOS" in ua:
        browser = "Chrome"
    elif "Safari" in ua and "Chrome" not in ua:
        browser = "Safari"
    elif "Edge" in ua or "Edg" in ua:
        browser = "Edge"

    platform = "Desktop"
    if "Android" in ua:
        platform = "Android"
    elif "iPhone" in ua or "iPad" in ua:
        platform = "iOS"
    elif "Windows" in ua:
        platform = "Windows"
    elif "Macintosh" in ua or "Mac OS" in ua:
        platform = "macOS"
    elif "Linux" in ua:
        platform = "Linux"

    return f"{browser} on {platform}"


def record_security_event(
    user_id: str,
    event_type: str,
    description: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    status: str = "Success"
) -> Dict[str, Any]:
    """
    Records an account security event safely.
    """
    if not user_id:
        return {"success": False, "error": "User ID required."}

    norm_type = event_type.strip().upper()
    if norm_type not in VALID_EVENT_TYPES:
        norm_type = "SIGN_IN"

    init_security_activity_table()
    event_id = f"sec-{uuid.uuid4().hex[:12]}"
    ip_masked = mask_ip_address(ip_address)
    device_safe = extract_safe_device(user_agent)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO security_activity_log (
                id, user_id, event_type, description, ip_masked, user_agent_safe, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                user_id,
                norm_type,
                description.strip(),
                ip_masked,
                device_safe,
                status.strip()
            )
        )
        conn.commit()
    finally:
        conn.close()

    return {"success": True, "event_id": event_id}


def get_user_security_activity(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Retrieves recent security activity for the student.
    """
    if not user_id:
        return []

    init_security_activity_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, event_type, description, ip_masked, user_agent_safe, status, created_at
            FROM security_activity_log
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
