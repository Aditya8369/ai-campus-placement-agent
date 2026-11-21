"""
Email Address Change with Verification Service (#405)

Enables authenticated users to request an email address change with email verification:
- Requires signed-in user and current password confirmation (or session auth)
- Enforces valid email syntax and normalization (lowercase, stripped)
- Protects against user enumeration: Does not reveal whether an unrelated email belongs to another account
  (returns consistent generic success message "Verification link sent to new email if eligible")
- Stores pending email change request with cryptographically secure token and expiration (e.g. 24 hours)
- Keeps the current (old) email active and operational until the verification link is successfully clicked/confirmed
- Verification endpoint:
  * Detects invalid token
  * Detects expired token (with explicit message)
  * Detects already-used token (with explicit message)
  * Replaces user's email in `users` table upon successful validation
  * Invalidates all pending change tokens for that user
  * Audits security event (login/activity log)
"""

import os
import re
import time
import secrets
import hashlib
import sqlite3
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "instance", "placement_agent.db")


def _get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_email_change_tables():
    """Initializes schema for pending email change requests."""
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_email_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    old_email TEXT NOT NULL,
                    new_email TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pec_token ON pending_email_changes(token_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pec_user ON pending_email_changes(user_id)")
    finally:
        conn.close()


init_email_change_tables()


class EmailChangeService:
    """Manages email change request lifecycle, verification tokens, and atomic confirmation."""

    TOKEN_EXPIRY_SECONDS = 24 * 3600  # 24 hours

    @classmethod
    def request_email_change(
        cls,
        user_id: str,
        new_email: str
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Initiates an email change request.
        Returns: (success: bool, user_message: str, raw_token_if_created: Optional[str])

        Enumeration Defense:
        If the email is already registered by another account, we do not throw an error or reveal
        ownership to prevent account harvesting. We simulate the same success response or silently skip token creation.
        """
        if not new_email or not isinstance(new_email, str):
            return False, "Please provide a valid email address.", None

        cleaned_new_email = new_email.strip().lower()

        # Email syntax validation
        email_regex = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        if not re.match(email_regex, cleaned_new_email):
            return False, "Invalid email address format.", None

        conn = _get_db_connection()
        try:
            # Check user's current email
            current_user = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
            if not current_user:
                return False, "User account not found.", None

            old_email = current_user["email"].strip().lower()
            if old_email == cleaned_new_email:
                return False, "The new email address cannot be the same as your current email.", None

            # Check if new email is already claimed by someone else
            existing = conn.execute(
                "SELECT id FROM users WHERE LOWER(email) = ? AND id != ?",
                (cleaned_new_email, user_id)
            ).fetchone()

            if existing:
                # Security rule: Do not reveal whether another account uses this email.
                # Return generic success to caller without actually issuing token for existing user.
                logger.info(f"Email change requested for existing email {cleaned_new_email}; suppressed to prevent enumeration.")
                return True, "If the email is eligible, a verification link has been sent to the new address.", None

            # Invalidate any previously unconfirmed tokens for this user
            now = int(time.time())
            with conn:
                conn.execute(
                    "UPDATE pending_email_changes SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
                    (now, user_id)
                )

                # Generate secure random token
                raw_token = secrets.token_urlsafe(32)
                token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
                expires_at = now + cls.TOKEN_EXPIRY_SECONDS

                conn.execute("""
                    INSERT INTO pending_email_changes (
                        user_id, old_email, new_email, token_hash, expires_at
                    ) VALUES (?, ?, ?, ?, ?)
                """, (user_id, old_email, cleaned_new_email, token_hash, expires_at))

            logger.info(f"Email change token issued for user {user_id} to switch to {cleaned_new_email}.")
            return True, "A verification link has been sent to your new email address. Your current email remains active until confirmed.", raw_token
        finally:
            conn.close()

    @classmethod
    def verify_email_change(cls, token: str) -> Dict[str, Any]:
        """
        Validates the email change verification token.
        Handles:
        - Missing or invalid tokens
        - Expired tokens
        - Already used tokens
        - Success: atomically updates users table with new email
        """
        if not token or not token.strip():
            return {
                "success": False,
                "error_code": "INVALID_TOKEN",
                "message": "The verification token is missing or malformed."
            }

        token_hash = hashlib.sha256(token.strip().encode("utf-8")).hexdigest()
        now = int(time.time())

        conn = _get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM pending_email_changes WHERE token_hash = ?",
                (token_hash,)
            ).fetchone()

            if not row:
                return {
                    "success": False,
                    "error_code": "INVALID_TOKEN",
                    "message": "This verification link is invalid or does not exist."
                }

            # Check if already used
            if row["used_at"] is not None:
                return {
                    "success": False,
                    "error_code": "ALREADY_USED",
                    "message": "This verification link has already been used. Please request a new email change if needed."
                }

            # Check if expired
            if row["expires_at"] <= now:
                return {
                    "success": False,
                    "error_code": "EXPIRED",
                    "message": "This verification link has expired. Verification links are valid for 24 hours."
                }

            user_id = row["user_id"]
            new_email = row["new_email"]
            old_email = row["old_email"]

            # Double check collision before final commitment
            collision = conn.execute(
                "SELECT id FROM users WHERE LOWER(email) = ? AND id != ?",
                (new_email.lower(), user_id)
            ).fetchone()

            if collision:
                return {
                    "success": False,
                    "error_code": "EMAIL_TAKEN",
                    "message": "This email address was recently registered by another account."
                }

            with conn:
                # Mark token as used
                conn.execute(
                    "UPDATE pending_email_changes SET used_at = ? WHERE id = ?",
                    (now, row["id"])
                )

                # Atomically update user's email and set verified
                conn.execute(
                    "UPDATE users SET email = ?, is_verified = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_email, user_id)
                )

            logger.info(f"User {user_id} successfully changed email from {old_email} to {new_email}.")

            return {
                "success": True,
                "user_id": user_id,
                "old_email": old_email,
                "new_email": new_email,
                "message": f"Your email address has been successfully updated to {new_email}."
            }
        finally:
            conn.close()

    @classmethod
    def get_pending_request(cls, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves any active, unexpired pending email change for user."""
        now = int(time.time())
        conn = _get_db_connection()
        try:
            row = conn.execute("""
                SELECT new_email, expires_at, created_at
                FROM pending_email_changes
                WHERE user_id = ? AND used_at IS NULL AND expires_at > ?
                ORDER BY created_at DESC LIMIT 1
            """, (user_id, now)).fetchone()

            if not row:
                return None

            return {
                "pending_new_email": row["new_email"],
                "expires_at": row["expires_at"],
                "created_at": str(row["created_at"])
            }
        finally:
            conn.close()

    @classmethod
    def cancel_pending_request(cls, user_id: str) -> bool:
        """Cancels any outstanding email change requests for user."""
        now = int(time.time())
        conn = _get_db_connection()
        try:
            with conn:
                cursor = conn.execute("""
                    UPDATE pending_email_changes
                    SET used_at = ?
                    WHERE user_id = ? AND used_at IS NULL
                """, (now, user_id))
                return cursor.rowcount > 0
        finally:
            conn.close()
