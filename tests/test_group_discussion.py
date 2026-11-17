"""
Unit and Integration Test Suite for Campus Group Discussion (GD) Practice & AI Feedback Coach (#427).

Acceptance Criteria:
1. Topic list and random topic selection work across Current Affairs, Technology, and Abstract categories.
2. Feedback shows four scored criteria (Content, Structure, Balance, Clarity) plus actionable suggestions:
   - Stronger opening line
   - Crucial counter-point / blind spot missed
3. Empty or very short answers (<30 words) are rejected with a clear message.
4. Tests use a mocked model response (mock_gemini_client).
5. Attempt persistence tracks student practice history in SQLite.
6. API and view endpoints handle inputs, authorization, and error cases gracefully.
"""

import json
import pytest
from unittest.mock import patch

from app import app
from utils.database import (
    init_db,
    save_gd_attempt,
    get_student_gd_attempts,
    get_gd_attempt_by_id,
    delete_student_gd_attempts
)
from utils.group_discussion_service import (
    load_gd_topics,
    get_topic_by_id,
    get_random_topic,
    get_topics_by_category,
    validate_contribution,
    evaluate_gd_contribution,
    generate_fallback_gd_feedback,
    record_and_evaluate_gd_attempt,
    MIN_WORD_COUNT
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


@pytest.fixture
def mock_gd_ai_payload():
    """Sample valid AI response payload conforming to GD evaluation schema."""
    return {
        "overall_score": 84,
        "scores": {
            "content": 85,
            "structure": 82,
            "balance": 80,
            "clarity": 88
        },
        "criteria_feedback": {
            "content": "Strong grasp of generative AI productivity benefits with relevant economic context.",
            "structure": "Logical flow progressing smoothly from short-term disruption to long-term value creation.",
            "balance": "Acknowledges white-collar displacement risks before arguing for cognitive augmentation.",
            "clarity": "Articulate, assertive, and professional delivery suitable for campus selection."
        },
        "strengths": [
            "Clearly articulated the distinction between automation and cognitive augmentation",
            "Used strong conversational hooks that invited group collaboration"
        ],
        "improvements": [
            "Cite concrete statistical studies regarding white-collar productivity gains",
            "Expand on specific entry-level junior developer vulnerabilities"
        ],
        "stronger_opening": "To kick off our discussion on generative AI, I propose we look past polarized hype and evaluate the concrete transition from manual coding to system orchestration.",
        "missed_counterpoint": "Consider how wage stagnation in entry-level engineering could disincentivize STEM enrollments.",
        "summary_verdict": "Very strong, articulate opening that anchors the discussion in actionable industrial realities."
    }


# ==============================================================================
# 1. Topic Bank & Random Selection Tests
# ==============================================================================

class TestGDTopics:
    """Verifies topic loading, categorization, and random selection mechanics."""

    def test_load_gd_topics_contains_all_categories(self):
        topics = load_gd_topics()
        assert isinstance(topics, list)
        assert len(topics) >= 15

        categories = {t.get("category") for t in topics}
        assert "technology" in categories
        assert "current_affairs" in categories
        assert "abstract" in categories

        # Validate structure of each topic
        for t in topics:
            assert "id" in t
            assert "title" in t
            assert "category" in t
            assert "description" in t
            assert "key_angles" in t
            assert len(t["key_angles"]) >= 2

    def test_get_topic_by_id_valid_and_invalid(self):
        topic = get_topic_by_id("gd_tech_01")
        assert topic is not None
        assert "Generative AI" in topic["title"]
        assert topic["category"] == "technology"

        invalid_topic = get_topic_by_id("non_existent_topic_xyz")
        assert invalid_topic is None

    def test_get_random_topic_without_category(self):
        topic = get_random_topic()
        assert topic is not None
        assert "title" in topic
        assert "category" in topic

    def test_get_random_topic_with_category_filter(self):
        tech_topic = get_random_topic(category="technology")
        assert tech_topic["category"] == "technology"

        ca_topic = get_random_topic(category="current_affairs")
        assert ca_topic["category"] == "current_affairs"

        abs_topic = get_random_topic(category="abstract")
        assert abs_topic["category"] == "abstract"

    def test_get_random_topic_invalid_category_raises_error(self):
        with pytest.raises(ValueError) as exc:
            get_random_topic(category="unsupported_quantum_physics")
        assert "No topics found for category" in str(exc.value)

    def test_get_topics_by_category_grouping(self):
        grouped = get_topics_by_category()
        assert "technology" in grouped
        assert "current_affairs" in grouped
        assert "abstract" in grouped
        assert len(grouped["technology"]) >= 4
        assert len(grouped["current_affairs"]) >= 4
        assert len(grouped["abstract"]) >= 4


# ==============================================================================
# 2. Input Validation Tests
# ==============================================================================

class TestGDInputValidation:
    """Verifies strict validation and rejection of empty or excessively short answers."""

    def test_empty_input_rejected(self):
        is_valid, err_msg, count = validate_contribution("")
        assert is_valid is False
        assert "Please write your group discussion contribution before submitting." in err_msg
        assert count == 0

        is_valid, err_msg, count = validate_contribution("    \n\t   ")
        assert is_valid is False
        assert "Please write your group discussion contribution" in err_msg
        assert count == 0

    def test_very_short_answer_rejected(self):
        short_text = "AI is good and bad. It will replace some jobs and help others."
        is_valid, err_msg, count = validate_contribution(short_text)
        assert is_valid is False
        assert count < MIN_WORD_COUNT
        assert "Contribution is too brief" in err_msg
        assert f"{count} words" in err_msg
        assert "at least 30 words" in err_msg

    def test_boundary_29_words_rejected(self):
        words = ["word"] * 29
        text = " ".join(words)
        is_valid, err_msg, count = validate_contribution(text)
        assert is_valid is False
        assert count == 29
        assert "Contribution is too brief" in err_msg

    def test_boundary_30_words_accepted(self):
        words = [
            "Good", "morning", "everyone,", "today", "we", "are", "examining",
            "the", "impact", "of", "generative", "artificial", "intelligence",
            "in", "the", "workplace.", "While", "automation", "displaces", "routine",
            "tasks,", "it", "fundamentally", "augments", "human", "creativity,",
            "strategic", "reasoning,", "and", "productivity."
        ]
        text = " ".join(words)
        is_valid, err_msg, count = validate_contribution(text)
        assert is_valid is True
        assert err_msg == ""
        assert count == 30

    def test_full_paragraph_150_words_accepted(self):
        text = (
            "Good morning respected moderator and colleagues. Today our campus group discussion topic asks "
            "whether generative AI in the modern workplace will act primarily as an outright replacement or an "
            "augmentation of human labour. In my analysis, framing this as an either-or binary choice misses the "
            "underlying structural evolution of modern knowledge work. In the immediate horizon, repetitive cognitive tasks such "
            "as boilerplate unit testing, basic copyediting, and first-tier customer triage are indeed "
            "being automated at scale. However, historical precedents from previous industrial and software "
            "revolutions indicate that technology transforms the nature of work rather than eliminating "
            "the demand for skilled human judgment. Engineers who master generative tooling operate at "
            "a 10x multiplier, shifting their focus toward architectural integrity, safety alignment, "
            "and domain-specific problem formulation. Therefore, generative AI does not replace engineers; "
            "rather, engineers fluent in AI augment their capabilities and will inevitably replace those "
            "who refuse to adapt to these new technological standards."
        )
        is_valid, err_msg, count = validate_contribution(text)
        assert is_valid is True
        assert count >= 150
        assert err_msg == ""


# ==============================================================================
# 3. AI Evaluation & Mocking Tests
# ==============================================================================

class TestGDAIEvaluation:
    """Verifies 4-criteria AI evaluation, stronger opening, and missed counter-point recommendations."""

    def test_ai_evaluation_happy_path_with_mock_client(self, mock_gemini_client, mock_gd_ai_payload):
        mock_gemini_client(payload=mock_gd_ai_payload)

        sample_contribution = (
            "Good morning team. Regarding whether AI will replace or augment human jobs, "
            "I believe AI will act as a major cognitive catalyst. While repetitive data entry "
            "will be displaced, software developers and knowledge workers will become systems orchestrators. "
            "Consequently, universities must overhaul computer science curricula immediately."
        )

        result = evaluate_gd_contribution(
            topic_title="Generative AI in the Workplace",
            category="technology",
            contribution_type="opening",
            contribution_text=sample_contribution
        )

        assert result["overall_score"] == 84
        assert result["is_fallback"] is False

        # Verify four scored criteria
        scores = result["scores"]
        assert scores["content"] == 85
        assert scores["structure"] == 82
        assert scores["balance"] == 80
        assert scores["clarity"] == 88

        # Verify criteria feedback
        feedback = result["criteria_feedback"]
        assert "content" in feedback
        assert "structure" in feedback
        assert "balance" in feedback
        assert "clarity" in feedback

        # Verify actionable suggestions
        assert "stronger_opening" in result
        assert len(result["stronger_opening"]) > 20
        assert "missed_counterpoint" in result
        assert len(result["missed_counterpoint"]) > 20

        # Verify strengths and improvements
        assert len(result["strengths"]) >= 1
        assert len(result["improvements"]) >= 1

    def test_ai_evaluation_fallback_on_api_error(self, mock_gemini_client):
        # Configure mock client to throw an exception
        mock_gemini_client(side_effect=Exception("Gemini quota exhausted or unreachable"))

        sample_contribution = (
            "Good morning everyone. In my perspective, electric vehicles represent a critical "
            "milestone toward decarbonization. Firstly, battery manufacturing costs have dropped. "
            "However, on the other hand, the transmission grid and charging network in tier-2 cities "
            "remain significant bottlenecks that require public-private partnerships."
        )

        result = evaluate_gd_contribution(
            topic_title="Electric Vehicles: Grid Infrastructure",
            category="current_affairs",
            contribution_type="opening",
            contribution_text=sample_contribution
        )

        # Confirm graceful fallback was triggered
        assert result["is_fallback"] is True
        assert 50 <= result["overall_score"] <= 100

        # Confirm all 4 scored criteria are present in fallback
        scores = result["scores"]
        assert "content" in scores
        assert "structure" in scores
        assert "balance" in scores
        assert "clarity" in scores
        for score_val in scores.values():
            assert 40 <= score_val <= 100

        # Confirm suggestions are generated
        assert result["stronger_opening"] != ""
        assert result["missed_counterpoint"] != ""
        assert len(result["strengths"]) >= 1
        assert len(result["improvements"]) >= 1

    def test_evaluate_gd_contribution_rejects_empty_with_value_error(self):
        with pytest.raises(ValueError) as exc:
            evaluate_gd_contribution(
                topic_title="Remote Work",
                category="technology",
                contribution_type="opening",
                contribution_text="   "
            )
        assert "Please write your group discussion contribution" in str(exc.value)

    def test_evaluate_gd_contribution_rejects_short_with_value_error(self):
        with pytest.raises(ValueError) as exc:
            evaluate_gd_contribution(
                topic_title="Remote Work",
                category="technology",
                contribution_type="opening",
                contribution_text="I think remote work is fine."
            )
        assert "Contribution is too brief" in str(exc.value)


# ==============================================================================
# 4. Database Persistence & Practice History Tests
# ==============================================================================

class TestGDDatabaseStorage:
    """Verifies SQLite persistence of GD attempts and student progress retrieval."""

    def test_save_and_retrieve_gd_attempt(self):
        student_id = "test_student_gd_01"
        delete_student_gd_attempts(student_id)

        feedback_dict = {
            "overall_score": 82,
            "scores": {"content": 80, "structure": 85, "balance": 75, "clarity": 88},
            "stronger_opening": "Let us frame this issue around economic feasibility.",
            "missed_counterpoint": "Consider rural infrastructure parity."
        }

        saved = save_gd_attempt(
            student_id=student_id,
            topic_title="Electric Vehicles in India",
            category="current_affairs",
            contribution_type="opening",
            contribution_text="This is a test opening speech about electric vehicle infrastructure and battery supply chains.",
            word_count=45,
            overall_score=82,
            content_score=80,
            structure_score=85,
            balance_score=75,
            clarity_score=88,
            stronger_opening="Let us frame this issue around economic feasibility.",
            missed_counterpoint="Consider rural infrastructure parity.",
            feedback_json=json.dumps(feedback_dict),
            topic_id="gd_ca_01"
        )

        assert saved["id"] is not None
        assert saved["student_id"] == student_id
        assert saved["topic_title"] == "Electric Vehicles in India"
        assert saved["overall_score"] == 82
        assert saved["content_score"] == 80

        # Retrieve student history
        history = get_student_gd_attempts(student_id, limit=5)
        assert len(history) == 1
        att = history[0]
        assert att["id"] == saved["id"]
        assert att["feedback"]["overall_score"] == 82

        # Retrieve by attempt ID
        fetched = get_gd_attempt_by_id(saved["id"], student_id=student_id)
        assert fetched is not None
        assert fetched["topic_title"] == "Electric Vehicles in India"

        # Cleanup
        delete_student_gd_attempts(student_id)

    def test_student_data_isolation(self):
        student_a = "student_alpha"
        student_b = "student_beta"
        delete_student_gd_attempts(student_a)
        delete_student_gd_attempts(student_b)

        save_gd_attempt(
            student_id=student_a,
            topic_title="Topic Alpha",
            category="technology",
            contribution_type="opening",
            contribution_text="Speech for Alpha student discussing tech disruptions.",
            word_count=35,
            overall_score=80,
            content_score=80,
            structure_score=80,
            balance_score=80,
            clarity_score=80,
            stronger_opening="Better opening",
            missed_counterpoint="Missed point",
            feedback_json="{}"
        )

        save_gd_attempt(
            student_id=student_b,
            topic_title="Topic Beta",
            category="abstract",
            contribution_type="rebuttal",
            contribution_text="Speech for Beta student discussing abstract philosophies.",
            word_count=38,
            overall_score=90,
            content_score=90,
            structure_score=90,
            balance_score=90,
            clarity_score=90,
            stronger_opening="Better opening B",
            missed_counterpoint="Missed point B",
            feedback_json="{}"
        )

        history_a = get_student_gd_attempts(student_a)
        history_b = get_student_gd_attempts(student_b)

        assert len(history_a) == 1
        assert history_a[0]["topic_title"] == "Topic Alpha"

        assert len(history_b) == 1
        assert history_b[0]["topic_title"] == "Topic Beta"

        delete_student_gd_attempts(student_a)
        delete_student_gd_attempts(student_b)


# ==============================================================================
# 5. Flask Endpoints & Integration Tests
# ==============================================================================

class TestGDEndpoints:
    """Verifies HTTP view routes and REST API endpoints."""

    def test_get_group_discussion_view_page(self, client):
        response = client.get("/group-discussion")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Campus Group Discussion" in html
        assert "Select Discussion Topic" in html
        assert "Your Contribution (150-250 Words)" in html
        assert "Evaluate Contribution with AI" in html
        assert "Four Core Placement Criteria" in html

    def test_api_get_topics_endpoint(self, client):
        response = client.get("/api/group-discussion/topics")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert data["count"] >= 15
        assert len(data["topics"]) >= 15
        assert "grouped" in data

    def test_api_get_topics_with_category_filter(self, client):
        response = client.get("/api/group-discussion/topics?category=technology")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert all(t["category"] == "technology" for t in data["topics"])

    def test_api_random_topic_endpoint(self, client):
        response = client.get("/api/group-discussion/random-topic")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert "title" in data["topic"]
        assert "category" in data["topic"]

    def test_api_evaluate_rejection_empty_contribution(self, client):
        response = client.post(
            "/api/group-discussion/evaluate",
            json={
                "topic_title": "Generative AI",
                "category": "technology",
                "contribution_type": "opening",
                "contribution_text": ""
            }
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["status"] == "error"
        assert "Please write your group discussion contribution" in data["message"]

    def test_api_evaluate_rejection_short_contribution(self, client):
        response = client.post(
            "/api/group-discussion/evaluate",
            json={
                "topic_title": "Generative AI",
                "category": "technology",
                "contribution_type": "opening",
                "contribution_text": "AI is the future and everyone will use it soon."
            }
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["status"] == "error"
        assert "Contribution is too brief" in data["message"]

    def test_api_evaluate_happy_path(self, client, mock_gemini_client, mock_gd_ai_payload):
        mock_gemini_client(payload=mock_gd_ai_payload)

        sample_text = (
            "Good morning respected colleagues. Today we are discussing whether generative AI "
            "replaces or augments human labor. In my view, routine repetitive engineering is "
            "being automated, but high-order system architecture and domain intuition remain "
            "uniquely human strengths that are amplified by intelligent assistants."
        )

        response = client.post(
            "/api/group-discussion/evaluate",
            json={
                "topic_id": "gd_tech_01",
                "topic_title": "Generative AI in the Workplace",
                "category": "technology",
                "contribution_type": "opening",
                "contribution_text": sample_text
            }
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"

        result = data["data"]
        evaluation = result["evaluation"]
        assert evaluation["overall_score"] == 84
        assert evaluation["scores"]["content"] == 85
        assert evaluation["scores"]["structure"] == 82
        assert evaluation["scores"]["balance"] == 80
        assert evaluation["scores"]["clarity"] == 88
        assert "stronger_opening" in evaluation
        assert "missed_counterpoint" in evaluation

        # Confirm persisted in database
        attempt = result["attempt"]
        assert attempt["id"] is not None
        assert attempt["overall_score"] == 84

    def test_api_history_endpoint(self, client, mock_gemini_client, mock_gd_ai_payload):
        mock_gemini_client(payload=mock_gd_ai_payload)

        # Run an evaluation first
        client.post(
            "/api/group-discussion/evaluate",
            json={
                "topic_title": "Quantum Computing Impact",
                "category": "technology",
                "contribution_type": "rebuttal",
                "contribution_text": (
                    "While public-key algorithms are vulnerable to quantum decryption, "
                    "NIST lattice-based standards are already mitigating this transition, "
                    "ensuring banking infrastructure remains resilient over the next decade."
                )
            }
        )

        # Fetch history
        response = client.get("/api/group-discussion/history")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert data["count"] >= 1
        assert isinstance(data["attempts"], list)
