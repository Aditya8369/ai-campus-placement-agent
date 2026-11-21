import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from config import Config
from utils.gemini import generate_structured_json

logger = logging.getLogger(__name__)

SUPPORTED_SECTIONS: Dict[str, Dict[str, str]] = {
    "resume_analysis": {
        "label": "Resume Analysis & Suggestions",
        "db_key": "resume_analysis",
    },
    "job_match": {
        "label": "Job Description Match",
        "db_key": "job_match",
    },
    "skill_gaps": {
        "label": "Skill Gap Remediation Matrix",
        "db_key": "skill_gaps",
    },
    "roadmap": {
        "label": "6-Week Study Roadmap",
        "db_key": "learning_roadmap",
    },
    "interview_questions": {
        "label": "Tailored Interview Questions",
        "db_key": "interview_questions",
    },
}


class SectionRetryError(Exception):
    """Raised when a targeted section retry fails validation or AI generation."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _build_section_prompt(
    section_key: str,
    resume_text: str,
    job_description: str,
    company_name: str,
    target_role: str,
) -> str:
    context_block = f"""
Target Company: {company_name or "General Tech Company"}
Target Role: {target_role or "Software Development Engineer"}

Job Description:
{(job_description or "Not provided")[:4000]}

Candidate Resume Text:
{(resume_text or "")[:8000]}
""".strip()

    prompts: Dict[str, str] = {
        "resume_analysis": f"""
You are the ResumeAgent for an AI Campus Placement system.
Regenerate ONLY the resume analysis feedback section based on the candidate profile below.
Return valid JSON matching this exact schema:
{{
  "strengths": ["string"],
  "weaknesses": ["string"],
  "grammar_suggestions": ["string"],
  "formatting_suggestions": ["string"],
  "summary": "string"
}}

{context_block}
""",
        "job_match": f"""
You are the JobMatchAgent for an AI Campus Placement system.
Regenerate ONLY the job description match section based on the candidate profile below.
Return valid JSON matching this exact schema:
{{
  "match_percentage": 0,
  "matched_keywords": ["string"],
  "missing_keywords": ["string"],
  "resume_changes": ["string"]
}}

{context_block}
""",
        "skill_gaps": f"""
You are the SkillGapAgent for an AI Campus Placement system.
Regenerate ONLY the prioritized skill gap remediation matrix based on the candidate profile below.
Return valid JSON matching this exact schema:
{{
  "skill_gaps": [
    {{
      "skill": "string",
      "importance": "High | Medium | Low",
      "learning_time": "string",
      "priority": "High | Medium | Low",
      "learning_resource": "string",
      "project_suggestion": "string"
    }}
  ]
}}

{context_block}
""",
        "roadmap": f"""
You are the RoadmapAgent for an AI Campus Placement system.
Regenerate ONLY the 6-week personalized placement preparation roadmap based on the candidate profile below.
Return valid JSON matching this exact schema:
{{
  "learning_roadmap": [
    {{
      "week": "Week 1",
      "estimated_hours": 10,
      "topics": ["string"],
      "coding_practice": ["string"],
      "mini_projects": ["string"],
      "interview_questions": ["string"],
      "revision_tasks": ["string"]
    }}
  ]
}}

{context_block}
""",
        "interview_questions": f"""
You are the InterviewAgent for an AI Campus Placement system.
Regenerate ONLY 10 tailored technical, behavioral, and HR interview questions based on the candidate profile below.
Return valid JSON matching this exact schema:
{{
  "interview_questions": [
    {{
      "category": "Technical | Behavioral | HR",
      "difficulty": "Easy | Medium | Hard",
      "question": "string",
      "expected_focus": "string"
    }}
  ]
}}

{context_block}
""",
    }
    return prompts[section_key].strip()


def _validate_and_extract_payload(section_key: str, raw_response: Any) -> Any:
    if isinstance(raw_response, str):
        try:
            raw_response = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise SectionRetryError(
                "AI returned malformed JSON while regenerating this section.", 502
            ) from exc

    if not isinstance(raw_response, dict):
        raise SectionRetryError("Unexpected AI response format for section retry.", 502)

    if section_key == "skill_gaps":
        items = raw_response.get("skill_gaps")
        if not isinstance(items, list) or len(items) == 0:
            raise SectionRetryError(
                "Regenerated skill gaps list was empty. Please try again.", 502
            )
        return items

    if section_key == "roadmap":
        weeks = raw_response.get("learning_roadmap")
        if not isinstance(weeks, list) or len(weeks) == 0:
            raise SectionRetryError(
                "Regenerated 6-week roadmap was empty. Please try again.", 502
            )
        return weeks

    if section_key == "interview_questions":
        questions = raw_response.get("interview_questions")
        if not isinstance(questions, list) or len(questions) == 0:
            raise SectionRetryError(
                "Regenerated interview questions list was empty. Please try again.", 502
            )
        return questions

    if section_key in ("resume_analysis", "job_match"):
        if not raw_response:
            raise SectionRetryError("Regenerated section payload was empty.", 502)
        return raw_response

    raise SectionRetryError(f"Unsupported section '{section_key}'.", 400)


def regenerate_failed_section(
    analysis_record: Dict[str, Any],
    section_key: str,
) -> Tuple[str, Any, Dict[str, Any]]:
    """
    Regenerates a single failed section using a targeted Gemini API call.

    Returns:
        (db_key, validated_section_data, ai_request_metadata)
    """
    if section_key not in SUPPORTED_SECTIONS:
        raise SectionRetryError(
            f"Invalid section '{section_key}'. Allowed sections: {', '.join(SUPPORTED_SECTIONS.keys())}",
            status_code=400,
        )

    analysis_id = str(analysis_record.get("id", ""))
    if analysis_id.startswith("demo-"):
        raise SectionRetryError(
            "Demo sample analyses are pre-bundled and do not make live Gemini AI requests.",
            status_code=400,
        )

    resume_text = (analysis_record.get("resume_text") or "").strip()
    if not resume_text:
        raise SectionRetryError(
            "Stored resume text is unavailable for this record; cannot regenerate section.",
            status_code=422,
        )

    prompt = _build_section_prompt(
        section_key=section_key,
        resume_text=resume_text,
        job_description=analysis_record.get("job_description") or "",
        company_name=analysis_record.get("company_name") or "",
        target_role=analysis_record.get("target_role") or "",
    )

    model_name = getattr(Config, "GEMINI_MODEL", "gemini-2.5-flash")
    requested_at = datetime.now(timezone.utc).isoformat()

    logger.info(
        "Triggering targeted Gemini AI request for analysis_id=%s section=%s model=%s",
        analysis_id,
        section_key,
        model_name,
    )

    raw_output = generate_structured_json(prompt=prompt, model=model_name)
    validated_data = _validate_and_extract_payload(section_key, raw_output)
    db_key = SUPPORTED_SECTIONS[section_key]["db_key"]

    ai_meta = {
        "ai_request_made": True,
        "model": model_name,
        "section": section_key,
        "section_label": SUPPORTED_SECTIONS[section_key]["label"],
        "requested_at": requested_at,
        "notice": (
            f"A targeted Gemini AI request ({model_name}) was executed to regenerate "
            f"'{SUPPORTED_SECTIONS[section_key]['label']}'. All other existing sections remained unchanged."
        ),
    }

    return db_key, validated_data, ai_meta