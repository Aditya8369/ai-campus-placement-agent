"""
Unit tests for Campus Placement Batch Analytics Dashboard (#514).
"""

import json
import pytest
from app import create_app
from utils.batch_analytics_service import BatchAnalyticsService


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_batch_analytics_service():
    # Enroll test students
    BatchAnalyticsService.enroll_student_profile("batch_s1", 2026, "Computer Science", 8.5, "placed")
    BatchAnalyticsService.enroll_student_profile("batch_s2", 2026, "Computer Science", 7.8, "seeking")
    BatchAnalyticsService.enroll_student_profile("batch_s3", 2026, "Electronics", 8.0, "seeking")

    metrics = BatchAnalyticsService.get_batch_metrics(graduation_year=2026)
    assert metrics["total_students"] >= 3
    assert metrics["placed_count"] >= 1
    assert metrics["placement_rate_pct"] > 0
    assert "Computer Science" in metrics["department_breakdown"]


def test_batch_analytics_api_routes(client):
    with client.session_transaction() as s:
        s["user_id"] = "admin_user"
        s["user_role"] = "admin"

    # 1. HTML View
    res_view = client.get("/admin/batch-analytics")
    assert res_view.status_code == 200
    assert b"Campus Placement Batch Analytics" in res_view.data

    # 2. JSON Metrics Endpoint
    res_api = client.get("/api/admin/batch-analytics?graduation_year=2026")
    assert res_api.status_code == 200
    data = json.loads(res_api.data)
    assert data["status"] == "success"
    assert "metrics" in data
    assert data["metrics"]["total_students"] >= 1

    # 3. Enroll Student API
    res_enroll = client.post("/api/admin/batch-analytics/enroll", json={
        "user_id": "test_batch_api_student",
        "graduation_year": 2026,
        "department": "Information Technology",
        "cgpa": 8.2,
        "placement_status": "placed"
    })
    assert res_enroll.status_code == 201
    en_data = json.loads(res_enroll.data)
    assert en_data["profile"]["department"] == "Information Technology"
