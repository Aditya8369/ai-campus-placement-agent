"""
Unit and integration tests for CoordinatorAgent response schema validation,
resilient fallback handling, one-time retry on format errors, and dashboard rendering.

Verifies acceptance criteria:
1. A malformed or partial response does not crash the dashboard.
2. Sections that failed validation show a clear "unavailable" state.
3. Valid responses behave exactly as before.
4. Tests cover missing keys, wrong types, and invalid JSON.
"""

from unittest.mock import patch, MagicMock
import pytest
from pydantic import ValidationError

from agents.coordinator import CoordinatorAgent
from agents.coordinator_schema import (
    validate_coordinator_payload,
    ResumeAnalysisSchema,
    JobMatchSchema,
    SkillGapItemSchema,
    RoadmapWeekSchema,
    InterviewQuestionsSchema,
)
from utils.gemini import AIResponseFormatError


# ==============================================================================
# 1. Schema Model Validation Tests
# ==============================================================================

class TestCoordinatorSchemaModels:
    """Tests Pydantic schema models for individual sub-agent blocks."""

    def test_resume_analysis_schema_valid_and_coercion(self):
        data = {
            "ats_score": "82",
            "summary": "Solid backend profile",
            "strengths": ["Python", "SQL"],
            "weaknesses": "Docker",  # string coerced to list
            "formatting_suggestions": ["Consistent headers"],
        }
        model = ResumeAnalysisSchema.model_validate(data)
        assert model.ats_score == 82
        assert model.strengths == ["Python", "SQL"]
        assert model.weaknesses == ["Docker"]
        assert model.formatting_suggestions == ["Consistent headers"]
        assert model.grammar_suggestions == []

    def test_resume_analysis_schema_invalid_ats_score(self):
        with pytest.raises(ValidationError):
            ResumeAnalysisSchema.model_validate({"ats_score": "not-a-number"})

    def test_job_match_schema_valid_and_coercion(self):
        data = {
            "match_percentage": "75.4",
            "matched_skills": ["Python"],
            "missing_skills": ["Kubernetes"],
            "top_5_resume_changes": ["Add project link"],
        }
        model = JobMatchSchema.model_validate(data)
        assert model.match_percentage == 75
        assert model.matched_skills == ["Python"]
        assert model.top_5_resume_changes == ["Add project link"]

    def test_job_match_schema_invalid_percentage(self):
        with pytest.raises(ValidationError):
            JobMatchSchema.model_validate({"match_percentage": "invalid"})

    def test_skill_gap_item_schema_enums_and_defaults(self):
        item = SkillGapItemSchema.model_validate({
            "skill": "Docker",
            "importance": "high",
            "difficulty": "medium",
            "priority": "HIGH",
        })
        assert item.skill == "Docker"
        assert item.importance == "High"
        assert item.difficulty == "Medium"
        assert item.priority == "High"

    def test_roadmap_week_schema_hours_clamping(self):
        week = RoadmapWeekSchema.model_validate({
            "week": "Week 1",
            "topics": ["DSA"],
            "estimated_hours": "15",
        })
        assert week.week == "Week 1"
        assert week.topics == ["DSA"]
        assert week.estimated_hours == 15

    def test_roadmap_week_schema_invalid_hours(self):
        with pytest.raises(ValidationError):
            RoadmapWeekSchema.model_validate({"estimated_hours": "unknown"})

    def test_interview_questions_schema_valid(self):
        qs = InterviewQuestionsSchema.model_validate({
            "hr": ["Tell me about yourself"],
            "technical": ["What is an index?"],
            "behavioral": ["Describe a challenge"],
        })
        assert len(qs.hr) == 1
        assert len(qs.technical) == 1
        assert len(qs.behavioral) == 1

    def test_interview_questions_schema_invalid_types(self):
        with pytest.raises(ValidationError):
            InterviewQuestionsSchema.model_validate({"hr": 12345})


# ==============================================================================
# 2. validate_coordinator_payload Function Tests
# ==============================================================================

class TestValidateCoordinatorPayload:
    """Tests the validate_coordinator_payload helper with missing keys and wrong types."""

    def test_empty_dict_marks_all_sections_unavailable_with_defaults(self):
        sanitized, status = validate_coordinator_payload({})
        for section in ["resume_analysis", "job_match", "skill_gap", "learning_roadmap", "interview_questions", "overall_recommendation_summary"]:
            assert status[section] == "unavailable"

        assert sanitized["resume_analysis"]["ats_score"] == 0
        assert sanitized["job_match"]["match_percentage"] == 0
        assert sanitized["skill_gap"] == []
        assert sanitized["learning_roadmap"] == []
        assert "hr" in sanitized["interview_questions"]

    def test_non_dict_root_marks_all_unavailable(self):
        sanitized, status = validate_coordinator_payload("not a json object")
        for s in status.values():
            assert s == "unavailable"
        assert sanitized["resume_analysis"]["ats_score"] == 0

    def test_partial_valid_payload_tracks_availability_per_section(self):
        raw = {
            "resume_analysis": {
                "ats_score": 85,
                "summary": "Good resume",
                "strengths": ["Python"],
                "weaknesses": ["Cloud"],
            },
            # job_match missing
            # skill_gap has wrong type (string instead of list)
            "skill_gap": "not-a-list",
            # learning_roadmap has wrong type (int instead of list)
            "learning_roadmap": 12345,
            # interview_questions is valid
            "interview_questions": {
                "hr": ["Q1"],
                "technical": ["Q2"],
                "behavioral": ["Q3"]
            },
            "overall_recommendation_summary": "Solid student profile."
        }
        sanitized, status = validate_coordinator_payload(raw)

        assert status["resume_analysis"] == "available"
        assert status["interview_questions"] == "available"
        assert status["overall_recommendation_summary"] == "available"
        assert status["job_match"] == "unavailable"
        assert status["skill_gap"] == "unavailable"
        assert status["learning_roadmap"] == "unavailable"

        # Check safe fallback values populated for unavailable sections
        assert sanitized["job_match"]["match_percentage"] == 0
        assert sanitized["skill_gap"] == []
        assert sanitized["learning_roadmap"] == []

    def test_wrong_types_inside_blocks_triggers_unavailable_safely(self):
        raw = {
            # ats_score is unparseable string
            "resume_analysis": {
                "ats_score": "unparseable_score",
                "summary": "Summary",
            },
            # match_percentage is unparseable
            "job_match": {
                "match_percentage": "not_numeric",
            },
            # interview_questions has integer instead of list
            "interview_questions": {
                "hr": 9999,
            },
            "overall_recommendation_summary": 12345,  # int instead of str
        }
        sanitized, status = validate_coordinator_payload(raw)

        assert status["resume_analysis"] == "unavailable"
        assert sanitized["resume_analysis"]["ats_score"] == 0
        assert status["job_match"] == "unavailable"
        assert sanitized["job_match"]["match_percentage"] == 0
        assert status["interview_questions"] == "unavailable"
        assert status["overall_recommendation_summary"] == "unavailable"


# ==============================================================================
# 3. CoordinatorAgent Integration & One-Time Retry Tests
# ==============================================================================

class TestCoordinatorAgentValidationAndRetry:
    """Tests CoordinatorAgent.analyze() with valid, partial, malformed, and retried inputs."""

    def test_coordinator_analyze_valid_response_exact_behavior(self, sample_coordinator_json):
        coordinator = CoordinatorAgent()
        with patch("agents.coordinator.generate_json_response", return_value=sample_coordinator_json):
            result = coordinator.analyze(resume_text="Valid resume content")

            assert result["section_status"]["resume_analysis"] == "available"
            assert result["section_status"]["job_match"] == "available"
            assert result["section_status"]["skill_gap"] == "available"
            assert result["section_status"]["learning_roadmap"] == "available"
            assert result["section_status"]["interview_questions"] == "available"
            assert result["section_status"]["overall_recommendation_summary"] == "available"

            assert result["resume_analysis"]["ats_score"] == 85
            assert result["job_match"]["match_percentage"] == 78
            assert len(result["learning_roadmap"]) == 6
            assert len(result["interview_questions"]["hr"]) == 5

    def test_coordinator_analyze_malformed_partial_response_does_not_crash(self):
        """Malformed/partial payload: Coordinator completes without raising KeyError."""
        partial_json = {
            "resume_analysis": {"ats_score": 72, "summary": "Acceptable resume"},
            "job_match": "malformed_string_instead_of_dict",
            "skill_gap": [{"skill": "Docker", "importance": "High"}],
            "learning_roadmap": "not_a_list",
            "interview_questions": None,
            "overall_recommendation_summary": "",
        }
        coordinator = CoordinatorAgent()
        with patch("agents.coordinator.generate_json_response", return_value=partial_json):
            result = coordinator.analyze(resume_text="Some resume")

            # Must not crash and return complete dictionary
            assert result["resume_analysis"]["ats_score"] == 72
            assert result["section_status"]["resume_analysis"] == "available"
            assert result["section_status"]["job_match"] == "unavailable"
            assert result["section_status"]["learning_roadmap"] == "unavailable"
            assert result["section_status"]["interview_questions"] == "unavailable"

            # Check safe fallbacks
            assert result["job_match"]["match_percentage"] == 0
            assert len(result["job_match"]["top_5_resume_changes"]) == 5
            assert len(result["learning_roadmap"]) == 6
            assert len(result["interview_questions"]["hr"]) == 5
            assert result["conflicts"] == []

    def test_coordinator_retry_success_after_initial_format_error(self, sample_coordinator_json):
        """First LLM call fails with AIResponseFormatError; retry succeeds with valid JSON."""
        coordinator = CoordinatorAgent()
        calls = []

        def side_effect_fn(system_instruction, prompt):
            calls.append(prompt)
            if len(calls) == 1:
                raise AIResponseFormatError("Malformed JSON output from model")
            return sample_coordinator_json

        with patch("agents.coordinator.generate_json_response", side_effect=side_effect_fn):
            result = coordinator.analyze(resume_text="Resume text")

            assert len(calls) == 2
            # Verify the reminder prompt was sent on the second call
            assert "CRITICAL REMINDER: Your previous response was malformed" in calls[1]
            assert result["resume_analysis"]["ats_score"] == 85
            assert result["section_status"]["resume_analysis"] == "available"

    def test_coordinator_retry_failure_propagates_format_error(self):
        """Both initial call and retry fail with AIResponseFormatError; raises error."""
        coordinator = CoordinatorAgent()
        calls = []

        def side_effect_fn(system_instruction, prompt):
            calls.append(prompt)
            raise AIResponseFormatError("Persistent malformed JSON")

        with patch("agents.coordinator.generate_json_response", side_effect=side_effect_fn):
            with pytest.raises(AIResponseFormatError):
                coordinator.analyze(resume_text="Resume text")

            assert len(calls) == 2


from app import app
import config
from utils.database import init_db


@pytest.fixture
def temp_db(tmp_path):
    test_db = tmp_path / "test_coordinator_validation.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        yield str(test_db)


@pytest.fixture
def client(temp_db):
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ==============================================================================
# 4. Dashboard Template Rendering with Unavailable Sections Tests
# ==============================================================================

class TestDashboardUnavailableSectionsUI:
    """Verifies that the dashboard template renders clear 'unavailable' badges/alerts when sections fail."""

    def test_dashboard_renders_with_partial_unavailable_sections(self, client):
        from utils.database import save_analysis

        test_analysis_id = "test-unavailable-uuid-001"
        partial_results = {
            "resume_analysis": {
                "ats_score": 0,
                "summary": "Resume summary details are currently unavailable.",
                "strengths": [],
                "weaknesses": [],
                "formatting_suggestions": [],
                "grammar_suggestions": [],
                "project_feedback": "Detailed project feedback is currently unavailable.",
                "experience_feedback": "Detailed professional experience feedback is currently unavailable.",
                "status": "unavailable",
            },
            "job_match": {
                "match_percentage": 0,
                "matched_skills": [],
                "missing_skills": [],
                "required_certifications": [],
                "top_5_resume_changes": ["Job match analysis is currently unavailable."],
                "status": "unavailable",
            },
            "skill_gap": [],
            "learning_roadmap": [
                {
                    "week": "Week 1",
                    "topics": ["Technical concept deep dive"],
                    "coding_practice": ["Basic coding"],
                    "mini_projects": ["Small CLI"],
                    "interview_questions": ["Explain concepts"],
                    "revision_tasks": ["Review edge cases"],
                    "estimated_hours": 10,
                }
            ],
            "interview_questions": {
                "hr": ["Q1"],
                "technical": ["Q2"],
                "behavioral": ["Q3"],
                "status": "unavailable",
            },
            "overall_recommendation_summary": "Overall recommendation is temporarily unavailable.",
            "conflicts": [],
            "section_status": {
                "resume_analysis": "unavailable",
                "job_match": "unavailable",
                "skill_gap": "unavailable",
                "learning_roadmap": "unavailable",
                "interview_questions": "unavailable",
                "overall_recommendation_summary": "unavailable",
            },
        }

        # Save to database
        save_analysis(
            analysis_id=test_analysis_id,
            resume_filename="Test_Resume.pdf",
            company_name="Google",
            job_description="Software Engineer",
            results_dict=partial_results,
            student_id="default_student",
        )

        response = client.get(f"/dashboard/{test_analysis_id}")
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        # Verify page rendered without crashing and shows unavailable indicators
        assert "Partial Analysis" in html
        assert "section-unavailable-alert" in html
        assert "Resume analysis details could not be validated" in html
        assert "Job matching details could not be validated" in html
        assert "Skill gap details could not be validated" in html
        assert "Personalized learning roadmap could not be validated" in html
