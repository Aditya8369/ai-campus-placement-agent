import pytest
from utils.data_import_service import preview_backup_import, execute_backup_import

def test_backup_import_preview():
    bad = preview_backup_import("not_a_dict")
    assert bad["success"] is False

    good_data = {
        "version": "1.0",
        "applications": [
            {"company_name": "Google", "role_title": "SDE", "status": "Applied"}
        ]
    }
    prev = preview_backup_import(good_data)
    assert prev["success"] is True
    assert prev["record_counts"]["applications"] == 1

def test_backup_import_execute():
    data = {
        "applications": [
            {"id": "app_imp_01", "company_name": "Netflix", "role_title": "Backend", "status": "Applied"}
        ]
    }
    res = execute_backup_import("test_student_imp", data)
    assert res["success"] is True
    assert res["imported_records"]["applications"] == 1

def test_backup_import_api(client):
    res = client.post("/api/account/data-import/preview", json={
        "backup": {"applications": [{"company_name": "Stripe"}]}
    })
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"
