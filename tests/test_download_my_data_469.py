"""
Unit & Integration Tests for User Data Download & Portability (#469)
===================================================================
Acceptance Criteria:
1. The file contains only the requesting user's data (multi-tenant isolation).
2. Password hashes, session tokens, and security credentials are never included.
3. Large histories download without timing out (on-demand streaming chunks, zero server disk storage).
4. Tests confirm one user cannot export another user's records.
5. Mentioned on the privacy page and accessible via "Download my data" on the profile page.
"""

import json
import zipfile
import io
import pytest

import config
from app import app
from utils.database import (
    init_db,
    save_job_application,
    create_preparation_note,
    save_coding_bookmark,
    save_calendar_event,
    save_analysis,
    create_user,
    get_db_connection,
)
from utils.student_data_exporter import (
    build_student_data_export_manifest,
    generate_student_data_zip_package,
    stream_student_data_json_chunks,
)


@pytest.fixture
def data_env(tmp_path, monkeypatch):
    """Sets up an isolated database with seeded users and placement records."""
    test_db = tmp_path / "test_download_data.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    # Seed User 1 (Alice) with account and placement records
    create_user(
        user_id="user_alice",
        name="Alice Walker",
        email="alice@campus.edu",
        password_hash="argon2$fake_hash_secret_alice_12345"
    )

    save_job_application(
        app_id="app_alice_101",
        student_id="user_alice",
        company_name="Google",
        role_title="Site Reliability Engineer",
        status="Interviewing",
        application_date="2026-11-10",
        notes="First technical interview scheduled on distributed systems."
    )

    create_preparation_note(
        student_id="user_alice",
        title="Distributed Consensus Notes",
        description="Raft and Paxos leader election algorithms.",
        category="System Design"
    )

    save_calendar_event(
        event_id="cal_alice_201",
        student_id="user_alice",
        title="Google System Design Round",
        event_type="interview",
        event_date="2026-11-25"
    )

    save_analysis(
        analysis_id="analysis_alice_301",
        resume_filename="alice_resume.pdf",
        company_name="Google",
        job_description="SRE Role",
        results_dict={"ats_score": 92, "recommendations": ["Review Paxos"]},
        student_id="user_alice"
    )

    # Seed User 2 (Bob) with separate records
    create_user(
        user_id="user_bob",
        name="Bob Martin",
        email="bob@campus.edu",
        password_hash="argon2$fake_hash_secret_bob_67890"
    )

    save_job_application(
        app_id="app_bob_201",
        student_id="user_bob",
        company_name="Amazon",
        role_title="Backend Developer",
        status="Applied",
        application_date="2026-11-12",
        notes="Applied via student placement portal."
    )

    create_preparation_note(
        student_id="user_bob",
        title="B-Trees & Indexing",
        description="Database indexing internals.",
        category="Databases"
    )

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "portability-test-secret"

    with app.test_client() as client:
        yield client


def test_download_data_as_json_stream(data_env):
    """Verify endpoint streams on-demand JSON attachment containing the user's data."""
    with data_env.session_transaction() as sess:
        sess["user_id"] = "user_alice"

    response = data_env.get("/api/student/data-export/download?format=json")
    assert response.status_code == 200
    assert response.mimetype == "application/json"
    disp = response.headers.get("Content-Disposition", "")
    assert "attachment" in disp
    assert "placement_data_export_user_alice" in disp
    assert disp.endswith('.json"')

    # Verify streamed JSON payload is valid and complete
    payload = json.loads(response.data.decode("utf-8"))
    assert payload["metadata"]["student_id"] == "user_alice"
    assert payload["profile"]["account"]["name"] == "Alice Walker"
    assert payload["profile"]["account"]["email"] == "alice@campus.edu"

    # Verify Alice's records are present
    apps = [a["company_name"] for a in payload["job_applications"]]
    assert "Google" in apps
    notes = [n["title"] for n in payload["preparation_notes"]]
    assert "Distributed Consensus Notes" in notes


def test_download_data_as_zip(data_env):
    """Verify endpoint provides a downloadable ZIP package when requested."""
    with data_env.session_transaction() as sess:
        sess["user_id"] = "user_alice"

    response = data_env.get("/api/student/data-export/download?format=zip")
    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    disp = response.headers.get("Content-Disposition", "")
    assert "attachment" in disp
    assert ".zip" in disp

    # Inspect ZIP buffer contents
    with zipfile.ZipFile(io.BytesIO(response.data), "r") as zf:
        names = zf.namelist()
        assert "student_placement_data_complete.json" in names
        assert "profile.json" in names
        assert "job_applications.json" in names
        assert "README.md" in names

        complete_json = json.loads(zf.read("student_placement_data_complete.json").decode("utf-8"))
        assert complete_json["metadata"]["student_id"] == "user_alice"


def test_multi_tenant_isolation_cannot_export_other_user(data_env):
    """Verify one student CANNOT export another student's records by tampering with query parameters."""
    # Alice is logged in
    with data_env.session_transaction() as sess:
        sess["user_id"] = "user_alice"

    # Alice maliciously passes student_id=user_bob in the URL query string
    response = data_env.get("/api/student/data-export/download?format=json&student_id=user_bob")
    assert response.status_code == 200
    payload = json.loads(response.data.decode("utf-8"))

    # Must still strictly return Alice's data, ignoring Bob's ID
    assert payload["metadata"]["student_id"] == "user_alice"
    companies = [a["company_name"] for a in payload["job_applications"]]
    assert "Google" in companies
    assert "Amazon" not in companies  # Bob's application must not appear

    # Now Bob logs in
    with data_env.session_transaction() as sess:
        sess["user_id"] = "user_bob"

    # Bob maliciously requests Alice's data
    resp_bob = data_env.get("/api/student/data-export/download?format=json&student_id=user_alice")
    assert resp_bob.status_code == 200
    payload_bob = json.loads(resp_bob.data.decode("utf-8"))

    assert payload_bob["metadata"]["student_id"] == "user_bob"
    bob_companies = [a["company_name"] for a in payload_bob["job_applications"]]
    assert "Amazon" in bob_companies
    assert "Google" not in bob_companies  # Alice's application must not appear


def test_password_hashes_and_tokens_are_never_included(data_env):
    """Verify password hashes, reset tokens, and security credentials are fundamentally absent."""
    with data_env.session_transaction() as sess:
        sess["user_id"] = "user_alice"

    response = data_env.get("/api/student/data-export/download?format=json")
    raw_text = response.data.decode("utf-8").lower()

    # Strict exclusions check
    assert "password_hash" not in raw_text
    assert "argon2" not in raw_text
    assert "fake_hash_secret" not in raw_text
    assert "token_hash" not in raw_text
    assert "session_token" not in raw_text
    assert "auth_session" not in raw_text
    assert "secret_key" not in raw_text


def test_streaming_large_history_without_timeouts(data_env):
    """Verify stream_student_data_json_chunks streams large histories in chunks without memory blowout."""
    # Seed 150 additional records for Alice to test streaming volume
    with get_db_connection() as conn:
        cursor = conn.cursor()
        for i in range(150):
            cursor.execute("""
                INSERT INTO job_applications (id, student_id, company_name, role_title, status, application_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (f"app_bulk_{i}", "user_alice", f"Company_{i}", "Engineer", "Applied", "2026-11-01", f"Detailed interview notes and prep syllabus #{i} " * 20))
        conn.commit()

    chunks = list(stream_student_data_json_chunks("user_alice"))
    assert len(chunks) > 1  # Verify it yielded multiple streamed chunks progressively

    full_output = "".join(chunks)
    parsed = json.loads(full_output)
    assert parsed["metadata"]["student_id"] == "user_alice"
    assert len(parsed["job_applications"]) >= 151


def test_profile_page_download_buttons_and_privacy_notice(data_env):
    """Verify profile.html has Download My Data buttons and privacy.html explains data portability."""
    with data_env.session_transaction() as sess:
        sess["user_id"] = "user_alice"

    # Profile page check
    res_profile = data_env.get("/profile")
    assert res_profile.status_code == 200
    html_profile = res_profile.data.decode("utf-8")
    assert "Download My Data" in html_profile
    assert "btnDownloadDataJson" in html_profile
    assert "btnDownloadDataZip" in html_profile
    assert "format=json" in html_profile
    assert "format=zip" in html_profile

    # Privacy page check
    res_privacy = data_env.get("/privacy")
    assert res_privacy.status_code == 200
    html_privacy = res_privacy.data.decode("utf-8")
    assert "Data Portability" in html_privacy
    assert "Download Your Data" in html_privacy
    assert "format=json" in html_privacy


def test_profile_download_data_route_alias(data_env):
    """Verify /profile/download-data route alias works seamlessly."""
    with data_env.session_transaction() as sess:
        sess["user_id"] = "user_alice"

    res = data_env.get("/profile/download-data?format=json")
    assert res.status_code == 200
    assert res.mimetype == "application/json"
    assert "attachment" in res.headers.get("Content-Disposition", "")
    data = json.loads(res.data.decode("utf-8"))
    assert data["metadata"]["student_id"] == "user_alice"
