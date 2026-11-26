"""
Unit and Integration Tests for Saved Interview Questions & Revision Practice (#846)
==================================================================================
Acceptance Criteria Tested:
1. Bookmarks can be added and removed from the interview and the saved list.
2. A practice session can be started from saved questions.
3. Only the owner sees the list (multi-tenant privacy & data isolation).
4. Limits: max 50 saved questions per user enforced with clear error message.
5. Score recording, good score tracking, and auto-removal after 2 good scores (>= 75).
"""

import pytest
import json
import config
from utils.database import (
    init_db,
    save_interview_bookmark,
    remove_interview_bookmark,
    get_interview_bookmarks,
    get_interview_bookmark_by_id,
    is_interview_bookmarked,
    record_bookmark_score,
    MAX_BOOKMARKS_PER_STUDENT,
)
from app import app


@pytest.fixture
def test_client(tmp_path, monkeypatch):
    """Sets up an isolated test database and Flask test client."""
    test_db = tmp_path / "test_saved_questions_846.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-saved-questions-secret-846"
    app.config["WTF_CSRF_ENABLED"] = False

    with app.test_client() as client:
        yield client


# ==========================================
# 1. Bookmark Addition, Removal, and Limit Tests
# ==========================================

def test_add_and_remove_bookmark(test_client):
    """Verify bookmarks can be added and removed."""
    student_id = "student_add_rem"

    # Add bookmark
    saved = save_interview_bookmark(
        student_id=student_id,
        question_id="sq-1",
        question_text="What is the difference between process and thread?",
        category="Technical",
        company_name="Microsoft",
    )
    assert saved is True
    assert is_interview_bookmarked(student_id, "sq-1") is True

    bm = get_interview_bookmark_by_id(student_id, "sq-1")
    assert bm is not None
    assert bm["category"] == "Technical"
    assert bm["company_name"] == "Microsoft"
    assert bm["good_score_count"] == 0
    assert bm["last_score"] is None

    # Remove bookmark
    removed = remove_interview_bookmark(student_id, "sq-1")
    assert removed is True
    assert is_interview_bookmarked(student_id, "sq-1") is False


def test_bookmark_limit_enforced_at_50(test_client):
    """Verify the 50 bookmarks per student limit is strictly enforced."""
    student_id = "student_limit_test"

    # Add 50 bookmarks
    for i in range(MAX_BOOKMARKS_PER_STUDENT):
        ok = save_interview_bookmark(
            student_id=student_id,
            question_id=f"sq-limit-{i}",
            question_text=f"Question number {i}",
            category="Technical",
        )
        assert ok is True

    bookmarks = get_interview_bookmarks(student_id)
    assert len(bookmarks) == MAX_BOOKMARKS_PER_STUDENT

    # 51st bookmark should be rejected
    rejected = save_interview_bookmark(
        student_id=student_id,
        question_id="sq-limit-overflow",
        question_text="Overflow question beyond 50",
        category="Technical",
    )
    assert rejected is False
    assert len(get_interview_bookmarks(student_id)) == MAX_BOOKMARKS_PER_STUDENT

    # Updating an existing bookmark should succeed even at limit
    updated = save_interview_bookmark(
        student_id=student_id,
        question_id="sq-limit-0",
        question_text="Updated question 0 text",
        category="Behavioral",
    )
    assert updated is True


def test_api_bookmark_limit_rejection(test_client):
    """Verify POST /api/interview/bookmark returns 400 when limit is reached."""
    # Pre-populate 50 bookmarks for the session user
    with test_client.session_transaction() as sess:
        sess["user_id"] = "student_api_limit"

    for i in range(MAX_BOOKMARKS_PER_STUDENT):
        save_interview_bookmark(
            student_id="student_api_limit",
            question_id=f"api-lim-{i}",
            question_text=f"API limit question {i}",
        )

    # Attempt to add 51st via API
    resp = test_client.post("/api/interview/bookmark", json={
        "question_id": "api-lim-51",
        "question_text": "This should be blocked due to limit.",
    })
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "limit" in data["error"].lower()


# ==========================================
# 2. Multi-Tenant Ownership Isolation Tests
# ==========================================

def test_multi_tenant_ownership_privacy(test_client):
    """Verify each student only sees and modifies their own saved questions."""
    student_a = "student_user_alpha"
    student_b = "student_user_beta"

    save_interview_bookmark(
        student_id=student_a,
        question_id="private-qa",
        question_text="Student A's confidential question",
        category="Technical",
    )
    save_interview_bookmark(
        student_id=student_b,
        question_id="private-qb",
        question_text="Student B's confidential question",
        category="HR",
    )

    # Student A can only see their question
    list_a = get_interview_bookmarks(student_a)
    assert len(list_a) == 1
    assert list_a[0]["question_id"] == "private-qa"
    assert get_interview_bookmark_by_id(student_a, "private-qb") is None

    # Student B can only see their question
    list_b = get_interview_bookmarks(student_b)
    assert len(list_b) == 1
    assert list_b[0]["question_id"] == "private-qb"
    assert get_interview_bookmark_by_id(student_b, "private-qa") is None

    # Student A cannot delete Student B's bookmark
    assert remove_interview_bookmark(student_a, "private-qb") is False
    assert is_interview_bookmarked(student_b, "private-qb") is True


# ==========================================
# 3. Score Recording and Mastery Auto-Removal Tests
# ==========================================

def test_score_recording_and_auto_removal_after_two_good_scores(test_client):
    """
    Verify:
    1. Score < 75 updates last_score without incrementing good_score_count.
    2. First score >= 75 increments good_score_count to 1 and keeps the bookmark.
    3. Second score >= 75 increments good_score_count to 2 and automatically removes the item.
    """
    student_id = "student_mastery_test"
    q_id = "mastery-q1"

    save_interview_bookmark(
        student_id=student_id,
        question_id=q_id,
        question_text="Explain database sharding and partitioning strategies.",
        category="Technical",
    )

    # Attempt 1: Low score (60)
    res1 = record_bookmark_score(student_id, q_id, 60.0)
    assert res1["found"] is True
    assert res1["last_score"] == 60.0
    assert res1["good_score_count"] == 0
    assert res1["mastery"] is False
    assert res1["removed"] is False

    bm1 = get_interview_bookmark_by_id(student_id, q_id)
    assert bm1 is not None
    assert bm1["last_score"] == 60.0
    assert bm1["good_score_count"] == 0

    # Attempt 2: First good score (80 >= 75)
    res2 = record_bookmark_score(student_id, q_id, 80.0)
    assert res2["found"] is True
    assert res2["last_score"] == 80.0
    assert res2["good_score_count"] == 1
    assert res2["mastery"] is False
    assert res2["removed"] is False

    bm2 = get_interview_bookmark_by_id(student_id, q_id)
    assert bm2 is not None
    assert bm2["last_score"] == 80.0
    assert bm2["good_score_count"] == 1

    # Attempt 3: Second good score (85 >= 75) -> Should be mastered and automatically removed
    res3 = record_bookmark_score(student_id, q_id, 85.0)
    assert res3["found"] is True
    assert res3["last_score"] == 85.0
    assert res3["good_score_count"] == 2
    assert res3["mastery"] is True
    assert res3["removed"] is True

    # Bookmark must be gone from saved questions
    bm3 = get_interview_bookmark_by_id(student_id, q_id)
    assert bm3 is None
    assert is_interview_bookmarked(student_id, q_id) is False


def test_api_practice_evaluate_mastery_auto_removal(test_client):
    """Test /api/interview/bookmarks/<question_id>/practice/evaluate triggers score tracking."""
    with test_client.session_transaction() as sess:
        sess["user_id"] = "student_eval_test"

    save_interview_bookmark(
        student_id="student_eval_test",
        question_id="eval-q-star",
        question_text="Tell me about a time you led a team project.",
        category="Behavioral",
    )

    # First evaluation
    resp1 = test_client.post("/api/interview/bookmarks/eval-q-star/practice/evaluate", json={
        "answer": "In my previous project as lead developer, our situation was a strict deadline. My task was coordinating 4 developers. I organized daily scrums, which resulted in on-time delivery with 0 critical bugs."
    })
    assert resp1.status_code == 200
    data1 = resp1.get_json()
    assert data1["success"] is True
    assert "mastery" in data1
    assert data1["mastery"]["good_score_count"] >= 1

    # If first score was good, send another good answer to trigger auto-removal
    if data1["mastery"]["good_score_count"] == 1:
        resp2 = test_client.post("/api/interview/bookmarks/eval-q-star/practice/evaluate", json={
            "answer": "Another great response demonstrating structured leadership and measurable project completion."
        })
        assert resp2.status_code == 200
        data2 = resp2.get_json()
        assert data2["success"] is True
        assert data2["mastery"]["removed"] is True
        assert data2["mastery"]["mastered"] is True


# ==========================================
# 4. Practice Session from Saved Questions Tests
# ==========================================

def test_start_saved_questions_session(test_client):
    """Verify starting a mock interview practice session with saved questions."""
    with test_client.session_transaction() as sess:
        sess["user_id"] = "student_session_test"

    # Add 2 saved questions
    save_interview_bookmark(
        student_id="student_session_test",
        question_id="q-sess-1",
        question_text="Explain virtual DOM in React.",
        category="Technical",
    )
    save_interview_bookmark(
        student_id="student_session_test",
        question_id="q-sess-2",
        question_text="How do you handle conflict with a senior engineer?",
        category="Behavioral",
    )

    # Start session via API
    resp = test_client.post("/api/interview/practice/start-from-saved")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["question_count"] == 2
    assert "session_id" in data
    assert "redirect_url" in data

    # Verify session can be loaded via GET /interview/saved-session redirect
    get_resp = test_client.get("/interview/saved-session")
    assert get_resp.status_code == 302
    assert "saved_session_student_session_test" in get_resp.location


def test_start_saved_session_empty_bookmarks(test_client):
    """Verify warning when attempting to start practice with 0 saved questions."""
    with test_client.session_transaction() as sess:
        sess["user_id"] = "student_empty"

    resp = test_client.post("/api/interview/practice/start-from-saved", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "no saved questions" in data["error"].lower()


def test_saved_questions_alias_route(test_client):
    """Verify /interview/saved-questions renders the saved questions view."""
    with test_client.session_transaction() as sess:
        sess["user_id"] = "student_alias_view"

    save_interview_bookmark(
        student_id="student_alias_view",
        question_id="alias-q1",
        question_text="What is inversion of control?",
        category="Technical",
        last_score=88.0,
    )

    resp = test_client.get("/interview/saved-questions")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Bookmarked Interview Questions" in html or "Saved" in html
    assert "inversion of control" in html
    assert "Score: 88/100" in html
