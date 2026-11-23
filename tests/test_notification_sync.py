import pytest
from utils.notification_sync_service import set_notification_state, get_user_notification_states

def test_notification_sync():
    user = "user_notif_1"
    nid = "notif_app_due"

    # Mark read
    r1 = set_notification_state(user, nid, is_read=True)
    assert r1["is_read"] is True
    assert r1["is_dismissed"] is False

    # Mark dismissed
    r2 = set_notification_state(user, nid, is_dismissed=True)
    assert r2["is_dismissed"] is True

    states = get_user_notification_states(user)
    assert nid in states
    assert states[nid]["is_read"] is True
    assert states[nid]["is_dismissed"] is True

def test_notification_sync_api(client):
    res = client.post("/api/notifications/sync-state", json={
        "notification_id": "notif_123",
        "is_read": True
    })
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"

    get_res = client.get("/api/notifications/sync-states")
    assert get_res.status_code == 200
    assert "notif_123" in get_res.get_json()["states"]
