import pytest
from utils.explanation_feedback_service import (
    submit_feedback,
    get_feedback_summary,
    remove_feedback
)

def test_explanation_feedback():
    user = "student_fb_1"
    exp_id = "exp_two_sum"

    res = submit_feedback(user, exp_id, "helpful", "Great concise approach <script>alert(1)</script>")
    assert res["success"] is True
    assert "&lt;script&gt;" in res["comment"]

    summary = get_feedback_summary(exp_id)
    assert summary["breakdown"]["helpful"] >= 1

    # Update feedback
    res_update = submit_feedback(user, exp_id, "too_long")
    assert res_update["success"] is True

    # Delete
    del_res = remove_feedback(user, exp_id)
    assert del_res is True

def test_explanation_feedback_api(client):
    post_res = client.post("/api/coding/explanations/feedback", json={
        "explanation_id": "exp_binary_search",
        "feedback_type": "confusing",
        "comment": "Step 3 was slightly vague"
    })
    assert post_res.status_code == 200
    assert post_res.get_json()["status"] == "success"

    get_res = client.get("/api/coding/explanations/feedback/summary?explanation_id=exp_binary_search")
    assert get_res.status_code == 200
    assert get_res.get_json()["summary"]["breakdown"]["confusing"] >= 1
