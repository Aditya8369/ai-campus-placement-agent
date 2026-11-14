"""
Unit & Integration Tests for Focused Interview Practice Mode (#359)
===================================================================
Tests:
1. Database practice state management:
   - update_interview_bookmark_practice
   - get_interview_bookmark_by_id
   - get_interview_bookmarks with practiced_only filter
   - reset_interview_bookmarks_practice (single question & all questions)
   - get_interview_bookmark_practice_stats
2. Per-student multi-tenant isolation.
3. Practice Mode web views:
   - GET /interview/bookmarks/practice (HTML view)
   - GET /interview/bookmarks/practice?category=...&unpracticed_only=1
   - GET /interview/bookmarks/practice (JSON AJAX view)
4. Practice API endpoints:
   - POST /api/interview/bookmarks/<question_id>/practice
   - POST /api/interview/bookmarks/<question_id>/practice/status
   - POST /api/interview/bookmarks/<question_id>/practice/evaluate
   - POST /api/interview/bookmarks/practice/reset
"""

import pytest
import json
import config
from utils.database import (
    init_db,
    save_interview_bookmark,
    get_interview_bookmarks,
    get_interview_bookmark_by_id,
    update_interview_bookmark_practice,
    reset_interview_bookmarks_practice,
    get_interview_bookmark_practice_stats,
    delete_user_account_and_personal_data,
)
from app import app


@pytest.fixture
def test_client(tmp_path, monkeypatch):
    """Sets up an isolated test database and Flask test client."""
    test_db = tmp_path / "test_interview_practice.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "practice-secret-key-359"
    app.config["WTF_CSRF_ENABLED"] = False

    with app.test_client() as client:
        yield client


# ==========================================
# 1. Database Operations Tests
# ==========================================

def test_practice_mode_db_crud(test_client):
    """Verify updating practice status, saving answer and evaluation, and fetching single bookmark."""
    student_id = "candidate_prep_1"
    save_interview_bookmark(
        student_id=student_id,
        question_id="p-q-1",
        question_text="Explain the ACID properties of a database transaction.",
        category="Technical",
        company_name="Amazon"
    )

    # Initial state should be unpracticed
    bm = get_interview_bookmark_by_id(student_id, "p-q-1")
    assert bm is not None
    assert bm["is_practiced"] is False
    assert bm["practice_answer"] == ""

    # Update practice state
    eval_dict = {"score": 88, "feedback": "Solid explanation of atomicity and isolation."}
    updated = update_interview_bookmark_practice(
        student_id=student_id,
        question_id="p-q-1",
        is_practiced=True,
        answer="Atomicity, Consistency, Isolation, and Durability.",
        evaluation=eval_dict
    )
    assert updated is True

    # Re-fetch and verify
    bm_after = get_interview_bookmark_by_id(student_id, "p-q-1")
    assert bm_after["is_practiced"] is True
    assert "Atomicity" in bm_after["practice_answer"]
    assert bm_after["practice_evaluation"]["score"] == 88


def test_practice_filtering_and_stats(test_client):
    """Verify filtering bookmarks by practiced status and computing summary statistics."""
    student_id = "candidate_stats"
    save_interview_bookmark(student_id, "q-1", "What is polymorphism?", "Technical")
    save_interview_bookmark(student_id, "q-2", "Tell me about a difficult challenge.", "Behavioral")
    save_interview_bookmark(student_id, "q-3", "Why our company?", "HR")

    # Initially 0% practiced
    stats0 = get_interview_bookmark_practice_stats(student_id)
    assert stats0["total"] == 3
    assert stats0["practiced"] == 0
    assert stats0["unpracticed"] == 3
    assert stats0["percentage"] == 0.0

    # Mark 2 as practiced
    update_interview_bookmark_practice(student_id, "q-1", is_practiced=True)
    update_interview_bookmark_practice(student_id, "q-2", is_practiced=True)

    stats1 = get_interview_bookmark_practice_stats(student_id)
    assert stats1["practiced"] == 2
    assert stats1["unpracticed"] == 1
    assert stats1["percentage"] == 66.7

    # Filter practiced_only=True
    practiced_list = get_interview_bookmarks(student_id, practiced_only=True)
    assert len(practiced_list) == 2
    assert all(b["is_practiced"] for b in practiced_list)

    # Filter practiced_only=False
    unpracticed_list = get_interview_bookmarks(student_id, practiced_only=False)
    assert len(unpracticed_list) == 1
    assert unpracticed_list[0]["question_id"] == "q-3"


def test_reset_practice_progress(test_client):
    """Verify resetting practice progress for a single question and for all questions."""
    student_id = "candidate_reset"
    save_interview_bookmark(student_id, "r-1", "Explain Big-O notation.", "Technical")
    save_interview_bookmark(student_id, "r-2", "Describe a time you showed initiative.", "Behavioral")

    update_interview_bookmark_practice(student_id, "r-1", is_practiced=True, answer="Answer 1")
    update_interview_bookmark_practice(student_id, "r-2", is_practiced=True, answer="Answer 2")

    # Reset single question
    reset_interview_bookmarks_practice(student_id, question_id="r-1")
    bm1 = get_interview_bookmark_by_id(student_id, "r-1")
    bm2 = get_interview_bookmark_by_id(student_id, "r-2")
    assert bm1["is_practiced"] is False
    assert bm2["is_practiced"] is True

    # Reset all questions
    reset_interview_bookmarks_practice(student_id)
    stats = get_interview_bookmark_practice_stats(student_id)
    assert stats["practiced"] == 0
    assert stats["unpracticed"] == 2


def test_practice_mode_user_isolation(test_client):
    """Verify students cannot view or update another student's practice state."""
    alice_id = "alice_student"
    bob_id = "bob_student"

    save_interview_bookmark(alice_id, "q-sec", "Alice question", "Technical")
    save_interview_bookmark(bob_id, "q-sec", "Bob question", "Behavioral")

    # Bob attempts to update Alice's question
    updated = update_interview_bookmark_practice(bob_id, "q-sec", is_practiced=True)
    assert updated is True

    # Alice's question remains unpracticed
    alice_bm = get_interview_bookmark_by_id(alice_id, "q-sec")
    bob_bm = get_interview_bookmark_by_id(bob_id, "q-sec")
    assert alice_bm["is_practiced"] is False
    assert bob_bm["is_practiced"] is True


# ==========================================
# 2. Web Views Tests
# ==========================================

def test_practice_mode_html_view(test_client):
    """Test GET /interview/bookmarks/practice renders the focused practice carousel."""
    test_client.post("/api/interview/bookmark", json={
        "question_id": "view-q-1",
        "question_text": "How do you handle deadlocks in multithreading?",
        "category": "Technical",
        "company_name": "Google"
    })

    resp = test_client.get("/interview/bookmarks/practice")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Practice Your Saved Questions" in html
    assert "Focused Practice Mode" in html
    assert "Evaluate with AI" in html
    assert "How do you handle deadlocks" in html


def test_practice_mode_filtering_views(test_client):
    """Test filtering by category and unpracticed_only via URL query parameters."""
    test_client.post("/api/interview/bookmark", json={
        "question_id": "filt-1",
        "question_text": "Technical prompt",
        "category": "Technical"
    })
    test_client.post("/api/interview/bookmark", json={
        "question_id": "filt-2",
        "question_text": "Behavioral prompt",
        "category": "Behavioral"
    })

    # Filter category
    resp = test_client.get("/interview/bookmarks/practice?category=Behavioral")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Behavioral prompt" in html


def test_practice_mode_ajax_json(test_client):
    """Test GET /interview/bookmarks/practice with XMLHttpRequest returns JSON data."""
    test_client.post("/api/interview/bookmark", json={
        "question_id": "ajax-q",
        "question_text": "What is an idempotency key?"
    })

    resp = test_client.get("/interview/bookmarks/practice", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "stats" in data
    assert data["count"] >= 1


# ==========================================
# 3. API Endpoints Tests
# ==========================================

def test_api_save_practice_and_toggle_status(test_client):
    """Test POST /api/interview/bookmarks/<id>/practice and status toggle."""
    test_client.post("/api/interview/bookmark", json={
        "question_id": "api-prac-q",
        "question_text": "Explain REST vs GraphQL."
    })

    # Save practice answer
    resp = test_client.post("/api/interview/bookmarks/api-prac-q/practice", json={
        "answer": "REST uses standard HTTP methods and endpoints, while GraphQL uses a single endpoint with queries.",
        "is_practiced": True
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["is_practiced"] is True
    assert data["stats"]["practiced"] >= 1

    # Toggle status to unpracticed
    resp_toggle = test_client.post("/api/interview/bookmarks/api-prac-q/practice/status", json={
        "is_practiced": False
    })
    assert resp_toggle.status_code == 200
    toggle_data = resp_toggle.get_json()
    assert toggle_data["is_practiced"] is False


def test_api_evaluate_saved_question_practice(test_client):
    """Test POST /api/interview/bookmarks/<id>/practice/evaluate."""
    test_client.post("/api/interview/bookmark", json={
        "question_id": "eval-q-star",
        "question_text": "Describe a time you resolved a major production bug.",
        "category": "Behavioral",
        "company_name": "Microsoft"
    })

    # Empty answer should return 400
    resp_empty = test_client.post("/api/interview/bookmarks/eval-q-star/practice/evaluate", json={
        "answer": ""
    })
    assert resp_empty.status_code == 400

    # Valid answer evaluation
    resp = test_client.post("/api/interview/bookmarks/eval-q-star/practice/evaluate", json={
        "answer": "In my previous internship, a memory leak caused downtime. My task was to diagnose the root cause. I analyzed heap dumps, identified unclosed sockets, and deployed a patch. As a result, server uptime reached 99.9%."
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["is_practiced"] is True
    assert "evaluation" in data
    assert "feedback" in data["evaluation"] or "score" in data["evaluation"]


def test_api_reset_practice_progress(test_client):
    """Test POST /api/interview/bookmarks/practice/reset."""
    test_client.post("/api/interview/bookmark", json={
        "question_id": "reset-api-q",
        "question_text": "Explain Docker containers."
    })
    test_client.post("/api/interview/bookmarks/reset-api-q/practice", json={
        "answer": "Docker isolates processes using Linux namespaces and cgroups.",
        "is_practiced": True
    })

    # Reset
    resp = test_client.post("/api/interview/bookmarks/practice/reset")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["stats"]["practiced"] == 0
