import pytest
import json
import uuid
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    create_preparation_note,
    get_preparation_notes,
    get_preparation_note_by_id,
    update_preparation_note,
    delete_preparation_note,
    get_note_category_counts
)

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_notes.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

def test_database_preparation_notes_crud(tmp_path):
    test_db = tmp_path / "test_notes_crud.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        student_id = "student_notes_user"

        # 1. Initial count should be empty
        initial_counts = get_note_category_counts(student_id)
        assert initial_counts["All"] == 0
        assert initial_counts["Technical"] == 0

        # 2. Create notes across different categories
        note1 = create_preparation_note(
            student_id=student_id,
            title="Database Indexing & B-Trees",
            description="B-Tree indexes provide O(log n) lookups. Clustered vs non-clustered index difference.",
            category="Technical"
        )
        assert note1["id"].startswith("note-")
        assert note1["title"] == "Database Indexing & B-Trees"
        assert note1["category"] == "Technical"

        note2 = create_preparation_note(
            student_id=student_id,
            title="Tell Me About a Time You Failed (STAR)",
            description="Situation: Production bug. Task: Rollback. Action: Postmortem. Result: Automated tests.",
            category="HR"
        )
        assert note2["category"] == "HR"

        note3 = create_preparation_note(
            student_id=student_id,
            title="Two Pointer Sliding Window Pattern",
            description="Maintain left and right pointer. Expand right until valid, contract left.",
            category="DSA"
        )
        assert note3["category"] == "DSA"

        note4 = create_preparation_note(
            student_id=student_id,
            title="Google System Design & Culture",
            description="Understand Google 3 pillars: Scalability, Availability, Fault Tolerance.",
            category="Company Preparation"
        )
        assert note4["category"] == "Company Preparation"

        # 3. Verify counts
        counts = get_note_category_counts(student_id)
        assert counts["All"] == 4
        assert counts["Technical"] == 1
        assert counts["HR"] == 1
        assert counts["DSA"] == 1
        assert counts["Company Preparation"] == 1

        # 4. Retrieve single note by ID
        fetched = get_preparation_note_by_id(note1["id"], student_id)
        assert fetched is not None
        assert fetched["title"] == "Database Indexing & B-Trees"

        # 5. Filter by category
        tech_notes = get_preparation_notes(student_id, category_filter="Technical")
        assert len(tech_notes) == 1
        assert tech_notes[0]["title"] == "Database Indexing & B-Trees"

        hr_notes = get_preparation_notes(student_id, category_filter="HR")
        assert len(hr_notes) == 1
        assert hr_notes[0]["title"] == "Tell Me About a Time You Failed (STAR)"

        # 6. Keyword search (matches title or description)
        search_res = get_preparation_notes(student_id, search_query="Sliding Window")
        assert len(search_res) == 1
        assert search_res[0]["id"] == note3["id"]

        search_res_desc = get_preparation_notes(student_id, search_query="Postmortem")
        assert len(search_res_desc) == 1
        assert search_res_desc[0]["id"] == note2["id"]

        # 7. Update note
        updated = update_preparation_note(
            note_id=note1["id"],
            student_id=student_id,
            title="Database Indexing, B-Trees & LSM Trees",
            description="Updated: Included LSM trees for write-heavy database workloads.",
            category="Technical"
        )
        assert updated is True
        fetched_updated = get_preparation_note_by_id(note1["id"], student_id)
        assert fetched_updated["title"] == "Database Indexing, B-Trees & LSM Trees"
        assert "LSM trees" in fetched_updated["description"]

        # 8. Delete note
        deleted = delete_preparation_note(note1["id"], student_id)
        assert deleted is True
        assert get_preparation_note_by_id(note1["id"], student_id) is None

        counts_after_del = get_note_category_counts(student_id)
        assert counts_after_del["All"] == 3
        assert counts_after_del["Technical"] == 0

def test_student_notes_isolation(tmp_path):
    test_db = tmp_path / "test_notes_isolation.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()

        # Student Alice creates private note
        alice_note = create_preparation_note(
            student_id="alice",
            title="Alice's Private Behavioral Notes",
            description="Confidential interview prep points for Google",
            category="HR"
        )

        # Student Bob tries to retrieve Alice's note
        bob_view = get_preparation_note_by_id(alice_note["id"], "bob")
        assert bob_view is None

        # Bob's notes list should be empty
        bob_notes = get_preparation_notes("bob")
        assert len(bob_notes) == 0

        # Bob cannot update Alice's note
        bob_update = update_preparation_note(
            note_id=alice_note["id"],
            student_id="bob",
            title="Hacked Title",
            description="Hacked content",
            category="HR"
        )
        assert bob_update is False

        # Bob cannot delete Alice's note
        bob_delete = delete_preparation_note(alice_note["id"], "bob")
        assert bob_delete is False

        # Alice's note remains intact
        alice_check = get_preparation_note_by_id(alice_note["id"], "alice")
        assert alice_check is not None
        assert alice_check["title"] == "Alice's Private Behavioral Notes"

def test_notes_web_view_and_form_create(client):
    # 1. Access GET /notes initially
    get_res = client.get("/notes?student_id=student_web")
    assert get_res.status_code == 200
    html = get_res.data.decode("utf-8")
    assert "Interview Preparation Notes" in html
    assert "createNoteModal" in html
    assert "editNoteModal" in html
    assert "deleteNoteModal" in html
    assert "No preparation notes found" in html

    # 2. Add note via HTML form POST
    post_res = client.post("/notes", data={
        "student_id": "student_web",
        "title": "Dynamic Programming Memoization vs Tabulation",
        "description": "Top-down memoization uses recursion + cache. Bottom-up tabulation uses iteration + array.",
        "category": "DSA"
    }, follow_redirects=True)
    assert post_res.status_code == 200
    html_after = post_res.data.decode("utf-8")
    assert "Dynamic Programming Memoization vs Tabulation" in html_after
    assert "Interview preparation note saved successfully!" in html_after

def test_api_notes_crud_and_validation(client):
    # 1. Validation error: Missing title or description
    bad_res = client.post("/api/notes", json={
        "student_id": "student_api",
        "title": "",
        "description": "Missing title"
    })
    assert bad_res.status_code == 400
    assert "required" in json.loads(bad_res.data)["error"].lower()

    # 2. Successful creation via JSON POST /api/notes
    create_res = client.post("/api/notes", json={
        "student_id": "student_api",
        "title": "CAP Theorem Deep Dive",
        "description": "Consistency, Availability, Partition tolerance. In network partitions, choose CP or AP.",
        "category": "Technical"
    })
    assert create_res.status_code == 201
    created_data = json.loads(create_res.data)
    assert created_data["success"] is True
    note_id = created_data["note"]["id"]
    assert created_data["note"]["title"] == "CAP Theorem Deep Dive"

    # 3. Fetch single note via GET /api/notes/<note_id>
    get_one = client.get(f"/api/notes/{note_id}?student_id=student_api")
    assert get_one.status_code == 200
    one_data = json.loads(get_one.data)
    assert one_data["success"] is True
    assert one_data["note"]["title"] == "CAP Theorem Deep Dive"

    # 4. Fetch collection via GET /api/notes
    list_res = client.get("/api/notes?student_id=student_api")
    assert list_res.status_code == 200
    list_data = json.loads(list_res.data)
    assert list_data["success"] is True
    assert len(list_data["notes"]) == 1

    # 5. Fetch category counts via GET /api/notes/categories
    cat_res = client.get("/api/notes/categories?student_id=student_api")
    assert cat_res.status_code == 200
    cat_data = json.loads(cat_res.data)
    assert cat_data["category_counts"]["Technical"] == 1
    assert cat_data["category_counts"]["All"] == 1

    # 6. Update note via POST /api/notes/<note_id>
    update_res = client.post(f"/api/notes/{note_id}", json={
        "student_id": "student_api",
        "title": "CAP Theorem & PACELC Theorem",
        "description": "If Partition: Availability or Consistency. Else: Latency or Consistency.",
        "category": "Technical"
    })
    assert update_res.status_code == 200
    update_data = json.loads(update_res.data)
    assert update_data["success"] is True
    assert update_data["note"]["title"] == "CAP Theorem & PACELC Theorem"

    # 7. Multi-tenant security: unauthorized student cannot access or modify
    unauth_get = client.get(f"/api/notes/{note_id}?student_id=other_student")
    assert unauth_get.status_code == 404

    unauth_put = client.post(f"/api/notes/{note_id}", json={
        "student_id": "other_student",
        "title": "Malicious Overwrite",
        "description": "Exploit"
    })
    assert unauth_put.status_code == 404

    unauth_del = client.delete(f"/api/notes/{note_id}?student_id=other_student")
    assert unauth_del.status_code == 404

    # 8. Delete note via DELETE /api/notes/<note_id>
    del_res = client.delete(f"/api/notes/{note_id}?student_id=student_api")
    assert del_res.status_code == 200
    del_data = json.loads(del_res.data)
    assert del_data["success"] is True

    # 9. Verify note is gone
    gone_res = client.get(f"/api/notes/{note_id}?student_id=student_api")
    assert gone_res.status_code == 404
