"""
Student Bulk Invitation Service (#690).
Handles placement officer batch onboarding workflows:
- CSV upload, parsing, validation, and preview of candidate rows.
- Duplicate and existing user detection.
- Single-use, expiring (14 days) invitation tokens.
- Revocation, resending, and status lifecycle tracking (sent, accepted, expired, revoked).
- Row limits per upload (200) and rate limits per hour (500).
- Admin audit logging for all invitation lifecycle events.
- CSV formula injection protection on export.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from utils.database import get_db_connection
from utils.email_domain_validator import is_email_domain_allowed
from utils.email_service import EmailNotificationService

logger = logging.getLogger(__name__)

# Constants and limits (#690)
MAX_INVITE_ROWS_PER_UPLOAD = 200
MAX_INVITATIONS_PER_HOUR = 500
DEFAULT_INVITATION_EXPIRY_DAYS = 14

INVITATION_STATUS_SENT = "sent"
INVITATION_STATUS_ACCEPTED = "accepted"
INVITATION_STATUS_EXPIRED = "expired"
INVITATION_STATUS_REVOKED = "revoked"

VALID_STATUSES = {
    INVITATION_STATUS_SENT,
    INVITATION_STATUS_ACCEPTED,
    INVITATION_STATUS_EXPIRED,
    INVITATION_STATUS_REVOKED,
}

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def sanitize_csv_field(val: Any) -> str:
    """
    Protects against CSV injection (formula injection).
    If a field begins with =, +, -, @, \\t, or \\r, prepends a single quote.
    """
    s = str(val or "")
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{s}"
    return s


def init_student_invitations_schema(conn: Optional[sqlite3.Connection] = None) -> None:
    """
    Initializes SQLite tables for student invitations and admin audit logs.
    """
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS student_invitations (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                name TEXT NOT NULL,
                branch TEXT,
                graduation_year INTEGER,
                token TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'sent',
                created_by TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                accepted_at TIMESTAMP,
                accepted_by TEXT,
                revoked_at TIMESTAMP,
                revoked_by TEXT,
                resend_count INTEGER DEFAULT 0,
                last_sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_invitation_audit_logs (
                id TEXT PRIMARY KEY,
                admin_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target_email TEXT,
                invitation_id TEXT,
                details TEXT,
                ip_address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invitations_token ON student_invitations(token)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invitations_email ON student_invitations(email)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invitations_status ON student_invitations(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invitations_created ON student_invitations(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON admin_invitation_audit_logs(action)")
        conn.commit()
    finally:
        if close_after:
            conn.close()


def record_invitation_audit_log(
    admin_id: str,
    action: str,
    target_email: Optional[str] = None,
    invitation_id: Optional[str] = None,
    details: Optional[Union[Dict[str, Any], str]] = None,
    ip_address: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """
    Appends an immutable audit entry to admin_invitation_audit_logs.
    """
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    init_student_invitations_schema(conn)

    log_id = str(uuid.uuid4())
    details_str = json.dumps(details) if isinstance(details, (dict, list)) else (details or "")

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO admin_invitation_audit_logs (
                id, admin_id, action, target_email, invitation_id, details, ip_address, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (log_id, admin_id or "system", action, target_email, invitation_id, details_str, ip_address),
        )
        conn.commit()
    except Exception as exc:
        logger.error(f"Failed to record invitation audit log: {exc}")
    finally:
        if close_after:
            conn.close()


def get_invitations_sent_in_last_hour(conn: Optional[sqlite3.Connection] = None) -> int:
    """
    Calculates total invitations sent across the system in the preceding 60 minutes.
    """
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    init_student_invitations_schema(conn)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*) FROM student_invitations
            WHERE created_at >= datetime('now', '-1 hour')
               OR last_sent_at >= datetime('now', '-1 hour')
            """
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    finally:
        if close_after:
            conn.close()


def generate_invitation_csv_template() -> str:
    """
    Generates standard CSV onboarding template content for placement officers.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name", "email", "branch", "graduation_year"])
    writer.writerow(["Aarav Sharma", "aarav.sharma@college.edu", "Computer Science", 2026])
    writer.writerow(["Priya Patel", "priya.patel@college.edu", "Information Technology", 2026])
    writer.writerow(["Rohan Verma", "rohan.verma@college.edu", "Electronics & Communication", 2027])
    return output.getvalue()


def parse_and_validate_invitation_csv(
    csv_content: Union[str, bytes],
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """
    Parses an uploaded CSV file, validates rows against formatting and duplication rules,
    and returns a structured preview of valid and invalid rows.
    """
    if isinstance(csv_content, bytes):
        try:
            csv_text = csv_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            csv_text = csv_content.decode("latin-1", errors="replace")
    else:
        csv_text = csv_content

    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    init_student_invitations_schema(conn)

    try:
        # Load existing user emails from users table
        cursor = conn.cursor()
        cursor.execute("SELECT LOWER(email) FROM users")
        existing_users = {row[0] for row in cursor.fetchall() if row[0]}

        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)

        if not rows:
            return {
                "success": False,
                "error": "The uploaded CSV file is empty.",
                "total_rows": 0,
                "valid_count": 0,
                "invalid_count": 0,
                "valid_rows": [],
                "invalid_rows": [],
            }

        # Header detection and column mapping
        raw_header = rows[0]
        col_map: Dict[str, int] = {}
        for idx, col in enumerate(raw_header):
            cleaned = col.strip().lower().replace(" ", "_").replace("/", "_")
            if "name" in cleaned:
                col_map["name"] = idx
            elif "email" in cleaned:
                col_map["email"] = idx
            elif "branch" in cleaned or "dept" in cleaned or "department" in cleaned:
                col_map["branch"] = idx
            elif "year" in cleaned or "grad" in cleaned:
                col_map["graduation_year"] = idx

        if "name" not in col_map or "email" not in col_map:
            return {
                "success": False,
                "error": "Invalid CSV header. Required columns: 'name' and 'email' (optional: 'branch', 'graduation_year').",
                "total_rows": 0,
                "valid_count": 0,
                "invalid_count": 0,
                "valid_rows": [],
                "invalid_rows": [],
            }

        data_rows = rows[1:]

        # Check row limit
        if len(data_rows) > MAX_INVITE_ROWS_PER_UPLOAD:
            return {
                "success": False,
                "error": f"Upload exceeds maximum limit of {MAX_INVITE_ROWS_PER_UPLOAD} rows per CSV (found {len(data_rows)} rows).",
                "total_rows": len(data_rows),
                "valid_count": 0,
                "invalid_count": len(data_rows),
                "valid_rows": [],
                "invalid_rows": [
                    {"row_number": i + 2, "reason": "Batch exceeds maximum row limit"}
                    for i in range(len(data_rows))
                ],
            }

        valid_rows: List[Dict[str, Any]] = []
        invalid_rows: List[Dict[str, Any]] = []
        seen_emails_in_csv: set[str] = set()

        for idx, r in enumerate(data_rows):
            row_num = idx + 2  # 1-based, accounts for header
            if not any(field.strip() for field in r):
                continue  # skip completely blank lines

            name_val = r[col_map["name"]].strip() if col_map["name"] < len(r) else ""
            email_val = r[col_map["email"]].strip().lower() if col_map["email"] < len(r) else ""
            branch_val = (
                r[col_map["branch"]].strip()
                if "branch" in col_map and col_map["branch"] < len(r)
                else None
            )
            year_val_raw = (
                r[col_map["graduation_year"]].strip()
                if "graduation_year" in col_map and col_map["graduation_year"] < len(r)
                else None
            )

            row_data = {
                "row_number": row_num,
                "name": name_val,
                "email": email_val,
                "branch": branch_val or None,
                "graduation_year": None,
            }

            # 1. Name validation
            if not name_val:
                invalid_rows.append({**row_data, "reason": "Missing candidate name"})
                continue
            if len(name_val) > 100:
                invalid_rows.append({**row_data, "reason": "Name exceeds 100 characters"})
                continue

            # 2. Email format validation
            if not email_val:
                invalid_rows.append({**row_data, "reason": "Missing email address"})
                continue
            if not EMAIL_REGEX.match(email_val) or len(email_val) > 254:
                invalid_rows.append({**row_data, "reason": f"Invalid email format: '{email_val}'"})
                continue
            if not is_email_domain_allowed(email_val):
                invalid_rows.append(
                    {**row_data, "reason": f"Email domain not allowed by institutional policy: '{email_val}'"}
                )
                continue

            # 3. Duplicate within CSV check
            if email_val in seen_emails_in_csv:
                invalid_rows.append({**row_data, "reason": f"Duplicate email in CSV upload: '{email_val}'"})
                continue
            seen_emails_in_csv.add(email_val)

            # 4. Existing registered user check
            if email_val in existing_users:
                invalid_rows.append(
                    {**row_data, "reason": f"Student with email '{email_val}' is already registered"}
                )
                continue

            # 5. Graduation year validation
            if year_val_raw:
                try:
                    grad_year = int(year_val_raw)
                    if grad_year < 2000 or grad_year > 2100:
                        invalid_rows.append(
                            {**row_data, "reason": f"Graduation year out of reasonable range (2000-2100): {grad_year}"}
                        )
                        continue
                    row_data["graduation_year"] = grad_year
                except ValueError:
                    invalid_rows.append(
                        {**row_data, "reason": f"Invalid graduation year format: '{year_val_raw}'"}
                    )
                    continue

            valid_rows.append(row_data)

        return {
            "success": True,
            "total_rows": len(data_rows),
            "valid_count": len(valid_rows),
            "invalid_count": len(invalid_rows),
            "valid_rows": valid_rows,
            "invalid_rows": invalid_rows,
            "can_send": len(valid_rows) > 0,
        }
    finally:
        if close_after:
            conn.close()


def create_and_send_invitations(
    candidate_rows: List[Dict[str, Any]],
    admin_id: str,
    base_url: str = "http://localhost:5000",
    ip_address: Optional[str] = None,
    expiry_days: int = DEFAULT_INVITATION_EXPIRY_DAYS,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """
    Creates single-use, 14-day expiring invitation tokens for valid candidate rows,
    persists them in the database, sends invitation emails, and logs an admin audit entry.
    """
    if not candidate_rows:
        return {"success": False, "error": "No valid candidate rows provided.", "created_count": 0}

    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    init_student_invitations_schema(conn)

    try:
        # Check hourly quota
        current_hour_count = get_invitations_sent_in_last_hour(conn)
        if current_hour_count + len(candidate_rows) > MAX_INVITATIONS_PER_HOUR:
            remaining_quota = max(0, MAX_INVITATIONS_PER_HOUR - current_hour_count)
            return {
                "success": False,
                "error": (
                    f"Hourly invitation quota exceeded. You have already sent {current_hour_count} "
                    f"invitations in the past hour (limit is {MAX_INVITATIONS_PER_HOUR}). "
                    f"You may send up to {remaining_quota} more at this time."
                ),
                "created_count": 0,
            }

        email_svc = EmailNotificationService()
        created_invitations: List[Dict[str, Any]] = []
        cursor = conn.cursor()

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=expiry_days)
        expires_at_iso = expires_at.isoformat()
        expires_at_display = expires_at.strftime("%b %d, %Y")

        for row in candidate_rows:
            invite_id = str(uuid.uuid4())
            token = secrets.token_urlsafe(32)
            name = row.get("name", "").strip()
            email = row.get("email", "").strip().lower()
            branch = row.get("branch")
            grad_year = row.get("graduation_year")

            cursor.execute(
                """
                INSERT INTO student_invitations (
                    id, email, name, branch, graduation_year, token, status,
                    created_by, created_at, expires_at, resend_count, last_sent_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    invite_id,
                    email,
                    name,
                    branch,
                    grad_year,
                    token,
                    INVITATION_STATUS_SENT,
                    admin_id,
                    now.isoformat(),
                    expires_at_iso,
                    now.isoformat(),
                ),
            )

            invite_url = f"{base_url.rstrip('/')}/register?invite_token={token}"

            # Dispatch invitation email via existing mail settings
            mail_sent = False
            try:
                mail_sent = email_svc.send_student_invitation_email(
                    recipient_email=email,
                    student_name=name,
                    invite_url=invite_url,
                    expires_at_str=expires_at_display,
                )
            except Exception as mail_err:
                logger.error(f"Error sending invitation email to {email}: {mail_err}")

            created_invitations.append({
                "id": invite_id,
                "email": email,
                "name": name,
                "token": token,
                "invite_url": invite_url,
                "mail_sent": mail_sent,
                "expires_at": expires_at_iso,
            })

        conn.commit()

        # Record admin audit log for the batch
        record_invitation_audit_log(
            admin_id=admin_id,
            action="STUDENT_INVITATIONS_BATCH_UPLOAD",
            details={
                "count": len(created_invitations),
                "recipient_emails": [i["email"] for i in created_invitations],
                "expiry_days": expiry_days,
            },
            ip_address=ip_address,
            conn=conn,
        )

        return {
            "success": True,
            "created_count": len(created_invitations),
            "invitations": created_invitations,
        }
    finally:
        if close_after:
            conn.close()


def verify_invitation_token(token: str, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Validates a student invitation token:
    - Must exist.
    - Must not be revoked.
    - Must not be accepted (single-use guarantee).
    - Must not be expired (14-day limit).
    """
    token = (token or "").strip()
    if not token:
        return {"valid": False, "error": "No invitation token provided."}

    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    init_student_invitations_schema(conn)

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, email, name, branch, graduation_year, status, expires_at, created_at, accepted_at
            FROM student_invitations
            WHERE token = ?
            """,
            (token,),
        )
        row = cursor.fetchone()
        if not row:
            return {"valid": False, "error": "Invalid or unknown invitation token."}

        invitation = dict(row)
        status = invitation.get("status")
        expires_at_str = invitation.get("expires_at", "")

        # Check revoked
        if status == INVITATION_STATUS_REVOKED:
            return {
                "valid": False,
                "error": "This invitation link has been revoked by the placement office.",
                "status": INVITATION_STATUS_REVOKED,
                "invitation": invitation,
            }

        # Check accepted (single use)
        if status == INVITATION_STATUS_ACCEPTED:
            return {
                "valid": False,
                "error": "This invitation link has already been used.",
                "status": INVITATION_STATUS_ACCEPTED,
                "invitation": invitation,
            }

        # Check expiration
        now = datetime.now(timezone.utc)
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except Exception:
            expires_at = now - timedelta(seconds=1)

        if now > expires_at:
            if status != INVITATION_STATUS_EXPIRED:
                cursor.execute(
                    "UPDATE student_invitations SET status = 'expired' WHERE id = ?",
                    (invitation["id"],),
                )
                conn.commit()
            return {
                "valid": False,
                "error": "This invitation link has expired (14-day limit). Please request a new invitation.",
                "status": INVITATION_STATUS_EXPIRED,
                "invitation": invitation,
            }

        return {"valid": True, "invitation": invitation}
    finally:
        if close_after:
            conn.close()


def accept_invitation_token(
    token: str,
    registered_user_id: str,
    ip_address: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> bool:
    """
    Marks an invitation token as accepted upon successful user registration,
    enforcing single-use semantics and recording audit trail.
    """
    token = (token or "").strip()
    if not token:
        return False

    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    try:
        verification = verify_invitation_token(token, conn=conn)
        if not verification.get("valid"):
            return False

        invitation = verification["invitation"]
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE student_invitations
            SET status = 'accepted', accepted_at = CURRENT_TIMESTAMP, accepted_by = ?
            WHERE id = ? AND status = 'sent'
            """,
            (registered_user_id, invitation["id"]),
        )
        conn.commit()

        record_invitation_audit_log(
            admin_id="student_self_registration",
            action="STUDENT_INVITATION_ACCEPTED",
            target_email=invitation.get("email"),
            invitation_id=invitation.get("id"),
            details={"registered_user_id": registered_user_id},
            ip_address=ip_address,
            conn=conn,
        )
        return True
    finally:
        if close_after:
            conn.close()


def revoke_invitation(
    invitation_id: str,
    admin_id: str,
    reason: Optional[str] = None,
    ip_address: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """
    Revokes an active invitation link so it stops working immediately (#690).
    """
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    init_student_invitations_schema(conn)

    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, email, status FROM student_invitations WHERE id = ?",
            (invitation_id,),
        )
        row = cursor.fetchone()
        if not row:
            return {"success": False, "error": "Invitation not found."}

        status = row["status"]
        if status == INVITATION_STATUS_ACCEPTED:
            return {"success": False, "error": "Cannot revoke an already accepted invitation."}

        cursor.execute(
            """
            UPDATE student_invitations
            SET status = 'revoked', revoked_at = CURRENT_TIMESTAMP, revoked_by = ?
            WHERE id = ?
            """,
            (admin_id, invitation_id),
        )
        conn.commit()

        record_invitation_audit_log(
            admin_id=admin_id,
            action="STUDENT_INVITATION_REVOKED",
            target_email=row["email"],
            invitation_id=invitation_id,
            details={"reason": reason or "Revoked by placement officer"},
            ip_address=ip_address,
            conn=conn,
        )

        return {"success": True, "message": f"Invitation for '{row['email']}' revoked successfully."}
    finally:
        if close_after:
            conn.close()


def resend_invitation(
    invitation_id: str,
    admin_id: str,
    base_url: str = "http://localhost:5000",
    ip_address: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """
    Resends an invitation link with refreshed expiration window (#690).
    """
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    init_student_invitations_schema(conn)

    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, email, name, status, resend_count FROM student_invitations WHERE id = ?",
            (invitation_id,),
        )
        row = cursor.fetchone()
        if not row:
            return {"success": False, "error": "Invitation not found."}

        if row["status"] == INVITATION_STATUS_ACCEPTED:
            return {"success": False, "error": "Cannot resend an already accepted invitation."}

        # Check hourly quota
        current_hour_count = get_invitations_sent_in_last_hour(conn)
        if current_hour_count >= MAX_INVITATIONS_PER_HOUR:
            return {
                "success": False,
                "error": f"Hourly invitation quota of {MAX_INVITATIONS_PER_HOUR} exceeded.",
            }

        new_token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=DEFAULT_INVITATION_EXPIRY_DAYS)
        expires_at_iso = expires_at.isoformat()
        expires_at_display = expires_at.strftime("%b %d, %Y")

        cursor.execute(
            """
            UPDATE student_invitations
            SET token = ?, status = 'sent', expires_at = ?,
                resend_count = resend_count + 1, last_sent_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (new_token, expires_at_iso, invitation_id),
        )
        conn.commit()

        invite_url = f"{base_url.rstrip('/')}/register?invite_token={new_token}"
        email_svc = EmailNotificationService()
        email_svc.send_student_invitation_email(
            recipient_email=row["email"],
            student_name=row["name"],
            invite_url=invite_url,
            expires_at_str=expires_at_display,
        )

        record_invitation_audit_log(
            admin_id=admin_id,
            action="STUDENT_INVITATION_RESENT",
            target_email=row["email"],
            invitation_id=invitation_id,
            details={"new_expires_at": expires_at_iso, "resend_count": row["resend_count"] + 1},
            ip_address=ip_address,
            conn=conn,
        )

        return {"success": True, "message": f"Invitation resent to '{row['email']}'."}
    finally:
        if close_after:
            conn.close()


def list_invitations(
    status_filter: Optional[str] = None,
    search_query: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """
    Queries student invitations with summary counts, status filtering, and search.
    Automatically marks elapsed invitations as expired.
    """
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    init_student_invitations_schema(conn)

    try:
        cursor = conn.cursor()

        # Update expired sent records
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            UPDATE student_invitations
            SET status = 'expired'
            WHERE status = 'sent' AND expires_at < ?
            """,
            (now_iso,),
        )
        conn.commit()

        # Aggregate counts
        cursor.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) as sent_count,
                SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) as accepted_count,
                SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END) as expired_count,
                SUM(CASE WHEN status = 'revoked' THEN 1 ELSE 0 END) as revoked_count
            FROM student_invitations
            """
        )
        counts_row = cursor.fetchone()
        counts = {
            "total": counts_row["total"] or 0,
            "sent": counts_row["sent_count"] or 0,
            "accepted": counts_row["accepted_count"] or 0,
            "expired": counts_row["expired_count"] or 0,
            "revoked": counts_row["revoked_count"] or 0,
        }

        # Filtered query
        query = "SELECT * FROM student_invitations WHERE 1=1"
        params: List[Any] = []

        if status_filter and status_filter.lower() != "all" and status_filter.lower() in VALID_STATUSES:
            query += " AND status = ?"
            params.append(status_filter.lower())

        if search_query:
            query += " AND (email LIKE ? OR name LIKE ? OR branch LIKE ?)"
            term = f"%{search_query.strip()}%"
            params.extend([term, term, term])

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        items = [dict(row) for row in cursor.fetchall()]

        return {"counts": counts, "invitations": items}
    finally:
        if close_after:
            conn.close()


def export_invitations_csv(
    status_filter: Optional[str] = None,
    search_query: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> str:
    """
    Exports invitation status records to CSV format with formula injection sanitization.
    """
    res = list_invitations(
        status_filter=status_filter,
        search_query=search_query,
        limit=5000,
        offset=0,
        conn=conn,
    )
    items = res.get("invitations", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Name",
        "Email",
        "Branch",
        "Graduation Year",
        "Status",
        "Sent Date",
        "Expires Date",
        "Accepted Date",
        "Revoked Date",
        "Resend Count",
    ])

    for item in items:
        writer.writerow([
            sanitize_csv_field(item.get("name")),
            sanitize_csv_field(item.get("email")),
            sanitize_csv_field(item.get("branch")),
            sanitize_csv_field(item.get("graduation_year")),
            sanitize_csv_field(item.get("status")),
            sanitize_csv_field(item.get("created_at")),
            sanitize_csv_field(item.get("expires_at")),
            sanitize_csv_field(item.get("accepted_at")),
            sanitize_csv_field(item.get("revoked_at")),
            sanitize_csv_field(item.get("resend_count")),
        ])

    return output.getvalue()


def get_invitation_audit_logs(limit: int = 50, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """
    Retrieves chronological admin invitation audit records.
    """
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    init_student_invitations_schema(conn)

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, admin_id, action, target_email, invitation_id, details, ip_address, created_at
            FROM admin_invitation_audit_logs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        if close_after:
            conn.close()
