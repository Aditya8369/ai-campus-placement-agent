import pytest
from utils.application_board_service import (
    validate_stage_transition,
    get_next_previous_stages,
    VALID_BOARD_COLUMNS
)

def test_stage_transition_validation():
    # Regular forward move
    t1 = validate_stage_transition("Applied", "Assessment")
    assert t1["valid"] is True
    assert t1["requires_confirmation"] is False

    # Move to Rejected requires confirmation
    t2 = validate_stage_transition("Assessment", "Rejected", requires_confirmation=False)
    assert t2["valid"] is True
    assert t2["requires_confirmation"] is True

    # Invalid stage
    t3 = validate_stage_transition("Applied", "InvalidStage")
    assert t3["valid"] is False

def test_keyboard_navigation_stages():
    nav = get_next_previous_stages("Assessment")
    assert nav["previous_stage"] == "Applied"
    assert nav["next_stage"] == "Interview"

def test_tracker_board_api(client):
    res = client.post("/api/applications/board/validate-move", json={
        "current_stage": "Interview",
        "target_stage": "Selected"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["result"]["valid"] is True
