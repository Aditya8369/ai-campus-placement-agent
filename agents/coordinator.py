import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

import prompts
import config
from utils.gemini import generate_json_response, AIResponseFormatError
from agents.coordinator_schema import validate_coordinator_payload
from utils.prompt_security import (
    sanitize_untrusted_text,
    encapsulate_untrusted_input,
    detect_prompt_injection,
    build_secure_system_instruction,
    validate_ai_response_safety,
)

# Import specialized agents
from agents.resume_agent import ResumeAgent
from agents.job_match_agent import JobMatchAgent
from agents.skill_gap_agent import SkillGapAgent
from agents.roadmap_agent import RoadmapAgent
from agents.interview_agent import InterviewAgent
from utils.pdf_reader import standardize_resume_sections, format_standardized_resume

logger = logging.getLogger(__name__)

# Fallback or placeholder skill values to exclude from conflict validation
GENERIC_FALLBACK_SKILLS = frozenset({
    "general technical concepts"
})

class CoordinatorAgent:
    """
    Central orchestrator agent. Coordinates loading static company profiles,
    invoking Gemini for a single JSON analysis, and delegating sections of that
    response to specialized sub-agent classes for validation and cleanup.
    """
    def __init__(self) -> None:
        self.resume_agent = ResumeAgent()
        self.job_match_agent = JobMatchAgent()
        self.skill_gap_agent = SkillGapAgent()
        self.roadmap_agent = RoadmapAgent()
        self.interview_agent = InterviewAgent()

    def _load_company_data(self, company_name: str) -> Dict[str, Any]:
        """
        Loads static company interview details from data/companies.json.
        """
        companies_file_path = Path(config.BASE_DIR) / "data" / "companies.json"
        try:
            if companies_file_path.exists():
                with open(companies_file_path, "r") as f:
                    companies_dict = json.load(f)
                return companies_dict.get(company_name, {})
            else:
                logger.warning(f"companies.json not found at: {companies_file_path}")
        except Exception as e:
            logger.error(f"Failed to load static company profiles: {str(e)}")
        return {}

    def analyze(
        self,
        resume_text: str,
        job_description: str = "",
        company_name: str = "General",
        on_progress: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Runs the placement preparation analysis workflow using a single Gemini model call.
        Optionally emits progress milestones via on_progress callback if supplied.
        """
        logger.info(f"CoordinatorAgent: Starting analysis cycle for company target: '{company_name}'")
        if on_progress:
            on_progress("step2", "ResumeAgent", "Evaluating resume formatting, bullet points, and ATS compatibility...", 30)

        # 0. Treat uploaded resume and pasted job descriptions as untrusted inputs
        sanitized_resume = sanitize_untrusted_text(resume_text, max_length=25000)
        sanitized_jd = sanitize_untrusted_text(job_description, max_length=15000)

        resume_threat = detect_prompt_injection(sanitized_resume)
        jd_threat = detect_prompt_injection(sanitized_jd)

        if resume_threat["is_suspicious"]:
            logger.warning(
                f"CoordinatorAgent: Suspicious prompt injection patterns detected in resume: {resume_threat['matched_categories']}"
            )
        if jd_threat["is_suspicious"]:
            logger.warning(
                f"CoordinatorAgent: Suspicious prompt injection patterns detected in job description: {jd_threat['matched_categories']}"
            )

        # 1. Load static company metadata to supply relevant hiring details
        company_profile = self._load_company_data(company_name)
        company_profile_str = json.dumps(company_profile, indent=2) if company_profile else "Generic technical engineering placement guidelines."

        # 2. Standardize resume sections for cleaner agent consumption
        parsed_sections = standardize_resume_sections(sanitized_resume)
        formatted_resume = format_standardized_resume(parsed_sections) if parsed_sections else sanitized_resume

        # 3. Encapsulate untrusted inputs within rigid boundary tags
        encapsulated_resume = encapsulate_untrusted_input(formatted_resume, document_type="candidate_resume")
        job_desc_str = sanitized_jd if sanitized_jd.strip() else "None provided. Assume General Software Development Engineer Role."
        encapsulated_jd = encapsulate_untrusted_input(job_desc_str, document_type="job_description")

        # 4. Format the user prompt combining all parameters and hardened system instruction
        user_prompt = prompts.ANALYSIS_USER_PROMPT_TEMPLATE.format(
            company_name=company_name,
            company_details=company_profile_str,
            job_description=encapsulated_jd,
            resume_text=encapsulated_resume
        )
        secure_system_instruction = build_secure_system_instruction(prompts.ANALYSIS_SYSTEM_INSTRUCTION)

        # 5. Call the Gemini API with structured JSON configs, with one-time retry for format failures
        logger.info("CoordinatorAgent: Issuing request to Gemini model.")
        raw_json_response = None
        try:
            raw_json_response = generate_json_response(
                system_instruction=secure_system_instruction,
                prompt=user_prompt
            )
        except AIResponseFormatError as fmt_err:
            logger.warning(
                f"CoordinatorAgent: Primary AI JSON generation failed ({fmt_err}). "
                "Retrying once with strict JSON schema reminder prompt."
            )
            reminder_prompt = (
                user_prompt +
                "\n\nCRITICAL REMINDER: Your previous response was malformed, incomplete, or not valid JSON. "
                "You MUST return ONLY a single valid JSON object matching the exact schema specified above. "
                "Do not include markdown tags (```json), explanations, or trailing commas."
            )
            try:
                raw_json_response = generate_json_response(
                    system_instruction=secure_system_instruction,
                    prompt=reminder_prompt
                )
            except AIResponseFormatError:
                logger.error("CoordinatorAgent: Retry also produced malformed/invalid JSON. Re-raising format error.")
                raise
        except Exception as api_err:
            logger.error(f"CoordinatorAgent: AI call failed ({api_err}). Re-raising for user handling.")
            raise

        if not isinstance(raw_json_response, dict):
            logger.warning(
                f"CoordinatorAgent: Unexpected non-dict root JSON response ({type(raw_json_response)}). "
                "Applying resilient defaults."
            )
            raw_json_response = {}

        # 6. Validate AI response for safety, secret leakage, persona breaches, and score tampering
        is_safe, sanitized_response, security_flags = validate_ai_response_safety(
            raw_json_response,
            original_resume=sanitized_resume,
            original_jd=sanitized_jd
        )
        if not is_safe:
            logger.warning(f"CoordinatorAgent: AI response flagged by safety validator: {security_flags}")
        raw_json_response = sanitized_response

        # 7. Validate response blocks with Pydantic schema before delegation
        logger.info("CoordinatorAgent: Validating JSON blocks against Pydantic schema.")
        validated_blocks, section_status = validate_coordinator_payload(raw_json_response)

        # 6. Extract sanitized blocks and delegate to specialized sub-agents
        logger.info("CoordinatorAgent: Delegating validated payload blocks to sub-agents.")
        resume_block = validated_blocks["resume_analysis"]
        job_match_block = validated_blocks["job_match"]
        skill_gap_block = validated_blocks["skill_gap"]
        roadmap_block = validated_blocks["learning_roadmap"]
        interview_block = validated_blocks["interview_questions"]
        overall_summary_block = validated_blocks["overall_recommendation_summary"]

        processed_resume = self.resume_agent.process(resume_block)
        processed_resume["status"] = section_status["resume_analysis"]

        if on_progress:
            on_progress("step3", "JobMatchAgent", f"Benchmarking technical capabilities against {company_name} hiring criteria...", 50)
        processed_job_match = self.job_match_agent.process(
            job_match_block,
            company_name=company_name,
            ats_score=processed_resume.get("ats_score", 70)
        )
        processed_job_match["status"] = section_status["job_match"]

        if on_progress:
            on_progress("step4", "SkillGapAgent", "Detecting critical skill deficiencies and recommending portfolio projects...", 65)
        processed_skill_gap = self.skill_gap_agent.process(skill_gap_block)

        if on_progress:
            on_progress("step5", "RoadmapAgent", "Constructing tailored 6-week progressive placement preparation roadmap...", 80)
        processed_roadmap = self.roadmap_agent.process(roadmap_block)

        if on_progress:
            on_progress("step6", "InterviewAgent", f"Synthesizing customized Technical, HR, and Behavioral questions for {company_name}...", 90)
        processed_interview = self.interview_agent.process(interview_block)
        processed_interview["status"] = section_status["interview_questions"]

        # 7. Detect cross-section conflicts deterministically without extra API calls
        conflicts = self._detect_conflicts(
            job_match=processed_job_match,
            skill_gap=processed_skill_gap,
            resume_analysis=processed_resume
        )

        if conflicts:
            conflict_types = [f"{c['conflict_type']}:{c['skill']}" for c in conflicts]
            logger.warning(
                f"CoordinatorAgent: Detected {len(conflicts)} cross-section conflict(s): {', '.join(conflict_types)}"
            )
        else:
            logger.info("CoordinatorAgent: No cross-section conflicts detected.")

        # 8. Combine validated data into a final coordinated results payload
        combined_payload = {
            "resume_analysis": processed_resume,
            "job_match": processed_job_match,
            "skill_gap": processed_skill_gap,
            "learning_roadmap": processed_roadmap,
            "interview_questions": processed_interview,
            "overall_recommendation_summary": overall_summary_block,
            "conflicts": conflicts,
            "section_status": section_status,
            "security_audit": {
                "prompt_injection_detected": bool(resume_threat["is_suspicious"] or jd_threat["is_suspicious"]),
                "resume_threat": resume_threat,
                "job_description_threat": jd_threat,
                "safety_flags": security_flags
            }
        }

        logger.info("CoordinatorAgent: Multi-agent processing complete.")
        return combined_payload

    def _detect_conflicts(
        self,
        job_match: Dict[str, Any],
        skill_gap: List[Dict[str, Any]],
        resume_analysis: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Deterministically detects cross-section contradictions across structured analysis blocks.
        Evaluates two rules:
        1. matched_skill_in_skill_gap: A skill is classified as matched in job_match while simultaneously
           flagged as a missing skill gap to learn in skill_gap.
        2. matched_skill_in_missing_skills: A skill is classified as both matched and missing within job_match.

        Skips blank, non-string, and generic fallback values. Deduplicates by (conflict_type, normalized_skill).
        """
        if not isinstance(job_match, dict):
            job_match = {}
        if not isinstance(skill_gap, list):
            skill_gap = []
        if not isinstance(resume_analysis, dict):
            resume_analysis = {}

        raw_matched = job_match.get("matched_skills", [])
        if not isinstance(raw_matched, list):
            raw_matched = []

        raw_missing = job_match.get("missing_skills", [])
        if not isinstance(raw_missing, list):
            raw_missing = []

        def normalize(val: Any) -> str:
            if not isinstance(val, str):
                return ""
            return val.strip().lower()

        def is_valid(norm_val: str) -> bool:
            return bool(norm_val) and norm_val not in GENERIC_FALLBACK_SKILLS

        # Map normalized skill -> original display string for skill_gap
        gap_skills: Dict[str, str] = {}
        for item in skill_gap:
            if isinstance(item, dict):
                raw_skill = item.get("skill")
                norm = normalize(raw_skill)
                if is_valid(norm) and norm not in gap_skills:
                    gap_skills[norm] = str(raw_skill).strip()

        # Map normalized skill -> original display string for missing_skills
        missing_skills_map: Dict[str, str] = {}
        for s in raw_missing:
            norm = normalize(s)
            if is_valid(norm) and norm not in missing_skills_map:
                missing_skills_map[norm] = str(s).strip()

        conflicts: List[Dict[str, Any]] = []
        seen_conflicts = set()

        for s in raw_matched:
            norm = normalize(s)
            if not is_valid(norm):
                continue
            display_skill = str(s).strip()

            # Rule 1: matched_skill_in_skill_gap
            if norm in gap_skills:
                conflict_key = ("matched_skill_in_skill_gap", norm)
                if conflict_key not in seen_conflicts:
                    seen_conflicts.add(conflict_key)
                    conflicts.append({
                        "conflict_type": "matched_skill_in_skill_gap",
                        "severity": "high",
                        "skill": display_skill,
                        "sections": ["job_match.matched_skills", "skill_gap"],
                        "message": (
                            f"Skill '{display_skill}' is listed as a matched skill in Job Match, "
                            f"but also flagged as a missing skill gap in Skill Gap Analysis."
                        ),
                        "recommended_action": (
                            f"Review the resume evidence for {display_skill} and "
                            f"verify whether the skill-gap recommendation is appropriate."
                        ),
                    })

            # Rule 2: matched_skill_in_missing_skills
            if norm in missing_skills_map:
                conflict_key = ("matched_skill_in_missing_skills", norm)
                if conflict_key not in seen_conflicts:
                    seen_conflicts.add(conflict_key)
                    conflicts.append({
                        "conflict_type": "matched_skill_in_missing_skills",
                        "severity": "high",
                        "skill": display_skill,
                        "sections": ["job_match.matched_skills", "job_match.missing_skills"],
                        "message": (
                            f"Skill '{display_skill}' is simultaneously classified as both a matched skill "
                            f"and a missing skill in Job Match."
                        ),
                        "recommended_action": (
                            f"Review the contradictory Job Match classifications for {display_skill} "
                            f"to verify whether your resume demonstrates this requirement."
                        ),
                    })

        return conflicts
