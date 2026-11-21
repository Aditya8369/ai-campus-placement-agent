"""
Unit and integration tests for Drive Day Practical Readiness Checklist (#651).

Tests verify:
- Default offline and online checklist generation and categories
- Progress calculation and formatting ("7 of 12 ready")
- Item lifecycle: add, rename, delete, and toggle
- Per-user and per-application isolation
- Permission checks preventing unauthorized access or mutation
- Dashboard upcoming drive reminder within 2 days
- REST API endpoints and view rendering
"""

import datetime
import pytest
from unittest.mock import patch

from app import app
import config
from db.migrations import init_db
from utils.database import (
    save_job_application,
    get_drive_day_checklist,
    save_drive_day_checklist,
    toggle_checklist_item,
    add_checklist_item,
    rename_checklist_item,
    delete_checklist_item,
    reset_drive_day_checklist,
    switch_drive_mode,
    calculate_checklist_progress,
    get_default_checklist,
    get_dashboard_drive_reminder,
)


@pytest.fixture
def test_db_env(tmp_path):
    """Sets up an isolated temporary database for test runs."""
    db_file = tmp_path / "test_drive_day.db"
    db_path = str(db_file)
    with patch.object(config, "DATABASE_PATH", db_path):
        init_db(db_path)
        app.config["TESTING"] = True
        yield db_path


def test_default_offline_and_online_checklists():
    """Verify default offline and online presets contain all four required categories and items."""
    offline = get_default_checklist("offline")
    online = get_default_checklist("online")

    required_cats = ["documents", "technical_setup", "logistics", "mindset"]
    for cat in required_cats:
        assert cat in offline
        assert cat in online
        assert len(offline[cat]) >= 4
        assert len(online[cat]) >= 4

        # Validate item structure
        for it in offline[cat] + online[cat]:
            assert "id" in it
            assert "text" in it and len(it["text"]) > 5
            assert "completed" in it
            assert it["completed"] is False
            assert "is_custom" in it


def test_calculate_checklist_progress():
    """Verify progress calculation, percentage, and label formatting."""
    # Empty checklist
    empty_prog = calculate_checklist_progress({})
    assert empty_prog["total_items"] == 0
    assert empty_prog["completed_items"] == 0
    assert empty_prog["completion_percentage"] == 0.0
    assert empty_prog["progress_label"] == "0 of 0 ready"
    assert empty_prog["all_completed"] is False

    # Partial checklist: 1 completed out of 4
    sample = {
        "documents": [
            {"id": "1", "text": "Resume", "completed": True},
            {"id": "2", "text": "ID", "completed": False},
        ],
        "technical_setup": [
            {"id": "3", "text": "Laptop", "completed": False},
        ],
        "logistics": [
            {"id": "4", "text": "Venue", "completed": False},
        ],
        "mindset": [],
    }
    prog = calculate_checklist_progress(sample)
    assert prog["total_items"] == 4
    assert prog["completed_items"] == 1
    assert prog["completion_percentage"] == 25.0
    assert prog["progress_label"] == "1 of 4 ready"
    assert prog["all_completed"] is False
    assert prog["category_stats"]["documents"]["completed"] == 1
    assert prog["category_stats"]["documents"]["ready_label"] == "1 of 2 ready"

    # All completed
    for cat in sample:
        for it in sample[cat]:
            it["completed"] = True
    all_prog = calculate_checklist_progress(sample)
    assert all_prog["total_items"] == 4
    assert all_prog["completed_items"] == 4
    assert all_prog["completion_percentage"] == 100.0
    assert all_prog["progress_label"] == "4 of 4 ready"
    assert all_prog["all_completed"] is True


def test_crud_item_lifecycle(test_db_env):
    """Verify adding, toggling, renaming, and deleting items dynamically."""
    student_id = "test_student_crud"

    # 1. Initialize checklist
    chk = get_drive_day_checklist(student_id, db_path=test_db_env)
    assert chk["total_items"] > 15
    assert chk["completed_items"] == 0
    first_item_id = chk["checklist"]["documents"][0]["id"]

    # 2. Toggle item completed
    toggled = toggle_checklist_item(student_id, None, first_item_id, True, db_path=test_db_env)
    assert toggled["completed_items"] == 1
    assert toggled["completion_percentage"] > 0
    assert "1 of" in toggled["progress_label"]

    # 3. Add custom item
    added = add_checklist_item(student_id, None, "logistics", "Pack spare battery and umbrella", db_path=test_db_env)
    custom_items = [it for it in added["checklist"]["logistics"] if it.get("is_custom")]
    assert len(custom_items) == 1
    custom_id = custom_items[0]["id"]
    assert custom_items[0]["text"] == "Pack spare battery and umbrella"

    # 4. Rename custom item
    renamed = rename_checklist_item(student_id, None, custom_id, "Pack compact umbrella and rain cover", db_path=test_db_env)
    renamed_item = next(it for it in renamed["checklist"]["logistics"] if it["id"] == custom_id)
    assert renamed_item["text"] == "Pack compact umbrella and rain cover"

    # 5. Delete custom item
    deleted = delete_checklist_item(student_id, None, custom_id, db_path=test_db_env)
    assert not any(it["id"] == custom_id for it in deleted["checklist"]["logistics"])

    # 6. Reset to defaults
    reset_data = reset_drive_day_checklist(student_id, None, drive_mode="online", db_path=test_db_env)
    assert reset_data["drive_mode"] == "online"
    assert reset_data["completed_items"] == 0


def test_per_user_and_application_isolation(test_db_env):
    """Verify checklists remain isolated between students and between applications."""
    student_a = "alice"
    student_b = "bob"
    app_1 = "app_google_123"
    app_2 = "app_amazon_456"

    # Save application records
    save_job_application(app_1, student_a, "Google", "SWE", db_path=test_db_env)
    save_job_application(app_2, student_a, "Amazon", "SDE", db_path=test_db_env)

    # Initialize Alice's standalone vs app_1 vs app_2 checklists
    chk_standalone = get_drive_day_checklist(student_a, None, db_path=test_db_env)
    chk_app1 = get_drive_day_checklist(student_a, app_1, db_path=test_db_env)
    chk_app2 = get_drive_day_checklist(student_a, app_2, db_path=test_db_env)

    # Modify app_1 checklist
    item_id = chk_app1["checklist"]["documents"][0]["id"]
    toggle_checklist_item(student_a, app_1, item_id, True, db_path=test_db_env)

    # Verify app_1 is updated, but standalone and app_2 are unchanged
    refreshed_app1 = get_drive_day_checklist(student_a, app_1, db_path=test_db_env)
    refreshed_app2 = get_drive_day_checklist(student_a, app_2, db_path=test_db_env)
    refreshed_standalone = get_drive_day_checklist(student_a, None, db_path=test_db_env)

    assert refreshed_app1["completed_items"] == 1
    assert refreshed_app2["completed_items"] == 0
    assert refreshed_standalone["completed_items"] == 0

    # Verify Bob has zero items completed
    chk_bob = get_drive_day_checklist(student_b, None, db_path=test_db_env)
    assert chk_bob["completed_items"] == 0


def test_dashboard_drive_reminder_within_2_days(test_db_env):
    """Verify drive reminder triggers for drives within 2 days with incomplete checklist."""
    student = "carol"
    now = datetime.datetime.now()

    # Application 1: drive tomorrow (within 2 days), incomplete checklist
    app_tomorrow = "app_drive_tomorrow"
    tomorrow_str = (now + datetime.timedelta(days=1, hours=2)).strftime("%Y-%m-%d %H:%M")
    save_job_application(app_tomorrow, student, "Microsoft", "SWE", deadline_date=tomorrow_str, db_path=test_db_env)

    # Application 2: drive in 5 days (beyond 2 days)
    app_next_week = "app_drive_next_week"
    next_week_str = (now + datetime.timedelta(days=5)).strftime("%Y-%m-%d")
    save_job_application(app_next_week, student, "Adobe", "QA", deadline_date=next_week_str, db_path=test_db_env)

    # 1. Reminder should trigger for Microsoft
    reminder = get_dashboard_drive_reminder(student, db_path=test_db_env)
    assert reminder is not None
    assert reminder["company_name"] == "Microsoft"
    assert reminder["application_id"] == app_tomorrow
    assert reminder["completed_items"] == 0
    assert "ready" in reminder["progress_label"]

    # 2. Mark all items in Microsoft checklist completed
    chk = get_drive_day_checklist(student, app_tomorrow, db_path=test_db_env)
    for cat in chk["checklist"]:
        for it in chk["checklist"][cat]:
            it["completed"] = True
    save_drive_day_checklist(student, app_tomorrow, "offline", chk["checklist"], db_path=test_db_env)

    # 3. Reminder should now be None because Microsoft checklist is complete and Adobe is > 2 days away
    assert get_dashboard_drive_reminder(student, db_path=test_db_env) is None


def test_permission_checks_unauthorized_application_access(test_db_env):
    """Verify a student cannot view or modify another student's application checklist."""
    student_owner = "alice"
    student_intruder = "eve"
    target_app_id = "app_secret_corp"

    # Alice creates an application
    save_job_application(target_app_id, student_owner, "Apple", "Hardware", db_path=test_db_env)

    with app.test_client() as client:
        # Simulate Eve signed in
        with client.session_transaction() as sess:
            sess["user_id"] = student_intruder

        # 1. Eve tries to GET Alice's application checklist -> 403 Forbidden
        res_view = client.get(f"/drive-day-checklist?application_id={target_app_id}")
        assert res_view.status_code == 403

        # 2. Eve tries to toggle a task on Alice's application checklist -> 403 Forbidden
        res_toggle = client.post(
            "/api/drive-day-checklist/toggle",
            json={"application_id": target_app_id, "item_id": "off_doc_1", "completed": True},
        )
        assert res_toggle.status_code == 403
        data_toggle = res_toggle.get_json()
        assert "Access denied" in data_toggle["error"]

        # 3. Eve tries to add an item to Alice's checklist -> 403 Forbidden
        res_add = client.post(
            "/api/drive-day-checklist/item",
            json={"application_id": target_app_id, "category": "documents", "text": "Hacked item"},
        )
        assert res_add.status_code == 403

        # 4. Eve tries to delete an item from Alice's checklist -> 403 Forbidden
        res_del = client.post(
            "/api/drive-day-checklist/delete",
            json={"application_id": target_app_id, "item_id": "off_doc_1"},
        )
        assert res_del.status_code == 403


def test_drive_day_checklist_view_and_api_endpoints(test_db_env):
    """Verify GET and POST API endpoints for drive day checklist."""
    student = "dave"

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = student

        # 1. HTML View loads with 200
        res = client.get("/drive-day-checklist")
        assert res.status_code == 200
        assert b"Drive Day Readiness Checklist" in res.data
        assert b"Documents &amp; Credentials" in res.data or b"Documents & Credentials" in res.data

        # 2. JSON Request
        res_json = client.get("/drive-day-checklist", headers={"Accept": "application/json"})
        assert res_json.status_code == 200
        body = res_json.get_json()
        assert body["success"] is True
        assert body["checklist"]["total_items"] > 10

        # 3. Toggle task via API
        item_id = body["checklist"]["checklist"]["documents"][0]["id"]
        res_toggle = client.post(
            "/api/drive-day-checklist/toggle",
            json={"item_id": item_id, "completed": True},
        )
        assert res_toggle.status_code == 200
        assert res_toggle.get_json()["data"]["completed_items"] == 1

        # 4. Add custom item via API
        res_add = client.post(
            "/api/drive-day-checklist/item",
            json={"category": "mindset", "text": "Listen to calming music on commute"},
        )
        assert res_add.status_code == 201
        custom_item = res_add.get_json()["data"]["checklist"]["mindset"][-1]
        assert custom_item["text"] == "Listen to calming music on commute"

        # 5. Rename item via API
        res_rename = client.post(
            "/api/drive-day-checklist/rename",
            json={"item_id": custom_item["id"], "text": "Listen to high-energy instrumental music"},
        )
        assert res_rename.status_code == 200

        # 6. Delete item via API
        res_del = client.post(
            "/api/drive-day-checklist/delete",
            json={"item_id": custom_item["id"]},
        )
        assert res_del.status_code == 200

        # 7. Switch mode via API
        res_mode = client.post(
            "/api/drive-day-checklist/mode",
            json={"mode": "online"},
        )
        assert res_mode.status_code == 200
        assert res_mode.get_json()["data"]["drive_mode"] == "online"

        # 8. Reset via API
        res_reset = client.post(
            "/api/drive-day-checklist/reset",
            json={"mode": "offline"},
        )
        assert res_reset.status_code == 200
        assert res_reset.get_json()["data"]["drive_mode"] == "offline"
