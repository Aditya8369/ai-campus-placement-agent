import pytest
from utils.interview_recovery_service import (
    save_session_checkpoint,
    get_session_checkpoint,
    clear_session_checkpoint
)

def test_interview_session_checkpoint():
    user = "user_rec_1"
    analysis = "analysis_rec_1"

    save_res = save_session_checkpoint(user, analysis, 2, "What is Docker?", "Docker is a container tool...")
    assert save_res["success"] is True

    checkpoint = get_session_checkpoint(user, analysis)
    assert checkpoint is not None
    assert checkpoint["current_question_index"] == 2
    assert "Docker is a container tool" in checkpoint["draft_answer"]

    # Clear checkpoint
    cleared = clear_session_checkpoint(user, analysis)
    assert cleared is True
    assert get_session_checkpoint(user, analysis) is None

def test_interview_recovery_api(client):
    post_res = client.post("/api/interview/recovery/checkpoint", json={
        "analysis_id": "test_an_123",
        "question_index": 1,
        "question_text": "Tell me about a challenge",
        "draft_answer": "I resolved a database bottleneck"
    })
    assert post_res.status_code == 200
    assert post_res.get_json()["status"] == "success"

    get_res = client.get("/api/interview/recovery/checkpoint?analysis_id=test_an_123")
    assert get_res.status_code == 200
    data = get_res.get_json()
    assert data["status"] == "success"
    assert data["checkpoint"]["draft_answer"] == "I resolved a database bottleneck"

    del_res = client.delete("/api/interview/recovery/checkpoint?analysis_id=test_an_123")
    assert del_res.status_code == 200
