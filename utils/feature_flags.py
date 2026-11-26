"""
Feature Flag Service (#854).
============================
Provides dynamic runtime feature flag management backed by environment variables
and a persistent SQLite table with optional percentage-based gradual rollout.

Key Capabilities:
1. Multi-tier evaluation hierarchy:
   - Database Override (Enabled / Disabled / Percentage Rollout)
   - Environment Variable Default (`FEATURE_<FLAG_NAME>=true|false` or `FEATURE_FLAG_<FLAG_NAME>=...`)
   - Code Registry Default (configured default value or False)
2. Deterministic Percentage Rollout:
   - Percentage rollout (0-100%) is calculated via stable SHA-256 hash modulo 100 on `(flag_key:user_id)`.
   - Guarantees deterministic, stable assignment for the same user without cross-flag correlation.
3. Admin Audit Trail:
   - All state changes (enable, disable, percentage adjustment) are logged with timestamp, admin actor, and previous/new values.
4. Seamless Context Integration:
   - `is_enabled(flag, user)` is directly usable in route handlers and Jinja2 templates.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

import config
from utils.database import get_db_connection

logger = logging.getLogger(__name__)

# Predefined registered flags and their default metadata
REGISTERED_FLAGS: Dict[str, Dict[str, Any]] = {
    "ai_resume_enhancement": {
        "description": "Advanced AI-powered suggestions for resume bullet rewrite and formatting.",
        "default_enabled": True,
        "default_rollout_percentage": 100,
    },
    "mock_interview_voice": {
        "description": "Experimental real-time voice input and speech synthesis during mock interviews.",
        "default_enabled": False,
        "default_rollout_percentage": 0,
    },
    "batch_comparison_v2": {
        "description": "Multi-company side-by-side comparative analysis matrix for placement drives.",
        "default_enabled": True,
        "default_rollout_percentage": 100,
    },
    "peer_leaderboard": {
        "description": "Competitive cohort preparation streak and aptitude percentile leaderboard.",
        "default_enabled": True,
        "default_rollout_percentage": 100,
    },
    "github_project_analysis": {
        "description": "Inspect candidate GitHub repositories to detect skills and project highlights.",
        "default_enabled": False,
        "default_rollout_percentage": 25,
    },
}


def _normalize_flag_key(key: str) -> str:
    """Normalizes a feature flag key to lower_snake_case."""
    return (key or "").strip().lower().replace("-", "_").replace(" ", "_")


def _get_env_flag_default(flag_key: str) -> Optional[bool]:
    """
    Checks environment variables for a default flag value.
    Supports formats:
      - `FEATURE_<KEY>=1|true|yes`
      - `FEATURE_FLAG_<KEY>=1|true|yes`
    """
    normalized = _normalize_flag_key(flag_key).upper()
    env_keys = [f"FEATURE_{normalized}", f"FEATURE_FLAG_{normalized}"]
    for ek in env_keys:
        val = os.environ.get(ek)
        if val is not None:
            clean = val.strip().lower()
            if clean in ("1", "true", "yes", "on", "enabled"):
                return True
            elif clean in ("0", "false", "no", "off", "disabled"):
                return False
    return None


def calculate_rollout_bucket(flag_key: str, user_identifier: str) -> int:
    """
    Computes a deterministic integer in range [0, 99] for a given user and flag.
    Uses SHA-256 hash of `f"{flag}:{user}"` to avoid clustering.
    """
    seed = f"{flag_key}:{user_identifier}".encode("utf-8")
    digest = hashlib.sha256(seed).hexdigest()
    # Take first 8 hex characters as integer modulo 100
    return int(digest[:8], 16) % 100


class FeatureFlagService:
    """Service for checking, toggling, and auditing feature flags."""

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables_cursor(self, cursor: sqlite3.Cursor) -> None:
        """Creates feature flags and audit log tables."""
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS feature_flags (
                key TEXT PRIMARY KEY,
                description TEXT,
                is_enabled INTEGER NOT NULL DEFAULT 0,
                rollout_percentage INTEGER NOT NULL DEFAULT 100,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS feature_flag_audit_logs (
                id TEXT PRIMARY KEY,
                flag_key TEXT NOT NULL,
                admin_id TEXT NOT NULL,
                action TEXT NOT NULL,
                previous_state TEXT,
                new_state TEXT,
                details TEXT,
                ip_address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ff_audit_flag ON feature_flag_audit_logs(flag_key)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ff_audit_created ON feature_flag_audit_logs(created_at DESC)"
        )

    def _ensure_tables(self) -> None:
        """Initializes tables using a new database connection."""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            self._ensure_tables_cursor(cursor)
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.error(f"FeatureFlagService: Error ensuring tables: {exc}")

    def is_enabled(
        self,
        flag_key: str,
        user: Optional[Union[str, Dict[str, Any]]] = None,
        default: Optional[bool] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> bool:
        """
        Determines if a feature flag is enabled for the specified user context.

        Hierarchy:
        1. Explicit DB record (if present)
           - If `is_enabled == 0`: False
           - If `is_enabled == 1`:
             - If `rollout_percentage >= 100`: True
             - If `rollout_percentage <= 0`: False
             - Otherwise, hashes user identifier to test bucket < rollout_percentage
        2. Environment variable default (`FEATURE_<FLAG>=true|false`)
        3. Registered flag default
        4. Explicit default argument (or False)
        """
        clean_key = _normalize_flag_key(flag_key)
        if not clean_key:
            return False

        # Extract user identifier (ID or email or string)
        user_identifier: Optional[str] = None
        if isinstance(user, dict):
            user_identifier = str(user.get("id") or user.get("user_id") or user.get("email") or "")
        elif user is not None:
            user_identifier = str(user).strip()

        # 1. Query database record
        close_after = False
        if conn is None:
            conn = get_db_connection()
            close_after = True

        try:
            cursor = conn.cursor()
            self._ensure_tables_cursor(cursor)
            cursor.execute(
                "SELECT is_enabled, rollout_percentage FROM feature_flags WHERE key = ?",
                (clean_key,),
            )
            row = cursor.fetchone()
            if row:
                flag_is_active = bool(row["is_enabled"])
                rollout_pct = int(row["rollout_percentage"])

                if not flag_is_active:
                    return False

                # Flag is marked enabled; evaluate percentage rollout
                if rollout_pct >= 100:
                    return True
                if rollout_pct <= 0:
                    return False

                if not user_identifier:
                    # Anonymous or unassigned user with percentage rollout
                    # Default to False unless user is explicitly identified
                    return False

                bucket = calculate_rollout_bucket(clean_key, user_identifier)
                return bucket < rollout_pct
        except Exception as exc:
            logger.error(f"FeatureFlagService: Error evaluating flag '{clean_key}': {exc}")
        finally:
            if close_after:
                conn.close()

        # 2. Check environment variable
        env_val = _get_env_flag_default(clean_key)
        if env_val is not None:
            return env_val

        # 3. Check registered flag default
        if clean_key in REGISTERED_FLAGS:
            reg_info = REGISTERED_FLAGS[clean_key]
            reg_enabled = reg_info.get("default_enabled", False)
            reg_pct = reg_info.get("default_rollout_percentage", 100)

            if not reg_enabled:
                return False
            if reg_pct >= 100:
                return True
            if reg_pct <= 0:
                return False
            if not user_identifier:
                return False
            return calculate_rollout_bucket(clean_key, user_identifier) < reg_pct

        # 4. Fallback to passed default or False
        return default if default is not None else False

    def list_flags(self, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
        """
        Retrieves all feature flags merged with registered definitions.
        """
        close_after = False
        if conn is None:
            conn = get_db_connection()
            close_after = True

        try:
            cursor = conn.cursor()
            self._ensure_tables_cursor(cursor)
            cursor.execute(
                "SELECT key, description, is_enabled, rollout_percentage, created_at, updated_at FROM feature_flags"
            )
            db_rows = {row["key"]: dict(row) for row in cursor.fetchall()}

            result = []
            # Combine registered flags and any ad-hoc flags in DB
            all_keys = set(REGISTERED_FLAGS.keys()) | set(db_rows.keys())

            for key in sorted(all_keys):
                reg = REGISTERED_FLAGS.get(key, {})
                db_data = db_rows.get(key)
                env_override = _get_env_flag_default(key)

                if db_data:
                    is_enabled = bool(db_data["is_enabled"])
                    rollout_pct = int(db_data["rollout_percentage"])
                    desc = db_data.get("description") or reg.get("description") or "Custom feature flag."
                    updated_at = db_data.get("updated_at")
                    has_db_record = True
                else:
                    is_enabled = reg.get("default_enabled", False) if env_override is None else env_override
                    rollout_pct = reg.get("default_rollout_percentage", 100)
                    desc = reg.get("description", "Custom feature flag.")
                    updated_at = None
                    has_db_record = False

                result.append({
                    "key": key,
                    "description": desc,
                    "is_enabled": is_enabled,
                    "rollout_percentage": rollout_pct,
                    "env_override": env_override,
                    "has_db_record": has_db_record,
                    "updated_at": updated_at,
                })

            return result
        finally:
            if close_after:
                conn.close()

    def get_flag(self, flag_key: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
        """Retrieves details of a specific feature flag."""
        flags = self.list_flags(conn=conn)
        clean = _normalize_flag_key(flag_key)
        for f in flags:
            if f["key"] == clean:
                return f
        return None

    def set_flag(
        self,
        flag_key: str,
        is_enabled: bool,
        rollout_percentage: int = 100,
        description: Optional[str] = None,
        admin_id: str = "admin",
        ip_address: Optional[str] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Tuple[bool, str]:
        """
        Creates or updates a feature flag and records an audit log entry.
        """
        clean_key = _normalize_flag_key(flag_key)
        if not clean_key:
            return False, "Invalid flag key."

        rollout_pct = max(0, min(100, int(rollout_percentage)))

        close_after = False
        if conn is None:
            conn = get_db_connection()
            close_after = True

        try:
            cursor = conn.cursor()
            self._ensure_tables_cursor(cursor)

            cursor.execute(
                "SELECT is_enabled, rollout_percentage, description FROM feature_flags WHERE key = ?",
                (clean_key,),
            )
            existing = cursor.fetchone()

            prev_state = {
                "is_enabled": bool(existing["is_enabled"]) if existing else None,
                "rollout_percentage": int(existing["rollout_percentage"]) if existing else None,
            }

            final_desc = description or (existing["description"] if existing else None) or REGISTERED_FLAGS.get(clean_key, {}).get("description", "Feature flag")

            cursor.execute(
                """
                INSERT OR REPLACE INTO feature_flags (key, description, is_enabled, rollout_percentage, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (clean_key, final_desc, 1 if is_enabled else 0, rollout_pct),
            )
            conn.commit()

            # Record audit log
            log_id = str(uuid.uuid4())
            new_state = {"is_enabled": is_enabled, "rollout_percentage": rollout_pct}
            action = "FLAG_CREATED" if not existing else ("FLAG_ENABLED" if is_enabled else "FLAG_DISABLED")

            cursor.execute(
                """
                INSERT INTO feature_flag_audit_logs (
                    id, flag_key, admin_id, action, previous_state, new_state, details, ip_address, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    log_id,
                    clean_key,
                    admin_id,
                    action,
                    json.dumps(prev_state),
                    json.dumps(new_state),
                    f"Rollout: {rollout_pct}%",
                    ip_address,
                ),
            )
            conn.commit()

            status_text = "enabled" if is_enabled else "disabled"
            return True, f"Flag '{clean_key}' {status_text} with {rollout_pct}% rollout."
        except Exception as exc:
            logger.error(f"FeatureFlagService: Error setting flag '{clean_key}': {exc}")
            return False, f"Failed to update feature flag: {str(exc)}"
        finally:
            if close_after:
                conn.close()

    def get_audit_logs(
        self,
        flag_key: Optional[str] = None,
        limit: int = 50,
        conn: Optional[sqlite3.Connection] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves audit trail of feature flag changes."""
        close_after = False
        if conn is None:
            conn = get_db_connection()
            close_after = True

        try:
            cursor = conn.cursor()
            self._ensure_tables_cursor(cursor)

            if flag_key:
                clean = _normalize_flag_key(flag_key)
                cursor.execute(
                    """
                    SELECT id, flag_key, admin_id, action, previous_state, new_state, details, ip_address, created_at
                    FROM feature_flag_audit_logs
                    WHERE flag_key = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (clean, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, flag_key, admin_id, action, previous_state, new_state, details, ip_address, created_at
                    FROM feature_flag_audit_logs
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                )

            return [dict(row) for row in cursor.fetchall()]
        finally:
            if close_after:
                conn.close()


# Global default instance
feature_flags = FeatureFlagService()


def is_feature_enabled(
    flag_key: str,
    user: Optional[Union[str, Dict[str, Any]]] = None,
    default: Optional[bool] = None,
) -> bool:
    """Helper shortcut function to check if a feature flag is enabled."""
    return feature_flags.is_enabled(flag_key, user=user, default=default)
