"""
Unit tests for Unsuitable Mock-Interview Question Reporting and Flagging (#327).
"""

import pytest
from app import app
from utils.database import get_db_connection, init_db
from utils.question_flag_service import (
    flag_interview_question,
    get_flagged_questions_summary,
    compute_question_hash,
    VALID_FLAG_REASONS
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def clean_flags_table():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS unsuitable_question_flags")
    conn.commit()
    conn.close()
    yield
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS unsuitable_question_flags")
    conn.commit()
    conn.close()


def test_compute_question_hash():
    h1 = compute_question_hash("How does Redis handle master-slave replication?")
    h2 = compute_question_hash("how does redis handle master-slave replication?")
    assert h1 == h2
    assert len(h1) == 16


def test_flag_interview_question_success():
    res = flag_interview_question(
        student_id="student-101",
        session_id="session-xyz",
        question_index=2,
        question_text="What is the square root of a banana?",
        reason="Irrelevant to Target Role",
        comment="This has nothing to do with software development."
    )
    assert res["success"] is True
    assert res["report_id"].startswith("flag-")


def test_flag_interview_question_invalid_reason():
    with pytest.raises(ValueError) as exc:
        flag_interview_question(
            student_id="student-101",
            session_id="session-xyz",
            question_index=0,
            question_text="Valid question?",
            reason="CompletelyMadeUpReason"
        )
    assert "Invalid reason" in str(exc.value)


def test_flag_interview_question_empty_text():
    with pytest.raises(ValueError) as exc:
        flag_interview_question(
            student_id="student-101",
            session_id="session-xyz",
            question_index=0,
            question_text="   ",
            reason="Unclear or Ambiguous"
        )
    assert "Question text is required" in str(exc.value)


def test_get_flagged_questions_summary_aggregation():
    # Flag the same question twice by different students
    q = "What is the differences between TCP and UDP?"
    flag_interview_question("student-1", "s1", 0, q, "Unclear or Ambiguous")
    flag_interview_question("student-2", "s2", 1, q, "Factually Incorrect")

    summary = get_flagged_questions_summary()
    assert len(summary) == 1
    item = summary[0]
    assert item["question_text"] == q
    assert item["flag_count"] == 2
    assert len(item["reasons"]) == 2


def test_resolve_and_suppression_logic():
    from utils.question_flag_service import is_question_suppressed, resolve_flagged_question
    q = "Obsolete technical question?"
    assert is_question_suppressed(q, flag_threshold=2) is False

    flag_interview_question("s1", "sess1", 0, q, "Factually Incorrect")
    flag_interview_question("s2", "sess2", 0, q, "Factually Incorrect")
    assert is_question_suppressed(q, flag_threshold=2) is True

    resolved = resolve_flagged_question(compute_question_hash(q), "Suppressed")
    assert resolved is True


def test_api_interview_question_flag_endpoints(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "student-api"

    # 1. Fetch reasons
    res_reasons = client.get("/api/interview/question/flag-reasons")
    assert res_reasons.status_code == 200
    assert len(res_reasons.get_json()["reasons"]) >= 5

    # 2. Submit Flag
    payload = {
        "session_id": "test-session-api",
        "question_index": 1,
        "question_text": "Is C++ better than Rust?",
        "reason": "Irrelevant to Target Role",
        "comment": "Too subjective."
    }
    res_post = client.post("/api/interview/question/flag", json=payload)
    assert res_post.status_code == 200
    assert res_post.get_json()["success"] is True


    with client.session_transaction() as sess:
        sess["user_id"] = "student-api"

    # 1. Fetch reasons
    res_reasons = client.get("/api/interview/question/flag-reasons")
    assert res_reasons.status_code == 200
    assert len(res_reasons.get_json()["reasons"]) >= 5

    # 2. Submit Flag
    payload = {
        "session_id": "test-session-api",
        "question_index": 1,
        "question_text": "Is C++ better than Rust?",
        "reason": "Irrelevant to Target Role",
        "comment": "Too subjective."
    }
    res_post = client.post("/api/interview/question/flag", json=payload)
    assert res_post.status_code == 200
    assert res_post.get_json()["success"] is True
