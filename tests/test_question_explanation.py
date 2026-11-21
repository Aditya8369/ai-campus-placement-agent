"""
Unit tests for Saved Interview Question Explanation Mode (#508).
"""

import json
import pytest
from app import create_app
from utils.question_explanation_service import QuestionExplanationService


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_question_explanation_generation_heuristic():
    """Verify heuristic generation for known technical questions (e.g. REST)."""
    res = QuestionExplanationService.generate_structured_explanation(
        "Explain RESTful API architecture principles", topic="rest"
    )
    assert res["is_ai_generated"] is True
    assert "Statelessness" in res["key_technical_terms"]
    assert len(res["common_mistakes"]) > 0
    assert "REST" in res["main_idea"]
    assert "ai_disclaimer" in res


def test_question_explanation_generic_fallback():
    """Verify dynamic breakdown generation for custom topics."""
    res = QuestionExplanationService.generate_structured_explanation(
        "How do you design a high throughput distributed message queue?",
        topic="Distributed Systems"
    )
    assert res["topic"] == "Distributed Systems"
    assert len(res["key_technical_terms"]) > 0
    assert "Time and Space Complexity" in res["key_technical_terms"] or "Design Patterns" in res["key_technical_terms"]
    assert len(res["related_questions"]) == 3


def test_api_question_explanation_endpoints(client):
    """Test REST API retrieval, creation, list, and deletion."""
    test_user = "test_student_expl_508"

    with client.session_transaction() as sess:
        sess["user_id"] = test_user

    # 1. Fetch explanation via GET
    resp = client.get("/api/interview/questions/q101/explanation?question_text=Explain+database+indexes&topic=database")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["status"] == "success"
    assert "explanation" in data
    assert data["explanation"]["user_id"] == test_user
    assert data["explanation"]["question_id"] == "q101"

    # 2. List saved explanations
    resp_list = client.get("/api/interview/questions/saved-explanations")
    assert resp_list.status_code == 200
    list_data = json.loads(resp_list.data)
    assert list_data["count"] >= 1
    assert any(e["question_id"] == "q101" for e in list_data["explanations"])

    # 3. Save custom explanation via POST
    post_payload = {
        "question_text": "What is polymorphism in OOP?",
        "topic": "oop"
    }
    resp_post = client.post(
        "/api/interview/questions/q102/explanation",
        json=post_payload,
        content_type="application/json"
    )
    assert resp_post.status_code == 200
    post_data = json.loads(resp_post.data)
    assert post_data["status"] == "success"
    assert post_data["explanation"]["question_id"] == "q102"
    assert "Polymorphism" in post_data["explanation"]["key_technical_terms"]

    # 4. Delete saved explanation
    resp_del = client.delete("/api/interview/questions/q101/explanation")
    assert resp_del.status_code == 200
    del_data = json.loads(resp_del.data)
    assert del_data["status"] == "success"
