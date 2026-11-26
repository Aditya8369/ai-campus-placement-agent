"""
Account Lockout and Failed Login Attempt Tracking Service (#851).
================================================================
Defends against distributed brute-force attacks and slow-rate credential stuffing
by tracking failed login attempts per account and per IP in a SQLite table with timestamps.

Key Capabilities:
1. Account & IP Failure Tracking:
   - Tracks failed attempts deterministically by normalized account identifier and client IP.
   - Computes failure count within a sliding window (default: 15 minutes).
2. Progressive Delays & Temporary Lockout:
   - Applies progressive delays after repeated failures (e.g. 1s after 3, 2s after 4).
   - Enforces a 15-minute temporary lockout after 5 failed attempts.
   - Automatically recovers once the lockout duration has elapsed.
3. User Enumeration Defense:
   - Unknown accounts and locked accounts receive identical user-facing error responses.
   - Attackers cannot deduce whether an account exists from error responses or lockout status.
4. Security Notification Email:
   - Dispatches a security alert email to the registered account owner when a lockout triggers.
5. Counter Reset & Growth Capping:
   - Resets failure counters upon successful authentication.
   - Prunes expired records older than retention threshold and caps table growth.
6. Fixed Clock Support:
   - All temporal methods accept an optional `current_time` parameter for deterministic testing.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import config
from utils.database import get_db_connection, get_user_by_email
from utils.email_service import EmailNotificationService

logger = logging.getLogger(__name__)

# Default security policy constants
DEFAULT_LOCKOUT_THRESHOLD = 5          # Number of failures before lockout
DEFAULT_LOCKOUT_DURATION_SECONDS = 900 # 15 minutes
DEFAULT_WINDOW_SECONDS = 900           # 15 minutes tracking window
DEFAULT_MAX_RETENTION_SECONDS = 86400  # 24 hours retention
DEFAULT_MAX_TABLE_ROWS = 10000         # Maximum records cap


def _get_time(custom_time: Optional[float] = None) -> float:
    """Returns custom_time if provided, otherwise system time."""
    return custom_time if custom_time is not None else time.time()


class AccountLockoutService:
    """Thread-safe SQLite-backed service for tracking failed attempts and lockouts."""

    def __init__(
        self,
        lockout_threshold: Optional[int] = None,
        lockout_duration_seconds: Optional[int] = None,
        window_seconds: Optional[int] = None,
        max_retention_seconds: Optional[int] = None,
        max_table_rows: Optional[int] = None,
        sleep_func: Optional[Any] = None,
    ):
        self.lockout_threshold = (
            lockout_threshold
            if lockout_threshold is not None
            else int(getattr(config, "ACCOUNT_LOCKOUT_THRESHOLD", DEFAULT_LOCKOUT_THRESHOLD))
        )
        self.lockout_duration_seconds = (
            lockout_duration_seconds
            if lockout_duration_seconds is not None
            else int(getattr(config, "ACCOUNT_LOCKOUT_DURATION_SECONDS", DEFAULT_LOCKOUT_DURATION_SECONDS))
        )
        self.window_seconds = (
            window_seconds
            if window_seconds is not None
            else int(getattr(config, "FAILED_LOGIN_WINDOW_SECONDS", DEFAULT_WINDOW_SECONDS))
        )
        self.max_retention_seconds = (
            max_retention_seconds
            if max_retention_seconds is not None
            else int(getattr(config, "FAILED_LOGIN_RETENTION_SECONDS", DEFAULT_MAX_RETENTION_SECONDS))
        )
        self.max_table_rows = (
            max_table_rows
            if max_table_rows is not None
            else int(getattr(config, "FAILED_LOGIN_MAX_ROWS", DEFAULT_MAX_TABLE_ROWS))
        )
        self.sleep_func = sleep_func or time.sleep
        self._ensure_tables()

    def _ensure_tables_cursor(self, cursor: Any) -> None:
        """Ensures the tracking tables exist using an existing cursor."""
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS failed_login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identifier TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                attempted_at REAL NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_failed_login_ident_time 
            ON failed_login_attempts (identifier, attempted_at)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_failed_login_ip_time 
            ON failed_login_attempts (ip_address, attempted_at)
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS account_lockouts (
                identifier TEXT PRIMARY KEY,
                locked_until REAL NOT NULL,
                created_at REAL NOT NULL,
                notified_at REAL
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_account_lockouts_until 
            ON account_lockouts (locked_until)
            """
        )

    def _ensure_tables(self) -> None:
        """Ensures the tracking tables exist in SQLite."""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            self._ensure_tables_cursor(cursor)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"AccountLockoutService: Error ensuring tables: {e}")

    def normalize_identifier(self, identifier: Optional[str]) -> str:
        """Normalizes an account identifier (email/username) for consistent tracking."""
        return (identifier or "").strip().lower()

    def normalize_ip(self, ip_address: Optional[str]) -> str:
        """Normalizes an IP address."""
        return (ip_address or "127.0.0.1").strip()

    def is_locked_out(
        self,
        identifier: str,
        current_time: Optional[float] = None,
    ) -> bool:
        """Checks if the given identifier is currently locked out."""
        is_locked, _, _ = self.check_lockout(identifier=identifier, current_time=current_time)
        return is_locked

    def check_lockout(
        self,
        identifier: str,
        ip_address: Optional[str] = None,
        current_time: Optional[float] = None,
    ) -> Tuple[bool, float, float]:
        """
        Inspects lockout and progressive delay status for an identifier and/or IP address.

        Returns:
            Tuple[bool, float, float]:
                - is_locked (bool): True if currently locked out
                - remaining_lockout_seconds (float): Seconds remaining until unlock (0.0 if not locked)
                - delay_seconds (float): Progressive delay in seconds to enforce (0.0 if none)
        """
        now = _get_time(current_time)
        clean_ident = self.normalize_identifier(identifier)
        clean_ip = self.normalize_ip(ip_address)

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            self._ensure_tables_cursor(cursor)

            # 1. Check active entry in account_lockouts table
            if clean_ident:
                cursor.execute(
                    "SELECT locked_until FROM account_lockouts WHERE identifier = ?",
                    (clean_ident,),
                )
                row = cursor.fetchone()
                if row:
                    locked_until = float(row[0])
                    if locked_until > now:
                        remaining = locked_until - now
                        logger.info(
                            f"AccountLockoutService: Identifier '{clean_ident}' is locked for {remaining:.1f}s."
                        )
                        return True, remaining, 0.0
                    else:
                        # Lockout has expired, remove stale entry
                        cursor.execute(
                            "DELETE FROM account_lockouts WHERE identifier = ?",
                            (clean_ident,),
                        )
                        conn.commit()

            # 2. Check recent failed attempts within tracking window
            cutoff = now - self.window_seconds
            ident_failures = 0
            ip_failures = 0

            if clean_ident:
                cursor.execute(
                    "SELECT COUNT(*) FROM failed_login_attempts WHERE identifier = ? AND attempted_at >= ?",
                    (clean_ident, cutoff),
                )
                ident_failures = int(cursor.fetchone()[0])

            if clean_ip:
                cursor.execute(
                    "SELECT COUNT(*) FROM failed_login_attempts WHERE ip_address = ? AND attempted_at >= ?",
                    (clean_ip, cutoff),
                )
                ip_failures = int(cursor.fetchone()[0])

            # Lockout threshold evaluation (account failure ceiling)
            if ident_failures >= self.lockout_threshold:
                locked_until = now + self.lockout_duration_seconds
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO account_lockouts (identifier, locked_until, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (clean_ident, locked_until, now),
                )
                conn.commit()
                return True, float(self.lockout_duration_seconds), 0.0

            # Progressive delay calculation
            max_failures = max(ident_failures, ip_failures)
            delay = 0.0
            if max_failures == 3:
                delay = 1.0
            elif max_failures == 4:
                delay = 2.0
            elif max_failures > 4:
                delay = min(5.0, float(max_failures - 2))

            return False, 0.0, delay

        except Exception as e:
            logger.error(f"AccountLockoutService: Error checking lockout: {e}")
            return False, 0.0, 0.0
        finally:
            conn.close()

    def record_failed_attempt(
        self,
        identifier: str,
        ip_address: Optional[str] = None,
        current_time: Optional[float] = None,
    ) -> Tuple[bool, int]:
        """
        Records a failed authentication attempt in SQLite and triggers lockout + notification
        if failure threshold is reached.

        Returns:
            Tuple[bool, int]:
                - is_locked_now (bool): True if this attempt triggered or remains in lockout
                - failure_count (int): Number of failures in current window
        """
        now = _get_time(current_time)
        clean_ident = self.normalize_identifier(identifier)
        clean_ip = self.normalize_ip(ip_address)

        if not clean_ident:
            return False, 0

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            self._ensure_tables_cursor(cursor)

            # 1. Insert new failed attempt
            cursor.execute(
                """
                INSERT INTO failed_login_attempts (identifier, ip_address, attempted_at)
                VALUES (?, ?, ?)
                """,
                (clean_ident, clean_ip, now),
            )
            conn.commit()

            # 2. Count failures in window
            cutoff = now - self.window_seconds
            cursor.execute(
                "SELECT COUNT(*) FROM failed_login_attempts WHERE identifier = ? AND attempted_at >= ?",
                (clean_ident, cutoff),
            )
            failure_count = int(cursor.fetchone()[0])

            is_locked = False
            if failure_count >= self.lockout_threshold:
                locked_until = now + self.lockout_duration_seconds
                is_locked = True

                # Check if notification already sent for this cycle
                cursor.execute(
                    "SELECT notified_at FROM account_lockouts WHERE identifier = ?",
                    (clean_ident,),
                )
                row = cursor.fetchone()
                already_notified = bool(row and row[0] and (now - float(row[0]) < self.lockout_duration_seconds))

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO account_lockouts (identifier, locked_until, created_at, notified_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (clean_ident, locked_until, now, now if not already_notified else (row[0] if row else None)),
                )
                conn.commit()

                # Dispatch notification email if account owner exists
                if not already_notified:
                    self._dispatch_lockout_notification(clean_ident)

            # Cap growth with periodic cleanup
            self._cleanup_internal(cursor, now)
            conn.commit()

            return is_locked, failure_count

        except Exception as e:
            logger.error(f"AccountLockoutService: Error recording failed attempt: {e}")
            return False, 0
        finally:
            conn.close()

    def _dispatch_lockout_notification(self, identifier: str) -> None:
        """Sends security alert notification email if the account exists in users table."""
        try:
            user = get_user_by_email(identifier)
            if user and isinstance(user, dict) and user.get("email"):
                email_service = EmailNotificationService()
                student_name = user.get("name") or "Student"
                lockout_mins = max(1, round(self.lockout_duration_seconds / 60))
                email_service.send_account_lockout_notification(
                    recipient_email=user["email"],
                    student_name=student_name,
                    lockout_minutes=lockout_mins,
                )
                logger.info(f"AccountLockoutService: Lockout alert email dispatched to {user['email']}.")
            else:
                logger.debug(f"AccountLockoutService: Identifier '{identifier}' not found in users. Email skipped.")
        except Exception as e:
            logger.error(f"AccountLockoutService: Failed to dispatch lockout email: {e}")

    def reset_failed_attempts(
        self,
        identifier: str,
        ip_address: Optional[str] = None,
    ) -> None:
        """
        Resets failed attempt counters and clears lockout state upon successful authentication.
        """
        clean_ident = self.normalize_identifier(identifier)
        clean_ip = self.normalize_ip(ip_address)

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            self._ensure_tables_cursor(cursor)
            if clean_ident:
                cursor.execute("DELETE FROM failed_login_attempts WHERE identifier = ?", (clean_ident,))
                cursor.execute("DELETE FROM account_lockouts WHERE identifier = ?", (clean_ident,))
            if clean_ip:
                cursor.execute("DELETE FROM failed_login_attempts WHERE ip_address = ?", (clean_ip,))
            conn.commit()
            logger.info(f"AccountLockoutService: Reset counters for identifier='{clean_ident}', ip='{clean_ip}'.")
        except Exception as e:
            logger.error(f"AccountLockoutService: Error resetting failed attempts: {e}")
        finally:
            conn.close()

    def _cleanup_internal(self, cursor: Any, now: float) -> None:
        """Cleans up expired attempts and caps table growth within open transaction."""
        retention_cutoff = now - self.max_retention_seconds
        cursor.execute("DELETE FROM failed_login_attempts WHERE attempted_at < ?", (retention_cutoff,))
        cursor.execute("DELETE FROM account_lockouts WHERE locked_until < ?", (now,))

        # Cap total rows to prevent unbounded disk growth
        cursor.execute("SELECT COUNT(*) FROM failed_login_attempts")
        total_rows = int(cursor.fetchone()[0])
        if total_rows > self.max_table_rows:
            excess = total_rows - self.max_table_rows
            cursor.execute(
                """
                DELETE FROM failed_login_attempts WHERE id IN (
                    SELECT id FROM failed_login_attempts ORDER BY attempted_at ASC LIMIT ?
                )
                """,
                (excess,),
            )

    def cleanup_old_attempts(
        self,
        retention_seconds: Optional[int] = None,
        current_time: Optional[float] = None,
    ) -> int:
        """
        Explicit maintenance cleanup to purge old attempts and expired lockouts.
        Returns the number of purged rows.
        """
        now = _get_time(current_time)
        retention = retention_seconds if retention_seconds is not None else self.max_retention_seconds
        retention_cutoff = now - retention

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            self._ensure_tables_cursor(cursor)
            cursor.execute("SELECT COUNT(*) FROM failed_login_attempts WHERE attempted_at < ?", (retention_cutoff,))
            purged = int(cursor.fetchone()[0])
            cursor.execute("DELETE FROM failed_login_attempts WHERE attempted_at < ?", (retention_cutoff,))
            cursor.execute("DELETE FROM account_lockouts WHERE locked_until < ?", (now,))
            conn.commit()
            return purged
        except Exception as e:
            logger.error(f"AccountLockoutService: Error cleaning up old attempts: {e}")
            return 0
        finally:
            conn.close()


# Global default instance
lockout_service = AccountLockoutService()
