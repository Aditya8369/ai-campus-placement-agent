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


def build_analysis_export_payload(analysis_record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compiles a complete, normalized, and stable dictionary structure representing the analysis.
    This schema is versioned (1.0) and documented in README.md.
    """
    if not isinstance(analysis_record, dict):
        analysis_record = {}

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
        analysis_record.get("target_role")
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

    return payload


def export_analysis_to_json(analysis_record: Dict[str, Any]) -> str:
    """
    Serializes the analysis record into a formatted, valid JSON string.
    Preserves all Unicode and non-English characters without ASCII escape sequences.
    """
    payload = build_analysis_export_payload(analysis_record)
    return json.dumps(payload, indent=2, ensure_ascii=False)


def export_analysis_to_markdown(analysis_record: Dict[str, Any]) -> str:
    """
    Generates a beautifully structured GitHub Flavored Markdown document from the analysis.
    Preserves all special characters, symbols, and non-English text verbatim.
    """
    payload = build_analysis_export_payload(analysis_record)
    meta = payload["metadata"]
    scores = payload["scores"]
    suggestions = payload["suggestions"]
    skill_gaps = payload["skill_gaps"]
    interview_tips = payload["interview_tips"]
    roadmap = payload["learning_roadmap"]
    advisories = payload["advisories"]

    lines = []

    # Title & Metadata
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

    # Scores & Readiness
    lines.append("## 1. Readiness Scores & ATS Evaluation")
    lines.append("")
    lines.append("| Evaluation Metric | Score / Value | Status / Benchmark |")
    lines.append("| :--- | :--- | :--- |")
    lines.append(f"| **ATS Compatibility Score** | **{scores['ats_score']}/100** | {scores['readiness_verdict']} |")
    lines.append(f"| **Job Role Match** | **{scores['job_match_score']}%** | Target Profile Alignment |")
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

    # Executive Summary & Recommendation
    lines.append("## 2. Executive Resume Summary & Recommendation")
    lines.append("")
    lines.append("### Executive Summary")
    lines.append(payload["summary"])
    lines.append("")
    lines.append("### Overall Placement Recommendation")
    lines.append(payload["overall_recommendation"])
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

    # Suggestions & Feedback
    lines.append("## 3. Resume Feedback & Suggestions")
    lines.append("")

    lines.append("### Strengths")
    if suggestions["strengths"]:
        for s in suggestions["strengths"]:
            lines.append(f"- {s}")
    else:
        lines.append("*No specific strengths noted.*")
    lines.append("")

    lines.append("### Weaknesses & Areas for Improvement")
    if suggestions["weaknesses"]:
        for w in suggestions["weaknesses"]:
            lines.append(f"- {w}")
    else:
        lines.append("*No critical weaknesses detected.*")
    lines.append("")

    lines.append("### Grammar & Formatting Suggestions")
    all_suggs = suggestions["grammar_suggestions"] + suggestions["formatting_suggestions"]
    if all_suggs:
        for sug in all_suggs:
            lines.append(f"- {sug}")
    else:
        lines.append("*Formatting and grammar adhere to standard placement guidelines.*")
    lines.append("")

    lines.append("### Top Recommended Resume Adjustments")
    if suggestions["resume_changes"]:
        for idx, change in enumerate(suggestions["resume_changes"], 1):
            lines.append(f"{idx}. {change}")
    else:
        lines.append("*No critical resume adjustments required for this role.*")
    lines.append("")

    if suggestions["general_recommendations"]:
        lines.append("### Actionable Recommendations")
        for rec in suggestions["general_recommendations"]:
            lines.append(f"- {rec}")
        lines.append("")

    lines.append("---")
    lines.append("")

    # Skill Gaps Table
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

    # Interview Tips & Questions
    lines.append("## 5. Interview Tips & Preparation Guidance")
    lines.append("")

    lines.append("### Preparation Best Practices")
    for tip in interview_tips["preparation_tips"]:
        lines.append(f"- {tip}")
    lines.append("")

    if interview_tips.get("interview_rounds"):
        lines.append("### Typical Interview Rounds")
        for rnd in interview_tips["interview_rounds"]:
            lines.append(f"- {rnd}")
        lines.append("")

    lines.append("### Tailored Interview Questions")
    if interview_tips["questions"]:
        for q in interview_tips["questions"]:
            lines.append(f"- {q}")
    else:
        lines.append("- Explain your core technical projects and space/time complexities of operations.")
        lines.append("- Describe a challenging bug you diagnosed and your resolution methodology.")
    lines.append("")

    lines.append(f"**Elevator Pitch Guidance:** {interview_tips['elevator_pitch_guidance']}")
    lines.append("")

    lines.append("---")
    lines.append("")

    # Six-Week Roadmap
    lines.append("## 6. Six-Week Learning Roadmap")
    lines.append("")
    if roadmap:
        for w in roadmap:
            lines.append(f"### {w['week']} ({w['estimated_hours']} Hours)")
            topics_str = ", ".join(w["topics"]) if w["topics"] else "None specified"
            coding_str = ", ".join(w["coding_practice"]) if w["coding_practice"] else "None specified"
            projects_str = ", ".join(w["mini_projects"]) if w["mini_projects"] else "None specified"
            revision_str = ", ".join(w["revision_tasks"]) if w["revision_tasks"] else "None specified"

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
    lines.append("*Report generated by AI Campus Placement Agent. Placement readiness scores and roadmaps represent guidance, not guarantees of employment.*")
    lines.append("")

    return "\n".join(lines)


def get_export_filename(analysis_record: Dict[str, Any], extension: str) -> str:
    """
    Constructs a consistent, clean download filename.
    Example: Placement_Readiness_Report_Google_demo-sample-analysis.json
    """
    company = _clean_slug(analysis_record.get("company_name", "Placement"))
    aid = _clean_slug(str(analysis_record.get("analysis_id") or analysis_record.get("id") or "report"))
    ext = extension.lstrip(".")
    return f"Placement_Readiness_Report_{company}_{aid}.{ext}"
