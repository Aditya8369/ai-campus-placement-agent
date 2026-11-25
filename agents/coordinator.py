import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

import prompts
import config
from utils.gemini import (
    generate_json_response,
    stream_json_response_sections,
    create_safe_fallback_analysis_payload,
    AIResponseFormatError,
    scrub_api_key,
)
from agents.coordinator_schema import validate_coordinator_payload
from utils.prompt_security import (
    sanitize_untrusted_text,
    encapsulate_untrusted_input,
    detect_prompt_injection,
    strip_prompt_injection,
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
from utils.skill_evidence_mapper import map_skill_evidence

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

        # Redact personal contact details from resume and JD before constructing AI model prompt (#295, #500)
        if getattr(config, "ENABLE_PII_REDACTION", True):
            from utils.pii_redactor import redact_pii
            redacted_resume = redact_pii(resume_text)
            redacted_jd = redact_pii(job_description)
            logger.info("CoordinatorAgent: Personal contact details redacted from inputs before prompt building.")
        else:
            redacted_resume = resume_text
            redacted_jd = job_description

        # 0. Check for prompt injection, instruction overrides, and hidden text on original inputs
        resume_threat = detect_prompt_injection(resume_text or redacted_resume)
        jd_threat = detect_prompt_injection(job_description or redacted_jd)

        # Treat uploaded resume and pasted job descriptions as untrusted inputs
        sanitized_resume = sanitize_untrusted_text(redacted_resume, max_length=25000)
        sanitized_jd = sanitize_untrusted_text(redacted_jd, max_length=15000)

        # If sanitized text revealed further threats (e.g. decoded entities)
        if not resume_threat["is_suspicious"]:
            resume_threat = detect_prompt_injection(sanitized_resume)
        if not jd_threat["is_suspicious"]:
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
                prompt=user_prompt,
                feature="analysis"
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
                    prompt=reminder_prompt,
                    feature="analysis"
                )
            except AIResponseFormatError:
                logger.error("CoordinatorAgent: Retry also produced malformed/invalid JSON. Re-raising format error.")
                raise
        except Exception as api_err:
            clean_err = scrub_api_key(str(api_err))
            logger.error(f"CoordinatorAgent: AI call failed ({clean_err}). Re-raising for user handling.")
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

        # 8. Map detected skill evidence across resume sections (#250)
        try:
            matched_skills_list = processed_job_match.get("matched_skills") or []
            evidence_mapping = map_skill_evidence(
                resume_text=resume_text,
                target_skills=matched_skills_list or None
            )
        except Exception as map_err:
            logger.warning(f"CoordinatorAgent: Skill evidence mapping failed ({map_err}). Falling back to empty mapping.")
            evidence_mapping = {
                "total_skills": 0,
                "supported_skills_count": 0,
                "unsupported_skills_count": 0,
                "partial_skills_count": 0,
                "evidence_score": 100,
                "summary": "Skill evidence mapping could not be evaluated.",
                "skills": []
            }

        # 9. Compute deterministic ATS score & section breakdown (#494, #762)
        # Ensure scores come strictly from deterministic checks that model output cannot override.
        # Defang/strip injection attempts so prompt injections cannot alter the score.
        scoring_resume_text = strip_prompt_injection(resume_text or sanitized_resume)
        try:
            from utils.ats_score_service import evaluate_resume_ats_score
            ats_breakdown = evaluate_resume_ats_score(scoring_resume_text or resume_text or sanitized_resume)
            processed_resume["ats_score"] = ats_breakdown["total_score"]
            processed_resume["ats_breakdown"] = ats_breakdown
        except Exception as ats_err:
            logger.warning(f"CoordinatorAgent: Error computing deterministic ATS score: {ats_err}")
            ats_breakdown = None

        # 10. Run resume timeline consistency and gap analysis (#840)
        try:
            from utils.resume_timeline_service import analyze_resume_timeline
            timeline_analysis = analyze_resume_timeline(resume_text or sanitized_resume)
        except Exception as timeline_err:
            logger.warning(f"CoordinatorAgent: Error analyzing resume timeline: {timeline_err}")
            timeline_analysis = {
                "status": "error",
                "has_flags": False,
                "has_active_flags": False,
                "total_flags": 0,
                "active_flags_count": 0,
                "dismissed_flags_count": 0,
                "gap_threshold_months": 6,
                "summary": {"gaps_count": 0, "overlaps_count": 0, "inverted_count": 0, "future_count": 0},
                "flags": [],
                "timeline_items": []
            }

        # 11. Combine validated data into a final coordinated results payload
        combined_payload = {
            "resume_analysis": processed_resume,
            "ats_breakdown": ats_breakdown,
            "timeline_analysis": timeline_analysis,
            "job_match": processed_job_match,
            "skill_gap": processed_skill_gap,
            "learning_roadmap": processed_roadmap,
            "interview_questions": processed_interview,
            "overall_recommendation_summary": overall_summary_block,
            "conflicts": conflicts,
            "section_status": section_status,
            "skill_evidence_mapping": evidence_mapping,
            "extracted_resume_text": resume_text,
            "security_warning": security_warning,
            "warning": security_warning,
            "security_audit": {
                "prompt_injection_detected": injection_detected,
                "has_hidden_text": bool(resume_threat.get("has_hidden_text") or jd_threat.get("has_hidden_text")),
                "has_instruction_phrases": bool(resume_threat.get("has_instruction_phrases") or jd_threat.get("has_instruction_phrases")),
                "warning": security_warning,
                "warning_message": security_warning,
                "resume_threat": resume_threat,
                "job_description_threat": jd_threat,
                "safety_flags": security_flags
            }
        }

        logger.info("CoordinatorAgent: Multi-agent processing complete.")
        return combined_payload

    def analyze_stream(
        self,
        resume_text: str,
        job_description: str = "",
        company_name: str = "General",
        on_section: Optional[Callable[[str, Any, int], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        use_fallback_on_failure: bool = True,
    ) -> Dict[str, Any]:
        """
        Runs placement analysis using streaming Gemini AI responses (#764).
        Invokes on_section(section_name, section_data, progress) as each section
        completes, rendering results before the entire response finishes.

        Features:
        - The first section appears before the whole response finishes.
        - Cancelling stops the underlying stream request immediately.
        - Mid-stream errors preserve all already generated sections.
        - Seamless non-streaming fallback when streaming cannot start.
        """
        logger.info(f"CoordinatorAgent: Starting streaming analysis cycle for company target: '{company_name}'")

        if getattr(config, "ENABLE_PII_REDACTION", True):
            from utils.pii_redactor import redact_pii
            redacted_resume = redact_pii(resume_text)
            redacted_jd = redact_pii(job_description)
        else:
            redacted_resume = resume_text
            redacted_jd = job_description

        sanitized_resume = sanitize_untrusted_text(redacted_resume, max_length=25000)
        sanitized_jd = sanitize_untrusted_text(redacted_jd, max_length=15000)

        resume_threat = detect_prompt_injection(sanitized_resume)
        jd_threat = detect_prompt_injection(sanitized_jd)

        company_profile = self._load_company_data(company_name)
        company_profile_str = json.dumps(company_profile, indent=2) if company_profile else "Generic technical engineering placement guidelines."

        parsed_sections = standardize_resume_sections(sanitized_resume)
        formatted_resume = format_standardized_resume(parsed_sections) if parsed_sections else sanitized_resume

        encapsulated_resume = encapsulate_untrusted_input(formatted_resume, document_type="candidate_resume")
        job_desc_str = sanitized_jd if sanitized_jd.strip() else "None provided. Assume General Software Development Engineer Role."
        encapsulated_jd = encapsulate_untrusted_input(job_desc_str, document_type="job_description")

        user_prompt = prompts.ANALYSIS_USER_PROMPT_TEMPLATE.format(
            company_name=company_name,
            company_details=company_profile_str,
            job_description=encapsulated_jd,
            resume_text=encapsulated_resume
        )
        secure_system_instruction = build_secure_system_instruction(prompts.ANALYSIS_SYSTEM_INSTRUCTION)

        completed_sections: Dict[str, Any] = {}
        section_status: Dict[str, str] = {
            "resume_analysis": "unavailable",
            "job_match": "unavailable",
            "skill_gap": "unavailable",
            "learning_roadmap": "unavailable",
            "interview_questions": "unavailable",
            "overall_recommendation_summary": "unavailable",
        }

        # Progress weights for each section
        progress_map = {
            "resume_analysis": 35,
            "job_match": 50,
            "skill_gap": 65,
            "learning_roadmap": 80,
            "interview_questions": 92,
            "overall_recommendation_summary": 100,
        }

        fallback_payload = create_safe_fallback_analysis_payload(company_name=company_name)

        stream_gen = stream_json_response_sections(
            system_instruction=secure_system_instruction,
            prompt=user_prompt,
            is_cancelled_fn=is_cancelled,
            feature="analysis",
        )

        had_stream_error = False
        stream_error_msg = None

        for sec_name, sec_data in stream_gen:
            if is_cancelled and is_cancelled():
                logger.info("CoordinatorAgent: Cancellation detected during stream iteration.")
                break

            if sec_name == "_cancelled":
                logger.info("CoordinatorAgent: Stream generator returned cancelled event.")
                break

            if sec_name == "_stream_error":
                had_stream_error = True
                stream_error_msg = sec_data.get("error", "Stream error occurred.")
                logger.warning(f"CoordinatorAgent: Mid-stream error: {stream_error_msg}")
                break

            # Process completed section with its specialized agent
            try:
                if sec_name == "resume_analysis":
                    processed = self.resume_agent.process(sec_data)
                    try:
                        from utils.ats_score_service import evaluate_resume_ats_score
                        ats_breakdown = evaluate_resume_ats_score(resume_text or sanitized_resume)
                        processed["ats_score"] = ats_breakdown["total_score"]
                        processed["ats_breakdown"] = ats_breakdown
                    except Exception as ats_err:
                        logger.warning(f"ATS scoring error during streaming: {ats_err}")
                    processed["status"] = "valid"
                    completed_sections["resume_analysis"] = processed
                    section_status["resume_analysis"] = "valid"

                elif sec_name == "job_match":
                    ats_score = completed_sections.get("resume_analysis", {}).get("ats_score", 70)
                    processed = self.job_match_agent.process(
                        sec_data,
                        company_name=company_name,
                        ats_score=ats_score
                    )
                    processed["status"] = "valid"
                    completed_sections["job_match"] = processed
                    section_status["job_match"] = "valid"

                elif sec_name == "skill_gap":
                    processed = self.skill_gap_agent.process(sec_data)
                    completed_sections["skill_gap"] = processed
                    section_status["skill_gap"] = "valid"

                elif sec_name == "learning_roadmap":
                    processed = self.roadmap_agent.process(sec_data)
                    completed_sections["learning_roadmap"] = processed
                    section_status["learning_roadmap"] = "valid"

                elif sec_name == "interview_questions":
                    processed = self.interview_agent.process(sec_data, company_name=company_name)
                    processed["status"] = "valid"
                    completed_sections["interview_questions"] = processed
                    section_status["interview_questions"] = "valid"

                elif sec_name == "overall_recommendation_summary":
                    summary_text = sec_data if isinstance(sec_data, str) else str(sec_data)
                    completed_sections["overall_recommendation_summary"] = summary_text
                    section_status["overall_recommendation_summary"] = "valid"

                # Notify caller immediately as soon as section is complete (#764)
                if on_section:
                    progress_pct = progress_map.get(sec_name, 50)
                    on_section(sec_name, completed_sections.get(sec_name, sec_data), progress_pct)

            except Exception as proc_err:
                logger.warning(f"Error processing section '{sec_name}': {proc_err}")
                completed_sections[sec_name] = sec_data

        # Fallback handling:
        # If streaming failed with zero sections completed and fallback is enabled, call non-streaming analyze()
        if had_stream_error and not completed_sections and use_fallback_on_failure:
            logger.info("Streaming failed before any section completed. Invoking non-streaming fallback.")
            return self.analyze(
                resume_text=resume_text,
                job_description=job_description,
                company_name=company_name,
            )

        # Assemble result payload, retaining all completed sections (mid-stream errors never discard content)
        final_resume = completed_sections.get("resume_analysis", fallback_payload["resume_analysis"])
        final_job_match = completed_sections.get("job_match", fallback_payload["job_match"])
        final_skill_gap = completed_sections.get("skill_gap", fallback_payload["skill_gap"])
        final_roadmap = completed_sections.get("learning_roadmap", fallback_payload["learning_roadmap"])
        final_interview = completed_sections.get("interview_questions", fallback_payload["interview_questions"])
        final_summary = completed_sections.get(
            "overall_recommendation_summary",
            fallback_payload["overall_recommendation_summary"]
        )

        conflicts = self._detect_conflicts(
            job_match=final_job_match,
            skill_gap=final_skill_gap,
            resume_analysis=final_resume
        )

        try:
            matched_skills = final_job_match.get("matched_skills") or []
            evidence_mapping = map_skill_evidence(
                resume_text=resume_text,
                target_skills=matched_skills or None
            )
        except Exception:
            evidence_mapping = {
                "total_skills": 0,
                "supported_skills_count": 0,
                "unsupported_skills_count": 0,
                "partial_skills_count": 0,
                "evidence_score": 100,
                "summary": "Skill evidence mapping could not be evaluated.",
                "skills": []
            }

        ats_breakdown = final_resume.get("ats_breakdown")

        # Run resume timeline consistency and gap analysis (#840)
        try:
            from utils.resume_timeline_service import analyze_resume_timeline
            timeline_analysis = analyze_resume_timeline(resume_text or sanitized_resume)
        except Exception as timeline_err:
            logger.warning(f"CoordinatorAgent (stream): Error analyzing resume timeline: {timeline_err}")
            timeline_analysis = {
                "status": "error",
                "has_flags": False,
                "has_active_flags": False,
                "total_flags": 0,
                "active_flags_count": 0,
                "dismissed_flags_count": 0,
                "gap_threshold_months": 6,
                "summary": {"gaps_count": 0, "overlaps_count": 0, "inverted_count": 0, "future_count": 0},
                "flags": [],
                "timeline_items": []
            }

        result_payload = {
            "resume_analysis": final_resume,
            "ats_breakdown": ats_breakdown,
            "timeline_analysis": timeline_analysis,
            "job_match": final_job_match,
            "skill_gap": final_skill_gap,
            "learning_roadmap": final_roadmap,
            "interview_questions": final_interview,
            "overall_recommendation_summary": final_summary,
            "conflicts": conflicts,
            "section_status": section_status,
            "skill_evidence_mapping": evidence_mapping,
            "extracted_resume_text": resume_text,
            "streaming": True,
            "completed_sections": list(completed_sections.keys()),
            "security_audit": {
                "prompt_injection_detected": bool(resume_threat["is_suspicious"] or jd_threat["is_suspicious"]),
                "resume_threat": resume_threat,
                "job_description_threat": jd_threat,
                "safety_flags": []
            }
        }

        if had_stream_error:
            result_payload["stream_error"] = stream_error_msg
            result_payload["is_partial"] = True

        if is_cancelled and is_cancelled():
            result_payload["is_cancelled"] = True

        return result_payload

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
