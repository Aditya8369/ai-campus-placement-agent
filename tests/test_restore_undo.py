import pytest
from app import app
from utils.restore_service import AccidentalDeletionRestoreService, restore_service


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_soft_delete_and_restore_cycle():
    service = AccidentalDeletionRestoreService(retention_days=30)
    student = "student_trash_1"
    item_data = {
        "title": "Google SWE Application",
        "company": "Google",
        "status": "Interview Scheduled"
    }

    # 1. Soft delete
    del_res = service.soft_delete_item(
        student_id=student,
        entity_type="job_application",
        entity_id="app_123",
        entity_title="Google SWE Application",
        original_data=item_data
    )
    assert del_res["success"] is True
    token = del_res["undo_token"]
    assert token.startswith("undo_")

    # 2. View in trash
    trash = service.list_trash_items(student)
    assert len(trash) >= 1
    assert any(t["undo_token"] == token for t in trash)

    # 3. Restore item
    restore_res = service.restore_item(student, token)
    assert restore_res["success"] is True
    assert restore_res["original_data"]["company"] == "Google"

    # 4. No longer in active trash
    trash_after = service.list_trash_items(student)
    assert not any(t["undo_token"] == token for t in trash_after)

    # 5. Restoring again fails
    second_restore = service.restore_item(student, token)
    assert second_restore["success"] is False
    assert "already been restored" in second_restore["error"]


def test_student_isolation_in_trash():
    service = AccidentalDeletionRestoreService()
    student_a = "student_trash_A"
    student_b = "student_trash_B"

    del_res = service.soft_delete_item(
        student_id=student_a,
        entity_type="resume",
        entity_id="res_777",
        entity_title="Student A Resume",
        original_data={"skills": ["Python"]}
    )
    token = del_res["undo_token"]

    # Student B tries to restore Student A's item
    stolen_restore = service.restore_item(student_b, token)
    assert stolen_restore["success"] is False
    assert "Item not found in Trash" in stolen_restore["error"]


def test_purge_expired():
    service = AccidentalDeletionRestoreService(retention_days=-1)  # expired immediately
    del_res = service.soft_delete_item(
        student_id="student_expired",
        entity_type="task",
        entity_id="task_00",
        entity_title="Old Task",
        original_data={}
    )
    purged = service.purge_expired_items()
    assert purged >= 1


def test_api_trash_endpoints(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "student_api_trash"

    # 1. Soft delete via API
    del_res = client.post("/api/trash/soft-delete", json={
        "entity_type": "interview_session",
        "entity_id": "sess_999",
        "entity_title": "System Design Practice",
        "original_data": {"score": 90}
    })
    assert del_res.status_code == 200
    data = del_res.get_json()
    assert data["success"] is True
    undo_token = data["undo_token"]

    # 2. List items in trash
    list_res = client.get("/api/trash/items")
    assert list_res.status_code == 200
    assert list_res.get_json()["count"] >= 1

    # 3. Undo deletion
    undo_res = client.post(f"/api/trash/undo/{undo_token}")
    assert undo_res.status_code == 200
    undo_data = undo_res.get_json()
    assert undo_data["success"] is True
    assert undo_data["original_data"]["score"] == 90
