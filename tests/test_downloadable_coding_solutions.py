import pytest
from app import app
from utils.coding_export_service import CodingSolutionsExportService, coding_export_service


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_record_and_list_solutions():
    service = CodingSolutionsExportService()
    student = "student_export_1"

    sid = service.record_solution(
        student_id=student,
        problem_id="prob_binary_search",
        problem_title="Binary Search in Sorted Array",
        programming_language="python",
        solution_code="def search(nums, target):\n    # implementation\n    return 0",
        difficulty="Easy",
        time_complexity="O(log N)",
        space_complexity="O(1)",
        notes="Standard binary search using two pointers."
    )
    assert sid > 0

    solutions = service.list_student_solutions(student)
    assert len(solutions) >= 1
    assert solutions[0]["problem_id"] == "prob_binary_search"
    assert solutions[0]["time_complexity"] == "O(log N)"


def test_export_solutions_as_markdown():
    service = CodingSolutionsExportService()
    student = "student_export_2"

    service.record_solution(
        student_id=student,
        problem_id="prob_merge_intervals",
        problem_title="Merge Overlapping Intervals",
        programming_language="python",
        solution_code="def merge(intervals):\n    return []",
        difficulty="Medium",
        notes="Sort by start interval first."
    )

    md = service.export_solutions_as_markdown(student)
    assert "# AI Campus Placement Agent - Coding Solutions Portfolio" in md
    assert "Merge Overlapping Intervals (Medium)" in md
    assert "```python" in md
    assert "Sort by start interval first" in md


def test_export_solutions_as_json():
    service = CodingSolutionsExportService()
    student = "student_export_3"

    service.record_solution(
        student_id=student,
        problem_id="prob_lru",
        problem_title="LRU Cache",
        programming_language="cpp",
        solution_code="class LRUCache {};",
        difficulty="Hard"
    )

    json_export = service.export_solutions_as_json(student)
    assert json_export["student_id"] == student
    assert json_export["total_solutions"] >= 1
    assert any(s["problem_id"] == "prob_lru" for s in json_export["solutions"])


def test_api_coding_solution_endpoints(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "student_api_code_export"

    # POST record solution
    post_res = client.post("/api/coding/solutions", json={
        "problem_id": "prob_api_1",
        "problem_title": "Valid Parentheses",
        "programming_language": "python",
        "solution_code": "def isValid(s):\n    return True",
        "difficulty": "Easy"
    })
    assert post_res.status_code == 201
    assert post_res.get_json()["success"] is True

    # GET solutions
    list_res = client.get("/api/coding/solutions")
    assert list_res.status_code == 200
    assert list_res.get_json()["count"] >= 1

    # GET export Markdown
    md_res = client.get("/api/coding/export-solutions?format=markdown")
    assert md_res.status_code == 200
    assert "Valid Parentheses" in md_res.get_json()["content"]

    # GET export JSON
    json_res = client.get("/api/coding/export-solutions?format=json")
    assert json_res.status_code == 200
    assert json_res.get_json()["export"]["total_solutions"] >= 1
