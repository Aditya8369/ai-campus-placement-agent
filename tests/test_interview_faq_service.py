"""
Unit & Integration Tests for Frequently Asked Interview Questions (#694)
========================================================================
Validates question normalization, token similarity grouping, exclusion of reported/hidden/rejected
experiences, minimum data thresholds, and practice mode integration.
"""

import json
import pytest
from utils.interview_faq_service import (
    normalize_question,
    clean_display_question,
    tokenize_question,
    calculate_token_similarity,
    is_near_identical_question,
    is_experience_eligible,
    extract_questions_from_experience,
    build_practice_url,
    group_frequently_asked_questions,
    get_frequently_asked_questions,
)


class TestQuestionNormalization:
    """Tests normalisation rules: lowercase, trim punctuation, collapse whitespace, strip prefixes."""

    def test_lowercase_conversion(self):
        assert normalize_question("What Is A Deadlock?") == "what is a deadlock"
        assert normalize_question("EXPLAIN B-TREES") == "explain b-trees"

    def test_trim_punctuation_and_symbols(self):
        assert normalize_question("???What is polymorphism???") == "what is polymorphism"
        assert normalize_question("Explain dependency injection.") == "explain dependency injection"
        assert normalize_question('"How does garbage collection work?"') == "how does garbage collection work"
        assert normalize_question("‘What is an index in SQL?’") == "what is an index in sql"

    def test_collapse_whitespace(self):
        assert normalize_question("  What   is   the   difference   between   process   and   thread?  ") == (
            "what is the difference between process and thread"
        )
        assert normalize_question("Explain\n\tREST\r\nAPI\tprinciples") == "explain rest api principles"

    def test_strip_leading_numbers_and_bullet_prefixes(self):
        assert normalize_question("1. What is an interface?") == "what is an interface"
        assert normalize_question("2) Explain multithreading") == "explain multithreading"
        assert normalize_question("Q1: What are microservices?") == "what are microservices"
        assert normalize_question("- Reverse a linked list") == "reverse a linked list"
        assert normalize_question("• Design a URL shortener") == "design a url shortener"
        assert normalize_question("* Explain CAP theorem") == "explain cap theorem"

    def test_html_unescaping(self):
        assert normalize_question("What is &lt;div&gt; in HTML?") == "what is <div> in html"
        assert normalize_question("Explain O(N &amp; M) complexity") == "explain o(n & m) complexity"

    def test_empty_and_none_handling(self):
        assert normalize_question("") == ""
        assert normalize_question(None) == ""
        assert normalize_question("   \t\n  ") == ""

    def test_clean_display_question(self):
        assert clean_display_question("1. what is an abstract class in java") == "What is an abstract class in java?"
        assert clean_display_question("explain indexing in PostgreSQL?") == "Explain indexing in PostgreSQL?"
        assert clean_display_question("- design an LRU cache") == "Design an LRU cache?"


class TestTokenOverlapAndSimilarity:
    """Tests lexical tokenization, stemming, Jaccard overlap, and near-identical matching."""

    def test_tokenize_stopwords_and_stemming(self):
        tokens1 = tokenize_question("how does a hashmap work in java")
        tokens2 = tokenize_question("explain how hashmaps work in java")
        # Both should resolve to common core tokens 'hashmap' (stemmed), 'work', 'java'
        assert "hashmap" in tokens1
        assert "hashmap" in tokens2
        assert "java" in tokens1
        assert "java" in tokens2

    def test_exact_normalized_match_is_identical(self):
        assert is_near_identical_question("what is polymorphism", "what is polymorphism") is True

    def test_near_identical_phrasings_group_together(self):
        # Conversational variation around the same core concept
        q1 = normalize_question("Explain how a HashMap works in Java?")
        q2 = normalize_question("Can you explain how HashMaps work in Java?")
        assert is_near_identical_question(q1, q2) is True

        q3 = normalize_question("What is the difference between a process and a thread?")
        q4 = normalize_question("Explain difference between process and thread.")
        assert is_near_identical_question(q3, q4) is True

    def test_distinct_questions_do_not_match(self):
        q1 = normalize_question("What is encapsulation in OOP?")
        q2 = normalize_question("What is polymorphism in OOP?")
        assert is_near_identical_question(q1, q2) is False

        q3 = normalize_question("Implement a Binary Search Tree")
        q4 = normalize_question("Implement Quick Sort algorithm")
        assert is_near_identical_question(q3, q4) is False


class TestExclusionRules:
    """Acceptance criterion: Hidden, rejected or reported content is excluded."""

    def test_approved_unreported_is_eligible(self):
        exp = {
            "id": "exp-1",
            "reported_flag": 0,
            "moderation_status": "approved",
            "is_hidden": 0,
        }
        assert is_experience_eligible(exp) is True

    def test_reported_experience_is_excluded(self):
        exp = {
            "id": "exp-2",
            "reported_flag": 1,
            "moderation_status": "approved",
        }
        assert is_experience_eligible(exp) is False

    def test_rejected_experience_is_excluded(self):
        exp = {
            "id": "exp-3",
            "reported_flag": 0,
            "moderation_status": "rejected",
        }
        assert is_experience_eligible(exp) is False

    def test_pending_and_flagged_experiences_are_excluded(self):
        exp_pending = {
            "id": "exp-4",
            "reported_flag": 0,
            "moderation_status": "pending_review",
        }
        assert is_experience_eligible(exp_pending) is False

        exp_flagged = {
            "id": "exp-5",
            "reported_flag": 0,
            "moderation_status": "flagged",
        }
        assert is_experience_eligible(exp_flagged) is False

    def test_hidden_experience_is_excluded(self):
        exp_hidden1 = {
            "id": "exp-6",
            "reported_flag": 0,
            "moderation_status": "approved",
            "is_hidden": 1,
        }
        assert is_experience_eligible(exp_hidden1) is False

        exp_hidden2 = {
            "id": "exp-7",
            "reported_flag": 0,
            "moderation_status": "approved",
            "hidden": True,
        }
        assert is_experience_eligible(exp_hidden2) is False


class TestGroupingAndCountingRules:
    """Acceptance criteria: Questions grouped and counted once per experience, threshold enforced."""

    @pytest.fixture
    def mock_google_experiences(self):
        """Creates 4 eligible approved experiences and 2 excluded experiences."""
        return [
            {
                "id": "exp-101",
                "company_name": "Google",
                "reported_flag": 0,
                "moderation_status": "approved",
                "rounds": [
                    {
                        "round_number": 1,
                        "category": "Technical",
                        "questions": [
                            "Explain how HashMaps work internally in Java",
                            "What is the difference between TCP and UDP?",
                        ],
                    },
                    {
                        "round_number": 2,
                        "category": "Coding",
                        "questions": [
                            "Implement LRU Cache using Doubly Linked List and HashMap",
                        ],
                    },
                ],
            },
            {
                "id": "exp-102",
                "company_name": "Google",
                "reported_flag": 0,
                "moderation_status": "approved",
                "rounds": [
                    {
                        "round_number": 1,
                        "category": "Technical",
                        "questions": [
                            # Near-identical phrasing to exp-101
                            "Can you explain how a HashMap works in Java?",
                            # Repeated in same round to test deduplication within same experience
                            "Explain how HashMaps work in Java",
                            "What is B-Tree index in DBMS?",
                        ],
                    },
                    {
                        "round_number": 2,
                        "category": "HR",
                        "questions": [
                            "Tell me about a challenging technical conflict you resolved",
                        ],
                    },
                ],
            },
            {
                "id": "exp-103",
                "company_name": "Google",
                "reported_flag": 0,
                "moderation_status": "approved",
                "rounds": [
                    {
                        "round_number": 1,
                        "category": "Technical",
                        "questions": [
                            # Third appearance of the HashMap question
                            "How do HashMaps work internally in Java?",
                            "What is the difference between TCP and UDP?",
                        ],
                    },
                    {
                        "round_number": 2,
                        "category": "Coding",
                        "questions": [
                            "Implement LRU cache",
                        ],
                    },
                ],
            },
            {
                "id": "exp-104",
                "company_name": "Google",
                "reported_flag": 0,
                "moderation_status": "approved",
                "rounds": [
                    {
                        "round_number": 1,
                        "category": "HR",
                        "questions": [
                            "Tell me about a time you handled a difficult conflict",
                        ],
                    },
                ],
            },
            # EXCLUDED 1: Reported
            {
                "id": "exp-998",
                "company_name": "Google",
                "reported_flag": 1,
                "moderation_status": "approved",
                "rounds": [
                    {
                        "round_number": 1,
                        "category": "Technical",
                        "questions": ["Spam or malicious question text"],
                    }
                ],
            },
            # EXCLUDED 2: Rejected by moderator
            {
                "id": "exp-999",
                "company_name": "Google",
                "reported_flag": 0,
                "moderation_status": "rejected",
                "rounds": [
                    {
                        "round_number": 1,
                        "category": "Technical",
                        "questions": ["Fake interview leak"],
                    }
                ],
            },
        ]

    def test_single_count_per_distinct_experience(self, mock_google_experiences):
        """
        In exp-102, the HashMap question is mentioned twice.
        Total count across exp-101, exp-102, exp-103 MUST be exactly 3, not 4.
        """
        results = group_frequently_asked_questions(
            mock_google_experiences,
            min_experiences=3,
            limit=10,
            company_name="Google",
        )
        assert len(results) > 0

        hashmap_faq = next(
            (r for r in results if "hashmap" in r["normalized_question"]),
            None,
        )
        assert hashmap_faq is not None
        assert hashmap_faq["count"] == 3
        assert hashmap_faq["total_experiences"] == 4  # 4 eligible approved experiences
        assert hashmap_faq["percentage"] == 75.0

    def test_top_frequently_asked_ordering(self, mock_google_experiences):
        results = group_frequently_asked_questions(
            mock_google_experiences,
            min_experiences=3,
            limit=10,
            company_name="Google",
        )
        # Results should be sorted by count descending
        counts = [r["count"] for r in results]
        assert counts == sorted(counts, reverse=True)
        # Top question is the HashMap question (asked in 3 experiences)
        assert results[0]["count"] == 3
        assert "hashmap" in results[0]["normalized_question"]

    def test_excluded_content_is_never_aggregated(self, mock_google_experiences):
        results = group_frequently_asked_questions(
            mock_google_experiences,
            min_experiences=3,
            limit=10,
            company_name="Google",
        )
        all_norm_questions = [r["normalized_question"] for r in results]
        assert not any("spam" in q for q in all_norm_questions)
        assert not any("fake" in q for q in all_norm_questions)

    def test_minimum_experience_threshold_enforced(self, mock_google_experiences):
        """When fewer than min_experiences eligible experiences exist, section is empty."""
        # Only 2 experiences passed with min_experiences=3
        few_experiences = mock_google_experiences[:2]
        res = group_frequently_asked_questions(
            few_experiences,
            min_experiences=3,
            company_name="Google",
        )
        assert res == [], "Must return empty list when fewer than min_experiences eligible exist"

        # With min_experiences=2, it should return questions
        res_allowed = group_frequently_asked_questions(
            few_experiences,
            min_experiences=2,
            company_name="Google",
        )
        assert len(res_allowed) > 0

    def test_top_ten_limit_respected(self):
        """Creates an experience set with 15 distinct questions and ensures top 10 is returned."""
        distinct_topics = [
            "Dijkstra algorithm", "Binary search tree", "Database indexing",
            "Garbage collection", "REST vs GraphQL", "ACID properties",
            "TCP handshake", "Polymorphism", "Virtual DOM", "HTTPS and TLS",
            "Docker containers", "CAP theorem", "Dependency injection",
            "Redis caching", "Microservices architecture",
        ]
        experiences = []
        for i in range(5):
            questions = [f"Explain {topic} in depth" for topic in distinct_topics]
            experiences.append({
                "id": f"bulk-exp-{i}",
                "reported_flag": 0,
                "moderation_status": "approved",
                "rounds": [
                    {"round_number": 1, "category": "Technical", "questions": questions}
                ],
            })

        results = group_frequently_asked_questions(experiences, min_experiences=3, limit=10)
        assert len(results) == 10

    def test_practice_url_generation(self, mock_google_experiences):
        results = group_frequently_asked_questions(
            mock_google_experiences,
            min_experiences=3,
            limit=10,
            company_name="Google",
        )
        for r in results:
            assert "practice_url" in r
            assert r["practice_url"].startswith("/interview/bookmarks/practice?")
            assert "question_text=" in r["practice_url"]
            assert "company=Google" in r["practice_url"]


class TestFlaskIntegration:
    """Validates endpoints and templates return frequently asked questions and deep-links."""

    def test_api_company_frequently_asked_endpoint(self, client):
        response = client.get("/api/company/Google/faq")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["company"] == "Google"
        assert "frequently_asked_questions" in data

    def test_api_company_profile_includes_faqs(self, client):
        response = client.get("/api/company/Google")
        if response.status_code == 200:
            data = response.get_json()
            assert "frequently_asked_questions" in data
            assert "frequently_asked_questions" in data.get("details", {})

    def test_practice_mode_deep_link_auto_bookmarks(self, client):
        """Tests that opening practice mode with ?question_text=... immediately pre-loads the question."""
        target_q = "How does deadlock detection work in distributed databases?"
        response = client.get(
            f"/interview/bookmarks/practice?question_text={target_q}&company=Google&category=Technical",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        matching = [b for b in data["bookmarks"] if b["question_text"] == target_q]
        assert len(matching) >= 1
        assert matching[0]["company_name"] == "Google"
        assert matching[0]["category"] == "Technical"

    def test_interview_practice_alias_route(self, client):
        """Tests that the /interview/practice alias route is active and functional."""
        target_q = "Explain the difference between optimistic and pessimistic locking."
        response = client.get(
            f"/interview/practice?question_text={target_q}&company=Microsoft",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
