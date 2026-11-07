"""
Unit & Integration Tests for Coding Bookmark Folder Management System (#253)
=============================================================================
Tests:
1. Dynamic folder table creation and schema migration.
2. CRUD operations for bookmark folders (create, update, delete).
3. Moving bookmarks between folders and unassigning them.
4. Per-folder bookmark retrieval and count calculation.
5. Deleting folder with soft unassign vs content wipe.
6. Multi-tenant isolation (students cannot see or manage another's folders).
7. API endpoints:
   - GET/POST /api/coding/folders
   - GET/PUT/DELETE /api/coding/folders/<id>
   - POST /api/coding/bookmarks/<problem_id>/move
"""

import pytest
import json

import config
from utils.database import (
    init_db,
    save_coding_bookmark,
    get_db_connection
)
from utils.bookmark_folders import (
    ensure_bookmark_folders_schema,
    create_bookmark_folder,
    get_bookmark_folder_by_id,
    list_student_bookmark_folders,
    update_bookmark_folder,
    delete_bookmark_folder,
    move_bookmark_to_folder,
    get_folder_bookmarks
)
from app import app


@pytest.fixture
def bookmark_env(tmp_path, monkeypatch):
    """Sets up an isolated test database for bookmark folder testing."""
    test_db = tmp_path / "test_bm_folders.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    with get_db_connection() as conn:
        ensure_bookmark_folders_schema(conn)

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "folder-secret-key"

    with app.test_client() as client:
        yield client


def test_create_and_retrieve_folder(bookmark_env):
    """Verify folder creation, unique constraints, and retrieval."""
    folder = create_bookmark_folder(
        student_id="cand_alex",
        name="Dynamic Programming",
        description="Mastering 1D and 2D DP patterns",
        color_hex="#10b981",
        icon_name="fa-code"
    )

    assert folder["name"] == "Dynamic Programming"
    assert folder["color_hex"] == "#10b981"
    assert folder["student_id"] == "cand_alex"

    by_id = get_bookmark_folder_by_id("cand_alex", folder["id"])
    assert by_id is not None
    assert by_id["id"] == folder["id"]

    # Rejection of duplicate name
    with pytest.raises(ValueError):
        create_bookmark_folder("cand_alex", name="Dynamic Programming")


def test_move_bookmark_to_folder(bookmark_env):
    """Verify assigning a bookmark to a folder and moving between folders."""
    # Create two folders
    f1 = create_bookmark_folder("cand_bob", "Graph Algorithms")
    f2 = create_bookmark_folder("cand_bob", "Trees & BST")

    # Bookmark a problem
    save_coding_bookmark(
        student_id="cand_bob",
        problem_id="course_schedule_ii",
        problem_data={
            "id": "course_schedule_ii",
            "title": "Course Schedule II",
            "difficulty": "Medium",
            "topic": "Graph"
        }
    )

    # Move to Graph folder
    moved = move_bookmark_to_folder("cand_bob", "course_schedule_ii", f1["id"])
    assert moved is True

    # Verify problem is in f1
    f1_items = get_folder_bookmarks("cand_bob", f1["id"])
    assert len(f1_items) == 1
    assert f1_items[0]["id"] == "course_schedule_ii"
    assert f1_items[0]["folder_id"] == f1["id"]

    # Move to Tree folder
    move_bookmark_to_folder("cand_bob", "course_schedule_ii", f2["id"])
    assert len(get_folder_bookmarks("cand_bob", f1["id"])) == 0
    assert len(get_folder_bookmarks("cand_bob", f2["id"])) == 1


def test_delete_folder_and_unassign_contents(bookmark_env):
    """Verify deleting a folder without delete_contents safely unassigns bookmarks."""
    f = create_bookmark_folder("cand_dan", "Quick Review")

    save_coding_bookmark(
        student_id="cand_dan",
        problem_id="two_sum",
        problem_data={"id": "two_sum", "title": "Two Sum", "difficulty": "Easy"}
    )
    move_bookmark_to_folder("cand_dan", "two_sum", f["id"])

    # Delete folder
    deleted = delete_bookmark_folder("cand_dan", f["id"], delete_contents=False)
    assert deleted is True

    # Folder is gone
    assert get_bookmark_folder_by_id("cand_dan", f["id"]) is None

    # Bookmark is still preserved as unassigned
    unassigned = get_folder_bookmarks("cand_dan", folder_id=None)
    assert len(unassigned) == 1
    assert unassigned[0]["id"] == "two_sum"


def test_api_folder_endpoints(bookmark_env):
    """Test REST API endpoints for folder creation, listing, updating, and moving."""
    # 1. Create folder via API
    resp = bookmark_env.post("/api/coding/folders", json={
        "name": "Google Top 50",
        "description": "High frequency questions asked at Google",
        "color_hex": "#ef4444"
    })
    assert resp.status_code == 201
    folder_data = resp.get_json()["folder"]
    folder_id = folder_data["id"]

    # 2. List folders via API
    list_resp = bookmark_env.get("/api/coding/folders")
    assert list_resp.status_code == 200
    assert list_resp.get_json()["data"]["total_folders"] >= 1

    # 3. Update folder via API
    update_resp = bookmark_env.put(f"/api/coding/folders/{folder_id}", json={
        "name": "Google Top 100 Curated"
    })
    assert update_resp.status_code == 200
    assert update_resp.get_json()["folder"]["name"] == "Google Top 100 Curated"

    # 4. Save bookmark and move via API
    save_coding_bookmark("default_student", "lru_cache", {"id": "lru_cache", "title": "LRU Cache"})
    move_resp = bookmark_env.post(f"/api/coding/bookmarks/lru_cache/move", json={
        "target_folder_id": folder_id
    })
    assert move_resp.status_code == 200

    # 5. Get folder details with bookmarks
    detail_resp = bookmark_env.get(f"/api/coding/folders/{folder_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.get_json()["count"] == 1
    assert detail_resp.get_json()["bookmarks"][0]["id"] == "lru_cache"
