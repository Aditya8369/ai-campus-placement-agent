"""
Admin User Management Service (#853).
====================================
Provides administrative user directory querying, account activation/deactivation,
forced session termination ('Sign out everywhere'), and audit logging.

Security & Integrity Guarantees:
1. Admin-only access enforcement.
2. Protection of last active administrator from deactivation.
3. Strict sanitization: Password hashes, verification tokens, and 2FA secrets are NEVER exposed.
4. Comprehensive, immutable audit trail for administrative actions.
5. Immediate session termination upon deactivation or forced logout.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

from utils.database import get_db_connection

logger = logging.getLogger(__name__)


def init_admin_user_management_schema(conn: Optional[sqlite3.Connection] = None) -> None:
    """Ensures necessary columns and audit logging table exist in the SQLite database."""
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    try:
        cursor = conn.cursor()

        # 1. Ensure users table has is_active and role columns
        cursor.execute("PRAGMA table_info(users)")
        user_cols = [col[1] for col in cursor.fetchall()]

        if "is_active" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        if "role" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'student'")

        # 2. Create immutable admin user audit log table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_user_audit_logs (
                id TEXT PRIMARY KEY,
                admin_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target_user_id TEXT NOT NULL,
                target_email TEXT,
                details TEXT,
                ip_address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_admin_user_audit_target ON admin_user_audit_logs(target_user_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_admin_user_audit_action ON admin_user_audit_logs(action)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_admin_user_audit_created ON admin_user_audit_logs(created_at)"
        )
        conn.commit()
    finally:
        if close_after:
            conn.close()


def record_admin_user_audit_log(
    admin_id: str,
    action: str,
    target_user_id: str,
    target_email: Optional[str] = None,
    details: Optional[Union[Dict[str, Any], str]] = None,
    ip_address: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Records an audit event for administrative actions on user accounts."""
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    init_admin_user_management_schema(conn)

    log_id = str(uuid.uuid4())
    details_str = json.dumps(details) if isinstance(details, (dict, list)) else (details or "")

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO admin_user_audit_logs (
                id, admin_id, action, target_user_id, target_email, details, ip_address, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (log_id, admin_id or "admin", action, target_user_id, target_email, details_str, ip_address),
        )
        conn.commit()
    except Exception as exc:
        logger.error(f"Failed to record admin user audit log: {exc}")
    finally:
        if close_after:
            conn.close()


def get_admin_user_audit_logs(
    target_user_id: Optional[str] = None,
    limit: int = 50,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """Retrieves recent audit log records."""
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    init_admin_user_management_schema(conn)

    try:
        cursor = conn.cursor()
        if target_user_id:
            cursor.execute(
                """
                SELECT id, admin_id, action, target_user_id, target_email, details, ip_address, created_at
                FROM admin_user_audit_logs
                WHERE target_user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (target_user_id, limit),
            )
        else:
            cursor.execute(
                """
                SELECT id, admin_id, action, target_user_id, target_email, details, ip_address, created_at
                FROM admin_user_audit_logs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        if close_after:
            conn.close()


def count_active_admins(conn: Optional[sqlite3.Connection] = None) -> int:
    """Counts the number of active admin users in the database."""
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    init_admin_user_management_schema(conn)

    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
        )
        return int(cursor.fetchone()[0])
    finally:
        if close_after:
            conn.close()


def list_users_for_admin(
    search_query: Optional[str] = None,
    status_filter: Optional[str] = None,
    page: int = 1,
    per_page: int = 15,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """
    Retrieves paginated, sanitized user records for administrative oversight.
    NEVER exposes password hashes, 2FA secrets, or verification tokens.
    """
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    init_admin_user_management_schema(conn)

    try:
        cursor = conn.cursor()
        conditions = ["1=1"]
        params: List[Any] = []

        if search_query and search_query.strip():
            clean_search = f"%{search_query.strip().lower()}%"
            conditions.append("(LOWER(name) LIKE ? OR LOWER(email) LIKE ?)")
            params.extend([clean_search, clean_search])

        if status_filter in ("active", "1"):
            conditions.append("is_active = 1")
        elif status_filter in ("deactivated", "0", "inactive"):
            conditions.append("is_active = 0")

        where_clause = " AND ".join(conditions)

        # Count total matching users
        cursor.execute(f"SELECT COUNT(*) FROM users WHERE {where_clause}", params)
        total_count = int(cursor.fetchone()[0])

        total_pages = max(1, (total_count + per_page - 1) // per_page)
        current_page = max(1, min(page, total_pages))
        offset = (current_page - 1) * per_page

        query = f"""
            SELECT 
                u.id, 
                u.name, 
                u.email, 
                u.created_at, 
                COALESCE(u.is_active, 1) as is_active, 
                COALESCE(u.role, 'student') as role,
                COALESCE(u.is_verified, 0) as is_verified,
                (SELECT COUNT(*) FROM auth_sessions s WHERE s.user_id = u.id AND s.revoked_at IS NULL) as active_sessions_count
            FROM users u
            WHERE {where_clause}
            ORDER BY u.created_at DESC
            LIMIT ? OFFSET ?
        """
        cursor.execute(query, params + [per_page, offset])
        rows = cursor.fetchall()

        users = []
        for r in rows:
            users.append({
                "id": r["id"],
                "name": r["name"],
                "email": r["email"],
                "created_at": r["created_at"],
                "is_active": bool(r["is_active"]),
                "role": r["role"],
                "is_verified": bool(r["is_verified"]),
                "active_sessions_count": int(r["active_sessions_count"]),
            })

        return {
            "users": users,
            "total_count": total_count,
            "page": current_page,
            "per_page": per_page,
            "total_pages": total_pages,
            "has_next": current_page < total_pages,
            "has_prev": current_page > 1,
            "active_count": _get_status_count(cursor, 1),
            "deactivated_count": _get_status_count(cursor, 0),
        }
    finally:
        if close_after:
            conn.close()


def _get_status_count(cursor: Any, is_active: int) -> int:
    try:
        cursor.execute("SELECT COUNT(*) FROM users WHERE COALESCE(is_active, 1) = ?", (is_active,))
        return int(cursor.fetchone()[0])
    except Exception:
        return 0


def set_user_active_status(
    target_user_id: str,
    is_active: bool,
    admin_id: str,
    ip_address: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str]:
    """
    Activates or deactivates a user account.
    If deactivating:
      - Prevents deactivating the last remaining active admin.
      - Automatically terminates all active auth sessions for the target user.
      - Audits the action.
    """
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    init_admin_user_management_schema(conn)

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, email, role, is_active FROM users WHERE id = ?", (target_user_id,))
        user = cursor.fetchone()
        if not user:
            return False, "User not found."

        target_role = user["role"] if user["role"] else "student"
        current_status = bool(user["is_active"])

        # Check last active admin safeguard if deactivating
        if not is_active:
            if target_role == "admin":
                active_admins = count_active_admins(conn)
                if active_admins <= 1:
                    logger.warning(
                        f"Admin {admin_id} attempted to deactivate the last remaining administrator {target_user_id}."
                    )
                    return False, "Cannot deactivate the last active administrator."

        new_status_int = 1 if is_active else 0
        cursor.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (new_status_int, target_user_id),
        )
        conn.commit()

        # If deactivated, immediately revoke all active sessions
        revoked_sessions = 0
        if not is_active:
            cursor.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (time.time(), target_user_id),
            )
            revoked_sessions = cursor.rowcount
            conn.commit()

        action = "USER_REACTIVATED" if is_active else "USER_DEACTIVATED"
        record_admin_user_audit_log(
            admin_id=admin_id,
            action=action,
            target_user_id=target_user_id,
            target_email=user["email"],
            details={
                "previous_status": current_status,
                "new_status": is_active,
                "revoked_sessions": revoked_sessions,
            },
            ip_address=ip_address,
            conn=conn,
        )

        status_label = "reactivated" if is_active else "deactivated"
        msg = f"User '{user['name']}' ({user['email']}) has been successfully {status_label}."
        if not is_active and revoked_sessions > 0:
            msg += f" {revoked_sessions} active session(s) were revoked."
        return True, msg
    except Exception as exc:
        logger.error(f"Error setting user active status: {exc}")
        return False, f"Failed to update user status: {str(exc)}"
    finally:
        if close_after:
            conn.close()


def sign_out_user_everywhere(
    target_user_id: str,
    admin_id: str,
    ip_address: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str, int]:
    """
    Terminates all active sessions for a target user ('Sign out everywhere').
    Writes to admin audit log.
    """
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    init_admin_user_management_schema(conn)

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, email FROM users WHERE id = ?", (target_user_id,))
        user = cursor.fetchone()
        if not user:
            return False, "User not found.", 0

        cursor.execute(
            "UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (time.time(), target_user_id),
        )
        revoked_count = cursor.rowcount
        conn.commit()

        record_admin_user_audit_log(
            admin_id=admin_id,
            action="USER_SESSIONS_REVOKED",
            target_user_id=target_user_id,
            target_email=user["email"],
            details={"revoked_sessions_count": revoked_count},
            ip_address=ip_address,
            conn=conn,
        )

        return True, f"Successfully signed out '{user['name']}' from all {revoked_count} active session(s).", revoked_count
    except Exception as exc:
        logger.error(f"Error revoking user sessions everywhere: {exc}")
        return False, f"Failed to sign out user everywhere: {str(exc)}", 0
    finally:
        if close_after:
            conn.close()
