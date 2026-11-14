"""
Unit and integration tests for Subject-Based Interviews (#272).
Verifies:
- Subject catalog includes Python, Java, SQL, DBMS, Operating Systems, and Computer Networks.
- Question generation produces subject-appropriate questions with targeted technical concepts.
- Answer evaluation checks technical keyword integration, depth, and returns subject-tailored feedback.
- Empty answer handling returns 0 score without exceptions.
- API endpoints /api/interview/subjects, /api/interview/subject/generate, /api/interview/subject/evaluate.
"""

import json
import pytest
from app import app
import config
from utils.database import init_db
from utils.subject_interview_service import (
    get_subject_catalog,
    generate_subject_question,
    evaluate_subject_answer,
    CANONICAL_SUBJECTS,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_subject_interview.db")
    monkeypatch.setattr(config, "DATABASE_PATH", test_db)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()
    return test_db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["ENFORCE_LOGIN_IN_TESTS"] = False
    with app.test_client() as client:
        yield client


def test_subject_catalog_contains_core_subjects():
    """Verify catalog lists Python, Java, SQL, DBMS, OS, and Computer Networks."""
    catalog = get_subject_catalog()
    assert len(catalog) >= 6
    names = [s["name"] for s in catalog]
    assert "Python" in names
    assert "Java" in names
    assert "SQL" in names
    assert "DBMS" in names
    assert "Operating Systems" in names
    assert "Computer Networks" in names


def test_generate_subject_question():
    """Verify question generation tailored to each specific subject."""
    q_py = generate_subject_question("Python")
    assert "GIL" in q_py["question"] or "python" in q_py["question"].lower()
    assert q_py["subject_name"] == "Python"

    q_os = generate_subject_question("Operating Systems")
    assert "thread" in q_os["question"].lower() or "deadlock" in q_os["question"].lower() or "memory" in q_os["question"].lower()

    q_net = generate_subject_question("Computer Networks")
    assert "tcp" in q_net["question"].lower() or "dns" in q_net["question"].lower()


def test_evaluate_subject_answer():
    """Verify evaluation scores subject terminology and provides constructive feedback."""
    good_py_answer = (
        "The Python Global Interpreter Lock (GIL) is a mutex that prevents multiple native threads "
        "from executing Python bytecodes simultaneously. For CPU-bound tasks, we can use the multiprocessing "
        "module to bypass the GIL and utilize multiple CPU cores."
    )
    res = evaluate_subject_answer("Python", "Explain GIL", good_py_answer)
    assert res["score"] >= 75
    assert "Python" in res["verdict"]
    assert len(res["matched_keywords"]) >= 2

    # Empty answer
    res_empty = evaluate_subject_answer("SQL", "Explain window functions", "")
    assert res_empty["score"] == 0
    assert res_empty["verdict"] == "Unanswered"


def test_api_subject_interview_endpoints(client):
    """Test REST API endpoints for subject mock interview workflow."""
    # 1. Subjects catalog
    resp_cat = client.get("/api/interview/subjects")
    assert resp_cat.status_code == 200
    data_cat = resp_cat.get_json()
    assert data_cat["status"] == "success"
    assert len(data_cat["subjects"]) >= 6

    # 2. Generate question for SQL
    resp_gen = client.post(
        "/api/interview/subject/generate",
        data=json.dumps({"subject": "sql"}),
        content_type="application/json"
    )
    assert resp_gen.status_code == 200
    data_gen = resp_gen.get_json()
    assert data_gen["status"] == "success"
    assert data_gen["data"]["subject_slug"] == "sql"

    # 3. Evaluate answer for SQL
    resp_eval = client.post(
        "/api/interview/subject/evaluate",
        data=json.dumps({
            "subject": "sql",
            "question": data_gen["data"]["question"],
            "answer": "RANK() leaves gaps in rankings upon ties whereas DENSE_RANK() provides contiguous ranks without skipping."
        }),
        content_type="application/json"
    )
    assert resp_eval.status_code == 200
    data_eval = resp_eval.get_json()
    assert data_eval["status"] == "success"
    assert data_eval["evaluation"]["score"] >= 60
