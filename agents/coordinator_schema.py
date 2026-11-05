import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field, field_validator, ValidationError

logger = logging.getLogger(__name__)

# Default fallbacks for each section when missing or invalid
DEFAULT_RESUME_ANALYSIS: Dict[str, Any] = {
    "ats_score": 0,
    "summary": "Resume summary details are currently unavailable.",
    "strengths": [],
    "weaknesses": [],
    "grammar_suggestions": [],
    "formatting_suggestions": [],
    "project_feedback": "Detailed project feedback is currently unavailable.",
    "experience_feedback": "Detailed professional experience feedback is currently unavailable.",
    "missing_skills": [],
    "overall_recommendation": "Resume recommendations are currently unavailable.",
    "status": "unavailable",
}

DEFAULT_JOB_MATCH: Dict[str, Any] = {
    "match_percentage": 0,
    "matched_skills": [],
    "missing_skills": [],
    "required_certifications": [],
    "recommended_improvements": ["Job match analysis is currently unavailable."],
    "top_5_resume_changes": [
        "Tailor the resume header and summary to highlight relevant keywords.",
        "Explicitly list all matched technical skills in the skills section.",
        "Detail past projects that utilize the missing skills identified.",
        "Incorporate action verbs when describing role responsibilities.",
        "Showcase certifications that demonstrate expertise in core areas."
    ],
    "status": "unavailable",
}

DEFAULT_SKILL_GAP: List[Dict[str, Any]] = []

DEFAULT_ROADMAP: List[Dict[str, Any]] = []

DEFAULT_INTERVIEW_QUESTIONS: Dict[str, List[str]] = {
    "hr": [
        "Tell me about yourself and walk me through your resume.",
        "Why are you interested in joining our company specifically?",
        "What are your core strengths and areas of improvement?",
        "Where do you see yourself five years from now?",
        "How do you prioritize tasks when working under tight deadlines?"
    ],
    "technical": [
        "What are the differences between SQL and NoSQL databases?",
        "Explain the concept and practical benefits of polymorphism in OOP.",
        "How do you analyze and optimize the complexity of a slow algorithm?",
        "What is the difference between TCP and UDP protocols?",
        "How does virtual memory work in modern operating systems?"
    ],
    "behavioral": [
        "Tell me about a challenging team project where a conflict arose and how you handled it.",
        "Describe a time you had to learn a complex new skill or framework in a very short time.",
        "Share an example of a mistake or failure in your academic/professional life and what you learned.",
        "Describe a situation where you went above and beyond to deliver a project on time.",
        "How do you handle receiving critical feedback from team members or mentors?"
    ],
}

DEFAULT_OVERALL_SUMMARY = "Overall campus placement analysis successfully compiled."


class ResumeAnalysisSchema(BaseModel):
    ats_score: int = Field(default=0, ge=0, le=100)
    summary: str = Field(default="Resume summary details are currently unavailable.")
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    grammar_suggestions: List[str] = Field(default_factory=list)
    formatting_suggestions: List[str] = Field(default_factory=list)
    project_feedback: str = Field(default="Detailed project feedback is unavailable.")
    experience_feedback: str = Field(default="Detailed professional experience feedback is unavailable.")
    missing_skills: List[str] = Field(default_factory=list)
    overall_recommendation: str = Field(default="Consider tailoring experience bullet points to matches.")

    @field_validator("ats_score", mode="before")
    @classmethod
    def parse_ats_score(cls, v: Any) -> int:
        if v is None:
            return 0
        try:
            val = int(round(float(v)))
            return max(0, min(100, val))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid ATS score: {v}") from e

    @field_validator("strengths", "weaknesses", "grammar_suggestions", "formatting_suggestions", "missing_skills", mode="before")
    @classmethod
    def parse_str_list(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if x is not None and str(x).strip()]
        if isinstance(v, str):
            clean = v.strip()
            return [clean] if clean else []
        raise ValueError(f"Expected list or string, got {type(v)}")

    @field_validator("summary", "project_feedback", "experience_feedback", "overall_recommendation", mode="before")
    @classmethod
    def parse_str_fields(cls, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, (str, int, float)):
            return str(v).strip()
        raise ValueError(f"Expected string, got {type(v)}")


class JobMatchSchema(BaseModel):
    match_percentage: int = Field(default=0, ge=0, le=100)
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    required_certifications: List[str] = Field(default_factory=list)
    recommended_improvements: List[str] = Field(default_factory=list)
    top_5_resume_changes: List[str] = Field(default_factory=list)

    @field_validator("match_percentage", mode="before")
    @classmethod
    def parse_match_percentage(cls, v: Any) -> int:
        if v is None:
            return 0
        try:
            val = int(round(float(v)))
            return max(0, min(100, val))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid match percentage: {v}") from e

    @field_validator("matched_skills", "missing_skills", "required_certifications", "recommended_improvements", "top_5_resume_changes", mode="before")
    @classmethod
    def parse_job_str_list(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if x is not None and str(x).strip()]
        if isinstance(v, str):
            clean = v.strip()
            return [clean] if clean else []
        raise ValueError(f"Expected list or string, got {type(v)}")


class SkillGapItemSchema(BaseModel):
    skill: str = Field(default="General Technical Concepts")
    importance: str = Field(default="Medium")
    difficulty: str = Field(default="Medium")
    learning_time: str = Field(default="2 weeks")
    learning_resource: str = Field(default="Coursera / Udemy / Official Documentation")
    project_suggestion: str = Field(default="Design a custom proof-of-concept project incorporating this skill.")
    priority: str = Field(default="Medium")

    @field_validator("importance", "priority", mode="before")
    @classmethod
    def validate_importance_priority(cls, v: Any) -> str:
        if not v:
            return "Medium"
        v_str = str(v).strip().capitalize()
        return v_str if v_str in ("High", "Medium", "Low") else "Medium"

    @field_validator("difficulty", mode="before")
    @classmethod
    def validate_difficulty(cls, v: Any) -> str:
        if not v:
            return "Medium"
        v_str = str(v).strip().capitalize()
        return v_str if v_str in ("Easy", "Medium", "Hard") else "Medium"

    @field_validator("skill", "learning_time", "learning_resource", "project_suggestion", mode="before")
    @classmethod
    def sanitize_str(cls, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, (str, int, float)):
            return str(v).strip()
        return ""


class RoadmapWeekSchema(BaseModel):
    week: str = Field(default="Week 1")
    topics: List[str] = Field(default_factory=list)
    coding_practice: List[str] = Field(default_factory=list)
    mini_projects: List[str] = Field(default_factory=list)
    interview_questions: List[str] = Field(default_factory=list)
    revision_tasks: List[str] = Field(default_factory=list)
    estimated_hours: int = Field(default=10, ge=1, le=80)

    @field_validator("estimated_hours", mode="before")
    @classmethod
    def parse_hours(cls, v: Any) -> int:
        if v is None:
            return 10
        try:
            val = int(round(float(v)))
            return max(1, min(80, val))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid estimated hours: {v}") from e

    @field_validator("topics", "coding_practice", "mini_projects", "interview_questions", "revision_tasks", mode="before")
    @classmethod
    def parse_roadmap_lists(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if x is not None and str(x).strip()]
        if isinstance(v, str):
            clean = v.strip()
            return [clean] if clean else []
        raise ValueError(f"Expected list or string, got {type(v)}")


class InterviewQuestionsSchema(BaseModel):
    hr: List[str] = Field(default_factory=list)
    technical: List[str] = Field(default_factory=list)
    behavioral: List[str] = Field(default_factory=list)

    @field_validator("hr", "technical", "behavioral", mode="before")
    @classmethod
    def parse_q_list(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if x is not None and str(x).strip()]
        if isinstance(v, str):
            clean = v.strip()
            return [clean] if clean else []
        raise ValueError(f"Expected list or string, got {type(v)}")


class CoordinatorResponseSchema(BaseModel):
    resume_analysis: Optional[ResumeAnalysisSchema] = None
    job_match: Optional[JobMatchSchema] = None
    skill_gap: Optional[List[SkillGapItemSchema]] = None
    learning_roadmap: Optional[List[RoadmapWeekSchema]] = None
    interview_questions: Optional[InterviewQuestionsSchema] = None
    overall_recommendation_summary: Optional[str] = None


def validate_coordinator_payload(raw_data: Any) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Validates the raw LLM response using Pydantic schemas for each sub-agent's block.
    If a section is missing, malformed, or of the wrong type:
    - Safe default values are filled in.
    - The section status is marked as 'unavailable'.
    - If valid, the section status is marked as 'available'.

    Returns a tuple of (sanitized_blocks_dict, section_status_dict).
    """
    section_status: Dict[str, str] = {
        "resume_analysis": "unavailable",
        "job_match": "unavailable",
        "skill_gap": "unavailable",
        "learning_roadmap": "unavailable",
        "interview_questions": "unavailable",
        "overall_recommendation_summary": "unavailable",
    }

    if not isinstance(raw_data, dict):
        logger.warning(
            f"CoordinatorSchema: Root payload is not a dict ({type(raw_data)}). "
            "All sections marked unavailable with safe defaults."
        )
        sanitized_payload = {
            "resume_analysis": DEFAULT_RESUME_ANALYSIS.copy(),
            "job_match": DEFAULT_JOB_MATCH.copy(),
            "skill_gap": list(DEFAULT_SKILL_GAP),
            "learning_roadmap": list(DEFAULT_ROADMAP),
            "interview_questions": dict(DEFAULT_INTERVIEW_QUESTIONS),
            "overall_recommendation_summary": DEFAULT_OVERALL_SUMMARY,
        }
        return sanitized_payload, section_status

    sanitized_payload: Dict[str, Any] = {}

    # 1. Resume Analysis Validation
    raw_resume = raw_data.get("resume_analysis")
    if isinstance(raw_resume, dict) and raw_resume:
        try:
            validated = ResumeAnalysisSchema.model_validate(raw_resume)
            data_dict = validated.model_dump()
            data_dict["status"] = "available"
            sanitized_payload["resume_analysis"] = data_dict
            section_status["resume_analysis"] = "available"
        except (ValidationError, ValueError) as err:
            logger.warning(f"CoordinatorSchema: resume_analysis schema validation failed ({err}).")
            fallback = DEFAULT_RESUME_ANALYSIS.copy()
            sanitized_payload["resume_analysis"] = fallback
            section_status["resume_analysis"] = "unavailable"
    else:
        logger.info("CoordinatorSchema: resume_analysis missing or empty.")
        fallback = DEFAULT_RESUME_ANALYSIS.copy()
        sanitized_payload["resume_analysis"] = fallback
        section_status["resume_analysis"] = "unavailable"

    # 2. Job Match Validation
    raw_job = raw_data.get("job_match")
    if isinstance(raw_job, dict) and raw_job:
        try:
            validated = JobMatchSchema.model_validate(raw_job)
            data_dict = validated.model_dump()
            data_dict["status"] = "available"
            sanitized_payload["job_match"] = data_dict
            section_status["job_match"] = "available"
        except (ValidationError, ValueError) as err:
            logger.warning(f"CoordinatorSchema: job_match schema validation failed ({err}).")
            fallback = DEFAULT_JOB_MATCH.copy()
            sanitized_payload["job_match"] = fallback
            section_status["job_match"] = "unavailable"
    else:
        logger.info("CoordinatorSchema: job_match missing or empty.")
        fallback = DEFAULT_JOB_MATCH.copy()
        sanitized_payload["job_match"] = fallback
        section_status["job_match"] = "unavailable"

    # 3. Skill Gap Validation
    raw_gap = raw_data.get("skill_gap")
    if isinstance(raw_gap, list):
        # If it's a list, validate individual items
        valid_items = []
        is_all_valid = True
        for idx, item in enumerate(raw_gap):
            if isinstance(item, dict):
                try:
                    v_item = SkillGapItemSchema.model_validate(item)
                    valid_items.append(v_item.model_dump())
                except (ValidationError, ValueError) as err:
                    logger.warning(f"CoordinatorSchema: skill_gap item {idx} invalid ({err}).")
                    is_all_valid = False
            else:
                logger.warning(f"CoordinatorSchema: skill_gap item {idx} is not a dict ({type(item)}).")
                is_all_valid = False

        sanitized_payload["skill_gap"] = valid_items
        # Available if list was present, had valid items, or was explicitly empty valid list
        if is_all_valid and ("skill_gap" in raw_data):
            section_status["skill_gap"] = "available"
        else:
            section_status["skill_gap"] = "available" if valid_items else "unavailable"
    else:
        logger.info("CoordinatorSchema: skill_gap missing or not a list.")
        sanitized_payload["skill_gap"] = list(DEFAULT_SKILL_GAP)
        section_status["skill_gap"] = "unavailable"

    # 4. Learning Roadmap Validation
    raw_roadmap = raw_data.get("learning_roadmap")
    if isinstance(raw_roadmap, list) and raw_roadmap:
        valid_weeks = []
        for idx, week_item in enumerate(raw_roadmap):
            if isinstance(week_item, dict):
                try:
                    v_week = RoadmapWeekSchema.model_validate(week_item)
                    valid_weeks.append(v_week.model_dump())
                except (ValidationError, ValueError) as err:
                    logger.warning(f"CoordinatorSchema: roadmap week {idx} invalid ({err}).")
            else:
                logger.warning(f"CoordinatorSchema: roadmap week {idx} is not a dict ({type(week_item)}).")

        if valid_weeks:
            sanitized_payload["learning_roadmap"] = valid_weeks
            section_status["learning_roadmap"] = "available"
        else:
            sanitized_payload["learning_roadmap"] = list(DEFAULT_ROADMAP)
            section_status["learning_roadmap"] = "unavailable"
    else:
        logger.info("CoordinatorSchema: learning_roadmap missing or not a list.")
        sanitized_payload["learning_roadmap"] = list(DEFAULT_ROADMAP)
        section_status["learning_roadmap"] = "unavailable"

    # 5. Interview Questions Validation
    raw_interview = raw_data.get("interview_questions")
    if isinstance(raw_interview, dict) and raw_interview:
        try:
            validated = InterviewQuestionsSchema.model_validate(raw_interview)
            sanitized_payload["interview_questions"] = validated.model_dump()
            section_status["interview_questions"] = "available"
        except (ValidationError, ValueError) as err:
            logger.warning(f"CoordinatorSchema: interview_questions validation failed ({err}).")
            sanitized_payload["interview_questions"] = dict(DEFAULT_INTERVIEW_QUESTIONS)
            section_status["interview_questions"] = "unavailable"
    else:
        logger.info("CoordinatorSchema: interview_questions missing or empty.")
        sanitized_payload["interview_questions"] = dict(DEFAULT_INTERVIEW_QUESTIONS)
        section_status["interview_questions"] = "unavailable"

    # 6. Overall Recommendation Summary Validation
    raw_summary = raw_data.get("overall_recommendation_summary")
    if isinstance(raw_summary, str) and raw_summary.strip():
        sanitized_payload["overall_recommendation_summary"] = raw_summary.strip()
        section_status["overall_recommendation_summary"] = "available"
    else:
        logger.info("CoordinatorSchema: overall_recommendation_summary missing or invalid.")
        sanitized_payload["overall_recommendation_summary"] = DEFAULT_OVERALL_SUMMARY
        section_status["overall_recommendation_summary"] = "unavailable"

    return sanitized_payload, section_status
