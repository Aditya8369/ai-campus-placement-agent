from unittest.mock import patch
import pytest

from agents.coordinator import CoordinatorAgent


@pytest.fixture
def coordinator():
    return CoordinatorAgent()


def test_rule_matched_skill_in_skill_gap(coordinator):
    """
    Test Rule 1: A skill marked as matched in job_match but also flagged as a gap in skill_gap
    should produce a 'matched_skill_in_skill_gap' conflict.
    """
    job_match = {
        "matched_skills": ["Docker", "Python"],
        "missing_skills": ["AWS"],
    }
    skill_gap = [
        {"skill": "Docker", "importance": "High", "priority": "High"},
        {"skill": "AWS", "importance": "High", "priority": "High"},
    ]
    resume_analysis = {"strengths": ["Python"]}

    conflicts = coordinator._detect_conflicts(job_match, skill_gap, resume_analysis)

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["conflict_type"] == "matched_skill_in_skill_gap"
    assert conflict["severity"] == "high"
    assert conflict["skill"] == "Docker"
    assert conflict["sections"] == ["job_match.matched_skills", "skill_gap"]
    assert "Docker" in conflict["message"]
    assert conflict["recommended_action"]
    assert "evidence for Docker" in conflict["recommended_action"]
    assert "skill-gap recommendation" in conflict["recommended_action"]


def test_rule_matched_skill_in_missing_skills(coordinator):
    """
    Test Rule 2: A skill listed in both matched_skills and missing_skills within job_match
    should produce a 'matched_skill_in_missing_skills' conflict.
    """
    job_match = {
        "matched_skills": ["Python", "Kubernetes"],
        "missing_skills": ["Kubernetes", "AWS"],
    }
    skill_gap = [
        {"skill": "AWS", "importance": "High", "priority": "High"},
    ]
    resume_analysis = {}

    conflicts = coordinator._detect_conflicts(job_match, skill_gap, resume_analysis)

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["conflict_type"] == "matched_skill_in_missing_skills"
    assert conflict["severity"] == "high"
    assert conflict["skill"] == "Kubernetes"
    assert conflict["sections"] == ["job_match.matched_skills", "job_match.missing_skills"]
    assert "Kubernetes" in conflict["message"]
    assert conflict["recommended_action"]
    assert "contradictory Job Match classifications for Kubernetes" in conflict["recommended_action"]


def test_multiple_conflicts_and_deduplication(coordinator):
    """
    Multiple conflicts should be reported deterministically, and duplicate entries
    within the same conflict type should be deduplicated.
    """
    job_match = {
        "matched_skills": ["Docker", "docker", " DOCKER ", "SQL", "Python"],
        "missing_skills": ["SQL", "sql"],
    }
    skill_gap = [
        {"skill": "Docker", "importance": "High"},
        {"skill": "docker", "importance": "Medium"},
    ]

    conflicts = coordinator._detect_conflicts(job_match, skill_gap, {})

    assert len(conflicts) == 2
    types = [c["conflict_type"] for c in conflicts]
    assert "matched_skill_in_skill_gap" in types
    assert "matched_skill_in_missing_skills" in types

    docker_conflicts = [c for c in conflicts if c["conflict_type"] == "matched_skill_in_skill_gap"]
    assert len(docker_conflicts) == 1
    assert docker_conflicts[0]["skill"] == "Docker"

    sql_conflicts = [c for c in conflicts if c["conflict_type"] == "matched_skill_in_missing_skills"]
    assert len(sql_conflicts) == 1
    assert sql_conflicts[0]["skill"] == "SQL"


def test_tri_section_simultaneous_conflict_and_deduplication(coordinator):
    """
    When a skill appears simultaneously in job_match['matched_skills'],
    job_match['missing_skills'], and skill_gap, exactly two conflicts must be reported:
    1. matched_skill_in_skill_gap
    2. matched_skill_in_missing_skills
    Duplicate entries across sections must not create duplicate conflict records.
    """
    job_match = {
        "matched_skills": ["Docker", "docker", " DOCKER "],
        "missing_skills": ["Docker", "docker"],
    }
    skill_gap = [
        {"skill": "Docker", "importance": "High"},
        {"skill": "docker", "importance": "Medium"},
    ]

    conflicts = coordinator._detect_conflicts(job_match, skill_gap, {})

    assert len(conflicts) == 2
    types = [c["conflict_type"] for c in conflicts]
    assert types == ["matched_skill_in_skill_gap", "matched_skill_in_missing_skills"]

    rule1 = next(c for c in conflicts if c["conflict_type"] == "matched_skill_in_skill_gap")
    assert rule1["skill"] == "Docker"
    assert rule1["severity"] == "high"
    assert rule1["sections"] == ["job_match.matched_skills", "skill_gap"]
    assert "Docker" in rule1["message"]
    assert rule1["recommended_action"]
    assert "evidence for Docker" in rule1["recommended_action"]

    rule2 = next(c for c in conflicts if c["conflict_type"] == "matched_skill_in_missing_skills")
    assert rule2["skill"] == "Docker"
    assert rule2["severity"] == "high"
    assert rule2["sections"] == ["job_match.matched_skills", "job_match.missing_skills"]
    assert "Docker" in rule2["message"]
    assert rule2["recommended_action"]
    assert "contradictory Job Match classifications for Docker" in rule2["recommended_action"]


def test_case_and_whitespace_normalization(coordinator):
    """
    Matching must be case-insensitive and ignore leading/trailing whitespace.
    """
    job_match = {
        "matched_skills": ["   postgresQL   "],
        "missing_skills": [],
    }
    skill_gap = [
        {"skill": "POSTGRESQL"},
    ]

    conflicts = coordinator._detect_conflicts(job_match, skill_gap, {})
    assert len(conflicts) == 1
    assert conflicts[0]["conflict_type"] == "matched_skill_in_skill_gap"
    assert conflicts[0]["skill"] == "postgresQL"


def test_no_substring_false_positives(coordinator):
    """
    Substring matches (e.g., 'Java' vs 'JavaScript', 'C' vs 'C++') must NOT be considered conflicts.
    """
    job_match = {
        "matched_skills": ["Java", "C"],
        "missing_skills": ["C++"],
    }
    skill_gap = [
        {"skill": "JavaScript"},
    ]

    conflicts = coordinator._detect_conflicts(job_match, skill_gap, {})
    assert conflicts == []


def test_legitimate_overlap_is_not_conflict(coordinator):
    """
    A skill appearing in both job_match['missing_skills'] and skill_gap is consistent
    and represents legitimate overlap, NOT a contradiction.
    """
    job_match = {
        "matched_skills": ["Python", "Flask"],
        "missing_skills": ["Docker", "Kubernetes", "AWS"],
    }
    skill_gap = [
        {"skill": "Docker", "importance": "High"},
        {"skill": "Kubernetes", "importance": "Medium"},
        {"skill": "AWS", "importance": "High"},
    ]

    conflicts = coordinator._detect_conflicts(job_match, skill_gap, {})
    assert conflicts == []


def test_resume_strength_does_not_trigger_conflict(coordinator):
    """
    A resume strength overlapping with missing skills should NOT be treated
    as a conflict because a strength does not establish job-specific proficiency.
    """
    job_match = {
        "matched_skills": ["Flask"],
        "missing_skills": ["Python"],
    }
    skill_gap = [
        {"skill": "Python"},
    ]
    resume_analysis = {
        "strengths": ["Python"],
    }

    conflicts = coordinator._detect_conflicts(job_match, skill_gap, resume_analysis)
    assert conflicts == []


def test_empty_missing_and_malformed_inputs(coordinator):
    """
    Should handle None, non-dict, non-list, empty strings, and malformed items gracefully.
    """
    assert coordinator._detect_conflicts(None, None, None) == []
    assert coordinator._detect_conflicts({}, [], {}) == []
    assert coordinator._detect_conflicts(
        {"matched_skills": "not-a-list", "missing_skills": None},
        "not-a-list",
        None,
    ) == []


def test_blank_and_fallback_values_skipped(coordinator):
    """
    Blank strings, whitespace-only, non-strings, and generic fallback values
    (e.g., 'General Technical Concepts') must be skipped and not produce conflicts.
    """
    job_match = {
        "matched_skills": [
            "",
            "   ",
            None,
            123,
            True,
            "General Technical Concepts",
            "general technical concepts",
        ],
        "missing_skills": [
            "General Technical Concepts",
            "   ",
        ],
    }
    skill_gap = [
        {"skill": "General Technical Concepts"},
        {"skill": ""},
        {"skill": None},
        "not-a-dict",
    ]

    conflicts = coordinator._detect_conflicts(job_match, skill_gap, {})
    assert conflicts == []


def test_no_conflicts_returns_empty_list(coordinator):
    """
    Clean, non-contradictory analysis results should return an empty list.
    """
    job_match = {
        "matched_skills": ["Python", "Flask"],
        "missing_skills": ["Docker", "Kubernetes"],
    }
    skill_gap = [
        {"skill": "Docker", "importance": "High"},
        {"skill": "AWS", "importance": "Medium"},
    ]

    conflicts = coordinator._detect_conflicts(job_match, skill_gap, {})
    assert conflicts == []


def test_coordinator_integration_preserves_keys_and_adds_conflicts(coordinator):
    """
    Full CoordinatorAgent.analyze() integration with mocked Gemini response:
    - Verifies all original payload keys are preserved.
    - Verifies 'conflicts' key is added with expected conflict objects.
    - Verifies single Gemini call count.
    """
    mock_gemini_response = {
        "resume_analysis": {
            "ats_score": 80,
            "summary": "Sample summary",
            "strengths": ["Python"],
            "weaknesses": ["Docker"],
            "grammar_suggestions": [],
            "formatting_suggestions": [],
            "project_feedback": "Good projects",
            "experience_feedback": "Good experience",
            "missing_skills": ["Docker"],
            "overall_recommendation": "Keep going",
        },
        "job_match": {
            "match_percentage": 70,
            "matched_skills": ["Python", "Docker"],
            "missing_skills": ["AWS"],
            "required_certifications": [],
            "recommended_improvements": [],
            "top_5_resume_changes": ["Update summary"],
        },
        "skill_gap": [
            {
                "skill": "Docker",
                "importance": "High",
                "difficulty": "Medium",
                "learning_time": "1 week",
                "learning_resource": "Docs",
                "project_suggestion": "Containerize",
                "priority": "High",
            }
        ],
        "learning_roadmap": [],
        "interview_questions": {"hr": [], "technical": [], "behavioral": []},
        "overall_recommendation_summary": "Ready for roles with some preparation.",
    }

    with patch("agents.coordinator.generate_json_response", return_value=mock_gemini_response) as mock_gemini:
        with patch.object(coordinator, "_load_company_data", return_value={}):
            result = coordinator.analyze(
                resume_text="Resume text with Python and Docker",
                job_description="Looking for Python and AWS developer",
                company_name="General",
            )

            # Gemini must have been invoked exactly once
            assert mock_gemini.call_count == 1

            # All original keys must be preserved
            expected_keys = {
                "resume_analysis",
                "job_match",
                "skill_gap",
                "learning_roadmap",
                "interview_questions",
                "overall_recommendation_summary",
                "conflicts",
                "section_status",
            }
            assert set(result.keys()) == expected_keys

            # Sub-agents processed their blocks correctly
            assert result["job_match"]["match_percentage"] == 70
            assert "Python" in result["job_match"]["matched_skills"]
            assert len(result["learning_roadmap"]) == 6  # RoadmapAgent fallback

            # Conflicts block correctly contains the detected conflict
            assert len(result["conflicts"]) == 1
            conflict = result["conflicts"][0]
            assert conflict["conflict_type"] == "matched_skill_in_skill_gap"
            assert conflict["skill"] == "Docker"
            assert conflict["severity"] == "high"
            assert conflict["recommended_action"]
            assert "evidence for Docker" in conflict["recommended_action"]

