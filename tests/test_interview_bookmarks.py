"""
Unit and Integration Tests for Interview Question Bookmarks (#358)
==================================================================
Tests:
1. Database schema and CRUD operations:
   - save_interview_bookmark
   - get_interview_bookmarks (all and category-filtered)
   - is_interview_bookmarked
   - remove_interview_bookmark
2. Per-student multi-tenant data isolation.
3. Account deletion cascading data cleanup.
4. REST API endpoints:
   - GET /api/interview/bookmarks
   - POST /api/interview/bookmark
   - DELETE /api/interview/bookmark/<question_id>
   - POST /api/interview/bookmark/toggle
5. Web review page:
   - GET /interview/bookmarks (HTML view, category filtering, search)
   - GET /interview/bookmarks (JSON AJAX view)
   - GET /interview/bookmarks/export (JSON file download)
"""

import pytest
import json
import config
from utils.database import (
    init_db,
    save_interview_bookmark,
    remove_interview_bookmark,
    get_interview_bookmarks,
    is_interview_bookmarked,
    delete_user_account_and_personal_data,
)
from app import app


@pytest.fixture
def test_client(tmp_path, monkeypatch):
    """Sets up an isolated test database and Flask test client."""
    test_db = tmp_path / "test_interview_bookmarks.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-interview-secret"
    app.config["WTF_CSRF_ENABLED"] = False

    with app.test_client() as client:
        yield client


# ==========================================
# 1. Database Operations Tests
# ==========================================

def test_save_and_retrieve_interview_bookmark(test_client):
    """Verify saving interview bookmark and fetching by category."""
    student_id = "student_test_1"
    saved = save_interview_bookmark(
        student_id=student_id,
        question_id="q-tech-01",
        question_text="Explain the difference between TCP and UDP.",
        category="Technical",
        company_name="Google",
        notes="Focus on connection-oriented vs connectionless protocols."
    )
    assert saved is True

    # Retrieve all
    bookmarks = get_interview_bookmarks(student_id)
    assert len(bookmarks) == 1
    assert bookmarks[0]["question_id"] == "q-tech-01"
    assert bookmarks[0]["category"] == "Technical"
    assert bookmarks[0]["company_name"] == "Google"
    assert bookmarks[0]["notes"] == "Focus on connection-oriented vs connectionless protocols."

    # Verify is_interview_bookmarked
    assert is_interview_bookmarked(student_id, "q-tech-01") is True
    assert is_interview_bookmarked(student_id, "non_existent") is False


def test_category_filtering_and_upsert(test_client):
    """Verify category filtering and updating existing bookmark on conflict."""
    student_id = "student_test_cat"
    save_interview_bookmark(
        student_id=student_id,
        question_id="q-1",
        question_text="Describe a time you resolved a conflict.",
        category="Behavioral",
        company_name="Amazon"
    )
    save_interview_bookmark(
        student_id=student_id,
        question_id="q-2",
        question_text="Tell me about yourself.",
        category="HR",
        company_name="General"
    )
    save_interview_bookmark(
        student_id=student_id,
        question_id="q-3",
        question_text="Why do you want to join Microsoft specifically?",
        category="Company-Specific",
        company_name="Microsoft"
    )

    all_bm = get_interview_bookmarks(student_id)
    assert len(all_bm) == 3

    beh_bm = get_interview_bookmarks(student_id, category="Behavioral")
    assert len(beh_bm) == 1
    assert beh_bm[0]["question_id"] == "q-1"

    hr_bm = get_interview_bookmarks(student_id, category="HR")
    assert len(hr_bm) == 1
    assert hr_bm[0]["question_id"] == "q-2"

    comp_bm = get_interview_bookmarks(student_id, category="Company-Specific")
    assert len(comp_bm) == 1
    assert comp_bm[0]["company_name"] == "Microsoft"

    # Test update existing bookmark (upsert)
    updated = save_interview_bookmark(
        student_id=student_id,
        question_id="q-1",
        question_text="Describe a time you resolved a conflict with a teammate.",
        category="Behavioral",
        company_name="Amazon",
        notes="Updated STAR notes"
    )
    assert updated is True
    updated_bm = get_interview_bookmarks(student_id, category="Behavioral")
    assert len(updated_bm) == 1
    assert updated_bm[0]["notes"] == "Updated STAR notes"


def test_remove_interview_bookmark(test_client):
    """Verify removing an interview bookmark."""
    student_id = "student_test_del"
    save_interview_bookmark(
        student_id=student_id,
        question_id="del-q-1",
        question_text="What is a hash collision?"
    )
    assert is_interview_bookmarked(student_id, "del-q-1") is True

    removed = remove_interview_bookmark(student_id, "del-q-1")
    assert removed is True
    assert is_interview_bookmarked(student_id, "del-q-1") is False

    # Second removal returns False
    assert remove_interview_bookmark(student_id, "del-q-1") is False


def test_user_data_isolation(test_client):
    """Verify student data isolation (students cannot see or delete each other's bookmarks)."""
    alice_id = "student_alice"
    bob_id = "student_bob"

    save_interview_bookmark(
        student_id=alice_id,
        question_id="alice-q-1",
        question_text="Alice's private question."
    )
    save_interview_bookmark(
        student_id=bob_id,
        question_id="bob-q-1",
        question_text="Bob's private question."
    )

    alice_bm = get_interview_bookmarks(alice_id)
    bob_bm = get_interview_bookmarks(bob_id)

    assert len(alice_bm) == 1
    assert alice_bm[0]["question_id"] == "alice-q-1"
    assert len(bob_bm) == 1
    assert bob_bm[0]["question_id"] == "bob-q-1"

    # Alice cannot delete Bob's bookmark
    assert remove_interview_bookmark(alice_id, "bob-q-1") is False
    assert is_interview_bookmarked(bob_id, "bob-q-1") is True


def test_account_deletion_cascades(test_client):
    """Verify deleting user account cascades to wipe interview bookmarks."""
    student_id = "student_wipe_me"
    save_interview_bookmark(
        student_id=student_id,
        question_id="wipe-q-1",
        question_text="Question to be wiped."
    )
    assert is_interview_bookmarked(student_id, "wipe-q-1") is True

    result = delete_user_account_and_personal_data(student_id)
    assert result.get("deleted_counts", {}).get("bookmarked_interview_questions", 0) == 1
    assert len(get_interview_bookmarks(student_id)) == 0


# ==========================================
# 2. REST API Endpoints Tests
# ==========================================

def test_api_save_and_get_bookmarks(test_client):
    """Test POST /api/interview/bookmark and GET /api/interview/bookmarks."""
    # Invalid request (empty question)
    resp = test_client.post("/api/interview/bookmark", json={"question_text": ""})
    assert resp.status_code == 400

    # Successful bookmark
    payload = {
        "question_id": "api-q-1",
        "question_text": "How do you handle ambiguous requirements?",
        "category": "Behavioral",
        "company_name": "Meta",
        "notes": "Ask clarifying questions."
    }
    resp = test_client.post("/api/interview/bookmark", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True

    # Get bookmarks via API
    get_resp = test_client.get("/api/interview/bookmarks")
    assert get_resp.status_code == 200
    get_data = get_resp.get_json()
    assert get_data["success"] is True
    assert get_data["count"] >= 1


def test_api_remove_bookmark(test_client):
    """Test DELETE /api/interview/bookmark/<id>."""
    # First save
    test_client.post("/api/interview/bookmark", json={
        "question_id": "api-del-q",
        "question_text": "What is dependency injection?"
    })

    # Delete
    del_resp = test_client.delete("/api/interview/bookmark/api-del-q")
    assert del_resp.status_code == 200
    del_data = del_resp.get_json()
    assert del_data["success"] is True


def test_api_toggle_bookmark(test_client):
    """Test POST /api/interview/bookmark/toggle."""
    payload = {
        "question_id": "toggle-q-101",
        "question_text": "What is an index in SQL?",
        "category": "Technical",
        "company_name": "Oracle"
    }

    # First toggle: should bookmark
    resp1 = test_client.post("/api/interview/bookmark/toggle", json=payload)
    assert resp1.status_code == 200
    data1 = resp1.get_json()
    assert data1["success"] is True
    assert data1["bookmarked"] is True

    # Second toggle: should unbookmark
    resp2 = test_client.post("/api/interview/bookmark/toggle", json=payload)
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2["success"] is True
    assert data2["bookmarked"] is False


# ==========================================
# 3. Web Views and Export Tests
# ==========================================

def test_web_bookmarks_view_html(test_client):
    """Test GET /interview/bookmarks renders HTML page."""
    # Add a bookmark
    test_client.post("/api/interview/bookmark", json={
        "question_id": "web-view-q",
        "question_text": "Explain CAP theorem and trade-offs.",
        "category": "Technical",
        "company_name": "Netflix"
    })

    resp = test_client.get("/interview/bookmarks")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Bookmarked Interview Questions" in html
    assert "Explain CAP theorem" in html
    assert "Netflix" in html


def test_web_bookmarks_view_filtering_and_search(test_client):
    """Test filtering by category and searching via query parameters."""
    test_client.post("/api/interview/bookmark", json={
        "question_id": "q-search-1",
        "question_text": "How do you optimize slow database queries?",
        "category": "Technical",
        "company_name": "Uber"
    })
    test_client.post("/api/interview/bookmark", json={
        "question_id": "q-search-2",
        "question_text": "Tell me about a time you showed leadership.",
        "category": "Behavioral",
        "company_name": "Apple"
    })

    # Filter category
    resp_cat = test_client.get("/interview/bookmarks?category=Behavioral")
    assert resp_cat.status_code == 200
    html_cat = resp_cat.get_data(as_text=True)
    assert "leadership" in html_cat
    assert "slow database queries" not in html_cat

    # Search keyword
    resp_search = test_client.get("/interview/bookmarks?search=Uber")
    assert resp_search.status_code == 200
    html_search = resp_search.get_data(as_text=True)
    assert "slow database queries" in html_search
    assert "leadership" not in html_search


def test_web_bookmarks_view_json(test_client):
    """Test GET /interview/bookmarks returns JSON when requested via AJAX."""
    test_client.post("/api/interview/bookmark", json={
        "question_id": "json-q",
        "question_text": "What is an event loop?"
    })

    resp = test_client.get("/interview/bookmarks", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "bookmarks" in data
    assert "counts" in data


def test_export_interview_bookmarks_json(test_client):
    """Test GET /interview/bookmarks/export downloads JSON file."""
    test_client.post("/api/interview/bookmark", json={
        "question_id": "export-q",
        "question_text": "Describe asynchronous programming in Python.",
        "category": "Technical",
        "company_name": "Stripe"
    })

    resp = test_client.get("/interview/bookmarks/export")
    assert resp.status_code == 200
    assert "application/json" in resp.content_type
    assert "attachment;filename=" in resp.headers.get("Content-Disposition", "")
    data = json.loads(resp.get_data(as_text=True))
    assert data["total_bookmarks"] >= 1
    assert data["bookmarks"][0]["question_text"] == "Describe asynchronous programming in Python."
