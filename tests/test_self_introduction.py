"""
Unit test suite for 'Tell me about yourself' Self-Introduction Builder and Practice Coach (#432).

Acceptance Criteria:
1. Three length options (30s, 60s, 90s) generate scripts with right approximate word counts.
2. Estimated speaking time updates accurately based on word count (140 wpm rate).
3. The script only uses verified facts from the student's resume data without fabricating achievements.
4. Unit tests use a mocked model response and check the word-count limits.
5. Practice evaluation tests cover structure (Present, Past, Future), clarity, and pacing.
6. API endpoints enforce authorization and handle errors gracefully.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

import config
from app import app
from agents.self_introduction_agent import SelfIntroductionAgent, calculate_speaking_time


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as test_client:
        with app.app_context():
            yield test_client


@pytest.fixture
def sample_analysis_record():
    return {
        "analysis_id": "test-self-intro-analysis-123",
        "student_id": "student-test-01",
        "company_name": "Google",
        "target_role": "Software Engineer",
        "resume_text": (
            "Alex Chen\n"
            "Education: Bachelor of Science in Computer Science, UC Berkeley. GPA: 3.82\n"
            "Skills: Python, Go, Docker, Redis, PostgreSQL, Distributed Systems, REST APIs\n"
            "Experience: Software Engineering Intern at CloudTech Solutions (June 2025 - August 2025)\n"
            "- Optimized backend microservices in Python and Redis, improving throughput by 25%.\n"
            "Projects: Distributed Task Queue (Python, Redis, Docker)\n"
            "- Built background job workers processing 5,000+ jobs/min with 40% fewer job failures.\n"
        ),
        "results": {
            "resume_analysis": {
                "ats_score": 88,
                "strengths": [
                    "Strong background in distributed systems and backend engineering",
                    "Demonstrated impact with measurable metrics in internship and projects",
                    "Proficiency in Python, Docker, and Redis"
                ],
                "summary": "Computer Science student with proven backend experience building scalable systems."
            },
            "job_match": {
                "matched_skills": ["Python", "Docker", "Redis", "Distributed Systems", "REST APIs"],
                "missing_skills": ["Kubernetes", "gRPC"],
                "match_percentage": 82
            }
        }
    }


# ===========================================================================
# 1. Speaking Time Calculation Tests
# ===========================================================================

class TestSpeakingTimeCalculation:
    """Tests for word count and conversational speaking duration calculation."""

    def test_empty_string(self):
        res = calculate_speaking_time("")
        assert res["word_count"] == 0
        assert res["estimated_seconds"] == 0
        assert res["formatted"] == "0s"

    def test_short_speech_30s_range(self):
        # 70 words at 140 wpm should be 30 seconds
        text = "word " * 70
        res = calculate_speaking_time(text)
        assert res["word_count"] == 70
        assert res["estimated_seconds"] == 30
        assert res["formatted"] == "30s"

    def test_60s_range_formatting(self):
        # 140 words at 140 wpm should be 60 seconds -> '1m'
        text = "word " * 140
        res = calculate_speaking_time(text)
        assert res["word_count"] == 140
        assert res["estimated_seconds"] == 60
        assert res["formatted"] == "1m"

    def test_90s_range_formatting(self):
        # 210 words at 140 wpm should be 90 seconds -> '1m 30s'
        text = "word " * 210
        res = calculate_speaking_time(text)
        assert res["word_count"] == 210
        assert res["estimated_seconds"] == 90
        assert res["formatted"] == "1m 30s"


# ===========================================================================
# 2. Agent Deterministic & Fact-Extraction Tests
# ===========================================================================

class TestSelfIntroductionAgentFactIntegrity:
    """Tests ensuring that generated pitches only use verified facts from the student's resume."""

    def test_extract_resume_context_contains_only_resume_facts(self, sample_analysis_record):
        agent = SelfIntroductionAgent()
        ctx = agent.extract_resume_context(sample_analysis_record)

        # Context must contain genuine resume facts
        assert "Alex Chen" in ctx["candidate_name"] or "Student" in ctx["candidate_name"]
        assert any("Python" in s for s in ctx["verified_skills"])
        assert any("UC Berkeley" in e or "Computer Science" in e for e in ctx["education"])

        # Context must NOT contain unmentioned technologies or claims
        assert "Blockchain" not in str(ctx["verified_skills"])
        assert "5 years experience" not in str(ctx["experiences"])

    def test_deterministic_fallback_word_count_limits(self, sample_analysis_record):
        """Checks word-count boundaries for 30s, 60s, and 90s scripts."""
        agent = SelfIntroductionAgent()
        result = agent._generate_fallback_scripts(
            company="Google",
            role="Software Engineer",
            context=agent.extract_resume_context(sample_analysis_record)
        )

        assert "scripts" in result
        scripts = result["scripts"]

        # 30s pitch: ~65-85 words
        s30 = scripts["30s"]
        assert 50 <= s30["word_count"] <= 95
        assert 20 <= s30["estimated_seconds"] <= 40
        assert "structure_breakdown" in s30
        assert s30["structure_breakdown"]["present"]

        # 60s pitch: ~130-160 words
        s60 = scripts["60s"]
        assert 115 <= s60["word_count"] <= 175
        assert 45 <= s60["estimated_seconds"] <= 75
        assert s60["structure_breakdown"]["past"]

        # 90s pitch: ~190-230 words
        s90 = scripts["90s"]
        assert 170 <= s90["word_count"] <= 245
        assert 75 <= s90["estimated_seconds"] <= 105
        assert s90["structure_breakdown"]["future"]


# ===========================================================================
# 3. Model Response Mocking Tests
# ===========================================================================

class TestSelfIntroductionAgentWithMockedModel:
    """Verifies that LLM responses adhere to schema and bounds with mocked Gemini call."""

    @patch("agents.self_introduction_agent.generate_json_response")
    def test_generate_scripts_with_mocked_gemini(self, mock_generate_json, sample_analysis_record):
        # Mock Gemini response
        mock_generate_json.return_value = {
            "target_role": "Software Engineer",
            "target_company": "Google",
            "candidate_name": "Alex Chen",
            "scripts": {
                "30": {
                    "duration_seconds": 30,
                    "target_word_count": "65-85",
                    "script": (
                        "Hello, I am Alex Chen, a Computer Science senior at UC Berkeley focusing on distributed "
                        "systems. Recently, I developed a high-throughput distributed task queue in Python and Redis "
                        "that reduced job dropouts by 40%. I also interned at CloudTech Solutions optimizing backend "
                        "microservices. I am eager to bring my backend passion to Google as a Software Engineer."
                    ),
                    "structure_breakdown": {
                        "present": "UC Berkeley CS senior in distributed systems",
                        "past": "Distributed task queue in Python/Redis and CloudTech internship",
                        "future": "Excited to contribute to Google as a Software Engineer"
                    }
                },
                "60": {
                    "duration_seconds": 60,
                    "target_word_count": "130-160",
                    "script": (
                        "Hi, I am Alex Chen, a Computer Science senior at UC Berkeley passionate about scalable "
                        "backend architectures. Over the past four years, I have built a strong foundation in "
                        "Python, Docker, and distributed storage systems. During my internship at CloudTech Solutions, "
                        "I re-architected critical backend microservices, boosting reporting throughput by 25% and "
                        "cutting query latency. In my capstone project, I designed a resilient asynchronous task queue "
                        "in Redis and Docker handling over 5,000 jobs per minute with priority scheduling and exponential "
                        "backoff retries. What excites me most about Google is your planetary-scale engineering and "
                        "commitment to distributed reliability. I would love to bring my technical rigor and backend "
                        "enthusiasm to Google's Software Engineering team."
                    ),
                    "structure_breakdown": {
                        "present": "UC Berkeley CS senior",
                        "past": "CloudTech internship & 5k jobs/min task queue project",
                        "future": "Planetary-scale systems impact at Google"
                    }
                },
                "90": {
                    "duration_seconds": 90,
                    "target_word_count": "190-230",
                    "script": (
                        "Good morning, my name is Alex Chen, and I am a Computer Science senior at UC Berkeley "
                        "specializing in backend systems and distributed computing. My engineering journey has been "
                        "driven by building systems that scale reliably under heavy traffic. Most recently, as a "
                        "Software Engineering Intern at CloudTech Solutions, I identified critical bottlenecks in our "
                        "REST APIs and optimized relational queries in PostgreSQL, achieving a 25% boost in end-to-end "
                        "throughput across high-volume pipelines. Outside the classroom, I built an open-source distributed "
                        "task queue in Python, Docker, and Redis. It reliably processes over 5,000 concurrent jobs per "
                        "minute, incorporating automated retries and dead-letter queues, which slashed dropout rates by 40%. "
                        "Through this work, I discovered how much I love tackling complex concurrency and latency challenges. "
                        "I have closely followed Google's infrastructure innovations, particularly in distributed consensus "
                        "and large-scale storage. I am thrilled at the opportunity to contribute to Google's Software "
                        "Engineering teams, where I can apply my backend engineering depth to build resilient, global-scale products."
                    ),
                    "structure_breakdown": {
                        "present": "UC Berkeley senior specializing in backend systems",
                        "past": "CloudTech internship query optimization and distributed task queue open-source project",
                        "future": "Joining Google's distributed teams to build resilient planetary products"
                    }
                }
            }
        }

        with patch.object(config, "GEMINI_API_KEY", "fake-test-key"):
            agent = SelfIntroductionAgent()
            result = agent.generate_scripts(sample_analysis_record, "Software Engineer", "Google")

            assert result["success"] is True
            assert "scripts" in result
            assert "30s" in result["scripts"]
            assert "60s" in result["scripts"]
            assert "90s" in result["scripts"]

            # Verify computed word counts match script contents
            for key in ["30s", "60s", "90s"]:
                s = result["scripts"][key]
                words = len(s["script"].split())
                assert abs(s["word_count"] - words) <= 2
                assert s["estimated_seconds"] > 0
                assert s["estimated_speaking_time"] != ""


# ===========================================================================
# 4. Practice Evaluation Tests
# ===========================================================================

class TestPracticeEvaluation:
    """Verifies feedback scoring on structure (Present-Past-Future), clarity, and pacing."""

    def test_complete_practice_delivery_gets_high_score(self, sample_analysis_record):
        agent = SelfIntroductionAgent()
        practice_pitch = (
            "Hi, I am currently a senior studying Computer Science at UC Berkeley focusing on distributed systems. "
            "Previously, I interned at CloudTech where I optimized microservices and built a distributed task queue in "
            "Python and Redis handling 5,000 jobs per minute. In the future, I want to join Google as a Software Engineer "
            "to build reliable, high-performance distributed infrastructure."
        )

        feedback = agent.evaluate_practice_delivery(
            practice_text=practice_pitch,
            target_duration=30,
            target_role="Software Engineer",
            target_company="Google",
            analysis_record=sample_analysis_record
        )

        assert feedback["clarity_score"] >= 80
        assert feedback["structure_score"]["has_present"] is True
        assert feedback["structure_score"]["has_past"] is True
        assert feedback["structure_score"]["has_future"] is True
        assert "Ideal" in feedback["length_verdict"] or "Good" in feedback["length_verdict"]

    def test_missing_future_structure_detected(self, sample_analysis_record):
        agent = SelfIntroductionAgent()
        # Pitch missing future alignment
        practice_pitch = (
            "I am Alex Chen studying at UC Berkeley. I worked on a Python Redis queue last semester and built several "
            "small backend projects."
        )

        feedback = agent.evaluate_practice_delivery(
            practice_text=practice_pitch,
            target_duration=60,
            target_role="Software Engineer",
            target_company="Google",
            analysis_record=sample_analysis_record
        )

        assert feedback["structure_score"]["has_future"] is False
        assert any("future" in imp.lower() for imp in feedback["improvements"])

    def test_too_brief_pacing_verdict(self, sample_analysis_record):
        agent = SelfIntroductionAgent()
        short_pitch = (
            "Hi, I am Alex Chen. I am a software developer with experience in Python and databases, "
            "and I am very excited to apply for this engineering role today."
        )

        feedback = agent.evaluate_practice_delivery(
            practice_text=short_pitch,
            target_duration=60,
            target_role="Software Engineer",
            target_company="Google",
            analysis_record=sample_analysis_record
        )

        assert "Too Brief" in feedback["length_verdict"]


# ===========================================================================
# 5. Flask Endpoints & API Integration Tests
# ===========================================================================

class TestSelfIntroductionEndpoints:
    """Tests for /api/self-introduction/* endpoints."""

    def test_calculate_time_endpoint(self, client):
        payload = {"text": "One two three four five six seven eight nine ten."}
        res = client.post(
            "/api/self-introduction/calculate-time",
            data=json.dumps(payload),
            content_type="application/json"
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["metrics"]["word_count"] == 10

    def test_generate_endpoint_not_found_analysis(self, client):
        res = client.post(
            "/api/self-introduction/non-existent-analysis/generate",
            data=json.dumps({"role_title": "SDE"}),
            content_type="application/json"
        )
        assert res.status_code == 404
        data = res.get_json()
        assert data["success"] is False

    @patch("app.get_analysis")
    @patch("app._is_student_authorized", return_value=True)
    def test_generate_endpoint_success(self, mock_auth, mock_get_analysis, client, sample_analysis_record):
        mock_get_analysis.return_value = sample_analysis_record

        res = client.post(
            f"/api/self-introduction/{sample_analysis_record['analysis_id']}/generate",
            data=json.dumps({"role_title": "Software Engineer", "company_name": "Google"}),
            content_type="application/json"
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert "scripts" in data["data"]
        assert "30s" in data["data"]["scripts"]
        assert "60s" in data["data"]["scripts"]
        assert "90s" in data["data"]["scripts"]

    @patch("app.get_analysis")
    @patch("app._is_student_authorized", return_value=True)
    def test_practice_endpoint_empty_text_rejected(self, mock_auth, mock_get_analysis, client, sample_analysis_record):
        mock_get_analysis.return_value = sample_analysis_record

        res = client.post(
            f"/api/self-introduction/{sample_analysis_record['analysis_id']}/practice",
            data=json.dumps({"practice_text": "   "}),
            content_type="application/json"
        )
        assert res.status_code == 400
        data = res.get_json()
        assert data["success"] is False

    @patch("app.get_analysis")
    @patch("app._is_student_authorized", return_value=True)
    def test_practice_endpoint_success(self, mock_auth, mock_get_analysis, client, sample_analysis_record):
        mock_get_analysis.return_value = sample_analysis_record

        pitch = (
            "I am currently studying Computer Science at UC Berkeley. In the past I built a task queue in Python. "
            "I want to contribute to Google as a Software Engineer."
        )
        res = client.post(
            f"/api/self-introduction/{sample_analysis_record['analysis_id']}/practice",
            data=json.dumps({
                "practice_text": pitch,
                "target_duration": 30,
                "role_title": "Software Engineer",
                "company_name": "Google"
            }),
            content_type="application/json"
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert "evaluation" in data
        assert data["evaluation"]["clarity_score"] > 0
        assert "structure_score" in data["evaluation"]
