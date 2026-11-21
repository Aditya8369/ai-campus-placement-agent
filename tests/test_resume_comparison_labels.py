"""
Unit tests for Custom Resume Comparison Labels (#523).
"""

import json
import pytest
from app import create_app
from utils.resume_comparison_labels_service import ResumeComparisonLabelsService


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_resume_comparison_labels_service():
    user = "label_student_523"
    res_id = "resume_test_abc123"

    # Default fallback label
    default_lbl = ResumeComparisonLabelsService.get_label(user, res_id)
    assert default_lbl["is_custom"] is False
    assert res_id[:8] in default_lbl["custom_label"]

    # Set custom label
    saved = ResumeComparisonLabelsService.set_label(
        user_id=user,
        resume_id=res_id,
        custom_label="Fintech Backend Specialist v2",
        color_tag="success",
        change_notes="Added distributed transactions section"
    )
    assert saved["is_custom"] is True
    assert saved["custom_label"] == "Fintech Backend Specialist v2"
    assert saved["color_tag"] == "success"

    # List user labels
    labels = ResumeComparisonLabelsService.list_user_labels(user)
    assert len(labels) == 1

    # Delete label
    del_ok = ResumeComparisonLabelsService.delete_label(user, res_id)
    assert del_ok is True
    assert ResumeComparisonLabelsService.get_label(user, res_id)["is_custom"] is False


def test_resume_label_validation():
    with pytest.raises(ValueError):
        ResumeComparisonLabelsService.set_label("u1", "r1", "   ")


def test_resume_label_api_routes(client):
    test_user = "api_label_student_523"
    with client.session_transaction() as s:
        s["user_id"] = test_user

    # 1. Set Label API
    res_set = client.post("/api/analysis/resume/res_999/label", json={
        "custom_label": "Google ML Engineer v3",
        "color_tag": "info",
        "change_notes": "Added PyTorch transformer project"
    })
    assert res_set.status_code == 200
    s_data = json.loads(res_set.data)
    assert s_data["label"]["custom_label"] == "Google ML Engineer v3"

    # 2. Get Label API
    res_get = client.get("/api/analysis/resume/res_999/label")
    assert res_get.status_code == 200
    g_data = json.loads(res_get.data)
    assert g_data["label"]["is_custom"] is True

    # 3. List Labels API
    res_list = client.get("/api/analysis/resume/labels")
    assert res_list.status_code == 200
    l_data = json.loads(res_list.data)
    assert l_data["count"] >= 1

    # 4. Delete Label API
    res_del = client.delete("/api/analysis/resume/res_999/label")
    assert res_del.status_code == 200
    d_data = json.loads(res_del.data)
    assert d_data["deleted"] is True
