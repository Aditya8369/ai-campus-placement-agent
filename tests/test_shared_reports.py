"""
Unit tests for Secure Report-Sharing Link Service (#408).
"""

import datetime as dt
import pytest
from app import app
from utils.database import get_db_connection, init_db
from utils.shared_reports_service import (
    create_shared_report_link,
    get_shared_report_by_token,
    revoke_shared_link
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
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS secure_shared_reports")
    cursor.execute("DELETE FROM analyses WHERE id LIKE 'test-share-%'")
    # Seed an analysis
    cursor.execute(
        """
        INSERT INTO analyses (id, student_id, resume_filename, company_name, job_description, results_json)
        VALUES ('test-share-aid-1', 'student-alice', 'cv.pdf', 'Uber', 'Backend Engineer', '{"resume_analysis": {"ats_score": 88}}')
        """
    )
    conn.commit()
    conn.close()
    yield
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS secure_shared_reports")
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
    assert report["company_name"] == "Uber"
    assert report["results"]["resume_analysis"]["ats_score"] == 88
    assert report["view_count"] == 1


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
    assert "Read-Only Shared Report" in res_view.data.decode("utf-8")
    assert "Uber" in res_view.data.decode("utf-8")

    # POST revoke
    res_rev = client.post(f"/api/reports/share/{share_id}/revoke")
    assert res_rev.status_code == 200

    # View again after revocation
    res_view_rev = client.get(f"/shared/report/{token}")
    assert res_view_rev.status_code == 404
    assert "revoked" in res_view_rev.data.decode("utf-8")
