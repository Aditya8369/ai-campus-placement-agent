import pytest
from app import app
from utils.delivery_history_service import (
    NotificationDeliveryHistoryService,
    delivery_history_service
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_mask_recipient():
    service = NotificationDeliveryHistoryService()
    assert service.mask_recipient("john.doe@company.com") == "j***e@company.com"
    assert service.mask_recipient("al@domain.org") == "a***@domain.org"
    assert service.mask_recipient("+1-555-123-4567") == "***-***-4567"
    assert service.mask_recipient("") == "N/A"


def test_log_and_list_deliveries():
    service = NotificationDeliveryHistoryService()
    student = "student_history_test_1"

    # Log 1 success email
    lid1 = service.log_delivery(
        student_id=student,
        channel="email",
        recipient="alice.wonderland@university.edu",
        template_name="interview_reminder",
        subject="Interview with Amazon tomorrow",
        status="DELIVERED",
        latency_ms=85
    )
    assert lid1 > 0

    # Log 1 failed email
    lid2 = service.log_delivery(
        student_id=student,
        channel="email",
        recipient="alice.wonderland@university.edu",
        template_name="status_update",
        subject="Application Status Update",
        status="FAILED",
        error_summary="SMTP 550 Mailbox unavailable",
        latency_ms=1200
    )
    assert lid2 > 0

    # Fetch list
    history = service.list_delivery_history(student)
    assert len(history) >= 2
    assert history[0]["masked_recipient"] == "a***d@university.edu"
    assert "alice.wonderland" not in history[0]["masked_recipient"]  # Privacy check

    # Fetch metrics
    metrics = service.get_delivery_metrics(student)
    assert metrics["total_sent"] >= 2
    assert metrics["delivered"] >= 1
    assert metrics["failed"] >= 1


def test_api_delivery_history_endpoints(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "student_api_delivery_history"

    # POST log
    res = client.post("/api/notifications/delivery-history", json={
        "channel": "email",
        "recipient": "placement.officer@college.ac.in",
        "template_name": "welcome_email",
        "subject": "Welcome to AI Placement Agent",
        "status": "DELIVERED",
        "latency_ms": 110
    })
    assert res.status_code == 201
    assert res.get_json()["success"] is True

    # GET history
    get_res = client.get("/api/notifications/delivery-history")
    assert get_res.status_code == 200
    data = get_res.get_json()
    assert data["success"] is True
    assert data["count"] >= 1
    assert data["metrics"]["total_sent"] >= 1
    assert any("p***r@college.ac.in" in h["masked_recipient"] for h in data["history"])
