"""
Basic Analysis Fallback Service (#849).
======================================
Produces a reduced, rule-based placement evaluation when the Gemini AI API
is temporarily down, rate limited (429), or unavailable (500/503).

Existing Rule-Based Components leveraged:
1. ATS Format Checks (utils.format_checker)
2. Section Completeness & Basic Length Checks (utils.ats_score_service)
3. Keyword & Skill Overlap with JD or Role Template (utils.role_skill_gap_service)

Guarantees:
- Labelled clearly as "basic analysis (AI unavailable)"
- Must never be cached as a full result
- Preserves 100% dashboard rendering compatibility
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set

from utils.ats_score_service import (
    COMMON_TECH_SKILLS,
    SECTION_TITLES,
    SECTION_WEIGHTS,
    evaluate_basics_checks,
    evaluate_resume_ats_score,
    extract_resume_sections,
)
from utils.format_checker import check_resume_format_compatibility
from utils.role_skill_gap_service import (
    SKILL_ALIASES,
    _resolve_suggested_topics_for_skill,
    extract_candidate_skills,
    get_available_roles,
    get_role_profile,
    normalize_skill_name,
    skills_match,
)

logger = logging.getLogger(__name__)

BASIC_ANALYSIS_LABEL = "basic analysis (AI unavailable)"


def _extract_jd_skills(job_description: str, company_name: str = "General") -> List[str]:
    """
    Extracts required skills from job description text or falls back to
    standard role templates if the JD is sparse or empty.
    """
    jd_skills: List[str] = []
    if job_description and job_description.strip():
        # 1. Direct candidate skill extraction over JD text
        extracted = extract_candidate_skills({"resume_text": job_description})
        if extracted:
            jd_skills.extend(extracted)

        # 2. Match common tech skills
        jd_lower = job_description.lower()
        for skill in COMMON_TECH_SKILLS:
            pattern = r"(?:^|\s|\b)" + re.escape(skill) + r"(?:\b|\s|$)"
            if re.search(pattern, jd_lower):
                canonical = SKILL_ALIASES.get(skill, skill)
                if canonical not in jd_skills:
                    jd_skills.append(canonical)

    # If JD provided no detectable skills, fallback to canonical role profile
    if not jd_skills:
        profile = get_role_profile("software-developer")
        if not profile:
            avail = get_available_roles()
            profile = avail[0] if avail else None

        if profile and isinstance(profile, dict):
            req = profile.get("required_skills", [])
            nice = profile.get("nice_to_have_skills", [])
            jd_skills = list(dict.fromkeys(req + nice))
        else:
            jd_skills = [
                "Python",
                "Data Structures",
                "Algorithms",
                "SQL",
                "Git",
                "Problem Solving",
                "REST APIs",
            ]

    # Return deduplicated skill list
    return list(dict.fromkeys(jd_skills))


def generate_basic_fallback_analysis(
    resume_text: str,
    job_description: str = "",
    company_name: str = "General",
    error_reason: str = "",
) -> Dict[str, Any]:
    """
    Computes a reduced, rule-based placement evaluation from existing deterministic components.
    Guaranteed to match the schema expected by the placement readiness dashboard.
    """
    logger.info(
        f"Generating rule-based basic fallback analysis for '{company_name}' "
        f"(reason: {error_reason or 'AI unavailable'})"
    )

    clean_resume = resume_text or ""
    clean_jd = job_description or ""
    clean_company = company_name.strip() if company_name else "General"

    # 1. Deterministic ATS Score and Section Evaluation
    ats_score_eval = evaluate_resume_ats_score(clean_resume)
    ats_score = ats_score_eval.get("total_score", 60)
    sections_eval = ats_score_eval.get("sections", {})
    hurts_most = ats_score_eval.get("hurts_most", {})

    # 2. Core Resume Basics Checks (Length, Action Verbs, Contact Info)
    basics_eval = evaluate_basics_checks(clean_resume)
    parsed_sections = extract_resume_sections(clean_resume)

    # 3. Format Compatibility Inspection
    format_compat = check_resume_format_compatibility(clean_resume, extracted_text=clean_resume)

    # 4. Keyword & Skill Overlap
    candidate_skills = extract_candidate_skills({"resume_text": clean_resume})
    # Also scan for common tech skills
    resume_lower = clean_resume.lower()
    for tech_skill in COMMON_TECH_SKILLS:
        pattern = r"(?:^|\s|\b)" + re.escape(tech_skill) + r"(?:\b|\s|$)"
        if re.search(pattern, resume_lower):
            canonical = SKILL_ALIASES.get(tech_skill, tech_skill)
            if canonical not in candidate_skills:
                candidate_skills.append(canonical)

    jd_target_skills = _extract_jd_skills(clean_jd, company_name=clean_company)

    matched_skills: List[str] = []
    missing_skills: List[str] = []

    for target in jd_target_skills:
        if any(skills_match(target, cand) for cand in candidate_skills):
            matched_skills.append(target)
        else:
            missing_skills.append(target)

    # Compute rule-based match percentage
    if jd_target_skills:
        match_percentage = int(round((len(matched_skills) / len(jd_target_skills)) * 100))
        match_percentage = max(15, min(95, match_percentage))
    else:
        match_percentage = 65

    # 5. Strengths and Areas of Improvement derivation
    strengths: List[str] = []
    areas_of_improvement: List[str] = []

    # Identify strong sections
    for sec_key, sec_data in sections_eval.items():
        if isinstance(sec_data, dict) and sec_data.get("earned_percentage", 0) >= 70:
            strengths.append(f"Strong evidence in {sec_data.get('title', sec_key)} section.")

    # Basics strengths
    word_count = basics_eval.get("word_count", 0)
    if 300 <= word_count <= 800:
        strengths.append(f"Ideal document length ({word_count} words) for campus recruitment review.")
    if basics_eval.get("has_email") and basics_eval.get("has_phone"):
        strengths.append("Complete, clear professional contact information present.")
    if matched_skills:
        strengths.append(f"Demonstrated core skills: {', '.join(matched_skills[:4])}.")

    if not strengths:
        strengths = [
            "Foundational document structure detected.",
            "Readable linear layout suitable for ATS indexing.",
        ]

    # Areas of improvement
    if hurts_most and isinstance(hurts_most, dict) and hurts_most.get("suggestion"):
        areas_of_improvement.append(
            f"{hurts_most.get('title', 'Resume')}: {hurts_most.get('suggestion')}"
        )

    # Missing sections
    for sec_key, sec_title in SECTION_TITLES.items():
        if not parsed_sections.get(sec_key):
            areas_of_improvement.append(f"Missing '{sec_title}' section. Adding this will improve your score.")

    # Missing skills
    if missing_skills:
        areas_of_improvement.append(
            f"Key target role competencies missing or not highlighted: {', '.join(missing_skills[:3])}."
        )

    # Basics warnings
    if word_count < 300:
        areas_of_improvement.append("Resume is too brief (< 300 words). Expand on project contributions and technical impact.")
    elif word_count > 900:
        areas_of_improvement.append("Resume exceeds 900 words. Condense bullet points to maintain recruiter attention.")

    # Format check warnings
    for chk in format_compat.get("checks", []):
        if isinstance(chk, dict) and chk.get("status") == "warn" and chk.get("fix"):
            areas_of_improvement.append(chk["fix"])

    if not areas_of_improvement:
        areas_of_improvement = [
            "Quantify engineering outcomes with measurable metrics (e.g. latency reduced, throughput gained).",
            "Align technical keywords closely with target company requirements.",
        ]

    # 6. Skill Gap items
    skill_gap_items: List[Dict[str, Any]] = []
    for idx, skill in enumerate(missing_skills[:5]):
        topics = _resolve_suggested_topics_for_skill(skill, {})
        skill_gap_items.append({
            "skill": skill,
            "priority": "High" if idx < 2 else "Medium",
            "reason": f"Required competency for {clean_company} placement evaluation.",
            "suggested_project": f"Build a practical capstone demonstrating {skill} implementation and testing.",
            "suggested_topics": topics,
        })

    # 7. Learning Roadmap (6-week progressive plan)
    primary_gap = missing_skills[0] if missing_skills else "System Design & Algorithms"
    secondary_gap = missing_skills[1] if len(missing_skills) > 1 else "Database Modeling & APIs"
    third_gap = missing_skills[2] if len(missing_skills) > 2 else "Cloud & Deployment"

    roadmap = [
        {
            "week": 1,
            "focus": "Core Resume & Section Enhancement",
            "tasks": [
                "Address ATS section completeness and formatting fixes.",
                f"Review fundamentals of {primary_gap}.",
            ],
        },
        {
            "week": 2,
            "focus": f"Technical Foundation: {primary_gap}",
            "tasks": [
                f"Study core documentation and syntax for {primary_gap}.",
                "Implement 3 practical coding exercises or micro-projects.",
            ],
        },
        {
            "week": 3,
            "focus": f"Intermediate Application: {secondary_gap}",
            "tasks": [
                f"Build a functional module utilizing {secondary_gap}.",
                "Write comprehensive unit tests for project code.",
            ],
        },
        {
            "week": 4,
            "focus": f"Architecture & Integration: {third_gap}",
            "tasks": [
                f"Integrate {third_gap} into existing resume portfolio work.",
                "Quantify measurable performance improvements.",
            ],
        },
        {
            "week": 5,
            "focus": f"{clean_company} Mock Technical Interviews",
            "tasks": [
                f"Practice standard technical questions for {clean_company}.",
                "Conduct timed data structures and algorithms practice.",
            ],
        },
        {
            "week": 6,
            "focus": "HR & Behavioral Preparation",
            "tasks": [
                "Prepare STAR-format stories for key project experiences.",
                "Review resume talking points for final rounds.",
            ],
        },
    ]

    # 8. Standard Interview Questions tailored to company & detected skills
    tech_skills_sample = (matched_skills + jd_target_skills)[:3]
    tech_focus = ", ".join(tech_skills_sample) if tech_skills_sample else "core algorithms and system design"

    interview_questions = {
        "hr": [
            f"Why are you interested in joining {clean_company}?",
            "Can you walk me through the most technically challenging project on your resume?",
            "How do you prioritize deadlines when managing multiple coursework or project deliverables?",
            "Describe a time when you received constructive feedback on your code and how you addressed it.",
            "Where do you see your engineering focus evolving over the next two years?",
        ],
        "technical": [
            f"Explain how you would architect a scalable system utilizing {tech_focus}.",
            "What are the trade-offs between relational databases and NoSQL stores for high-write workloads?",
            "Describe the difference between process threads and async event loops with practical examples.",
            "How do you ensure data consistency and prevent race conditions in distributed applications?",
            "Walk me through your debugging methodology when diagnosing a high-latency API endpoint.",
        ],
        "behavioral": [
            "Describe a technical disagreement you had with a team member and how you resolved it collaboratively.",
            "Tell me about a situation where a project deliverable was delayed. What corrective actions did you take?",
            "Give an example of a complex technical concept you explained to a non-technical stakeholder.",
            "How do you approach learning an entirely new technology or framework under tight deadlines?",
            "Describe a time you proactively identified a bug or performance bottleneck before release.",
        ],
    }

    overall_feedback = (
        f"{BASIC_ANALYSIS_LABEL.title()}: Generated using rule-based ATS format inspection, "
        f"section completeness, and keyword matching. "
        f"Full AI deep-dive is temporarily unavailable ({error_reason or 'service busy/rate limited'}). "
        "You can re-run with full AI when the service is restored."
    )

    return {
        # Core identification and labels
        "is_basic_analysis": True,
        "analysis_mode": "basic_fallback",
        "analysis_label": BASIC_ANALYSIS_LABEL,
        "ai_unavailable": True,
        "fallback_reason": error_reason or "AI service temporarily unavailable",
        # Sub-agent compatible payload blocks
        "resume_analysis": {
            "ats_score": ats_score,
            "overall_feedback": overall_feedback,
            "strengths": strengths,
            "areas_of_improvement": areas_of_improvement,
            "keywords_found": matched_skills or candidate_skills[:8],
            "keywords_missing": missing_skills[:6],
            "basics": basics_eval,
            "sections": sections_eval,
            "hurts_most": hurts_most,
        },
        "job_match": {
            "match_percentage": match_percentage,
            "matched_skills": matched_skills or candidate_skills[:6],
            "missing_skills": missing_skills[:6],
            "hiring_criteria": f"Rule-based benchmark for {clean_company} campus placement.",
            "recommendation": (
                "Strengthen resume section completeness and add portfolio evidence for missing competencies."
            ),
        },
        "skill_gap": skill_gap_items,
        "learning_roadmap": roadmap,
        "interview_questions": interview_questions,
        "overall_recommendation_summary": (
            f"Preliminary rule-based placement evaluation for {clean_company}. "
            f"ATS compatibility score: {ats_score}/100. Target role match: {match_percentage}%. "
            f"AI generation was temporarily bypassed ({error_reason or 'AI unavailable'})."
        ),
        "format_compatibility": format_compat,
        "section_status": {
            "resume_analysis": "basic_fallback",
            "job_match": "basic_fallback",
            "skill_gap": "basic_fallback",
            "learning_roadmap": "basic_fallback",
            "interview_questions": "basic_fallback",
            "overall_recommendation_summary": "basic_fallback",
        },
    }
