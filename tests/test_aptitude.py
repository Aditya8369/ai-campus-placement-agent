"""
Unit and Integration Test Suite for Timed Aptitude Practice Module (#426).

Acceptance Criteria Tested:
1. Curated question bank in data/aptitude_questions.json across Quantitative, Logical, and Verbal.
2. Timed set generation with client sanitization (answers and explanations omitted).
3. Accurate scoring, per-topic accuracy, per-category breakdown, and detailed explanations.
4. Countdown timeout handling (auto-submit preserves partial score, sets timed_out flag).
5. Identification of weak topics (<60% accuracy) for dashboard display.
6. Persistent attempt tracking in SQLite per student with strict user isolation.
7. Web view (/aptitude) and REST API endpoints.
"""

import json
import pytest

from app import app
from utils.database import (
    init_db,
    save_aptitude_attempt,
    get_student_aptitude_attempts,
    get_aptitude_attempt_by_id,
    get_student_weak_aptitude_topics,
    delete_student_aptitude_attempts
)
from utils.aptitude_service import (
    load_aptitude_questions,
    get_question_by_id,
    get_questions_by_category,
    generate_aptitude_test_set,
    evaluate_aptitude_submission,
    record_and_evaluate_aptitude_test,
    get_student_aptitude_summary,
    VALID_CATEGORIES,
    WEAK_TOPIC_THRESHOLD_PCT
)


@pytest.fixture(autouse=True)
def setup_test_db():
    """Ensure database schema is initialized before every test."""
    init_db()


@pytest.fixture
def client():
    """Flask test client fixture."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as test_client:
        with app.app_context():
            yield test_client


# ==============================================================================
# 1. Question Bank Integrity Tests
# ==============================================================================

class TestAptitudeQuestionBank:
    """Verifies curated aptitude question bank structure, schema, and validity."""

    def test_load_aptitude_questions_has_all_categories(self):
        questions = load_aptitude_questions()
        assert isinstance(questions, list)
        assert len(questions) >= 30

        categories = {q.get("category") for q in questions}
        assert "quantitative" in categories
        assert "logical_reasoning" in categories
        assert "verbal_ability" in categories

        # Validate that each question has required keys and valid answers
        for q in questions:
            assert "id" in q and q["id"].strip()
            assert "category" in q and q["category"] in VALID_CATEGORIES
            assert "topic" in q and q["topic"].strip()
            assert "question" in q and len(q["question"]) > 10
            assert "options" in q and isinstance(q["options"], list)
            assert len(q["options"]) >= 4
            assert "answer" in q and q["answer"].strip()
            assert q["answer"] in q["options"], f"Answer '{q['answer']}' must be in options for question {q['id']}"
            assert "explanation" in q and len(q["explanation"]) > 15

    def test_get_question_by_id_valid_and_invalid(self):
        q = get_question_by_id("quant_01")
        assert q is not None
        assert q["topic"] == "Time and Work"
        assert q["category"] == "quantitative"

        missing = get_question_by_id("non_existent_q_999")
        assert missing is None

    def test_get_questions_by_category_filtering(self):
        quant = get_questions_by_category("quantitative")
        assert len(quant) >= 10
        assert all(q["category"] == "quantitative" for q in quant)

        logical = get_questions_by_category("logical_reasoning")
        assert len(logical) >= 10
        assert all(q["category"] == "logical_reasoning" for q in logical)

        verbal = get_questions_by_category("verbal_ability")
        assert len(verbal) >= 10
        assert all(q["category"] == "verbal_ability" for q in verbal)

        all_q = get_questions_by_category("all")
        assert len(all_q) >= 30


# ==============================================================================
# 2. Test Set Generation & Client Sanitization
# ==============================================================================

class TestAptitudeTestGeneration:
    """Verifies test set sampling, question selection, and answer sanitization."""

    def test_generate_comprehensive_test_set(self):
        test_set = generate_aptitude_test_set(category="all", num_questions=12, time_limit_seconds=720)
        assert test_set["test_id"].startswith("test_")
        assert test_set["total_questions"] == 12
        assert test_set["time_limit_seconds"] == 720
        assert len(test_set["questions"]) == 12

        # Verify balanced categories
        cats = [q["category"] for q in test_set["questions"]]
        assert "quantitative" in cats
        assert "logical_reasoning" in cats
        assert "verbal_ability" in cats

    def test_generate_sectional_test_set(self):
        test_set = generate_aptitude_test_set(category="quantitative", num_questions=8)
        assert test_set["total_questions"] == 8
        assert all(q["category"] == "quantitative" for q in test_set["questions"])

    def test_generate_test_set_sanitizes_answers(self):
        """CRITICAL: Answers and explanations must NOT be sent to client when taking test."""
        test_set = generate_aptitude_test_set(category="all", num_questions=5)
        for q in test_set["questions"]:
            assert "answer" not in q, f"Correct answer leaked in client test question: {q['id']}"
            assert "explanation" not in q, f"Explanation leaked in client test question: {q['id']}"
            assert "question" in q
            assert "options" in q
            assert "topic" in q

    def test_auto_calculated_time_limit(self):
        # 10 questions defaults to 600 seconds (10 mins)
        test_set = generate_aptitude_test_set(num_questions=10)
        assert test_set["time_limit_seconds"] == 600


# ==============================================================================
# 3. Scoring, Accuracy & Timeout Evaluation
# ==============================================================================

class TestAptitudeEvaluation:
    """Verifies score computation, topic diagnostic accuracy, weak topic identification, and timeout."""

    def test_scoring_perfect_all_correct(self):
        q_ids = ["quant_01", "quant_02", "logical_01", "verbal_01"]
        answers = {
            "quant_01": "4/9",
            "quant_02": "$240",
            "logical_01": "Only conclusion II follows",
            "verbal_01": "Part C"
        }

        res = evaluate_aptitude_submission(
            question_ids=q_ids,
            answers=answers,
            time_taken_seconds=180,
            time_limit_seconds=600,
            timed_out=False
        )

        assert res["total_questions"] == 4
        assert res["correct_count"] == 4
        assert res["incorrect_count"] == 0
        assert res["unattempted_count"] == 0
        assert res["score_percentage"] == 100.0
        assert res["timed_out"] is False
        assert len(res["weak_topics"]) == 0

        # Explanations must be populated in results
        assert len(res["reviews"]) == 4
        for rev in res["reviews"]:
            assert rev["is_correct"] is True
            assert rev["explanation"] != ""

    def test_scoring_partial_incorrect_and_unattempted(self):
        q_ids = ["quant_01", "quant_02", "logical_01", "verbal_01"]
        answers = {
            "quant_01": "4/9",               # Correct
            "quant_02": "$320",               # Incorrect ($240 was correct)
            # logical_01 omitted -> Unattempted
            "verbal_01": "Part C"             # Correct
        }

        res = evaluate_aptitude_submission(
            question_ids=q_ids,
            answers=answers,
            time_taken_seconds=240,
            time_limit_seconds=600,
            timed_out=False
        )

        assert res["total_questions"] == 4
        assert res["correct_count"] == 2
        assert res["incorrect_count"] == 1
        assert res["unattempted_count"] == 1
        assert res["score_percentage"] == 50.0

        # Topic accuracy verification
        topics = res["topic_accuracy"]
        assert "Time and Work" in topics
        assert topics["Time and Work"]["accuracy_percentage"] == 100.0

        assert "Profit and Loss" in topics
        assert topics["Profit and Loss"]["accuracy_percentage"] == 0.0
        assert topics["Profit and Loss"]["is_weak"] is True

        assert "Syllogisms" in topics
        assert topics["Syllogisms"]["accuracy_percentage"] == 0.0
        assert topics["Syllogisms"]["is_weak"] is True

        # Weak topics detected (<60% accuracy)
        weak_names = [wt["topic"] for wt in res["weak_topics"]]
        assert "Profit and Loss" in weak_names
        assert "Syllogisms" in weak_names

    def test_timeout_handling_auto_submit(self):
        q_ids = ["quant_01", "quant_02"]
        answers = {
            "quant_01": "4/9"  # Answered 1 before time ran out
        }

        res = evaluate_aptitude_submission(
            question_ids=q_ids,
            answers=answers,
            time_taken_seconds=600,
            time_limit_seconds=600,
            timed_out=True
        )

        assert res["timed_out"] is True
        assert res["total_questions"] == 2
        assert res["correct_count"] == 1
        assert res["unattempted_count"] == 1
        assert res["score_percentage"] == 50.0


# ==============================================================================
# 4. Database Persistence & Weak Topics History
# ==============================================================================

class TestAptitudeDatabaseStorage:
    """Verifies SQLite storage, per-student isolation, and multi-test weak topic aggregation."""

    def test_save_and_retrieve_attempts(self):
        student_id = "student_aptitude_test_01"
        delete_student_aptitude_attempts(student_id)

        saved = save_aptitude_attempt(
            student_id=student_id,
            test_category="quantitative",
            total_questions=10,
            correct_count=7,
            score_percentage=70.0,
            time_taken_seconds=520,
            time_limit_seconds=600,
            timed_out=False,
            topic_accuracy_json=json.dumps({"Time and Work": {"total": 2, "correct": 2, "accuracy_percentage": 100.0}}),
            weak_topics_json=json.dumps([]),
            results_json=json.dumps({"score_percentage": 70.0})
        )

        assert saved["id"] is not None
        assert saved["student_id"] == student_id
        assert saved["score_percentage"] == 70.0

        history = get_student_aptitude_attempts(student_id)
        assert len(history) == 1
        assert history[0]["id"] == saved["id"]
        assert history[0]["topic_accuracy"]["Time and Work"]["accuracy_percentage"] == 100.0

        delete_student_aptitude_attempts(student_id)

    def test_student_data_isolation(self):
        student_a = "student_apt_alpha"
        student_b = "student_apt_beta"
        delete_student_aptitude_attempts(student_a)
        delete_student_aptitude_attempts(student_b)

        save_aptitude_attempt(
            student_id=student_a,
            test_category="quantitative",
            total_questions=10,
            correct_count=8,
            score_percentage=80.0,
            time_taken_seconds=400,
            time_limit_seconds=600,
            timed_out=False,
            topic_accuracy_json="{}",
            weak_topics_json="[]",
            results_json="{}"
        )

        save_aptitude_attempt(
            student_id=student_b,
            test_category="verbal_ability",
            total_questions=10,
            correct_count=5,
            score_percentage=50.0,
            time_taken_seconds=600,
            time_limit_seconds=600,
            timed_out=True,
            topic_accuracy_json="{}",
            weak_topics_json="[]",
            results_json="{}"
        )

        history_a = get_student_aptitude_attempts(student_a)
        history_b = get_student_aptitude_attempts(student_b)

        assert len(history_a) == 1
        assert history_a[0]["test_category"] == "quantitative"
        assert history_a[0]["score_percentage"] == 80.0

        assert len(history_b) == 1
        assert history_b[0]["test_category"] == "verbal_ability"
        assert history_b[0]["score_percentage"] == 50.0

        delete_student_aptitude_attempts(student_a)
        delete_student_aptitude_attempts(student_b)

    def test_multi_attempt_weak_topics_aggregation(self):
        student_id = "student_weak_topics_test"
        delete_student_aptitude_attempts(student_id)

        # Attempt 1: Failed Profit and Loss (0/2), Passed Time and Work (2/2)
        save_aptitude_attempt(
            student_id=student_id,
            test_category="quantitative",
            total_questions=4,
            correct_count=2,
            score_percentage=50.0,
            time_taken_seconds=300,
            time_limit_seconds=600,
            timed_out=False,
            topic_accuracy_json=json.dumps({
                "Profit and Loss": {"category": "quantitative", "total": 2, "correct": 0},
                "Time and Work": {"category": "quantitative", "total": 2, "correct": 2}
            }),
            weak_topics_json="[]",
            results_json="{}"
        )

        # Attempt 2: Failed Profit and Loss again (0/1), Passed Syllogisms (2/2)
        save_aptitude_attempt(
            student_id=student_id,
            test_category="all",
            total_questions=3,
            correct_count=2,
            score_percentage=66.7,
            time_taken_seconds=200,
            time_limit_seconds=600,
            timed_out=False,
            topic_accuracy_json=json.dumps({
                "Profit and Loss": {"category": "quantitative", "total": 1, "correct": 0},
                "Syllogisms": {"category": "logical_reasoning", "total": 2, "correct": 2}
            }),
            weak_topics_json="[]",
            results_json="{}"
        )

        weak_topics = get_student_weak_aptitude_topics(student_id, threshold=WEAK_TOPIC_THRESHOLD_PCT)
        assert len(weak_topics) == 1
        wt = weak_topics[0]
        assert wt["topic"] == "Profit and Loss"
        assert wt["total_questions"] == 3
        assert wt["correct_answers"] == 0
        assert wt["accuracy_percentage"] == 0.0

        # Summary computation
        summary = get_student_aptitude_summary(student_id)
        assert summary["has_attempts"] is True
        assert summary["total_attempts"] == 2
        assert len(summary["weak_topics"]) == 1

        delete_student_aptitude_attempts(student_id)


# ==============================================================================
# 5. HTTP Views & REST API Endpoints
# ==============================================================================

class TestAptitudeEndpoints:
    """Verifies HTTP routes, test session generation, submission evaluation, and errors."""

    def test_get_aptitude_view_page(self, client):
        response = client.get("/aptitude")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Timed Aptitude Practice" in html
        assert "Choose Practice Mode" in html
        assert "Comprehensive Placement Test" in html
        assert "Quantitative Aptitude" in html
        assert "Logical Reasoning" in html
        assert "Verbal Ability" in html

    def test_api_start_test_endpoint(self, client):
        response = client.post(
            "/api/aptitude/start",
            json={
                "category": "quantitative",
                "num_questions": 5,
                "time_limit_seconds": 300
            }
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        test_set = data["data"]
        assert test_set["category"] == "quantitative"
        assert test_set["total_questions"] == 5
        assert len(test_set["questions"]) == 5

        # Check answers stripped
        for q in test_set["questions"]:
            assert "answer" not in q
            assert "explanation" not in q

    def test_api_submit_endpoint_missing_questions(self, client):
        response = client.post(
            "/api/aptitude/submit",
            json={
                "question_ids": [],
                "answers": {}
            }
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["status"] == "error"
        assert "question_ids" in data["message"]

    def test_api_submit_endpoint_success(self, client):
        response = client.post(
            "/api/aptitude/submit",
            json={
                "question_ids": ["quant_01", "quant_02"],
                "answers": {
                    "quant_01": "4/9",
                    "quant_02": "$240"
                },
                "time_taken_seconds": 120,
                "time_limit_seconds": 600,
                "timed_out": False,
                "test_category": "quantitative"
            }
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        res = data["data"]

        eval_data = res["evaluation"]
        assert eval_data["score_percentage"] == 100.0
        assert eval_data["correct_count"] == 2
        assert "topic_accuracy" in eval_data
        assert "reviews" in eval_data
        assert len(eval_data["reviews"]) == 2
        assert eval_data["reviews"][0]["explanation"] != ""

        # Saved attempt record returned
        attempt = res["attempt"]
        assert attempt["id"] is not None
        assert attempt["score_percentage"] == 100.0

    def test_api_history_endpoint(self, client):
        # Run a submission first
        client.post(
            "/api/aptitude/submit",
            json={
                "question_ids": ["verbal_01"],
                "answers": {"verbal_01": "Part C"},
                "time_taken_seconds": 30,
                "time_limit_seconds": 600,
                "timed_out": False,
                "test_category": "verbal_ability"
            }
        )

        response = client.get("/api/aptitude/history")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert data["count"] >= 1
        assert isinstance(data["attempts"], list)

    def test_api_weak_topics_endpoint(self, client):
        response = client.get("/api/aptitude/weak-topics")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert "weak_topics" in data
