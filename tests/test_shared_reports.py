"""
Unit tests for Secure Report-Sharing Link with Expiration, Revocation, and Redaction (#408, #468).
"""

import datetime as dt
import pytest
from app import app
from utils.database import get_db_connection, init_db
from utils.shared_reports_service import (
    init_shared_links_table,
    create_shared_report_link,
    get_shared_report_by_token,
    revoke_shared_link,
    list_user_active_shares,
    SharePermissionError,
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def clean_shared_reports_tables():
    init_db()
    init_shared_links_table()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM secure_shared_reports")
    cursor.execute("DELETE FROM analyses WHERE id LIKE 'test-share-%'")
    # Seed an analysis
    cursor.execute(
        """
        INSERT INTO analyses (id, student_id, resume_filename, company_name, job_description, results_json)
        VALUES (
            'test-share-aid-1',
            'student-alice',
            'alice_resume.pdf',
            'Uber Technologies',
            'Backend Engineer with Python and Distributed Systems experience.',
            '{"resume_analysis": {"ats_score": 88, "strengths": ["Python expertise"], "improvements": ["Add Docker"]}}'
        )
        """
    )
    conn.commit()
    conn.close()
    yield
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM secure_shared_reports")
    cursor.execute("DELETE FROM analyses WHERE id LIKE 'test-share-%'")
    conn.commit()
    conn.close()


def test_create_and_view_shared_report():
    created = create_shared_report_link(
        analysis_id="test-share-aid-1",
        student_id="student-alice",
        expiration_choice="24h"
    )
    assert created["success"] is True
    token = created["token"]
    assert len(token) > 20

    # Retrieve by token
    valid, report, err = get_shared_report_by_token(token)
    assert valid is True
    assert err is None
    assert report["company_name"] == "Uber Technologies"
    assert report["results"]["resume_analysis"]["ats_score"] == 88
    assert report["view_count"] == 1
    assert report["last_viewed_at"] is not None


def test_share_report_ownership_enforcement():
    # Bob attempts to share Alice's analysis
    with pytest.raises(KeyError):
        create_shared_report_link(
            analysis_id="test-share-aid-1",
            student_id="student-bob",
            expiration_choice="24h"
        )


def test_revoke_shared_report():
    created = create_shared_report_link(
        analysis_id="test-share-aid-1",
        student_id="student-alice",
        expiration_choice="1h"
    )
    token = created["token"]
    share_id = created["share_id"]

    # Revoke
    revoked = revoke_shared_link("student-alice", share_id)
    assert revoked is True

    # Try viewing
    valid, report, err = get_shared_report_by_token(token)
    assert valid is False
    assert "revoked" in err


def test_api_report_share_endpoints(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "student-alice"

    # POST create share
    res_post = client.post(
        "/api/reports/share",
        json={"analysis_id": "test-share-aid-1", "expiration": "7d"}
    )
    assert res_post.status_code == 201
    data = res_post.get_json()
    token = data["token"]
    share_id = data["share_id"]

    # GET shared view (public, read-only)
    res_view = client.get(f"/shared/report/{token}")
    assert res_view.status_code == 200
    content = res_view.data.decode("utf-8")
    assert "Read-Only Shared Report" in content
    assert "Uber Technologies" in content
    assert res_view.headers.get("X-Robots-Tag") == "noindex, nofollow, noarchive"
    assert '<meta name="robots" content="noindex, nofollow, noarchive">' in content

    # POST revoke
    res_rev = client.post(f"/api/reports/share/{share_id}/revoke")
    assert res_rev.status_code == 200

    # View again after revocation
    res_view_rev = client.get(f"/shared/report/{token}")
    assert res_view_rev.status_code == 404
    err_content = res_view_rev.data.decode("utf-8")
    assert "Link No Longer Valid" in err_content
    assert "revoked" in err_content
    assert res_view_rev.headers.get("X-Robots-Tag") == "noindex, nofollow, noarchive"


def test_expired_shared_link(client):
    # Manually insert an expired link
    conn = get_db_connection()
    cursor = conn.cursor()
    past_time = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        INSERT INTO secure_shared_reports (id, token, analysis_id, student_id, is_active, expires_at)
        VALUES ('shr-expired-1', 'expired-token-12345', 'test-share-aid-1', 'student-alice', 1, ?)
        """,
        (past_time,)
    )
    conn.commit()
    conn.close()

    # Viewing expired token
    valid, report, err = get_shared_report_by_token("expired-token-12345")
    assert valid is False
    assert "expired" in err

    res = client.get("/shared/report/expired-token-12345")
    assert res.status_code == 404
    body = res.data.decode("utf-8")
    assert "Link No Longer Valid" in body
    assert "expired" in body
    assert res.headers.get("X-Robots-Tag") == "noindex, nofollow, noarchive"


def test_wrong_or_invalid_token(client):
    valid, report, err = get_shared_report_by_token("non-existent-token-xyz")
    assert valid is False

    res = client.get("/shared/report/non-existent-token-xyz")
    assert res.status_code == 404
    body = res.data.decode("utf-8")
    assert "Link No Longer Valid" in body
    assert res.headers.get("X-Robots-Tag") == "noindex, nofollow, noarchive"


def test_redaction_of_personal_details_in_shared_report(client):
    # Seed an analysis containing candidate PII: email, phone, physical address, personal link
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO analyses (id, student_id, resume_filename, company_name, job_description, results_json)
        VALUES (
            'test-share-aid-pii',
            'student-alice',
            'alice_pii_resume.pdf',
            'Google Contact: recruiter@google.com',
            'Reach out at hiring@google.com or call +1 650 253 0000',
            '{"resume_analysis": {"ats_score": 92, "candidate_email": "alice.student@example.com", "raw_text": "Candidate Alice.\\nEmail: alice.student@example.com\\nPhone: +91 98765 43210\\nAddress: 123 MG Road, Bengaluru 560001\\nProfile: https://linkedin.com/in/alicestudent"}}'
        )
        """
    )
    conn.commit()
    conn.close()

    created = create_shared_report_link("test-share-aid-pii", "student-alice", "24h")
    token = created["token"]

    valid, report, err = get_shared_report_by_token(token)
    assert valid is True

    # Check that PII is redacted in structured report dict
    assert "alice.student@example.com" not in str(report)
    assert "98765 43210" not in str(report)
    assert "123 MG Road" not in str(report)
    assert "https://linkedin.com/in/alicestudent" not in str(report)
    assert "student_id" not in report
    assert "[EMAIL]" in str(report)
    assert "[PHONE]" in str(report)
    assert "[ADDRESS]" in str(report)
    assert "[LINK]" in str(report)

    # Check HTTP response content
    res = client.get(f"/shared/report/{token}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "alice.student@example.com" not in html
    assert "98765 43210" not in html
    assert "123 MG Road" not in html


def test_shared_page_hides_edit_delete_download_actions(client):
    created = create_shared_report_link("test-share-aid-1", "student-alice", "24h")
    token = created["token"]

    res = client.get(f"/shared/report/{token}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Ensure actions (edit, delete, download, account settings) are absent
    assert 'btn-delete' not in html
    assert 'action="/delete' not in html
    assert 'download_report' not in html
    assert 'Download .docx' not in html
    assert 'Download .txt' not in html
    assert 'Download PDF' not in html
    assert 'Edit Analysis' not in html
    assert 'Read-Only Shared Report' in html


def test_view_tracking_increments_and_updates_timestamp(client):
    created = create_shared_report_link("test-share-aid-1", "student-alice", "24h")
    token = created["token"]

    # Initial view count should be 0 before any access
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT view_count, last_viewed_at FROM secure_shared_reports WHERE token = ?", (token,))
    row = cursor.fetchone()
    assert row["view_count"] == 0
    assert row["last_viewed_at"] is None
    conn.close()

    # First access
    res1 = client.get(f"/shared/report/{token}")
    assert res1.status_code == 200
    assert "Views: 1" in res1.data.decode("utf-8")

    # Second access
    res2 = client.get(f"/shared/report/{token}")
    assert res2.status_code == 200
    assert "Views: 2" in res2.data.decode("utf-8")

    # Verify database state
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT view_count, last_viewed_at FROM secure_shared_reports WHERE token = ?", (token,))
    row2 = cursor.fetchone()
    assert row2["view_count"] == 2
    assert row2["last_viewed_at"] is not None
    conn.close()


def test_authorization_non_owner_cannot_create_or_revoke(client):
    # Alice creates analysis
    # Bob attempts to create share link via API -> 403
    with client.session_transaction() as sess:
        sess["user_id"] = "student-bob"

    res_bob_create = client.post(
        "/api/reports/share",
        json={"analysis_id": "test-share-aid-1", "expiration": "24h"}
    )
    assert res_bob_create.status_code == 403

    # Alice creates a share link
    with client.session_transaction() as sess:
        sess["user_id"] = "student-alice"

    res_alice_create = client.post(
        "/api/reports/share",
        json={"analysis_id": "test-share-aid-1", "expiration": "24h"}
    )
    assert res_alice_create.status_code == 201
    share_id = res_alice_create.get_json()["share_id"]

    # Bob attempts to revoke Alice's share link -> 403
    with client.session_transaction() as sess:
        sess["user_id"] = "student-bob"

    res_bob_revoke = client.post(f"/api/reports/share/{share_id}/revoke")
    assert res_bob_revoke.status_code == 403

    # Alice revokes her own link -> 200
    with client.session_transaction() as sess:
        sess["user_id"] = "student-alice"

    res_alice_revoke = client.post(f"/api/reports/share/{share_id}/revoke")
    assert res_alice_revoke.status_code == 200


def test_list_shares_endpoint(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "student-alice"

    # Create two shares for test-share-aid-1
    client.post("/api/reports/share", json={"analysis_id": "test-share-aid-1", "expiration": "24h"})
    client.post("/api/reports/share", json={"analysis_id": "test-share-aid-1", "expiration": "7d"})

    res = client.get("/api/reports/test-share-aid-1/shares")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert len(data["shares"]) == 2
    assert "token" in data["shares"][0]
    assert "view_count" in data["shares"][0]
    assert "share_url" in data["shares"][0]


def test_anonymous_mentor_access_requires_no_login(client):
    # Enable login enforcement in tests to verify public endpoint bypassing
    app.config["ENFORCE_LOGIN_IN_TESTS"] = True
    try:
        created = create_shared_report_link("test-share-aid-1", "student-alice", "24h")
        token = created["token"]

        # An unauthenticated user (mentor) makes request without any session cookie
        anon_client = app.test_client()
        res = anon_client.get(f"/shared/report/{token}")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "Read-Only Shared Report" in html
        assert "Uber Technologies" in html
        assert res.headers.get("X-Robots-Tag") == "noindex, nofollow, noarchive"
    finally:
        app.config["ENFORCE_LOGIN_IN_TESTS"] = False
