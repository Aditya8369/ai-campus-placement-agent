import csv
import io
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import config
from utils.database import get_db_connection, create_user
from utils.student_invitation_service import (
    MAX_INVITE_ROWS_PER_UPLOAD,
    MAX_INVITATIONS_PER_HOUR,
    DEFAULT_INVITATION_EXPIRY_DAYS,
    INVITATION_STATUS_SENT,
    INVITATION_STATUS_ACCEPTED,
    INVITATION_STATUS_EXPIRED,
    INVITATION_STATUS_REVOKED,
    init_student_invitations_schema,
    generate_invitation_csv_template,
    parse_and_validate_invitation_csv,
    create_and_send_invitations,
    verify_invitation_token,
    accept_invitation_token,
    revoke_invitation,
    resend_invitation,
    list_invitations,
    export_invitations_csv,
    get_invitation_audit_logs,
    sanitize_csv_field,
)


@pytest.fixture(autouse=True)
def setup_invitations_db():
    """Initializes schema and cleans invitations tables before each test."""
    conn = get_db_connection()
    init_student_invitations_schema(conn)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM student_invitations")
    cursor.execute("DELETE FROM admin_invitation_audit_logs")
    conn.commit()
    conn.close()


def test_csv_template_generation():
    """Verifies that the CSV template contains required and optional columns."""
    template_str = generate_invitation_csv_template()
    reader = csv.reader(io.StringIO(template_str))
    rows = list(reader)
    assert len(rows) >= 2
    header = [c.strip().lower() for c in rows[0]]
    assert "name" in header
    assert "email" in header
    assert "branch" in header
    assert "graduation_year" in header


def test_csv_validation_valid_and_invalid_rows():
    """Valid rows are accepted and invalid rows report reasons."""
    csv_text = """name,email,branch,graduation_year
Valid Candidate,valid.candidate@college.edu,Computer Science,2026
,missing.name@college.edu,IT,2026
Missing Email,,CS,2026
Invalid Email Format,not-an-email,ECE,2027
Bad Grad Year,bad.grad@college.edu,Mechanical,1850
Another Valid,another.valid@college.edu,,2025
"""
    preview = parse_and_validate_invitation_csv(csv_text)
    assert preview["success"] is True
    assert preview["total_rows"] == 6
    assert preview["valid_count"] == 2
    assert preview["invalid_count"] == 4

    valid_emails = [r["email"] for r in preview["valid_rows"]]
    assert "valid.candidate@college.edu" in valid_emails
    assert "another.valid@college.edu" in valid_emails

    reasons = [r["reason"] for r in preview["invalid_rows"]]
    assert any("name" in r.lower() for r in reasons)
    assert any("missing email" in r.lower() for r in reasons)
    assert any("invalid email" in r.lower() for r in reasons)
    assert any("graduation year" in r.lower() for r in reasons)


def test_csv_validation_duplicate_emails_in_csv():
    """Subsequent occurrences of duplicate emails within the CSV are flagged."""
    csv_text = """name,email,branch,graduation_year
Student One,duplicate@college.edu,CS,2026
Student Two Duplicate,duplicate@college.edu,IT,2026
Student Three,duplicate@college.edu,ECE,2026
"""
    preview = parse_and_validate_invitation_csv(csv_text)
    assert preview["success"] is True
    assert preview["valid_count"] == 1
    assert preview["invalid_count"] == 2
    assert "Duplicate email in CSV upload" in preview["invalid_rows"][0]["reason"]
    assert "Duplicate email in CSV upload" in preview["invalid_rows"][1]["reason"]


def test_csv_validation_existing_registered_users():
    """Candidates with emails that already exist in the users table are flagged."""
    conn = get_db_connection()
    existing_id = str(uuid.uuid4())
    create_user(existing_id, "Existing Student", "already.registered@college.edu", "hash123")
    conn.close()

    csv_text = """name,email,branch,graduation_year
New Candidate,new.candidate@college.edu,CS,2026
Old Candidate,already.registered@college.edu,IT,2026
"""
    preview = parse_and_validate_invitation_csv(csv_text)
    assert preview["success"] is True
    assert preview["valid_count"] == 1
    assert preview["invalid_count"] == 1
    assert "already registered" in preview["invalid_rows"][0]["reason"].lower()


def test_csv_row_limit_enforcement():
    """Uploading more than MAX_INVITE_ROWS_PER_UPLOAD rows is rejected."""
    lines = ["name,email,branch,graduation_year"]
    for i in range(MAX_INVITE_ROWS_PER_UPLOAD + 10):
        lines.append(f"Student {i},student{i}@college.edu,CS,2026")
    csv_text = "\n".join(lines)

    preview = parse_and_validate_invitation_csv(csv_text)
    assert preview["success"] is False
    assert "maximum limit" in preview["error"].lower()
    assert preview["valid_count"] == 0


def test_hourly_rate_limit_enforcement():
    """Sending invitations when the hourly limit is exceeded returns an error."""
    conn = get_db_connection()
    cursor = conn.cursor()
    # Artificially insert invitations up to the limit
    now = datetime.now(timezone.utc).isoformat()
    for i in range(MAX_INVITATIONS_PER_HOUR):
        cursor.execute(
            """
            INSERT INTO student_invitations (
                id, email, name, token, status, created_by, created_at, expires_at, last_sent_at
            ) VALUES (?, ?, ?, ?, 'sent', 'admin', ?, ?, ?)
            """,
            (str(uuid.uuid4()), f"dummy{i}@test.com", f"Dummy {i}", f"token_{i}", now, now, now),
        )
    conn.commit()
    conn.close()

    candidates = [{"name": "New Person", "email": "new.person@college.edu"}]
    res = create_and_send_invitations(candidates, admin_id="admin_user")
    assert res["success"] is False
    assert "quota exceeded" in res["error"].lower()


def test_invitation_creation_and_token_verification():
    """Creates invitations with 14-day expiry and verifies token lifecycle."""
    candidates = [
        {"name": "Dev Sharma", "email": "dev.sharma@college.edu", "branch": "CS", "graduation_year": 2026}
    ]
    res = create_and_send_invitations(candidates, admin_id="admin_user")
    assert res["success"] is True
    assert res["created_count"] == 1
    token = res["invitations"][0]["token"]
    assert len(token) >= 32

    # Verification before acceptance
    check = verify_invitation_token(token)
    assert check["valid"] is True
    assert check["invitation"]["email"] == "dev.sharma@college.edu"
    assert check["invitation"]["name"] == "Dev Sharma"

    # Single-use acceptance
    accepted = accept_invitation_token(token, registered_user_id="user_12345")
    assert accepted is True

    # Verification after acceptance must fail
    check2 = verify_invitation_token(token)
    assert check2["valid"] is False
    assert "already been used" in check2["error"].lower()
    assert check2["status"] == INVITATION_STATUS_ACCEPTED

    # Re-acceptance must fail
    accepted_again = accept_invitation_token(token, registered_user_id="user_99999")
    assert accepted_again is False


def test_invitation_expiration():
    """Expired invitations stop functioning and report expired status."""
    conn = get_db_connection()
    cursor = conn.cursor()
    expired_token = "expired_token_123456789"
    past_time = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    cursor.execute(
        """
        INSERT INTO student_invitations (
            id, email, name, token, status, created_by, created_at, expires_at, last_sent_at
        ) VALUES (?, ?, ?, ?, 'sent', 'admin', ?, ?, ?)
        """,
        (str(uuid.uuid4()), "expired.candidate@college.edu", "Expired Candidate", expired_token, past_time, past_time, past_time),
    )
    conn.commit()
    conn.close()

    check = verify_invitation_token(expired_token)
    assert check["valid"] is False
    assert "expired" in check["error"].lower()
    assert check["status"] == INVITATION_STATUS_EXPIRED


def test_invitation_revocation():
    """Revoked invitations immediately stop working and log audit trail."""
    candidates = [{"name": "Revoke Test", "email": "revoke.test@college.edu"}]
    res = create_and_send_invitations(candidates, admin_id="admin_user")
    invite_id = res["invitations"][0]["id"]
    token = res["invitations"][0]["token"]

    # Revoke
    revoke_res = revoke_invitation(invite_id, admin_id="admin_user", reason="Candidate left college")
    assert revoke_res["success"] is True

    # Verification must fail
    check = verify_invitation_token(token)
    assert check["valid"] is False
    assert "revoked" in check["error"].lower()
    assert check["status"] == INVITATION_STATUS_REVOKED

    # Audit log check
    logs = get_invitation_audit_logs()
    assert any(log["action"] == "STUDENT_INVITATION_REVOKED" for log in logs)


def test_invitation_resend():
    """Resending refreshes the token, resets expiry, and records audit trail."""
    candidates = [{"name": "Resend Test", "email": "resend.test@college.edu"}]
    res = create_and_send_invitations(candidates, admin_id="admin_user")
    invite_id = res["invitations"][0]["id"]
    old_token = res["invitations"][0]["token"]

    resend_res = resend_invitation(invite_id, admin_id="admin_user")
    assert resend_res["success"] is True

    # Old token is replaced
    old_check = verify_invitation_token(old_token)
    assert old_check["valid"] is False

    # Status list reflects incremented resend count
    listing = list_invitations(search_query="resend.test@college.edu")
    inv = listing["invitations"][0]
    assert inv["resend_count"] == 1
    assert inv["status"] == INVITATION_STATUS_SENT


def test_csv_injection_protection_on_export():
    """Sanitizes formula injection prefixes on export (=, +, -, @, \\t, \\r)."""
    assert sanitize_csv_field("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0"
    assert sanitize_csv_field("+123456") == "'+123456"
    assert sanitize_csv_field("-SUM(A1:A10)") == "'-SUM(A1:A10)"
    assert sanitize_csv_field("@malicious") == "'@malicious"
    assert sanitize_csv_field("Normal Student") == "Normal Student"

    # Export CSV containing potentially dangerous student names
    candidates = [
        {"name": "=cmd|' /C calc'!A0", "email": "dangerous@college.edu", "branch": "+DangerousDept"}
    ]
    create_and_send_invitations(candidates, admin_id="admin_user")

    csv_data = export_invitations_csv()
    assert "'=cmd|" in csv_data
    assert "'+DangerousDept" in csv_data


def test_admin_authorization_guards(client):
    """Verifies that only administrative users can access student onboarding endpoints."""
    # 1. Anonymous / Student access is rejected with 403 Forbidden
    routes = [
        ("GET", "/admin/invite-students"),
        ("GET", "/admin/invitations/template.csv"),
        ("POST", "/api/admin/invitations/preview"),
        ("POST", "/api/admin/invitations/send"),
        ("GET", "/admin/invitations/export.csv"),
        ("GET", "/api/admin/invitations/audit-log"),
    ]

    for method, path in routes:
        if method == "GET":
            res = client.get(path)
        else:
            res = client.post(path, json={})
        assert res.status_code == 403, f"Expected 403 for unauthorized {method} {path}, got {res.status_code}"

    # 2. Administrator session has access
    with client.session_transaction() as sess:
        sess["is_admin"] = True
        sess["user_id"] = "admin_user"

    res_page = client.get("/admin/invite-students")
    assert res_page.status_code == 200
    assert "Invite Students in Bulk" in res_page.get_data(as_text=True)

    res_template = client.get("/admin/invitations/template.csv")
    assert res_template.status_code == 200
    assert "attachment" in res_template.headers["Content-Disposition"]

    res_preview = client.post(
        "/api/admin/invitations/preview",
        json={"csv_content": "name,email\nTest Candidate,test@college.edu"},
    )
    assert res_preview.status_code == 200
    assert res_preview.get_json()["valid_count"] == 1


def test_registration_with_invite_token_flow(client):
    """Full onboarding flow: placement officer creates invite, student registers using link."""
    from app import app
    app.config["WTF_CSRF_ENABLED"] = False

    test_email = f"ananya.{uuid.uuid4().hex[:8]}@college.edu"

    # 1. Create invitation
    candidates = [
        {
            "name": "Ananya Roy",
            "email": test_email,
            "branch": "Computer Science",
            "graduation_year": 2026,
        }
    ]
    create_res = create_and_send_invitations(candidates, admin_id="admin_user")
    token = create_res["invitations"][0]["token"]

    # 2. Student opens registration link
    res_get = client.get(f"/register?invite_token={token}")
    assert res_get.status_code == 200
    html = res_get.get_data(as_text=True)
    assert "Ananya Roy" in html
    assert test_email in html
    assert token in html

    # 3. Student submits registration
    res_post = client.post(
        "/register",
        data={
            "name": "Ananya Roy",
            "email": test_email,
            "password": "SecurePassword123!",
            "college": "Test Engineering College",
            "invite_token": token,
        },
        follow_redirects=True,
    )
    assert res_post.status_code == 200

    # 4. Token is now consumed
    check_consumed = verify_invitation_token(token)
    assert check_consumed["valid"] is False
    assert check_consumed["status"] == INVITATION_STATUS_ACCEPTED

    # 5. Subsequent attempt with same token is rejected
    res_repeat = client.post(
        "/register",
        data={
            "name": "Imposter",
            "email": f"imposter.{uuid.uuid4().hex[:8]}@college.edu",
            "password": "SecurePassword123!",
            "invite_token": token,
        },
    )
    assert "already been used" in res_repeat.get_data(as_text=True).lower()
