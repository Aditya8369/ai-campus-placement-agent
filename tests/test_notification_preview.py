import pytest
from utils.notification_preview_service import get_notification_previews, generate_test_notification

def test_notification_previews():
    previews = get_notification_previews()
    assert len(previews) >= 3
    assert any(p["category"] == "Application Updates" for p in previews)

def test_generate_test_notification():
    test_notif = generate_test_notification("interview_reminder", recipient="test@edu.com")
    assert test_notif["success"] is True
    assert test_notif["is_test"] is True
    assert "synthetic" in test_notif["disclaimer"].lower()

def test_notification_preview_api(client):
    res = client.get("/api/notifications/previews")
    assert res.status_code == 200
    assert len(res.get_json()["previews"]) >= 3

    send_res = client.post("/api/notifications/test-delivery", json={
        "notification_type": "status_change",
        "recipient": "user@test.com"
    })
    assert send_res.status_code == 200
    assert send_res.get_json()["status"] == "success"
