"""
Unit tests for Gemini Response Validation and Fallback Recovery (#277).
"""

import json
import pytest
from utils.gemini_response_validator import (
    attempt_json_repair,
    validate_and_recover_resume_analysis,
    validate_and_recover_interview_eval,
    validate_and_recover_coding_eval,
)


def test_attempt_json_repair_valid_and_markdown():
    valid = '{"key": "value", "count": 10}'
    assert attempt_json_repair(valid) == {"key": "value", "count": 10}

    fenced = '```json\n{"status": "ok"}\n```'
    assert attempt_json_repair(fenced) == {"status": "ok"}


def test_attempt_json_repair_unclosed_braces():
    # Truncated JSON missing closing brace
    truncated = '{"name": "Alice", "skills": ["Python", "Docker"'
    repaired = attempt_json_repair(truncated)
    assert repaired is not None
    assert repaired["name"] == "Alice"
    assert "Python" in repaired["skills"]


def test_attempt_json_repair_trailing_commas():
    malformed = '{"title": "DevOps", "tools": ["Git", "Terraform",],}'
    repaired = attempt_json_repair(malformed)
    assert repaired is not None
    assert repaired["title"] == "DevOps"
    assert len(repaired["tools"]) == 2


def test_validate_and_recover_resume_analysis_complete():
    raw = {
        "ats_score": 88,
        "strengths": ["Strong project impact", "Clear tech stack"],
        "improvements": ["Add GitHub URLs"],
        "skill_gaps": ["Kubernetes"],
        "recommendation": "Ready for tier-1 interviews."
    }
    validated = validate_and_recover_resume_analysis(raw)
    assert validated["ats_score"] == 88
    assert len(validated["strengths"]) == 2
    assert validated["recovered"] is False


def test_validate_and_recover_resume_analysis_incomplete_or_string():
    # Incomplete string with missing fields and bad score type
    raw_str = '{"score": "75.5", "strengths": ["Good education"]'
    validated = validate_and_recover_resume_analysis(raw_str)
    assert validated["ats_score"] == 75
    assert len(validated["strengths"]) >= 1
    assert len(validated["improvements"]) >= 1
    assert isinstance(validated["skill_gaps"], list)


def test_validate_and_recover_resume_analysis_complete_garbage():
    garbage = "I am a helpful AI and I cannot evaluate this file."
    validated = validate_and_recover_resume_analysis(garbage)
    assert validated["recovered"] is True
    assert 0 <= validated["ats_score"] <= 100
    assert len(validated["strengths"]) > 0


def test_validate_and_recover_interview_eval():
    raw_eval = '{"score": 82, "feedback": "Solid architectural explanation."'
    recovered = validate_and_recover_interview_eval(raw_eval)
    assert recovered["score"] == 82
    assert "Solid" in recovered["feedback"]
    assert len(recovered["strengths"]) > 0


def test_validate_and_recover_coding_eval():
    raw_eval = '{"passed": true, "score": 95, "tests_passed": 5, "total_tests": 5'
    recovered = validate_and_recover_coding_eval(raw_eval)
    assert recovered["passed"] is True
    assert recovered["score"] == 95
    assert recovered["tests_passed"] == 5


def test_validate_and_recover_coding_eval_fallback():
    broken = "Syntax error in python code evaluator"
    recovered = validate_and_recover_coding_eval(broken)
    assert recovered["recovered"] is True
    assert recovered["passed"] is False
    assert recovered["score"] == 40
    assert "Solution implements" in recovered["feedback"]
    assert recovered["total_tests"] == 5
    assert recovered["tests_passed"] == 2


def test_validate_and_recover_interview_eval_defaults():
    corrupted = "Invalid json here"
    recovered = validate_and_recover_interview_eval(corrupted)
    assert recovered["recovered"] is True
    assert recovered["score"] == 70
    assert recovered["technical_accuracy"] == 70
    assert len(recovered["strengths"]) == 1
    assert len(recovered["improvements"]) == 1
    assert "Response answered" in recovered["feedback"]


def test_attempt_json_repair_embedded_json():
    text_with_noise = "Pre-amble text from model:\n\n```json\n{\"placement_ready\": true, \"candidate_id\": 42}\n```\nExtra summary notes."
    res = attempt_json_repair(text_with_noise)
    assert res is not None
    assert res["placement_ready"] is True
    assert res["candidate_id"] == 42


def test_attempt_json_repair_empty_and_invalid():
    assert attempt_json_repair("") is None
    assert attempt_json_repair(None) is None
    assert attempt_json_repair("Not json at all without any braces") is None


def test_validate_and_recover_resume_score_bounding():
    # Test scores outside [0, 100] bound correctly
    over = {"score": 150}
    res_over = validate_and_recover_resume_analysis(over)
    assert res_over["ats_score"] == 100

    under = {"score": -50}
    res_under = validate_and_recover_resume_analysis(under)
    assert res_under["ats_score"] == 0

    non_numeric = {"score": "invalid"}
    res_nan = validate_and_recover_resume_analysis(non_numeric)
    assert res_nan["ats_score"] == 65

