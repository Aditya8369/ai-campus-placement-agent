"""
Unit & Integration Tests for Custom Technical Topic AI Interview Practice Mode (#255)
======================================================================================
Tests:
1. Supported topics catalog retrieval and metadata integrity.
2. Question generation across topics (dsa, system_design, database, etc.) and difficulty levels.
3. Validation and error handling for invalid or unsupported topics/difficulties.
4. Comprehensive answer evaluation (technical accuracy, depth, conceptual coverage).
5. Unanswered or low-effort response handling with targeted suggestions.
6. Persistent practice session history recording and retrieval per student.
7. REST API Endpoints:
   - GET /api/interview/practice/topics
   - POST /api/interview/practice/generate
   - POST /api/interview/practice/evaluate
   - GET /api/interview/practice/history
"""

import pytest
import json
import uuid

import config
from utils.database import init_db, get_db_connection
from utils.topic_practice_service import (
    ensure_custom_practice_table,
    get_supported_topics,
    generate_topic_interview_question,
    evaluate_topic_answer,
    record_practice_session,
    get_student_practice_history,
    SUPPORTED_TOPICS
)
from app import app


@pytest.fixture
def practice_env(tmp_path, monkeypatch):
    """Sets up an isolated database and test client for custom topic practice."""
    test_db = tmp_path / "test_topic_practice.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    with get_db_connection() as conn:
        ensure_custom_practice_table(conn)

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "topic-practice-secret-test"

    with app.test_client() as client:
        yield client


def test_supported_topics_catalog():
    """Verify supported topics return required titles, descriptions, and keywords."""
    catalog = get_supported_topics()
    assert "topics" in catalog
    assert "difficulty_levels" in catalog
    assert len(catalog["topics"]) >= 5
    topic_keys = [t["key"] for t in catalog["topics"]]
    assert "dsa" in topic_keys
    assert "system_design" in topic_keys
    assert "database" in topic_keys
    assert "easy" in catalog["difficulty_levels"]
    assert "hard" in catalog["difficulty_levels"]


def test_question_generation_valid_topics():
    """Verify questions are generated for valid topic and difficulty combinations."""
    for topic in ["dsa", "system_design", "database"]:
        for diff in ["easy", "medium", "hard"]:
            res = generate_topic_interview_question(topic=topic, difficulty=diff)
            assert res["topic_key"] == topic
            assert res["difficulty"] == diff
            assert len(res["question"]) > 20
            assert "expected_concepts" in res


def test_question_generation_unsupported_topic():
    """Verify error is raised when requesting invalid topic or difficulty."""
    with pytest.raises(ValueError) as exc:
        generate_topic_interview_question(topic="astrology", difficulty="easy")
    assert "Unsupported topic" in str(exc.value)

    with pytest.raises(ValueError) as exc_diff:
        generate_topic_interview_question(topic="dsa", difficulty="impossible")
    assert "Invalid difficulty" in str(exc_diff.value)


def test_evaluate_topic_answer_high_quality():
    """Verify high-quality answer receives strong technical and depth scores."""
    question = "Explain how an LRU Cache is implemented in O(1) get and put operations."
    answer = (
        "An LRU cache achieves O(1) time complexity by combining a Hash Map with a Doubly Linked List. "
        "The hash map stores keys mapped to pointers/references of doubly linked list nodes, allowing O(1) lookup. "
        "The doubly linked list maintains the temporal order of usage: recently accessed items are moved to the head, "
        "while the least recently used item sits at the tail. When capacity is exceeded, the node at the tail is evicted "
        "in O(1) time by removing it from both the list and the map. For thread safety, a ReentrantReadWriteLock or striped locks can be used."
    )
    eval_result = evaluate_topic_answer(topic="dsa", difficulty="hard", question=question, answer=answer)

    assert eval_result["score"] >= 75
    assert eval_result["verdict"] in ("Good", "Excellent")
    assert eval_result["technical_depth_score"] >= 70
    assert len(eval_result["matched_concepts"]) > 0
    assert "doubly linked list" in answer.lower()


def test_evaluate_topic_answer_empty_or_poor():
    """Verify empty response is flagged as unanswered with actionable suggestions."""
    eval_empty = evaluate_topic_answer(topic="database", difficulty="medium", question="Explain ACID.", answer="")
    assert eval_empty["score"] == 0
    assert eval_empty["verdict"] == "Unanswered"
    assert len(eval_empty["improvement_suggestions"]) > 0


def test_record_and_retrieve_practice_history(practice_env):
    """Verify recording practice sessions and retrieving student history."""
    student = "student_topic_alpha"
    eval_res = {
        "score": 85,
        "verdict": "Excellent",
        "technical_depth_score": 88,
        "conceptual_coverage_score": 85,
        "clarity_score": 90,
        "matched_concepts": ["indexing", "b-trees"],
        "missed_concepts": [],
        "strengths": ["Clear explanation"],
        "improvement_suggestions": [],
        "topic_feedback": "Strong grasp of database indexing."
    }

    recorded = record_practice_session(
        student_id=student,
        topic="database",
        difficulty="medium",
        question_id="db-m1",
        question_text="Explain B+ Trees in indexing.",
        answer="B+ trees provide high branching factor and disk page alignment.",
        evaluation=eval_res
    )

    assert recorded["student_id"] == student
    assert recorded["score"] == 85

    history = get_student_practice_history(student)
    assert len(history) == 1
    assert history[0]["topic_key"] == "database"
    assert history[0]["score"] == 85
    assert history[0]["evaluation"]["verdict"] == "Excellent"


def test_api_practice_endpoints(practice_env):
    """Verify REST API flow for topic practice mode."""
    # 1. GET topics
    resp_topics = practice_env.get("/api/interview/practice/topics")
    assert resp_topics.status_code == 200
    assert len(resp_topics.get_json()["data"]["topics"]) >= 5

    # 2. POST generate
    resp_gen = practice_env.post("/api/interview/practice/generate", json={
        "topic": "system_design",
        "difficulty": "medium"
    })
    assert resp_gen.status_code == 200
    gen_data = resp_gen.get_json()["data"]
    assert "question" in gen_data
    assert gen_data["topic_key"] == "system_design"

    # 3. POST evaluate
    resp_eval = practice_env.post("/api/interview/practice/evaluate", json={
        "topic": "system_design",
        "difficulty": "medium",
        "question": gen_data["question"],
        "question_id": gen_data["question_id"],
        "answer": "We use load balancers, redis caching, and horizontal sharding to achieve scalability and fault tolerance."
    })
    assert resp_eval.status_code == 200
    eval_data = resp_eval.get_json()
    assert eval_data["status"] == "success"
    assert "evaluation" in eval_data
    assert eval_data["evaluation"]["score"] > 0

    # 4. GET history
    resp_hist = practice_env.get("/api/interview/practice/history")
    assert resp_hist.status_code == 200
    hist_data = resp_hist.get_json()
    assert hist_data["total_sessions"] >= 1
