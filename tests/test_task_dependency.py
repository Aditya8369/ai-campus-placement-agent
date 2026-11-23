"""
Unit tests for Preparation task dependency view (#606)
"""

import pytest
from utils.task_dependency_service import (
    DEFAULT_TASK_DEPENDENCY_GRAPH,
    detect_cycle_in_dependencies,
    evaluate_task_dependency_states,
    complete_task_with_validation
)


def test_detect_cycle_in_dependencies():
    # Valid acyclic tasks
    tasks = [
        {"id": "A", "prerequisites": []},
        {"id": "B", "prerequisites": ["A"]},
        {"id": "C", "prerequisites": ["B"]}
    ]
    has_cycle, _ = detect_cycle_in_dependencies(tasks)
    assert has_cycle is False

    # Circular tasks
    circular_tasks = [
        {"id": "A", "prerequisites": ["C"]},
        {"id": "B", "prerequisites": ["A"]},
        {"id": "C", "prerequisites": ["B"]}
    ]
    has_cycle, cycle = detect_cycle_in_dependencies(circular_tasks)
    assert has_cycle is True
    assert len(cycle) >= 3


def test_evaluate_task_dependency_states():
    # Initially, root tasks are available, children are locked
    eval_res = evaluate_task_dependency_states(DEFAULT_TASK_DEPENDENCY_GRAPH, completed_task_ids=[])
    assert eval_res["status"] == "success"
    task_map = {t["id"]: t for t in eval_res["tasks"]}
    
    assert task_map["task_arrays"]["status"] == "available"
    assert task_map["task_sql_basics"]["status"] == "available"
    assert task_map["task_linked_lists"]["status"] == "locked"
    assert "task_arrays" in task_map["task_linked_lists"]["unmet_prerequisites"]

    # When task_arrays is completed, task_linked_lists becomes available
    eval_after = evaluate_task_dependency_states(DEFAULT_TASK_DEPENDENCY_GRAPH, completed_task_ids=["task_arrays"])
    after_map = {t["id"]: t for t in eval_after["tasks"]}
    assert after_map["task_arrays"]["status"] == "completed"
    assert after_map["task_linked_lists"]["status"] == "available"


def test_complete_task_with_validation():
    # Cannot complete locked task
    ok, err, completed = complete_task_with_validation(
        task_id="task_linked_lists",
        tasks=DEFAULT_TASK_DEPENDENCY_GRAPH,
        completed_task_ids=[]
    )
    assert ok is False
    assert "prerequisites are unfinished" in err

    # Can complete available root task
    ok2, err2, completed2 = complete_task_with_validation(
        task_id="task_arrays",
        tasks=DEFAULT_TASK_DEPENDENCY_GRAPH,
        completed_task_ids=[]
    )
    assert ok2 is True
    assert "task_arrays" in completed2


def test_api_task_dependencies(client):
    # GET dependency states
    resp = client.get("/api/tasks/dependencies")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert len(data["tasks"]) > 0

    # POST complete task
    complete_resp = client.post(
        "/api/tasks/dependencies",
        json={
            "action": "complete",
            "task_id": "task_arrays",
            "completed_ids": []
        }
    )
    assert complete_resp.status_code == 200
    comp_data = complete_resp.get_json()
    assert "task_arrays" in comp_data["updated_completed_ids"]
