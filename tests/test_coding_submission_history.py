import pytest
import json
import uuid
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    save_coding_submission,
    get_coding_submissions
)

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_coding_sub.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

def test_database_coding_submission_history(tmp_path):
    test_db = tmp_path / "test_sub_crud.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()

        # Save first attempt (failed)
        sub_1 = save_coding_submission(
            sub_id="sub-01",
            student_id="student_fred",
            question_title="Two Sum",
            language="python",
            code="def twoSum(nums, target):\n    return []",
            passed=False,
            score=20,
            tests_passed=1,
            total_tests=5,
            test_results=[{"input": "[2,7,11,15], 9", "passed": False}],
            complexity_analysis="O(1)",
            feedback="Return correct indices instead of empty list."
        )
        assert sub_1 == "sub-01"

        # Save second attempt (passed)
        sub_2 = save_coding_submission(
            sub_id="sub-02",
            student_id="student_fred",
            question_title="Two Sum",
            language="python",
            code="def twoSum(nums, target):\n    seen = {}\n    for i, n in enumerate(nums):\n        diff = target - n\n        if diff in seen:\n            return [seen[diff], i]\n        seen[n] = i",
            passed=True,
            score=100,
            tests_passed=5,
            total_tests=5,
            test_results=[{"input": "[2,7,11,15], 9", "passed": True}],
            complexity_analysis="O(N) Time, O(N) Space",
            feedback="Optimal hash map solution."
        )
        assert sub_2 == "sub-02"

        # Retrieve attempts
        attempts = get_coding_submissions("student_fred", question_title="Two Sum")
        assert len(attempts) == 2
        # Verify attempt-over-attempt improvement
        assert attempts[0]["score"] == 100  # latest attempt
        assert attempts[1]["score"] == 20   # previous attempt

        # Filter by status
        passed_attempts = get_coding_submissions("student_fred", status_filter="passed")
        assert len(passed_attempts) == 1
        assert passed_attempts[0]["id"] == "sub-02"

        failed_attempts = get_coding_submissions("student_fred", status_filter="failed")
        assert len(failed_attempts) == 1
        assert failed_attempts[0]["id"] == "sub-01"

def test_coding_submission_endpoints(client):
    # GET page
    get_res = client.get("/coding-submissions?student_id=default_student")
    assert get_res.status_code == 200
    assert b"Coding Assessment Submissions" in get_res.data

    # Save via evaluate-code API
    eval_res = client.post("/api/interview/evaluate-code", json={
        "student_id": "default_student",
        "language": "python",
        "code": "def solve(): return True",
        "problem": {
            "title": "Reverse Linked List",
            "description": "Reverse a singly linked list"
        }
    })
    assert eval_res.status_code == 200
    eval_data = json.loads(eval_res.data)
    assert "submission_id" in eval_data

    # Verify presence in submissions API
    sub_res = client.get("/api/coding-submissions?student_id=default_student")
    assert sub_res.status_code == 200
    sub_data = json.loads(sub_res.data)
    assert sub_data["success"] is True
    assert len(sub_data["submissions"]) >= 1
    assert sub_data["submissions"][0]["question_title"] == "Reverse Linked List"
