import pytest
from app import app
from utils.placement_checklist_service import (
    PlacementSetupChecklistService,
    placement_checklist_service,
    DEFAULT_CHECKLIST_TASKS
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_checklist_initial_state():
    service = PlacementSetupChecklistService()
    student = "student_chk_101"

    service.reset_checklist(student)
    data = service.get_student_checklist(student)

    assert data["student_id"] == student
    assert data["total_tasks"] == 7
    assert data["completed_tasks"] == 0
    assert data["remaining_tasks"] == 7
    assert data["progress_percent"] == 0
    assert data["is_all_completed"] is False
    assert data["should_display"] is True
    assert len(data["tasks"]) == 7


def test_checklist_task_completion_and_progress():
    service = PlacementSetupChecklistService()
    student = "student_chk_102"
    service.reset_checklist(student)

    # Complete 2 tasks
    service.update_task_status(student, "upload_resume", True, notes="Uploaded resume v1")
    service.update_task_status(student, "target_role", True, notes="Software Engineer")

    data = service.get_student_checklist(student)
    assert data["completed_tasks"] == 2
    assert data["remaining_tasks"] == 5
    assert data["progress_percent"] > 0

    # Toggle one task back to incomplete
    service.update_task_status(student, "upload_resume", False)
    data_after = service.get_student_checklist(student)
    assert data_after["completed_tasks"] == 1


def test_checklist_completion_and_hide_logic():
    service = PlacementSetupChecklistService()
    student = "student_chk_103"
    service.reset_checklist(student)

    # Complete all tasks
    for task in DEFAULT_CHECKLIST_TASKS:
        service.update_task_status(student, task["id"], True)

    data = service.get_student_checklist(student)
    assert data["is_all_completed"] is True
    assert data["completed_tasks"] == 7
    assert data["progress_percent"] == 100
    # Should not display repeatedly after completion
    assert data["should_display"] is False


def test_checklist_dismissal():
    service = PlacementSetupChecklistService()
    student = "student_chk_104"
    service.reset_checklist(student)

    # Initially visible
    assert service.get_student_checklist(student)["should_display"] is True

    # Dismiss temporarily
    service.set_dismissal(student, True, hours=24)
    data = service.get_student_checklist(student)
    assert data["is_dismissed"] is True
    assert data["should_display"] is False

    # Undismiss
    service.set_dismissal(student, False)
    assert service.get_student_checklist(student)["should_display"] is True


def test_api_checklist_endpoints(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "student_api_checklist_test"

    # GET checklist
    res = client.get("/api/checklist")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["checklist"]["total_tasks"] == 7

    # POST complete task
    post_res = client.post("/api/checklist/task", json={
        "task_id": "interview_practice",
        "is_completed": True
    })
    assert post_res.status_code == 200
    assert post_res.get_json()["checklist"]["completed_tasks"] >= 1

    # POST dismiss checklist
    dis_res = client.post("/api/checklist/dismiss", json={
        "is_dismissed": True,
        "hours": 12
    })
    assert dis_res.status_code == 200
    assert dis_res.get_json()["is_dismissed"] is True

    # POST reset
    rst_res = client.post("/api/checklist/reset")
    assert rst_res.status_code == 200
    assert rst_res.get_json()["checklist"]["completed_tasks"] == 0
