"""
Unit & Integration Tests for Interview Experience Helpful Votes (#693)
======================================================================
Tests:
1. Voting rules: one vote per user per experience, withdrawable (toggle), disallowed on own posts.
2. Moderation checks: cannot vote on reported or rejected experiences.
3. Most helpful sorting: combines with filters and pagination.
4. Privacy: voter identities are never exposed through any API response.
5. Rate limiting: throttling on repeated rapid voting attempts.
6. Contributor impact: total 'helped N students' counter calculation and profile integration.
"""

import json
import pytest

import config
from utils.database import (
    init_db,
    save_interview_experience,
    get_db_connection,
    get_interview_experiences,
)
from utils.interview_helpful_service import (
    toggle_helpful_vote,
    get_user_helpful_votes,
    get_contributor_helped_students_count,
    check_voting_rate_limit,
    ensure_helpful_votes_schema,
)
from utils.experience_search_service import search_and_filter_interview_experiences
from utils.interview_moderation import moderate_interview_experience
from app import app


@pytest.fixture
def helpful_test_env(tmp_path, monkeypatch):
    """Sets up an isolated SQLite database and seeds test interview experiences."""
    test_db = tmp_path / "test_helpful_votes.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "helpful-test-secret"

    # Seed experiences
    # exp-1 by author_alice
    save_interview_experience(
        exp_id="exp-1",
        student_id="author_alice",
        candidate_name="Alice A.",
        company_name="Google",
        role_title="Software Engineer",
        interview_date="2026-10-01",
        rounds=[{"category": "Technical", "questions": ["Explain HashMaps"]}],
        overall_verdict="Offer",
        difficulty_level="Hard",
        tips_and_preparation="Review core algorithms and system design."
    )

    # exp-2 by author_bob
    save_interview_experience(
        exp_id="exp-2",
        student_id="author_bob",
        candidate_name="Bob B.",
        company_name="Google",
        role_title="Software Engineer",
        interview_date="2026-10-05",
        rounds=[{"category": "Technical", "questions": ["Explain B-Trees"]}],
        overall_verdict="Offer",
        difficulty_level="Medium",
        tips_and_preparation="Practice graph traversals."
    )

    # exp-3 by author_alice (second post by Alice)
    save_interview_experience(
        exp_id="exp-3",
        student_id="author_alice",
        candidate_name="Alice A.",
        company_name="Amazon",
        role_title="SDE-1",
        interview_date="2026-10-12",
        rounds=[{"category": "HR", "questions": ["Tell me about customer obsession"]}],
        overall_verdict="Offer",
        difficulty_level="Medium",
        tips_and_preparation="Prepare STAR format stories."
    )

    return test_db


class TestVotingRules:
    """Acceptance criterion: One vote per user per experience, can be removed, and not possible on own posts."""

    def test_single_vote_increments_count(self, helpful_test_env):
        res = toggle_helpful_vote(experience_id="exp-1", student_id="voter_carol")
        assert res["success"] is True
        assert res["voted"] is True
        assert res["helpful_count"] == 1
        assert res["code"] == 200

    def test_toggle_withdraws_vote(self, helpful_test_env):
        # First vote adds
        res1 = toggle_helpful_vote(experience_id="exp-1", student_id="voter_carol")
        assert res1["voted"] is True
        assert res1["helpful_count"] == 1

        # Second vote removes (toggles off)
        res2 = toggle_helpful_vote(experience_id="exp-1", student_id="voter_carol")
        assert res2["success"] is True
        assert res2["voted"] is False
        assert res2["helpful_count"] == 0

    def test_multiple_distinct_users_can_vote(self, helpful_test_env):
        toggle_helpful_vote("exp-1", "user_1")
        toggle_helpful_vote("exp-1", "user_2")
        res = toggle_helpful_vote("exp-1", "user_3")
        assert res["helpful_count"] == 3

        # One user withdraws
        res_withdrawn = toggle_helpful_vote("exp-1", "user_2")
        assert res_withdrawn["voted"] is False
        assert res_withdrawn["helpful_count"] == 2

    def test_disallow_voting_on_own_post(self, helpful_test_env):
        """Author cannot vote on their own post."""
        res = toggle_helpful_vote(experience_id="exp-1", student_id="author_alice")
        assert res["success"] is False
        assert res["code"] == 403
        assert "cannot vote on your own" in res["error"].lower()

    def test_nonexistent_experience_returns_404(self, helpful_test_env):
        res = toggle_helpful_vote(experience_id="exp-nonexistent-999", student_id="user_1")
        assert res["success"] is False
        assert res["code"] == 404

    def test_disallow_voting_on_reported_experience(self, helpful_test_env):
        with get_db_connection() as conn:
            conn.execute("UPDATE interview_experiences SET reported_flag = 1 WHERE id = 'exp-1'")
            conn.commit()

        res = toggle_helpful_vote(experience_id="exp-1", student_id="voter_carol")
        assert res["success"] is False
        assert res["code"] == 400
        assert "reported" in res["error"].lower()

    def test_disallow_voting_on_rejected_experience(self, helpful_test_env):
        moderate_interview_experience(
            experience_id="exp-1",
            action="reject",
            moderator_id="admin_mod",
            reason="Violation of guidelines"
        )
        res = toggle_helpful_vote(experience_id="exp-1", student_id="voter_carol")
        assert res["success"] is False
        assert res["code"] == 400
        assert "rejected" in res["error"].lower()


class TestMostHelpfulSortingAndFilters:
    """Acceptance criterion: Most helpful sorting works together with existing filters and pagination."""

    def test_most_helpful_sorting_order(self, helpful_test_env):
        # exp-2 gets 5 votes
        for i in range(5):
            toggle_helpful_vote("exp-2", f"voter_{i}")

        # exp-1 gets 2 votes
        for i in range(2):
            toggle_helpful_vote("exp-1", f"voter_b_{i}")

        # exp-3 gets 0 votes

        # Query using search_and_filter_interview_experiences with sort_by="helpful_desc"
        res = search_and_filter_interview_experiences(sort_by="helpful_desc")
        exps = res["experiences"]
        assert len(exps) >= 3

        # Highest helpful count must be first
        assert exps[0]["id"] == "exp-2"
        assert exps[0]["helpful_count"] == 5
        assert exps[1]["id"] == "exp-1"
        assert exps[1]["helpful_count"] == 2
        assert exps[2]["id"] == "exp-3"
        assert exps[2]["helpful_count"] == 0

    def test_sorting_combines_with_company_filter(self, helpful_test_env):
        # exp-2 gets 3 votes (Google)
        for i in range(3):
            toggle_helpful_vote("exp-2", f"v_{i}")

        # exp-3 gets 10 votes (Amazon)
        for i in range(10):
            toggle_helpful_vote("exp-3", f"v_amz_{i}")

        # When filtered to Google with most helpful sorting, exp-2 must be #1 and exp-3 excluded
        res = search_and_filter_interview_experiences(company_name="Google", sort_by="most_helpful")
        exps = res["experiences"]
        assert all(e["company_name"] == "Google" for e in exps)
        assert exps[0]["id"] == "exp-2"
        assert exps[0]["helpful_count"] == 3

    def test_sorting_combines_with_pagination(self, helpful_test_env):
        for i in range(4):
            toggle_helpful_vote("exp-2", f"v_{i}")
        for i in range(2):
            toggle_helpful_vote("exp-1", f"v_a_{i}")

        # Page 1 with page_size=1
        res_p1 = search_and_filter_interview_experiences(sort_by="helpful_desc", page=1, page_size=1)
        assert len(res_p1["experiences"]) == 1
        assert res_p1["experiences"][0]["id"] == "exp-2"
        assert res_p1["total_matches"] == 3
        assert res_p1["total_pages"] == 3

        # Page 2 with page_size=1
        res_p2 = search_and_filter_interview_experiences(sort_by="helpful_desc", page=2, page_size=1)
        assert len(res_p2["experiences"]) == 1
        assert res_p2["experiences"][0]["id"] == "exp-1"

    def test_get_interview_experiences_helper_supports_helpful_sort(self, helpful_test_env):
        for i in range(3):
            toggle_helpful_vote("exp-2", f"v_{i}")

        exps = get_interview_experiences(sort_by="helpful_desc")
        assert len(exps) >= 3
        assert exps[0]["id"] == "exp-2"
        assert exps[0]["helpful_count"] == 3


class TestPrivacyAndVoterAnonymity:
    """Acceptance criterion: Voter identities are never exposed through the API."""

    def test_toggle_helpful_endpoint_does_not_leak_voters(self, client, helpful_test_env):
        toggle_helpful_vote("exp-1", "secret_voter_123")

        response = client.post(
            "/api/interview-experiences/exp-1/helpful",
            json={"student_id": "voter_456"}
        )
        assert response.status_code == 200
        data = response.get_json()

        # Check that voter identities are not in response
        assert "secret_voter_123" not in json.dumps(data)
        assert "voter_ids" not in data
        assert "voters" not in data
        assert "user_ids" not in data
        # Aggregate count is present
        assert "helpful_count" in data
        assert data["helpful_count"] == 2

    def test_search_api_does_not_leak_voters(self, client, helpful_test_env):
        toggle_helpful_vote("exp-1", "confidential_student_789")

        response = client.get("/api/interview-experiences/search?sort=helpful_desc")
        assert response.status_code == 200
        raw_text = response.get_data(as_text=True)

        assert "confidential_student_789" not in raw_text
        assert "voter" not in raw_text.lower() or "helpful" in raw_text.lower()

    def test_html_view_does_not_leak_voter_ids(self, client, helpful_test_env):
        toggle_helpful_vote("exp-1", "secret_user_999")

        response = client.get("/interview-experiences")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "secret_user_999" not in html


class TestRateLimiting:
    """Acceptance criterion: Rate limiting prevents voting spam/abuse."""

    def test_voting_rate_limit_helper(self, helpful_test_env):
        student = "rate_limit_tester"
        # Within limit
        for _ in range(10):
            allowed, rem, reset = check_voting_rate_limit(student, max_requests=10, window_seconds=60)
        # Exceeded
        allowed_exceeded, _, reset_exceeded = check_voting_rate_limit(student, max_requests=10, window_seconds=60)
        assert allowed_exceeded is False
        assert reset_exceeded > 0

    def test_api_rate_limit_throttling(self, client, helpful_test_env, monkeypatch):
        """Simulates exceeding rate limit on the voting route."""
        # Monkeypatch check_voting_rate_limit in both service and routes modules
        import utils.interview_helpful_service as svc
        import routes.interview as r_interview
        monkeypatch.setattr(svc, "check_voting_rate_limit", lambda student, *a, **k: (False, 0, 45.0))
        monkeypatch.setattr(r_interview, "check_voting_rate_limit", lambda student, *a, **k: (False, 0, 45.0))

        response = client.post(
            "/api/interview-experiences/exp-1/helpful",
            json={"student_id": "spammer_1"}
        )
        assert response.status_code == 429
        data = response.get_json()
        assert data["success"] is False
        assert "exceeded" in data["error"].lower()
        assert "retry_after" in data


class TestContributorHelpedCountAndProfile:
    """Acceptance criterion: Show the contributor a small 'helped N students' total on their profile."""

    def test_contributor_helped_students_count_aggregation(self, helpful_test_env):
        # Alice authored exp-1 and exp-3
        # exp-1 gets 3 votes
        toggle_helpful_vote("exp-1", "user_1")
        toggle_helpful_vote("exp-1", "user_2")
        toggle_helpful_vote("exp-1", "user_3")

        # exp-3 gets 2 votes
        toggle_helpful_vote("exp-3", "user_4")
        toggle_helpful_vote("exp-3", "user_5")

        # Bob authored exp-2, which gets 4 votes
        for i in range(4):
            toggle_helpful_vote("exp-2", f"bob_fan_{i}")

        # Total helped by Alice = 3 + 2 = 5
        alice_helped = get_contributor_helped_students_count("author_alice")
        assert alice_helped == 5

        # Total helped by Bob = 4
        bob_helped = get_contributor_helped_students_count("author_bob")
        assert bob_helped == 4

        # Non-contributor = 0
        assert get_contributor_helped_students_count("random_user") == 0

    def test_reported_experiences_do_not_count_toward_helped(self, helpful_test_env):
        toggle_helpful_vote("exp-1", "user_1")
        toggle_helpful_vote("exp-1", "user_2")
        assert get_contributor_helped_students_count("author_alice") == 2

        # Flag exp-1 as reported
        with get_db_connection() as conn:
            conn.execute("UPDATE interview_experiences SET reported_flag = 1 WHERE id = 'exp-1'")
            conn.commit()

        # Alice's helped count should exclude reported exp-1
        assert get_contributor_helped_students_count("author_alice") == 0

    def test_profile_view_displays_helped_students(self, client, helpful_test_env):
        # Alice receives 3 votes on exp-1
        toggle_helpful_vote("exp-1", "user_1")
        toggle_helpful_vote("exp-1", "user_2")
        toggle_helpful_vote("exp-1", "user_3")

        with client.session_transaction() as sess:
            sess["user_id"] = "author_alice"

        response = client.get("/profile")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Helped 3 students" in html

    def test_api_profile_completion_includes_helped_count(self, client, helpful_test_env):
        toggle_helpful_vote("exp-1", "user_1")

        response = client.get("/api/profile/completion?student_id=author_alice")
        assert response.status_code == 200
        data = response.get_json()
        assert data["helped_students_count"] == 1
