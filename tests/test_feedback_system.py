import pytest
import json
import uuid
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    submit_user_feedback,
    get_user_feedback_list,
    get_feedback_metrics_summary
)

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_feedback.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = "test_feedback_user"
                sess["user_name"] = "Feedback Student"
            yield client


def test_database_feedback_crud_and_metrics(tmp_path):
    test_db = tmp_path / "test_db_fb.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        student_id = "student_fb_01"

        # 1. Insert feedback records
        fb1 = submit_user_feedback(
            student_id=student_id,
            rating=5,
            category="Resume Analysis & ATS Scoring",
            comment="The ATS score breakdowns and missing keywords were spot on!"
        )
        assert fb1["student_id"] == student_id
        assert fb1["rating"] == 5

        submit_user_feedback(
            student_id="student_fb_02",
            rating=4,
            category="Mock Interview Simulator",
            comment="Great live questions, would love more system design prompts."
        )

        submit_user_feedback(
            student_id=student_id,
            rating=5,
            category="Coding Practice & DSA",
            comment="Saved so much time practicing test cases directly."
        )

        # 2. Test list retrieval
        all_fb = get_user_feedback_list()
        assert len(all_fb) == 3

        # 3. Test filter by student
        student_fb = get_user_feedback_list(student_id=student_id)
        assert len(student_fb) == 2

        # 4. Test filter by category
        interview_fb = get_user_feedback_list(category_filter="Mock Interview Simulator")
        assert len(interview_fb) == 1
        assert interview_fb[0]["comment"] == "Great live questions, would love more system design prompts."

        # 5. Test metrics calculation
        metrics = get_feedback_metrics_summary()
        assert metrics["total_feedback"] == 3
        assert metrics["five_star_count"] == 2
        assert metrics["four_star_count"] == 1
        assert metrics["avg_rating"] == pytest.approx(4.67, 0.05)
        assert len(metrics["category_breakdown"]) == 3


def test_feedback_endpoints_http(client, tmp_path):
    # 1. GET feedback page
    res_page = client.get("/feedback")
    assert res_page.status_code == 200
    assert b"Platform Feedback & Reviews" in res_page.data

    # 2. POST feedback form submission
    res_post = client.post(
        "/feedback",
        data={
            "category": "Resume Analysis & ATS Scoring",
            "rating": "5",
            "comment": "Saved my placement season!"
        },
        follow_redirects=True
    )
    assert res_post.status_code == 200
    assert b"Saved my placement season!" in res_post.data

    # 3. GET feedback API
    res_api_get = client.get("/api/feedback")
    assert res_api_get.status_code == 200
    api_data = res_api_get.get_json()
    assert api_data["status"] == "success"
    assert api_data["total"] >= 1

    # 4. POST feedback API
    res_api_post = client.post(
        "/api/feedback",
        json={
            "student_id": "api_student",
            "category": "UI & Performance",
            "rating": 5,
            "comment": "Super fast response time and clean dark mode."
        }
    )
    assert res_api_post.status_code == 201
    assert res_api_post.get_json()["status"] == "success"

    # 5. POST feedback API validation failure on empty comment
    res_invalid = client.post(
        "/api/feedback",
        json={
            "category": "UI & Performance",
            "rating": 5,
            "comment": "   "
        }
    )
    assert res_invalid.status_code == 400
    assert "comment is required" in res_invalid.get_json()["message"]
