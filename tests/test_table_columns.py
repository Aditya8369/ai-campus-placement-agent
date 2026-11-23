import pytest
from utils.table_columns_service import get_table_column_preferences, DEFAULT_APPLICATION_COLUMNS

def test_default_columns():
    cols = get_table_column_preferences()
    assert len(cols) == len(DEFAULT_APPLICATION_COLUMNS)
    assert any(c["id"] == "company_name" and c["visible"] for c in cols)

def test_custom_column_preferences():
    # Hide deadline_date (non-essential)
    cols = get_table_column_preferences({"deadline_date": False})
    deadline = next(c for c in cols if c["id"] == "deadline_date")
    assert deadline["visible"] is False

    # Attempt to hide essential column company_name (should stay visible)
    cols_essential = get_table_column_preferences({"company_name": False})
    comp = next(c for c in cols_essential if c["id"] == "company_name")
    assert comp["visible"] is True

def test_table_columns_api(client):
    res = client.get("/api/table-preferences/columns?table=applications")
    assert res.status_code == 200
    assert len(res.get_json()["columns"]) >= 5

    post_res = client.post("/api/table-preferences/columns", json={
        "table": "applications",
        "preferences": {"location": True}
    })
    assert post_res.status_code == 200
    assert post_res.get_json()["status"] == "success"
