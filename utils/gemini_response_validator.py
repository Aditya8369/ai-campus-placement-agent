"""
Gemini Response Validation and Fallback Recovery Service (#277).

Provides robust, fault-tolerant schema verification and automatic repair mechanisms
for Gemini LLM outputs across:
1. Resume analysis reports (ATS score, strengths, improvements, skill gaps, matching keywords).
2. Mock interview questions generation and evaluation rubrics.
3. Coding challenge test case evaluations and complexity analysis.

Capabilities:
- Validates structural schema invariants, required fields, and type bounds.
- Extracts JSON enclosed in markdown code fences (```json ... ``` or raw strings).
- Auto-completes unclosed braces/brackets caused by token truncation.
- Applies deterministic, safe fallbacks if the response cannot be salvaged, ensuring the application never crashes.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CODE_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def attempt_json_repair(raw_text: str) -> Optional[Dict[str, Any]]:
    """
    Attempts to repair incomplete or malformed JSON caused by truncation or trailing commas.
    """
    if not raw_text or not isinstance(raw_text, str):
        return None

    cleaned = raw_text.strip()
    match = CODE_BLOCK_PATTERN.search(cleaned)
    if match:
        cleaned = match.group(1).strip()

    # Try direct parse
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # Strip trailing comma before closing tokens
    cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)

    # Balance brackets and braces
    open_curly = cleaned.count("{") - cleaned.count("}")
    open_square = cleaned.count("[") - cleaned.count("]")

    repaired = cleaned
    if open_square > 0:
        repaired += "]" * open_square
    if open_curly > 0:
        repaired += "}" * open_curly

    try:
        return json.loads(repaired)
    except Exception:
        pass

    # Find the largest valid JSON substring
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        sub = cleaned[first_brace:last_brace + 1]
        sub = re.sub(r",\s*([\]}])", r"\1", sub)
        try:
            return json.loads(sub)
        except Exception:
            pass

    return None


def validate_and_recover_resume_analysis(raw_response: Any) -> Dict[str, Any]:
    """
    Validates resume analysis schema and injects safe defaults if fields are missing.
    Expected fields: ats_score, strengths, improvements, skill_gaps, recommendation.
    """
    data = None
    if isinstance(raw_response, dict):
        data = raw_response
    elif isinstance(raw_response, str):
        data = attempt_json_repair(raw_response)

    if not isinstance(data, dict):
        logger.warning("Resume analysis response could not be parsed; generating safe recovery payload.")
        data = {}

    ats_score = data.get("ats_score") or data.get("score")
    try:
        ats_val = int(float(ats_score))
        ats_val = max(0, min(100, ats_val))
    except (ValueError, TypeError):
        ats_val = 65

    strengths = data.get("strengths") or []
    if not isinstance(strengths, list) or not strengths:
        strengths = ["Resume layout is well-formatted with clear contact information."]

    improvements = data.get("improvements") or []
    if not isinstance(improvements, list) or not improvements:
        improvements = ["Add quantifiable business metrics to project outcome descriptions."]

    skill_gaps = data.get("skill_gaps") or []
    if not isinstance(skill_gaps, list):
        skill_gaps = []

    matching_skills = data.get("matching_skills") or data.get("matched_skills") or []
    if not isinstance(matching_skills, list):
        matching_skills = []

    recommendation = data.get("recommendation") or data.get("summary") or "Good foundational resume with clear avenues for role-specific alignment."

    return {
        "ats_score": ats_val,
        "strengths": [str(s) for s in strengths],
        "improvements": [str(i) for i in improvements],
        "skill_gaps": [str(g) for g in skill_gaps],
        "matching_skills": [str(m) for m in matching_skills],
        "recommendation": str(recommendation),
        "recovered": data == {} or "ats_score" not in data
    }


def validate_and_recover_interview_eval(raw_response: Any) -> Dict[str, Any]:
    """
    Validates interview answer evaluation schema and repairs missing scores/feedback.
    """
    data = None
    if isinstance(raw_response, dict):
        data = raw_response
    elif isinstance(raw_response, str):
        data = attempt_json_repair(raw_response)

    if not isinstance(data, dict):
        logger.warning("Interview evaluation response could not be parsed; generating safe recovery payload.")
        data = {}

    score = data.get("score") or data.get("technical_accuracy")
    try:
        score_val = int(float(score))
        score_val = max(0, min(100, score_val))
    except (ValueError, TypeError):
        score_val = 70

    feedback = data.get("feedback") or data.get("general_feedback") or data.get("comments") or "Response answered the question reasonably well."
    strengths = data.get("strengths") or ["Clear articulation of main concepts."]
    improvements = data.get("improvements") or ["Provide deeper context and specific real-world examples."]

    return {
        "score": score_val,
        "technical_accuracy": score_val,
        "feedback": str(feedback),
        "strengths": [str(s) for s in strengths] if isinstance(strengths, list) else [str(strengths)],
        "improvements": [str(i) for i in improvements] if isinstance(improvements, list) else [str(improvements)],
        "recovered": data == {} or "score" not in data
    }


def validate_and_recover_coding_eval(raw_response: Any) -> Dict[str, Any]:
    """
    Validates coding solution evaluation schema and repairs test execution details.
    """
    data = None
    if isinstance(raw_response, dict):
        data = raw_response
    elif isinstance(raw_response, str):
        data = attempt_json_repair(raw_response)

    if not isinstance(data, dict):
        logger.warning("Coding evaluation response could not be parsed; generating safe recovery payload.")
        data = {}

    passed = bool(data.get("passed", False))
    score = data.get("score")
    try:
        score_val = int(float(score))
        score_val = max(0, min(100, score_val))
    except (ValueError, TypeError):
        score_val = 80 if passed else 40

    tests_passed = data.get("tests_passed") or (5 if passed else 2)
    total_tests = data.get("total_tests") or 5
    complexity = data.get("complexity_analysis") or "Time: O(N), Space: O(1)"
    feedback = data.get("feedback") or "Solution implements the core algorithmic requirements."

    return {
        "passed": passed,
        "score": score_val,
        "tests_passed": int(tests_passed),
        "total_tests": int(total_tests),
        "complexity_analysis": str(complexity),
        "feedback": str(feedback),
        "recovered": data == {} or "score" not in data
    }


def validate_and_recover_quiz_questions(raw_response: Any, topic: str = "General") -> List[Dict[str, Any]]:
    """
    Validates practice quiz question generator outputs and repairs malformed question structures.
    """
    data = None
    if isinstance(raw_response, list):
        items = raw_response
    elif isinstance(raw_response, dict) and "questions" in raw_response:
        items = raw_response["questions"]
    elif isinstance(raw_response, str):
        repaired = attempt_json_repair(raw_response)
        if isinstance(repaired, list):
            items = repaired
        elif isinstance(repaired, dict) and "questions" in repaired:
            items = repaired["questions"]
        else:
            items = []
    else:
        items = []

    valid_questions = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        q_text = str(item.get("question") or f"Core concept question on {topic} #{idx+1}")
        options = item.get("options") or ["Option A", "Option B", "Option C", "Option D"]
        answer = item.get("answer") or options[0]
        explanation = item.get("explanation") or f"Detailed review for topic {topic}."
        valid_questions.append({
            "question": q_text,
            "options": [str(opt) for opt in options],
            "answer": str(answer),
            "explanation": str(explanation)
        })

    if not valid_questions:
        valid_questions = [{
            "question": f"Explain key foundational aspects and practical applications of {topic}.",
            "options": ["Fundamental Architecture", "Syntax", "Design Patterns", "Security"],
            "answer": "Fundamental Architecture",
            "explanation": f"Foundational knowledge is required for {topic} placement tests."
        }]

    return valid_questions

