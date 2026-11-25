"""
Unit & Integration Tests for Searchable Interview Question Bank (#759)
======================================================================
Tests:
- JSON data file validity and schema
- Adding new questions through the data file only (zero code changes)
- Combined search and tag/category/difficulty/role filters working together
- Empty result states displaying clear messaging
- Short answer outlines for all questions
- Session favorites toggling, persistence, and list export
- Web UI and REST API endpoints
"""

import json
import pytest
from pathlib import Path
from utils.question_bank_service import QuestionBankService, question_bank_service


class TestQuestionBankDataAndLoading:
    """Verifies question bank dataset integrity and dynamic loading from JSON file."""

    def test_json_data_file_exists_and_valid(self):
        data_path = Path(__file__).resolve().parent.parent / "data" / "interview_questions.json"
        assert data_path.exists(), f"Data file missing at {data_path}"

        with open(data_path, "r", encoding="utf-8") as f:
            questions = json.load(f)

        assert isinstance(questions, list)
        assert len(questions) >= 20, f"Expected at least 20 questions, got {len(questions)}"

        for q in questions:
            assert "id" in q and q["id"], "Missing or empty id"
            assert "question" in q and q["question"], f"Missing question text in {q['id']}"
            assert "category" in q and q["category"] in ("hr", "technical", "behavioral", "projects"), f"Invalid category in {q['id']}"
            assert "difficulty" in q and q["difficulty"] in ("Easy", "Medium", "Hard"), f"Invalid difficulty in {q['id']}"
            assert "roles" in q and isinstance(q["roles"], list) and len(q["roles"]) > 0, f"Missing roles in {q['id']}"
            assert "tags" in q and isinstance(q["tags"], list), f"Missing tags in {q['id']}"
            assert "short_answer_outline" in q and isinstance(q["short_answer_outline"], list) and len(q["short_answer_outline"]) >= 2, f"Missing outline in {q['id']}"

    def test_new_questions_can_be_added_through_data_file_only(self, tmp_path):
        """
        Acceptance Criteria: New questions can be added through the data file only.
        Verifies that adding a new question entry to the JSON file immediately makes it
        available through the service without modifying any code.
        """
        custom_json = tmp_path / "custom_questions.json"
        sample_questions = [
            {
                "id": "q_custom_001",
                "question": "What is the difference between TCP and UDP?",
                "category": "technical",
                "difficulty": "Easy",
                "roles": ["Software Engineer"],
                "tags": ["Networking", "TCP", "UDP"],
                "short_answer_outline": [
                    "TCP is connection-oriented and reliable with handshakes and flow control.",
                    "UDP is connectionless and lightweight without guaranteed packet ordering."
                ],
                "key_takeaway": "Choose TCP for accuracy (HTTP, banking); UDP for real-time speed (gaming, VoIP)."
            }
        ]
        with open(custom_json, "w", encoding="utf-8") as f:
            json.dump(sample_questions, f)

        # Service reading custom JSON file
        service = QuestionBankService(data_path=str(custom_json))
        loaded = service.load_questions()
        assert len(loaded) == 1
        assert loaded[0]["id"] == "q_custom_001"

        # Now simulate adding a brand new question strictly through the data file
        new_q = {
            "id": "q_custom_002",
            "question": "Explain idempotency in REST APIs.",
            "category": "technical",
            "difficulty": "Medium",
            "roles": ["Backend Developer"],
            "tags": ["REST", "HTTP", "APIs"],
            "short_answer_outline": [
                "An idempotent HTTP method produces identical side effects regardless of how many times it is called.",
                "GET, PUT, and DELETE are idempotent; POST is non-idempotent."
            ],
            "key_takeaway": "Critical for network retries and distributed reliability."
        }
        sample_questions.append(new_q)
        with open(custom_json, "w", encoding="utf-8") as f:
            json.dump(sample_questions, f)

        # Without any code modification, reloading reads the newly added question
        updated = service.load_questions(force_reload=True)
        assert len(updated) == 2
        assert any(q["id"] == "q_custom_002" for q in updated)
        search_res = service.search_and_filter(query="idempotency")
        assert len(search_res) == 1
        assert search_res[0]["id"] == "q_custom_002"


class TestSearchAndFilterCombination:
    """Verifies that search query and tag/category/difficulty/role filters work together."""

    def test_search_and_filters_work_together(self):
        """
        Acceptance Criteria: Search and filters work together.
        Ensures search keywords AND category AND difficulty AND role are combined.
        """
        # 1. Broad technical filter
        tech_all = question_bank_service.search_and_filter(category="technical")
        assert len(tech_all) >= 5

        # 2. Combine technical category + Medium difficulty
        tech_medium = question_bank_service.search_and_filter(
            category="technical",
            difficulty="Medium"
        )
        assert len(tech_medium) >= 1
        assert all(q["category"] == "technical" and q["difficulty"] == "Medium" for q in tech_medium)

        # 3. Combine technical + Medium + specific search keyword 'Virtual DOM'
        tech_med_dom = question_bank_service.search_and_filter(
            query="Virtual DOM",
            category="technical",
            difficulty="Medium"
        )
        assert len(tech_med_dom) == 1
        assert "Virtual DOM" in tech_med_dom[0]["question"]

        # 4. Combine search query with role filter
        backend_query = question_bank_service.search_and_filter(
            query="ACID",
            role="Backend Developer"
        )
        assert len(backend_query) >= 1
        assert "ACID" in backend_query[0]["question"]

        # 5. Combine search query with tag filter
        networking_q = question_bank_service.search_and_filter(
            query="browser",
            tag="Networking"
        )
        assert len(networking_q) >= 1
        assert "URL" in networking_q[0]["question"]

    def test_empty_result_on_conflicting_filters(self):
        """
        Acceptance Criteria: An empty result shows a clear message.
        """
        # Search for HR question with technical keywords
        res = question_bank_service.search_and_filter(
            query="Linux cgroups namespaces",
            category="hr"
        )
        assert len(res) == 0

        # Impossible query
        res_none = question_bank_service.search_and_filter(query="zzz_nonexistent_xyz_123")
        assert len(res_none) == 0


class TestShortAnswerOutlinesAndFavorites:
    """Verifies short answer outlines and student session favorites formatting."""

    def test_each_question_has_short_answer_outline(self):
        questions = question_bank_service.get_all_questions()
        for q in questions:
            outline = q.get("short_answer_outline")
            assert outline and isinstance(outline, list)
            assert len(outline) >= 2, f"Outline too sparse for {q['id']}"
            assert all(isinstance(point, str) and len(point) > 10 for point in outline)

    def test_favorites_export_formatting(self):
        fav_ids = ["q_hr_001", "q_behav_001"]
        formatted = question_bank_service.format_favorites_as_text(fav_ids, include_outlines=True)

        assert "# My Favorite Interview Questions (2 Saved)" in formatted
        assert "Tell me about yourself" in formatted
        assert "disagreement" in formatted
        assert "- **Short Answer Outline**:" in formatted

        # Test empty favorites
        empty_text = question_bank_service.format_favorites_as_text([])
        assert "No interview questions currently selected" in empty_text


class TestQuestionBankWebAndApi:
    """Tests web rendering, filter options, and session favorites REST endpoints."""

    def test_view_question_bank_page(self, client):
        resp = client.get("/interview/question-bank")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        # Check page header and branding
        assert "Common Interview Question Bank" in html
        assert "Search Keywords" in html
        assert "Category" in html
        assert "Difficulty" in html
        assert "Target Role" in html
        assert "Short Answer Outline" in html

        # Alias route works
        alias_resp = client.get("/question-bank")
        assert alias_resp.status_code == 200

    def test_view_question_bank_empty_state_shows_clear_message(self, client):
        """
        Acceptance Criteria: An empty result shows a clear message.
        """
        resp = client.get("/interview/question-bank?q=zzz_impossible_search_query_999")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        assert "No interview questions matched your search criteria" in html
        assert "Try adjusting your search keywords" in html
        assert "Clear All Filters" in html

    def test_api_question_bank_search_and_filters(self, client):
        resp = client.get("/api/interview/question-bank?category=technical&difficulty=Easy")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["total"] > 0
        assert all(q["category"] == "technical" and q["difficulty"] == "Easy" for q in data["questions"])

    def test_api_question_bank_filters_endpoint(self, client):
        resp = client.get("/api/interview/question-bank/filters")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        opts = data["filter_options"]
        assert "categories" in opts
        assert "difficulties" in opts
        assert "roles" in opts
        assert "technical" in opts["categories"]
        assert "Easy" in opts["difficulties"]

    def test_api_question_bank_single_item(self, client):
        resp = client.get("/api/interview/question-bank/q_tech_001")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["question"]["id"] == "q_tech_001"
        assert "URL" in data["question"]["question"]

        # 404 for invalid question
        resp_404 = client.get("/api/interview/question-bank/non_existent_id")
        assert resp_404.status_code == 404

    def test_session_favorites_lifecycle_and_export(self, client):
        # 1. Toggle favorite ON for q_tech_001
        toggle_resp = client.post(
            "/api/interview/question-bank/favorites/toggle",
            json={"question_id": "q_tech_001"}
        )
        assert toggle_resp.status_code == 200
        t_data = toggle_resp.get_json()
        assert t_data["success"] is True
        assert t_data["is_favorite"] is True
        assert t_data["total_favorites"] == 1

        # 2. Add second favorite q_hr_001
        client.post(
            "/api/interview/question-bank/favorites/toggle",
            json={"question_id": "q_hr_001", "favorite": True}
        )

        # 3. GET favorites
        fav_resp = client.get("/api/interview/question-bank/favorites")
        assert fav_resp.status_code == 200
        fav_data = fav_resp.get_json()
        assert fav_data["count"] == 2
        fav_ids = [q["id"] for q in fav_data["questions"]]
        assert "q_tech_001" in fav_ids
        assert "q_hr_001" in fav_ids

        # 4. Export favorites as text
        export_resp = client.post(
            "/api/interview/question-bank/favorites/export",
            json={"include_outlines": True}
        )
        assert export_resp.status_code == 200
        exp_data = export_resp.get_json()
        assert exp_data["success"] is True
        assert "What happens under the hood" in exp_data["formatted_text"]
        assert "Tell me about yourself" in exp_data["formatted_text"]

        # 5. Toggle favorite OFF for q_tech_001
        toggle_off_resp = client.post(
            "/api/interview/question-bank/favorites/toggle",
            json={"question_id": "q_tech_001", "favorite": False}
        )
        assert toggle_off_resp.status_code == 200
        off_data = toggle_off_resp.get_json()
        assert off_data["is_favorite"] is False
        assert off_data["total_favorites"] == 1
