import pytest
from app import app
from utils.in_app_notification_service import InAppNotificationCenterService, in_app_notification_service


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_notification_creation_and_unread_count():
    service = InAppNotificationCenterService()
    student = "student_notif_1"

    initial_unread = service.get_unread_count(student)

    nid1 = service.create_notification(
        student_id=student,
        title="Mock Interview Scheduled",
        message="Your mock interview starts in 30 minutes.",
        category="interview_reminder",
        priority="high"
    )
    assert nid1 > 0
    assert service.get_unread_count(student) == initial_unread + 1

    # Mark as read
    res = service.mark_as_read(student, nid1)
    assert res is True
    assert service.get_unread_count(student) == initial_unread


def test_mark_all_read():
    service = InAppNotificationCenterService()
    student = "student_notif_2"

    service.create_notification(student, "Alert 1", "Msg 1")
    service.create_notification(student, "Alert 2", "Msg 2")
    assert service.get_unread_count(student) >= 2

    updated = service.mark_all_as_read(student)
    assert updated >= 2
    assert service.get_unread_count(student) == 0


def test_delete_notification():
    service = InAppNotificationCenterService()
    student = "student_notif_3"

    nid = service.create_notification(student, "To Delete", "Will be removed")
    deleted = service.delete_notification(student, nid)
    assert deleted is True

    # Deleting again returns False
    assert service.delete_notification(student, nid) is False


def test_api_notification_endpoints(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "student_api_notif"

    # POST create
    res = client.post("/api/notifications", json={
        "title": "Resume Feedback Ready",
        "message": "Your ATS resume score is 87/100.",
        "category": "resume_analysis"
    })
    assert res.status_code == 201
    nid = res.get_json()["notification_id"]

    # GET list
    list_res = client.get("/api/notifications")
    assert list_res.status_code == 200
    data = list_res.get_json()
    assert data["unread_count"] >= 1
    assert any(n["id"] == nid for n in data["notifications"])

    # GET unread count
    cnt_res = client.get("/api/notifications/unread-count")
    assert cnt_res.status_code == 200
    assert cnt_res.get_json()["unread_count"] >= 1

    # POST mark single read
    read_res = client.post(f"/api/notifications/{nid}/read")
    assert read_res.status_code == 200
    assert read_res.get_json()["success"] is True

    # DELETE
    del_res = client.delete(f"/api/notifications/{nid}")
    assert del_res.status_code == 200
    assert del_res.get_json()["success"] is True
