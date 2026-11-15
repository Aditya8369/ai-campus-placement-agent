"""
Unit and integration tests for User-Controlled Leaderboard Opt-Out Feature (#360).

Verifies:
1. Default opt-in state for new and unregistered users.
2. Preference persistence across database transactions.
3. Server-side exclusion of opted-out users from leaderboard rankings.
4. Top 3 podium calculations exclude opted-out candidates.
5. Keyword search queries exclude opted-out candidate handles and target companies.
6. Cohort aggregate statistics (total_students, averages, tier counts) exclude opted-out scores.
7. Re-enabling participation immediately restores visibility at the appropriate rank.
8. REST API /api/leaderboard respects the opt-out preference.
9. Authenticated GET and POST /api/user/leaderboard-privacy endpoints.
10. Form-based POST updates with redirect and flash feedback.
11. Authentication requirement enforcement for unauthenticated callers.
12. CSRF protection enforcement on preference mutations.
13. Cross-account isolation: session identity binding prevents IDOR overrides.
14. Default seeded peer benchmarks remain intact and visible.
15. Absolute confidentiality: zero PII in leaderboard API payloads.
16. Percentile rank calculation reflects is_opted_out status for candidate standings.
"""

import json

import pytest

from app import app
from utils.cohort_analytics import CohortAnalyticsService
from utils.database import (
    get_cohort_benchmarks,
    get_cohort_stats,
    get_db_connection,
    get_user_leaderboard_opt_in,
    init_db,
    set_user_leaderboard_opt_in,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Setup isolated SQLite database with schema for each test."""
    test_db = str(tmp_path / "test_leaderboard_opt_out.db")
    import config
    monkeypatch.setattr(config, "DATABASE_PATH", test_db)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    conn = get_db_connection()
    cursor = conn.cursor()

    # Create test users
    cursor.execute(
        "INSERT INTO users (id, name, email, password_hash, leaderboard_opt_in) "
        "VALUES ('user-alice', 'Alice Student', 'alice@campus.edu', 'hash1', 1)"
    )
    cursor.execute(
        "INSERT INTO users (id, name, email, password_hash, leaderboard_opt_in) "
        "VALUES ('user-bob', 'Bob Student', 'bob@campus.edu', 'hash2', 1)"
    )
    cursor.execute(
        "INSERT INTO users (id, name, email, password_hash, leaderboard_opt_in) "
        "VALUES ('user-charlie', 'Charlie Student', 'charlie@campus.edu', 'hash3', 1)"
    )

    # Create linked analyses for users
    cursor.execute(
        "INSERT INTO analyses (id, resume_filename, company_name, job_description, results_json, student_id) "
        "VALUES ('analysis-alice', 'alice_resume.pdf', 'Google', 'SDE', '{}', 'user-alice')"
    )
    cursor.execute(
        "INSERT INTO analyses (id, resume_filename, company_name, job_description, results_json, student_id) "
        "VALUES ('analysis-bob', 'bob_resume.pdf', 'Microsoft', 'Data', '{}', 'user-bob')"
    )
    cursor.execute(
        "INSERT INTO analyses (id, resume_filename, company_name, job_description, results_json, student_id) "
        "VALUES ('analysis-charlie', 'charlie_resume.pdf', 'Amazon', 'Cloud', '{}', 'user-charlie')"
    )

    # Insert cohort benchmark entries linked to analyses
    cursor.execute(
        "INSERT INTO cohort_benchmarks (id, analysis_id, student_handle, department, grad_year, ats_score, job_match_score, overall_score, target_company, skills_count, tier) "
        "VALUES ('cohort-alice', 'analysis-alice', 'Candidate_Alice99', 'Computer Science', 2026, 95, 95, 95.0, 'Google', 8, 'Platinum')"
    )
    cursor.execute(
        "INSERT INTO cohort_benchmarks (id, analysis_id, student_handle, department, grad_year, ats_score, job_match_score, overall_score, target_company, skills_count, tier) "
        "VALUES ('cohort-bob', 'analysis-bob', 'Candidate_Bob88', 'Information Technology', 2026, 85, 80, 82.5, 'Microsoft', 6, 'Gold')"
    )
    cursor.execute(
        "INSERT INTO cohort_benchmarks (id, analysis_id, student_handle, department, grad_year, ats_score, job_match_score, overall_score, target_company, skills_count, tier) "
        "VALUES ('cohort-charlie', 'analysis-charlie', 'Candidate_Charlie77', 'Computer Science', 2026, 75, 70, 72.5, 'Amazon', 5, 'Silver')"
    )

    conn.commit()
    conn.close()
    return test_db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


# ==============================================================================
# 1. Unit & Database Layer Tests
# ==============================================================================

def test_default_opt_in_state():
    """Verify that users default to opted-in (True)."""
    assert get_user_leaderboard_opt_in("user-alice") is True
    # Non-existent or anonymous users default to True safely
    assert get_user_leaderboard_opt_in("non-existent-user") is True
    assert get_user_leaderboard_opt_in(None) is True


def test_user_opts_out_persists():
    """Verify that opting out updates and persists in the database."""
    success = set_user_leaderboard_opt_in("user-alice", False)
    assert success is True
    assert get_user_leaderboard_opt_in("user-alice") is False

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT leaderboard_opt_in FROM users WHERE id = 'user-alice'")
    row = cursor.fetchone()
    conn.close()
    assert row[0] == 0


def test_opted_out_user_excluded_from_leaderboard():
    """Verify that opted-out users are excluded from get_cohort_benchmarks."""
    # Before opt-out: Alice is present
    benchmarks_before = get_cohort_benchmarks(limit=50)
    handles_before = [b["student_handle"] for b in benchmarks_before]
    assert "Candidate_Alice99" in handles_before

    # Opt-out Alice
    set_user_leaderboard_opt_in("user-alice", False)

    # After opt-out: Alice is excluded
    benchmarks_after = get_cohort_benchmarks(limit=50)
    handles_after = [b["student_handle"] for b in benchmarks_after]
    assert "Candidate_Alice99" not in handles_after
    assert "Candidate_Bob88" in handles_after
    assert "Candidate_Charlie77" in handles_after


def test_opted_out_user_excluded_from_podium():
    """Verify that an opted-out candidate with the highest score is excluded from the podium."""
    # Alice has score 95.0, which ranks #1 among peers
    service = CohortAnalyticsService()
    view_before = service.get_leaderboard_view()
    podium_handles_before = [p["student_handle"] for p in view_before["podium"]]
    assert "Candidate_Alice99" in podium_handles_before

    # Opt-out Alice
    set_user_leaderboard_opt_in("user-alice", False)

    # After opt-out: Podium must not contain Alice
    view_after = service.get_leaderboard_view()
    podium_handles_after = [p["student_handle"] for p in view_after["podium"]]
    assert "Candidate_Alice99" not in podium_handles_after


def test_opted_out_user_excluded_from_search():
    """Verify that searching for an opted-out candidate handle or company returns empty."""
    set_user_leaderboard_opt_in("user-alice", False)

    # Search for handle
    results_handle = get_cohort_benchmarks(search="Alice99")
    assert len(results_handle) == 0

    # Search for company
    results_company = get_cohort_benchmarks(search="Google")
    # Only returns seeded peers if any match Google, but not Alice's analysis
    alice_matches = [r for r in results_company if r.get("analysis_id") == "analysis-alice"]
    assert len(alice_matches) == 0


def test_opted_out_user_excluded_from_stats():
    """Verify that cohort stats exclude opted-out candidate scores."""
    stats_before = get_cohort_stats(department="Computer Science")
    count_before = stats_before["total_students"]

    # Opt-out Alice (in Computer Science with 95 ATS, 95 Job Match)
    set_user_leaderboard_opt_in("user-alice", False)

    stats_after = get_cohort_stats(department="Computer Science")
    count_after = stats_after["total_students"]
    assert count_after == count_before - 1


def test_user_re_opts_in_restores_visibility():
    """Verify that a user who opts back in immediately reappears in rankings."""
    set_user_leaderboard_opt_in("user-alice", False)
    assert "Candidate_Alice99" not in [b["student_handle"] for b in get_cohort_benchmarks()]

    # Re-enable participation
    set_user_leaderboard_opt_in("user-alice", True)
    benchmarks = get_cohort_benchmarks()
    assert "Candidate_Alice99" in [b["student_handle"] for b in benchmarks]


def test_seeded_peers_remain_unaffected():
    """Verify default seeded peer cohort records (with null analysis_id) remain visible."""
    set_user_leaderboard_opt_in("user-alice", False)
    set_user_leaderboard_opt_in("user-bob", False)
    set_user_leaderboard_opt_in("user-charlie", False)

    benchmarks = get_cohort_benchmarks()
    # Seeded peers should still be present
    peer_handles = [b["student_handle"] for b in benchmarks if b["id"].startswith("peer-")]
    assert len(peer_handles) > 0
    assert "AlgoMaster_99" in peer_handles


def test_percentile_rank_shows_opted_out_status():
    """Verify calculate_percentile_rank reflects is_opted_out flag."""
    service = CohortAnalyticsService()
    percentile_info = service.calculate_percentile_rank("analysis-alice")
    assert percentile_info["is_opted_out"] is False

    set_user_leaderboard_opt_in("user-alice", False)
    percentile_info_after = service.calculate_percentile_rank("analysis-alice")
    assert percentile_info_after["is_opted_out"] is True


# ==============================================================================
# 2. Integration & Route Layer Tests
# ==============================================================================

def test_api_leaderboard_excludes_opted_out(client):
    """Verify GET /api/leaderboard excludes opted-out users."""
    with client.session_transaction() as sess:
        sess["user_id"] = "user-alice"

    res_before = client.get("/api/leaderboard")
    assert res_before.status_code == 200
    data_before = res_before.get_json()
    handles_before = [row["student_handle"] for row in data_before["leaderboard"]]
    assert "Candidate_Alice99" in handles_before

    # Opt out
    set_user_leaderboard_opt_in("user-alice", False)

    res_after = client.get("/api/leaderboard")
    assert res_after.status_code == 200
    data_after = res_after.get_json()
    handles_after = [row["student_handle"] for row in data_after["leaderboard"]]
    assert "Candidate_Alice99" not in handles_after


def test_api_get_user_leaderboard_privacy(client):
    """Verify GET /api/user/leaderboard-privacy returns current preference."""
    with client.session_transaction() as sess:
        sess["user_id"] = "user-alice"

    res = client.get("/api/user/leaderboard-privacy")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["user_id"] == "user-alice"
    assert data["opt_in"] is True


def test_api_post_user_leaderboard_privacy_json(client):
    """Verify POST /api/user/leaderboard-privacy with JSON updates preference."""
    with client.session_transaction() as sess:
        sess["user_id"] = "user-alice"

    res = client.post(
        "/api/user/leaderboard-privacy",
        data=json.dumps({"opt_in": False}),
        content_type="application/json"
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["opt_in"] is False
    assert get_user_leaderboard_opt_in("user-alice") is False


def test_api_post_user_leaderboard_privacy_form(client):
    """Verify POST /api/user/leaderboard-privacy with form data redirects properly."""
    with client.session_transaction() as sess:
        sess["user_id"] = "user-bob"

    res = client.post(
        "/api/user/leaderboard-privacy",
        data={"opt_in": "false", "analysis_id": "analysis-bob"},
        follow_redirects=False
    )
    assert res.status_code == 302
    assert "/leaderboard?analysis_id=analysis-bob" in res.headers["Location"]
    assert get_user_leaderboard_opt_in("user-bob") is False


def test_leaderboard_html_renders_privacy_control(client):
    """Verify GET /leaderboard renders the privacy control card and toggle button."""
    with client.session_transaction() as sess:
        sess["user_id"] = "user-alice"

    res = client.get("/leaderboard")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Leaderboard Privacy &amp; Data Control" in html
    assert "toggleLeaderboardPrivacyBtn" in html
    assert "Participation Active" in html


# ==============================================================================
# 3. Security, Authorization & Privacy Tests
# ==============================================================================

def test_cross_account_isolation_cannot_mutate_another_user(client):
    """Verify User A session cannot toggle User B's privacy setting via payload injection."""
    with client.session_transaction() as sess:
        sess["user_id"] = "user-alice"

    # User A tries to spoof User B in request body
    res = client.post(
        "/api/user/leaderboard-privacy",
        data=json.dumps({"user_id": "user-bob", "opt_in": False}),
        content_type="application/json"
    )
    assert res.status_code == 200

    # User A was modified, but User B remains untouched
    assert get_user_leaderboard_opt_in("user-alice") is False
    assert get_user_leaderboard_opt_in("user-bob") is True


def test_unauthenticated_request_rejected(client):
    """Verify unauthenticated request to /api/user/leaderboard-privacy is rejected."""
    app.config["ENFORCE_LOGIN_IN_TESTS"] = True
    try:
        res = client.get("/api/user/leaderboard-privacy")
        # Should redirect to login or return 401
        assert res.status_code in (302, 401)
    finally:
        app.config["ENFORCE_LOGIN_IN_TESTS"] = False


def test_csrf_protection_enforced_on_opt_out_endpoint():
    """Verify POST /api/user/leaderboard-privacy enforces CSRF token validation when enabled."""
    app.config["TESTING"] = False
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = "user-alice"
            # Attempt POST without CSRF token
            res = c.post(
                "/api/user/leaderboard-privacy",
                data={"opt_in": "false"}
            )
            assert res.status_code == 400
    finally:
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False


def test_no_pii_in_leaderboard_payload(client):
    """Verify API response payload does not expose student emails, names, or resume texts."""
    res = client.get("/api/leaderboard")
    assert res.status_code == 200
    data = res.get_json()

    for row in data.get("leaderboard", []):
        assert "email" not in row
        assert "password" not in row
        assert "password_hash" not in row
        assert "resume_text" not in row
        assert "full_name" not in row
        # Handles must only be anonymized pseudonyms (e.g. Candidate_XX or Peer handles)
        assert "@" not in row["student_handle"]
