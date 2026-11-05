import pytest
import json
import uuid
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    get_default_company_checklist,
    get_company_checklist,
    save_company_checklist,
    reset_company_checklist
)

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_checklists.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

def test_database_company_checklist_logic(tmp_path):
    test_db = tmp_path / "test_chk_crud.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()

        # 1. Fetch default checklist
        data = get_company_checklist("student_evan", "Google")
        assert data["company_name"] == "Google"
        assert data["overall_percentage"] == 0.0
        assert data["total_tasks"] > 10
        assert "Coding & Data Structures" in data["checklist"]

        # 2. Mark task completed
        checklist = data["checklist"]
        checklist["Coding & Data Structures"][0]["completed"] = True
        save_company_checklist("student_evan", "Google", checklist)

        refetched = get_company_checklist("student_evan", "Google")
        assert refetched["completed_tasks"] == 1
        assert refetched["overall_percentage"] > 0.0

        # 3. Verify per-company isolation
        amazon_data = get_company_checklist("student_evan", "Amazon")
        assert amazon_data["completed_tasks"] == 0

        # 4. Reset checklist
        reset_res = reset_company_checklist("student_evan", "Google")
        assert reset_res is True
        after_reset = get_company_checklist("student_evan", "Google")
        assert after_reset["completed_tasks"] == 0
        assert after_reset["overall_percentage"] == 0.0

def test_company_checklist_endpoints(client):
    # GET view
    get_res = client.get("/company-checklist?company=Google")
    assert get_res.status_code == 200
    assert b"Company Preparation Checklist" in get_res.data
    assert b"Google Placement Readiness" in get_res.data

    # API Toggle Task
    toggle_res = client.post("/api/company-checklist/toggle-task", json={
        "student_id": "default_student",
        "company_name": "Google",
        "category": "Aptitude & Logical Reasoning",
        "task_id": "apt_01",
        "completed": True
    })
    assert toggle_res.status_code == 200
    toggle_data = json.loads(toggle_res.data)
    assert toggle_data["success"] is True
    assert toggle_data["completed_tasks"] >= 1

    # API Reset
    reset_res = client.post("/api/company-checklist/reset", json={
        "student_id": "default_student",
        "company_name": "Google"
    })
    assert reset_res.status_code == 200
    reset_data = json.loads(reset_res.data)
    assert reset_data["success"] is True
    assert reset_data["data"]["completed_tasks"] == 0
