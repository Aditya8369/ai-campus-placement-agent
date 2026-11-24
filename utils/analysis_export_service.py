"""
Analysis Export Service (#534)
==============================
Provides structured, stable export generation for Placement Readiness Reports in
both Markdown (.md) and JSON (.json) formats.

Guarantees:
1. Complete content parity with on-screen report (scores, skill gaps, suggestions, interview tips, roadmaps).
2. Stable, fully documented JSON schema (version 1.0).
3. Preservation of Unicode, special characters (C++, C#, &), non-English languages, and symbols without ASCII escaping.
"""

import os
import re
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from pathlib import Path

import config

logger = logging.getLogger(__name__)

CURRENT_EXPORT_VERSION = "1.0"

CANONICAL_SECTIONS = [
    "scores",
    "summary",
    "overall_recommendation",
    "resume_analysis",
    "job_adjustments",
    "skill_gaps",
    "interview_tips",
    "learning_roadmap",
]

SECTION_ALIASES = {
    "score": "scores",
    "metrics": "scores",
    "readiness_scores": "scores",
    "ats_score": "scores",
    "executive_summary": "summary",
    "resume_summary": "summary",
    "recommendation": "overall_recommendation",
    "overall_recommendations": "overall_recommendation",
    "advisories": "overall_recommendation",
    "resume_details": "resume_analysis",
    "resume_feedback": "resume_analysis",
    "suggestions": "resume_analysis",
    "adjustments": "job_adjustments",
    "resume_changes": "job_adjustments",
    "top_adjustments": "job_adjustments",
    "top_5_resume_changes": "job_adjustments",
    "skill_gap": "skill_gaps",
    "skills_gap": "skill_gaps",
    "gaps": "skill_gaps",
    "interview": "interview_tips",
    "interview_guidance": "interview_tips",
    "tips": "interview_tips",
    "interview_questions": "interview_tips",
    "roadmap": "learning_roadmap",
    "study_plan": "learning_roadmap",
}

SECTION_TITLES = {
    "scores": "Readiness Scores & ATS Evaluation",
    "summary": "Executive Resume Summary",
    "overall_recommendation": "Overall Placement Recommendation",
    "resume_analysis": "Resume Feedback & Suggestions",
    "job_adjustments": "Top Recommended Resume Adjustments",
    "skill_gaps": "Skill Gap Assessment",
    "interview_tips": "Interview Tips & Preparation Guidance",
    "learning_roadmap": "Six-Week Learning Roadmap",
}


def normalize_report_customization(customization: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Normalizes report customization options (student_name, target_role, included_sections, section_order).
    Guarantees that when customization is None or empty, default report settings are preserved.
    """
    if not isinstance(customization, dict):
        return {
            "student_name": None,
            "target_role": None,
            "included_sections": list(CANONICAL_SECTIONS),
            "section_order": list(CANONICAL_SECTIONS),
            "is_customized": False,
        }

    raw_name = customization.get("student_name") or customization.get("candidate_name") or customization.get("name")
    student_name = str(raw_name).strip() if raw_name and str(raw_name).strip() else None

    raw_role = customization.get("target_role") or customization.get("role") or customization.get("role_target")
    target_role = str(raw_role).strip() if raw_role and str(raw_role).strip() else None

    # Handle included sections
    raw_sections = customization.get("included_sections") or customization.get("sections")
    if raw_sections is not None:
        if isinstance(raw_sections, str):
            raw_list = [s.strip().lower() for s in raw_sections.split(",") if s.strip()]
        elif isinstance(raw_sections, (list, tuple, set)):
            raw_list = [str(s).strip().lower() for s in raw_sections if str(s).strip()]
        else:
            raw_list = list(CANONICAL_SECTIONS)

        included = []
        for s in raw_list:
            canonical = SECTION_ALIASES.get(s, s)
            if canonical in CANONICAL_SECTIONS and canonical not in included:
                included.append(canonical)
    else:
        included = list(CANONICAL_SECTIONS)

    # Handle section order
    raw_order = customization.get("section_order") or customization.get("order")
    if raw_order is not None:
        if isinstance(raw_order, str):
            order_list = [s.strip().lower() for s in raw_order.split(",") if s.strip()]
        elif isinstance(raw_order, (list, tuple)):
            order_list = [str(s).strip().lower() for s in raw_order if str(s).strip()]
        else:
            order_list = list(CANONICAL_SECTIONS)

        order = []
        for s in order_list:
            canonical = SECTION_ALIASES.get(s, s)
            if canonical in included and canonical not in order:
                order.append(canonical)
        # Any included section not explicitly in order is appended at the end
        for s in included:
            if s not in order:
                order.append(s)
    else:
        order = [s for s in CANONICAL_SECTIONS if s in included]

    # Detect if actually customized from default
    is_customized = bool(
        student_name
        or target_role
        or set(included) != set(CANONICAL_SECTIONS)
        or order != [s for s in CANONICAL_SECTIONS if s in included]
        or customization.get("is_customized")
    )

    return {
        "student_name": student_name,
        "target_role": target_role,
        "included_sections": included,
        "section_order": order,
        "is_customized": is_customized,
    }


def _clean_slug(text: str) -> str:
    """Creates a filesystem-friendly name snippet from company or candidate text."""
    if not text:
        return "Report"
    # Replace whitespace and problematic characters with underscore
    cleaned = re.sub(r"[^\w\-.]+", "_", text.strip())
    return cleaned.strip("_") or "Report"


def _load_company_prep_data(company_name: str) -> Dict[str, Any]:
    """Safely loads interview rounds and preparation advice from data/companies.json if available."""
    if not company_name:
        return {}
    try:
        base_dir = getattr(config, "BASE_DIR", None) or os.getcwd()
        companies_file = Path(base_dir) / "data" / "companies.json"
        if companies_file.exists():
            with open(companies_file, "r", encoding="utf-8") as f:
                all_data = json.load(f)
                return all_data.get(company_name, {})
    except Exception as e:
        logger.debug(f"Unable to read company profiles from companies.json: {e}")
    return {}


def build_analysis_export_payload(
    analysis_record: Dict[str, Any],
    customization: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compiles a complete, normalized, and stable dictionary structure representing the analysis.
    This schema is versioned (1.0) and documented in README.md.
    Supports optional candidate name, target role, and section customizations (#761).
    """
    if not isinstance(analysis_record, dict):
        analysis_record = {}

    custom_cfg = normalize_report_customization(customization)

    analysis_id = str(
        analysis_record.get("analysis_id")
        or analysis_record.get("id")
        or "analysis_summary"
    ).strip()

    company_name = str(
        analysis_record.get("company_name")
        or "Target Recruiter"
    ).strip()

    target_role = str(
        custom_cfg["target_role"]
        or analysis_record.get("target_role")
        or analysis_record.get("role_target")
        or "Software Development Engineer"
    ).strip()

    resume_filename = str(
        analysis_record.get("resume_filename")
        or "Candidate_Resume.pdf"
    ).strip()

    created_at = str(
        analysis_record.get("created_at")
        or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    ).strip()

    results = analysis_record.get("results")
    if not isinstance(results, dict):
        results = {}

    resume_analysis = results.get("resume_analysis")
    if not isinstance(resume_analysis, dict):
        resume_analysis = {}

    job_match = results.get("job_match")
    if not isinstance(job_match, dict):
        job_match = {}

    # 1. Scores Extraction & Normalization
    try:
        ats_score = int(analysis_record.get("ats_score") or resume_analysis.get("ats_score", 0))
    except (ValueError, TypeError):
        ats_score = 0

    try:
        match_score = int(analysis_record.get("match_percentage") or job_match.get("match_percentage", 0))
    except (ValueError, TypeError):
        match_score = 0

    if ats_score >= 80:
        verdict = "High ATS Compatibility"
    elif ats_score >= 65:
        verdict = "Competitive Candidate"
    else:
        verdict = "Needs Structural Optimization"

    breakdown = resume_analysis.get("breakdown")
    if not isinstance(breakdown, dict):
        breakdown = {
            "contact_info": 100 if ats_score > 0 else 0,
            "formatting": max(0, min(100, ats_score)),
            "experience": max(0, min(100, ats_score)),
            "skills": max(0, min(100, match_score)),
        }

    scores = {
        "ats_score": ats_score,
        "job_match_score": match_score,
        "readiness_verdict": verdict,
        "breakdown": breakdown,
    }

    # 2. Executive Summary & Overall Recommendation
    summary = str(
        resume_analysis.get("summary")
        or results.get("summary")
        or "Campus placement resume analysis successfully compiled."
    ).strip()

    overall_recommendation = str(
        results.get("overall_recommendation_summary")
        or resume_analysis.get("overall_recommendation")
        or "Review prioritized skill gaps and practice STAR responses before interviews."
    ).strip()

    # 3. Suggestions Extraction
    strengths = [str(s).strip() for s in resume_analysis.get("strengths", []) if s]
    weaknesses = [str(w).strip() for w in resume_analysis.get("weaknesses", []) if w]
    grammar_suggestions = [str(g).strip() for g in resume_analysis.get("grammar_suggestions", []) if g]
    formatting_suggestions = [str(f).strip() for f in resume_analysis.get("formatting_suggestions", []) if f]
    resume_changes = [str(c).strip() for c in job_match.get("top_5_resume_changes", []) if c]

    # Additional recommendations if stored in results
    general_recommendations = []
    raw_recs = results.get("recommendations") or results.get("active_recommendations") or []
    if isinstance(raw_recs, list):
        for r in raw_recs:
            if isinstance(r, dict) and r.get("text"):
                general_recommendations.append(str(r["text"]).strip())
            elif isinstance(r, str) and r.strip():
                general_recommendations.append(r.strip())

    suggestions = {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "grammar_suggestions": grammar_suggestions,
        "formatting_suggestions": formatting_suggestions,
        "resume_changes": resume_changes,
        "general_recommendations": general_recommendations,
    }

    # 4. Skill Gaps Extraction
    skill_gaps_list = []
    raw_skill_gaps = results.get("skill_gap") or results.get("skill_gaps") or []
    if isinstance(raw_skill_gaps, list):
        for gap in raw_skill_gaps:
            if isinstance(gap, dict):
                skill_gaps_list.append({
                    "skill": str(gap.get("skill") or "Technical Competency").strip(),
                    "importance": str(gap.get("importance") or "High").strip(),
                    "learning_time": str(gap.get("learning_time") or gap.get("estimated_time") or "1-2 weeks").strip(),
                    "priority": str(gap.get("priority") or "Medium").strip(),
                    "learning_resource": str(gap.get("learning_resource") or "Documentation & Online Tutorials").strip(),
                    "project_suggestion": str(gap.get("project_suggestion") or "Implement a hands-on project demonstrating this skill").strip(),
                })

    # 5. Interview Tips & Questions Extraction
    interview_questions_collected = []
    raw_questions = results.get("interview_questions")
    if isinstance(raw_questions, dict):
        for category, q_list in raw_questions.items():
            if isinstance(q_list, list):
                for q in q_list:
                    if q and str(q).strip():
                        interview_questions_collected.append(f"[{category.capitalize()}] {str(q).strip()}")
    elif isinstance(raw_questions, list):
        for q in raw_questions:
            if q and str(q).strip():
                interview_questions_collected.append(str(q).strip())

    # Collect roadmap questions
    roadmap_list = results.get("learning_roadmap") or []
    if isinstance(roadmap_list, list):
        for week in roadmap_list:
            if isinstance(week, dict):
                w_title = str(week.get("week") or "Week").strip()
                for q in week.get("interview_questions", []):
                    if q and str(q).strip():
                        formatted_q = f"[{w_title}] {str(q).strip()}"
                        if formatted_q not in interview_questions_collected:
                            interview_questions_collected.append(formatted_q)

    # Company prep tips
    company_info = _load_company_prep_data(company_name)
    prep_tips = []
    if company_info.get("prep_tips") and isinstance(company_info["prep_tips"], list):
        prep_tips.extend([str(t).strip() for t in company_info["prep_tips"] if t])
    else:
        prep_tips.extend([
            "Structure behavioral responses using the STAR method (Situation, Task, Action, Result).",
            "State time and space complexity upfront before writing algorithmic solutions.",
            "Ask clarifying questions regarding edge cases, input constraints, and scale.",
            "Quantify project achievements and explain real-world architectural trade-offs.",
            f"Review recent engineering initiatives and core products at {company_name}."
        ])

    interview_rounds = []
    if company_info.get("technical_rounds") and isinstance(company_info["technical_rounds"], list):
        interview_rounds.extend([str(r).strip() for r in company_info["technical_rounds"] if r])
    if company_info.get("hr_rounds") and isinstance(company_info["hr_rounds"], list):
        interview_rounds.extend([str(r).strip() for r in company_info["hr_rounds"] if r])

    interview_tips = {
        "preparation_tips": prep_tips,
        "questions": interview_questions_collected,
        "interview_rounds": interview_rounds,
        "elevator_pitch_guidance": "Lead with your core technical competencies, cite a measurable project achievement, and articulate your direct alignment with the target company's mission.",
    }

    # 6. Learning Roadmap Normalization
    normalized_roadmap = []
    if isinstance(roadmap_list, list):
        for idx, w in enumerate(roadmap_list, 1):
            if isinstance(w, dict):
                normalized_roadmap.append({
                    "week": str(w.get("week") or f"Week {idx}").strip(),
                    "estimated_hours": w.get("estimated_hours") or 10,
                    "topics": [str(t).strip() for t in w.get("topics", []) if t],
                    "coding_practice": [str(c).strip() for c in w.get("coding_practice", []) if c],
                    "mini_projects": [str(p).strip() for p in w.get("mini_projects", []) if p],
                    "interview_questions": [str(q).strip() for q in w.get("interview_questions", []) if q],
                    "revision_tasks": [str(r).strip() for r in w.get("revision_tasks", []) if r],
                })

    # 7. Conflict Advisories
    advisories = []
    raw_conflicts = results.get("conflicts") or []
    if isinstance(raw_conflicts, list):
        for c in raw_conflicts:
            if isinstance(c, dict):
                advisories.append({
                    "conflict_type": str(c.get("conflict_type") or "Advisory").strip(),
                    "skill": str(c.get("skill") or "General").strip(),
                    "rule_description": str(c.get("rule_description") or "Contradiction flagged in automated analysis.").strip(),
                })

    # Construct the final schema
    payload = {
        "version": CURRENT_EXPORT_VERSION,
        "metadata": {
            "analysis_id": analysis_id,
            "company_name": company_name,
            "target_role": target_role,
            "resume_filename": resume_filename,
            "created_at": created_at,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        },
        "score": ats_score,  # Top-level score for immediate access
        "scores": scores,
        "summary": summary,
        "overall_recommendation": overall_recommendation,
        "suggestions": suggestions,
        "skill_gaps": skill_gaps_list,
        "interview_tips": interview_tips,
        "learning_roadmap": normalized_roadmap,
        "advisories": advisories,
    }

    if custom_cfg["student_name"]:
        payload["metadata"]["candidate_name"] = custom_cfg["student_name"]

    if custom_cfg["is_customized"]:
        payload["metadata"]["customization"] = {
            "included_sections": custom_cfg["included_sections"],
            "section_order": custom_cfg["section_order"],
        }
        included = set(custom_cfg["included_sections"])
        if "scores" not in included:
            payload.pop("score", None)
            payload.pop("scores", None)
        if "summary" not in included:
            payload.pop("summary", None)
        if "overall_recommendation" not in included:
            payload.pop("overall_recommendation", None)
            payload.pop("advisories", None)
        if "resume_analysis" not in included and "job_adjustments" not in included:
            payload.pop("suggestions", None)
        elif "resume_analysis" not in included and "job_adjustments" in included:
            payload["suggestions"] = {
                "strengths": [],
                "weaknesses": [],
                "grammar_suggestions": [],
                "formatting_suggestions": [],
                "resume_changes": suggestions.get("resume_changes", []),
                "general_recommendations": [],
            }
        elif "resume_analysis" in included and "job_adjustments" not in included:
            payload["suggestions"]["resume_changes"] = []
        if "skill_gaps" not in included:
            payload.pop("skill_gaps", None)
        if "interview_tips" not in included:
            payload.pop("interview_tips", None)
        if "learning_roadmap" not in included:
            payload.pop("learning_roadmap", None)

    return payload


def export_analysis_to_json(
    analysis_record: Dict[str, Any],
    customization: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Serializes the analysis record into a formatted, valid JSON string.
    Preserves all Unicode and non-English characters without ASCII escape sequences.
    Supports customization options (included_sections, candidate name, etc.) (#761).
    """
    payload = build_analysis_export_payload(analysis_record, customization=customization)
    return json.dumps(payload, indent=2, ensure_ascii=False)


def export_analysis_to_markdown(
    analysis_record: Dict[str, Any],
    customization: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generates a beautifully structured GitHub Flavored Markdown document from the analysis.
    Preserves all special characters, symbols, and non-English text verbatim.
    Supports student customization of candidate name, target role, included sections, and order (#761).
    """
    custom_cfg = normalize_report_customization(customization)
    payload = build_analysis_export_payload(analysis_record, customization=customization)
    meta = payload["metadata"]
    scores = payload.get("scores") or {}
    suggestions = payload.get("suggestions") or {}
    skill_gaps = payload.get("skill_gaps") or []
    interview_tips = payload.get("interview_tips") or {}
    roadmap = payload.get("learning_roadmap") or []
    advisories = payload.get("advisories") or []

    lines = []

    # Title & Metadata
    if custom_cfg["student_name"]:
        lines.append(f"# Placement Readiness Report: {meta['company_name']} — {custom_cfg['student_name']}")
        lines.append("")
        lines.append(f"- **Candidate Name:** {custom_cfg['student_name']}")
    else:
        lines.append(f"# Placement Readiness Report: {meta['company_name']}")
        lines.append("")

    lines.append(f"- **Target Role:** {meta['target_role']}")
    lines.append(f"- **Candidate Resume:** `{meta['resume_filename']}`")
    lines.append(f"- **Evaluation Date:** {meta['created_at']}")
    lines.append(f"- **Exported On:** {meta['exported_at']}")
    lines.append(f"- **Analysis ID:** `{meta['analysis_id']}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    # If NOT customized, maintain exact legacy output structure and section numbering
    if not custom_cfg["is_customized"]:
        # 1. Scores & Readiness
        lines.append("## 1. Readiness Scores & ATS Evaluation")
        lines.append("")
        lines.append("| Evaluation Metric | Score / Value | Status / Benchmark |")
        lines.append("| :--- | :--- | :--- |")
        lines.append(f"| **ATS Compatibility Score** | **{scores.get('ats_score', 0)}/100** | {scores.get('readiness_verdict', 'N/A')} |")
        lines.append(f"| **Job Role Match** | **{scores.get('job_match_score', 0)}%** | Target Profile Alignment |")
        lines.append("")

        if scores.get("breakdown"):
            lines.append("### Section Score Breakdown")
            lines.append("")
            for sec, val in scores["breakdown"].items():
                sec_name = sec.replace("_", " ").capitalize()
                lines.append(f"- **{sec_name}:** {val}/100")
            lines.append("")

        lines.append("---")
        lines.append("")

        # 2. Executive Summary & Recommendation
        lines.append("## 2. Executive Resume Summary & Recommendation")
        lines.append("")
        lines.append("### Executive Summary")
        lines.append(payload.get("summary", ""))
        lines.append("")
        lines.append("### Overall Placement Recommendation")
        lines.append(payload.get("overall_recommendation", ""))
        lines.append("")

        # Advisories if any
        if advisories:
            lines.append("### ⚠️ Placement Advisory: Contradictions Detected")
            lines.append("")
            for adv in advisories:
                lines.append(f"- **[{adv['conflict_type']}]** *{adv['skill']}*: {adv['rule_description']}")
            lines.append("")

        lines.append("---")
        lines.append("")

        # 3. Suggestions & Feedback
        lines.append("## 3. Resume Feedback & Suggestions")
        lines.append("")

        lines.append("### Strengths")
        if suggestions.get("strengths"):
            for s in suggestions["strengths"]:
                lines.append(f"- {s}")
        else:
            lines.append("*No specific strengths noted.*")
        lines.append("")

        lines.append("### Weaknesses & Areas for Improvement")
        if suggestions.get("weaknesses"):
            for w in suggestions["weaknesses"]:
                lines.append(f"- {w}")
        else:
            lines.append("*No critical weaknesses detected.*")
        lines.append("")

        lines.append("### Grammar & Formatting Suggestions")
        all_suggs = suggestions.get("grammar_suggestions", []) + suggestions.get("formatting_suggestions", [])
        if all_suggs:
            for sug in all_suggs:
                lines.append(f"- {sug}")
        else:
            lines.append("*Formatting and grammar adhere to standard placement guidelines.*")
        lines.append("")

        lines.append("### Top Recommended Resume Adjustments")
        if suggestions.get("resume_changes"):
            for idx, change in enumerate(suggestions["resume_changes"], 1):
                lines.append(f"{idx}. {change}")
        else:
            lines.append("*No critical resume adjustments required for this role.*")
        lines.append("")

        if suggestions.get("general_recommendations"):
            lines.append("### Actionable Recommendations")
            for rec in suggestions["general_recommendations"]:
                lines.append(f"- {rec}")
            lines.append("")

        lines.append("---")
        lines.append("")

        # 4. Skill Gaps Table
        lines.append("## 4. Skill Gap Assessment")
        lines.append("")
        lines.append("Skills required for the target placement role that were not identified in the uploaded resume:")
        lines.append("")
        if skill_gaps:
            lines.append("| Missing Skill | Importance | Estimated Time | Priority | Learning Resource & Project |")
            lines.append("| :--- | :--- | :--- | :--- | :--- |")
            for gap in skill_gaps:
                clean_skill = gap["skill"].replace("|", "\\|")
                clean_res = gap["learning_resource"].replace("|", "\\|")
                clean_proj = gap["project_suggestion"].replace("|", "\\|")
                res_proj = f"**Resource:** {clean_res}<br>**Project:** {clean_proj}"
                lines.append(f"| {clean_skill} | {gap['importance']} | {gap['learning_time']} | {gap['priority']} | {res_proj} |")
        else:
            lines.append("*No major technical skill gaps identified relative to the target role.*")
        lines.append("")

        lines.append("---")
        lines.append("")

        # 5. Interview Tips & Questions
        lines.append("## 5. Interview Tips & Preparation Guidance")
        lines.append("")

        lines.append("### Preparation Best Practices")
        for tip in interview_tips.get("preparation_tips", []):
            lines.append(f"- {tip}")
        lines.append("")

        if interview_tips.get("interview_rounds"):
            lines.append("### Typical Interview Rounds")
            for rnd in interview_tips["interview_rounds"]:
                lines.append(f"- {rnd}")
            lines.append("")

        lines.append("### Tailored Interview Questions")
        if interview_tips.get("questions"):
            for q in interview_tips["questions"]:
                lines.append(f"- {q}")
        else:
            lines.append("- Explain your core technical projects and space/time complexities of operations.")
            lines.append("- Describe a challenging bug you diagnosed and your resolution methodology.")
        lines.append("")

        lines.append(f"**Elevator Pitch Guidance:** {interview_tips.get('elevator_pitch_guidance', '')}")
        lines.append("")

        lines.append("---")
        lines.append("")

        # 6. Six-Week Roadmap
        lines.append("## 6. Six-Week Learning Roadmap")
        lines.append("")
        if roadmap:
            for w in roadmap:
                lines.append(f"### {w['week']} ({w['estimated_hours']} Hours)")
                topics_str = ", ".join(w["topics"]) if w.get("topics") else "None specified"
                coding_str = ", ".join(w["coding_practice"]) if w.get("coding_practice") else "None specified"
                projects_str = ", ".join(w["mini_projects"]) if w.get("mini_projects") else "None specified"
                revision_str = ", ".join(w["revision_tasks"]) if w.get("revision_tasks") else "None specified"

                lines.append(f"- **Topics to Cover:** {topics_str}")
                lines.append(f"- **Coding Practice:** {coding_str}")
                lines.append(f"- **Mini-Projects:** {projects_str}")
                if w.get("interview_questions"):
                    lines.append(f"- **Interview Questions:** {'; '.join(w['interview_questions'])}")
                lines.append(f"- **Revision Tasks:** {revision_str}")
                lines.append("")
        else:
            lines.append("*No customized learning roadmap available for this evaluation.*")
            lines.append("")

    else:
        # CUSTOMIZED RENDERING: Render only included sections in the chosen section_order
        included_set = set(custom_cfg["included_sections"])
        section_number = 1

        for sec in custom_cfg["section_order"]:
            if sec not in included_set:
                continue

            sec_title = SECTION_TITLES.get(sec, sec.replace("_", " ").title())

            if sec == "scores" and scores:
                lines.append(f"## {section_number}. {sec_title}")
                lines.append("")
                lines.append("| Evaluation Metric | Score / Value | Status / Benchmark |")
                lines.append("| :--- | :--- | :--- |")
                lines.append(f"| **ATS Compatibility Score** | **{scores.get('ats_score', 0)}/100** | {scores.get('readiness_verdict', 'N/A')} |")
                lines.append(f"| **Job Role Match** | **{scores.get('job_match_score', 0)}%** | Target Profile Alignment |")
                lines.append("")

                if scores.get("breakdown"):
                    lines.append("### Section Score Breakdown")
                    lines.append("")
                    for s_k, val in scores["breakdown"].items():
                        s_name = s_k.replace("_", " ").capitalize()
                        lines.append(f"- **{s_name}:** {val}/100")
                    lines.append("")
                lines.append("---")
                lines.append("")
                section_number += 1

            elif sec == "summary" and payload.get("summary"):
                lines.append(f"## {section_number}. {sec_title}")
                lines.append("")
                lines.append(payload["summary"])
                lines.append("")
                lines.append("---")
                lines.append("")
                section_number += 1

            elif sec == "overall_recommendation" and payload.get("overall_recommendation"):
                lines.append(f"## {section_number}. {sec_title}")
                lines.append("")
                lines.append(payload["overall_recommendation"])
                lines.append("")
                if advisories:
                    lines.append("### ⚠️ Placement Advisory: Contradictions Detected")
                    lines.append("")
                    for adv in advisories:
                        lines.append(f"- **[{adv['conflict_type']}]** *{adv['skill']}*: {adv['rule_description']}")
                    lines.append("")
                lines.append("---")
                lines.append("")
                section_number += 1

            elif sec == "resume_analysis" and suggestions:
                lines.append(f"## {section_number}. {sec_title}")
                lines.append("")
                lines.append("### Strengths")
                if suggestions.get("strengths"):
                    for s in suggestions["strengths"]:
                        lines.append(f"- {s}")
                else:
                    lines.append("*No specific strengths noted.*")
                lines.append("")

                lines.append("### Weaknesses & Areas for Improvement")
                if suggestions.get("weaknesses"):
                    for w in suggestions["weaknesses"]:
                        lines.append(f"- {w}")
                else:
                    lines.append("*No critical weaknesses detected.*")
                lines.append("")

                lines.append("### Grammar & Formatting Suggestions")
                all_suggs = suggestions.get("grammar_suggestions", []) + suggestions.get("formatting_suggestions", [])
                if all_suggs:
                    for sug in all_suggs:
                        lines.append(f"- {sug}")
                else:
                    lines.append("*Formatting and grammar adhere to standard placement guidelines.*")
                lines.append("")

                if suggestions.get("general_recommendations"):
                    lines.append("### Actionable Recommendations")
                    for rec in suggestions["general_recommendations"]:
                        lines.append(f"- {rec}")
                    lines.append("")

                lines.append("---")
                lines.append("")
                section_number += 1

            elif sec == "job_adjustments":
                lines.append(f"## {section_number}. {sec_title}")
                lines.append("")
                resume_changes = suggestions.get("resume_changes", [])
                if resume_changes:
                    for idx, change in enumerate(resume_changes, 1):
                        lines.append(f"{idx}. {change}")
                else:
                    lines.append("*No critical resume adjustments required for this role.*")
                lines.append("")
                lines.append("---")
                lines.append("")
                section_number += 1

            elif sec == "skill_gaps":
                lines.append(f"## {section_number}. {sec_title}")
                lines.append("")
                lines.append("Skills required for the target placement role that were not identified in the uploaded resume:")
                lines.append("")
                if skill_gaps:
                    lines.append("| Missing Skill | Importance | Estimated Time | Priority | Learning Resource & Project |")
                    lines.append("| :--- | :--- | :--- | :--- | :--- |")
                    for gap in skill_gaps:
                        clean_skill = gap["skill"].replace("|", "\\|")
                        clean_res = gap["learning_resource"].replace("|", "\\|")
                        clean_proj = gap["project_suggestion"].replace("|", "\\|")
                        res_proj = f"**Resource:** {clean_res}<br>**Project:** {clean_proj}"
                        lines.append(f"| {clean_skill} | {gap['importance']} | {gap['learning_time']} | {gap['priority']} | {res_proj} |")
                else:
                    lines.append("*No major technical skill gaps identified relative to the target role.*")
                lines.append("")
                lines.append("---")
                lines.append("")
                section_number += 1

            elif sec == "interview_tips":
                lines.append(f"## {section_number}. {sec_title}")
                lines.append("")
                lines.append("### Preparation Best Practices")
                for tip in interview_tips.get("preparation_tips", []):
                    lines.append(f"- {tip}")
                lines.append("")

                if interview_tips.get("interview_rounds"):
                    lines.append("### Typical Interview Rounds")
                    for rnd in interview_tips["interview_rounds"]:
                        lines.append(f"- {rnd}")
                    lines.append("")

                lines.append("### Tailored Interview Questions")
                if interview_tips.get("questions"):
                    for q in interview_tips["questions"]:
                        lines.append(f"- {q}")
                else:
                    lines.append("- Explain your core technical projects and space/time complexities of operations.")
                    lines.append("- Describe a challenging bug you diagnosed and your resolution methodology.")
                lines.append("")

                if interview_tips.get("elevator_pitch_guidance"):
                    lines.append(f"**Elevator Pitch Guidance:** {interview_tips['elevator_pitch_guidance']}")
                    lines.append("")
                lines.append("---")
                lines.append("")
                section_number += 1

            elif sec == "learning_roadmap":
                lines.append(f"## {section_number}. {sec_title}")
                lines.append("")
                if roadmap:
                    for w in roadmap:
                        lines.append(f"### {w['week']} ({w['estimated_hours']} Hours)")
                        topics_str = ", ".join(w["topics"]) if w.get("topics") else "None specified"
                        coding_str = ", ".join(w["coding_practice"]) if w.get("coding_practice") else "None specified"
                        projects_str = ", ".join(w["mini_projects"]) if w.get("mini_projects") else "None specified"
                        revision_str = ", ".join(w["revision_tasks"]) if w.get("revision_tasks") else "None specified"

                        lines.append(f"- **Topics to Cover:** {topics_str}")
                        lines.append(f"- **Coding Practice:** {coding_str}")
                        lines.append(f"- **Mini-Projects:** {projects_str}")
                        if w.get("interview_questions"):
                            lines.append(f"- **Interview Questions:** {'; '.join(w['interview_questions'])}")
                        lines.append(f"- **Revision Tasks:** {revision_str}")
                        lines.append("")
                else:
                    lines.append("*No customized learning roadmap available for this evaluation.*")
                    lines.append("")
                lines.append("---")
                lines.append("")
                section_number += 1

    lines.append("---")
    lines.append("*Report generated by AI Campus Placement Agent. Placement readiness scores and roadmaps represent guidance, not guarantees of employment.*")
    lines.append("")

    return "\n".join(lines)


def get_export_filename(
    analysis_record: Dict[str, Any],
    extension: str,
    customization: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Constructs a consistent, clean download filename.
    Example: Placement_Readiness_Report_Google_demo-sample-analysis.json
    """
    company = _clean_slug(analysis_record.get("company_name", "Placement"))
    aid = _clean_slug(str(analysis_record.get("analysis_id") or analysis_record.get("id") or "report"))
    ext = extension.lstrip(".")
    if customization and (customization.get("student_name") or customization.get("name")):
        cand_raw = customization.get("student_name") or customization.get("name")
        cand = _clean_slug(str(cand_raw))
        return f"Placement_Readiness_Report_{company}_{cand}_{aid}.{ext}"
    return f"Placement_Readiness_Report_{company}_{aid}.{ext}"
