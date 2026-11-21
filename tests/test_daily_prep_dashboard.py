"""
Unit tests for Daily Placement Preparation Dashboard (#512).
"""

import json
import pytest
from app import create_app
from utils.daily_prep_service import DailyPrepDashboardService


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_daily_prep_service():
    import uuid
    user = f"daily_prep_{uuid.uuid4().hex[:8]}"

    # Get today dashboard
    dash = DailyPrepDashboardService.get_today_dashboard(user)
    assert dash["total_tasks"] >= 3
    assert dash["completed_tasks"] == 0
    assert dash["completion_pct"] == 0.0
    assert "daily_focus_tip" in dash

    # Toggle first task
    first_task = dash["tasks"][0]
    toggle_res = DailyPrepDashboardService.toggle_task(user, first_task["id"])
    assert toggle_res["is_completed"] is True

    # Add custom task
    custom = DailyPrepDashboardService.add_custom_daily_task(user, "Review System Design Patterns")
    assert custom["title"] == "Review System Design Patterns"
    assert custom["task_type"] == "custom"


def test_daily_prep_api_routes(client):
    import uuid
    test_user = f"api_daily_prep_{uuid.uuid4().hex[:8]}"
    with client.session_transaction() as s:
        s["user_id"] = test_user

    # 1. HTML View
    view_res = client.get("/daily-prep")
    assert view_res.status_code == 200
    assert b"Daily Placement Prep Hub" in view_res.data

    # 2. JSON Endpoint
    api_res = client.get("/api/daily-prep/dashboard")
    assert api_res.status_code == 200
    data = json.loads(api_res.data)
    assert data["status"] == "success"
    task_id = data["dashboard"]["tasks"][0]["id"]

    # 3. Toggle Endpoint
    t_res = client.post(f"/api/daily-prep/tasks/{task_id}/toggle")
    assert t_res.status_code == 200
    t_data = json.loads(t_res.data)
    assert t_data["task"]["is_completed"] is True

    # 4. Add Custom Task
    add_res = client.post("/api/daily-prep/tasks", json={"title": "Prepare 2 behavioral answers"})
    assert add_res.status_code == 201
