"""
Resume Keyword Highlighter & Job Match Optimization Service (#430)

Extracts top keywords from the job description (reusing JobMatchAgent output),
escapes extracted resume text to prevent XSS, highlights matched keywords
using whole-word, case-insensitive boundary matching, and provides a separate
structured breakdown of missing keywords mapped to suggested resume sections
(skills, projects, experience).
"""

import os
import re
import html
import logging
from typing import Dict, List, Tuple, Any, Optional

import config

logger = logging.getLogger(__name__)

# Section mapping taxonomy for missing keywords (#430)
EXPERIENCE_KEYWORDS = {
    "agile", "scrum", "kanban", "sprint", "jira", "leadership", "cross-functional",
    "collaboration", "collaborative", "mentoring", "stakeholder", "stakeholders",
    "communication", "client", "clients", "production", "on-call", "oncall",
    "site reliability", "code review", "code reviews", "ci/cd", "cicd", "devops",
    "incident", "incidents", "testing", "unit testing", "qa", "quality assurance",
    "sdlc", "waterfall", "team management", "project management", "release management"
}

PROJECTS_KEYWORDS = {
    "system design", "distributed systems", "distributed", "microservices", "microservice",
    "rest api", "rest apis", "restful", "restful api", "graphql", "websocket", "websockets",
    "full stack", "full-stack", "pipeline", "pipelines", "etl", "machine learning",
    "deep learning", "nlp", "computer vision", "cloud architecture", "event-driven",
    "message queue", "message broker", "kafka", "rabbitmq", "redis", "docker",
    "kubernetes", "aws", "gcp", "azure", "oauth", "jwt", "serverless", "mvc",
    "backend architecture", "frontend architecture", "scalable", "scalability",
    "database design", "nosql", "sharding", "caching", "data streaming"
}


def suggest_section_for_keyword(keyword: str) -> str:
    """
    Suggests the optimal resume section (skills, projects, experience)
    where a missing keyword or skill should be incorporated.

    Returns one of: 'skills', 'projects', 'experience'.
    """
    if not keyword or not isinstance(keyword, str):
        return "skills"

    clean_kw = keyword.strip().lower()

    # Check exact match or substring in experience keywords
    for exp_kw in EXPERIENCE_KEYWORDS:
        if clean_kw == exp_kw or exp_kw in clean_kw:
            return "experience"

    # Check exact match or substring in project keywords
    for proj_kw in PROJECTS_KEYWORDS:
        if clean_kw == proj_kw or proj_kw in clean_kw:
            return "projects"

    # Default to technical skills section for languages, tools, databases, frameworks
    return "skills"


def get_section_metadata(section: str) -> Dict[str, str]:
    """Returns user-facing label, badge styling, and actionable recommendation for a section."""
    section_normalized = (section or "skills").strip().lower()
    if section_normalized == "projects":
        return {
            "section": "projects",
            "label": "Projects",
            "badge_class": "bg-info-subtle text-info border border-info-subtle",
            "icon": "fa-diagram-project",
            "tip": "Demonstrate this keyword in a portfolio project bullet with quantifiable impact."
        }
    elif section_normalized == "experience":
        return {
            "section": "experience",
            "label": "Experience",
            "badge_class": "bg-success-subtle text-success border border-success-subtle",
            "icon": "fa-briefcase",
            "tip": "Incorporate into internship or work experience bullet points describing team workflows."
        }
    else:
        return {
            "section": "skills",
            "label": "Skills",
            "badge_class": "bg-primary-subtle text-primary border border-primary-subtle",
            "icon": "fa-code",
            "tip": "List directly in your Technical Skills section under Languages, Tools, or Frameworks."
        }


def extract_keywords_from_analysis(analysis_record: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """
    Extracts matched and missing keywords from JobMatchAgent output
    within the placement analysis record.

    Returns:
        Tuple of (matched_keywords, missing_keywords).
    """
    if not analysis_record or not isinstance(analysis_record, dict):
        return [], []

    results = analysis_record.get("results") or {}
    job_match = results.get("job_match") or results.get("job_compatibility") or {}

    raw_matched = job_match.get("matched_skills") or job_match.get("matching_skills") or []
    if isinstance(raw_matched, str):
        raw_matched = [s.strip() for s in raw_matched.split(",") if s.strip()]
    elif not isinstance(raw_matched, list):
        raw_matched = []

    raw_missing = job_match.get("missing_skills") or []
    if not raw_missing and results.get("skill_gap"):
        for gap in results["skill_gap"]:
            if isinstance(gap, dict):
                skill_name = gap.get("missing_skill") or gap.get("skill")
                if skill_name:
                    raw_missing.append(skill_name)
            elif isinstance(gap, str) and gap.strip():
                raw_missing.append(gap.strip())

    if isinstance(raw_missing, str):
        raw_missing = [s.strip() for s in raw_missing.split(",") if s.strip()]
    elif not isinstance(raw_missing, list):
        raw_missing = []

    # Clean and deduplicate case-insensitively
    clean_matched: List[str] = []
    seen_matched = set()
    for item in raw_matched:
        s = str(item).strip()
        if s and s.lower() not in seen_matched:
            clean_matched.append(s)
            seen_matched.add(s.lower())

    clean_missing: List[str] = []
    seen_missing = set()
    for item in raw_missing:
        s = str(item).strip()
        if s and s.lower() not in seen_missing and s.lower() not in seen_matched:
            clean_missing.append(s)
            seen_missing.add(s.lower())

    return clean_matched, clean_missing


def highlight_resume_keywords(
    resume_text: str,
    matched_keywords: Optional[List[str]]
) -> str:
    """
    Escapes resume text to neutralize HTML / script injection,
    and highlights matched keywords using case-insensitive, whole-word matching.

    Partial matches (e.g., 'Java' inside 'JavaScript') are NOT highlighted.
    Empty keyword cases safely return the escaped text.

    Args:
        resume_text: Raw extracted resume text string.
        matched_keywords: List of keywords to highlight.

    Returns:
        HTML string with safe text and <mark class="resume-keyword-matched"> tags.
    """
    if not resume_text:
        return ""

    escaped_text = html.escape(resume_text)

    if not matched_keywords:
        return escaped_text

    # Filter out empty or whitespace-only keywords
    clean_kws = [str(k).strip() for k in matched_keywords if k and str(k).strip()]
    if not clean_kws:
        return escaped_text

    # Deduplicate case-insensitively and sort descending by length to match longer phrases first
    seen = set()
    unique_kws: List[str] = []
    for k in sorted(clean_kws, key=lambda x: len(x), reverse=True):
        if k.lower() not in seen:
            seen.add(k.lower())
            unique_kws.append(k)

    patterns = []
    for k in unique_kws:
        # Escape the keyword for both HTML (to match escaped text) and regex
        esc_k = re.escape(html.escape(k))
        # Support flexible whitespace within multi-word keywords (e.g. 'REST   API')
        esc_k = re.sub(r"\\\s+", r"\\s+", esc_k)

        # Whole-word boundaries that work for words and symbol-ending tokens (e.g. 'C++', 'Node.js')
        lead = r"(?<![a-zA-Z0-9_])"
        trail = r"(?![a-zA-Z0-9_])"
        patterns.append(f"{lead}{esc_k}{trail}")

    if not patterns:
        return escaped_text

    combined_regex = re.compile("|".join(patterns), re.IGNORECASE)

    def _replace_match(match: re.Match) -> str:
        matched_content = match.group(0)
        return f'<mark class="resume-keyword-matched">{matched_content}</mark>'

    return combined_regex.sub(_replace_match, escaped_text)


def get_analysis_resume_text(analysis_record: Dict[str, Any]) -> str:
    """
    Retrieves the extracted resume text for an analysis record.
    Checks:
    1. analysis_record.get('resume_text')
    2. analysis_record['results'].get('extracted_resume_text')
    3. Stored resume files in config.UPLOAD_FOLDER
    4. Synthetic sample resume text for demo analyses
    5. Fallback reconstruction from analysis summary and strengths
    """
    if not analysis_record or not isinstance(analysis_record, dict):
        return ""

    # 1. Direct record property
    direct_text = analysis_record.get("resume_text")
    if direct_text and isinstance(direct_text, str) and direct_text.strip():
        return direct_text.strip()

    # 2. Inside results dictionary
    results = analysis_record.get("results") or {}
    if isinstance(results, dict):
        extracted_in_res = results.get("extracted_resume_text") or results.get("resume_text")
        if extracted_in_res and isinstance(extracted_in_res, str) and extracted_in_res.strip():
            return extracted_in_res.strip()

    analysis_id = analysis_record.get("id") or analysis_record.get("analysis_id") or ""

    # 3. Demo mode detection
    is_demo = bool(
        analysis_record.get("is_demo")
        or analysis_id in ("demo-sample-analysis", "demo_sample_analysis", "demo")
        or analysis_record.get("student_id") == "demo_visitor"
    )
    if is_demo:
        try:
            from utils.demo_mode import SYNTHETIC_SAMPLE_RESUME_TEXT
            return SYNTHETIC_SAMPLE_RESUME_TEXT.strip()
        except ImportError:
            pass

    # 4. Check upload folder on disk
    if analysis_id and os.path.exists(config.UPLOAD_FOLDER):
        for candidate_ext in ("_resume.txt", ".txt", ".pdf", ".docx"):
            candidate_path = os.path.join(config.UPLOAD_FOLDER, f"{analysis_id}{candidate_ext}")
            if os.path.exists(candidate_path):
                try:
                    from utils.pdf_reader import extract_text_from_file
                    text = extract_text_from_file(candidate_path)
                    if text and text.strip():
                        return text.strip()
                except Exception as e:
                    logger.warning(f"Could not read upload file {candidate_path}: {e}")

        # Check for files starting with analysis_id
        try:
            for fname in os.listdir(config.UPLOAD_FOLDER):
                if fname.startswith(f"{analysis_id}_") or fname.startswith(f"{analysis_id}."):
                    candidate_path = os.path.join(config.UPLOAD_FOLDER, fname)
                    try:
                        from utils.pdf_reader import extract_text_from_file
                        text = extract_text_from_file(candidate_path)
                        if text and text.strip():
                            return text.strip()
                    except Exception as e:
                        logger.warning(f"Could not read file {candidate_path}: {e}")
        except Exception as dir_err:
            logger.warning(f"Error scanning upload directory: {dir_err}")

    # 5. Check resume_filename in upload folder
    filename = analysis_record.get("resume_filename", "")
    if filename and os.path.exists(config.UPLOAD_FOLDER):
        direct_file_path = os.path.join(config.UPLOAD_FOLDER, filename)
        if os.path.exists(direct_file_path):
            try:
                from utils.pdf_reader import extract_text_from_file
                text = extract_text_from_file(direct_file_path)
                if text and text.strip():
                    return text.strip()
            except Exception as e:
                logger.warning(f"Could not read resume file {direct_file_path}: {e}")

    # 6. Fallback: Reconstruct resume text representation from analysis results
    resume_analysis = results.get("resume_analysis") or {}
    strengths = resume_analysis.get("strengths") or []
    summary = resume_analysis.get("summary") or ""
    company_name = analysis_record.get("company_name", "Target Company")
    if summary or strengths:
        return f"Professional Summary: {summary}\n\nKey Strengths & Competencies:\n- " + "\n- ".join(strengths)
    else:
        return f"Candidate placement profile evaluated for {company_name}."


def prepare_keyword_highlight_data(analysis_record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepares complete keyword matching and highlighting payload for the dashboard.
    Extracts resume text, highlights matched keywords safely, and maps missing
    keywords to their recommended resume sections.
    """
    raw_text = get_analysis_resume_text(analysis_record)
    matched_kws, missing_kws = extract_keywords_from_analysis(analysis_record)

    highlighted_html = highlight_resume_keywords(raw_text, matched_kws)
    plain_escaped_html = html.escape(raw_text)

    missing_with_sections = []
    for kw in missing_kws:
        suggested_sec = suggest_section_for_keyword(kw)
        sec_meta = get_section_metadata(suggested_sec)
        missing_with_sections.append({
            "keyword": kw,
            "suggested_section": suggested_sec,
            "section_label": sec_meta["label"],
            "badge_class": sec_meta["badge_class"],
            "icon": sec_meta["icon"],
            "tip": sec_meta["tip"],
        })

    # Group missing keywords by suggested section for structured tabs or display
    grouped_missing: Dict[str, List[Dict[str, Any]]] = {
        "skills": [],
        "projects": [],
        "experience": []
    }
    for item in missing_with_sections:
        sec = item["suggested_section"]
        if sec in grouped_missing:
            grouped_missing[sec].append(item)
        else:
            grouped_missing["skills"].append(item)

    return {
        "has_resume_text": bool(raw_text.strip()),
        "raw_resume_text": raw_text,
        "highlighted_resume_html": highlighted_html,
        "plain_escaped_resume_html": plain_escaped_html,
        "matched_keywords": matched_kws,
        "missing_keywords": missing_kws,
        "missing_keywords_with_sections": missing_with_sections,
        "grouped_missing": grouped_missing,
        "matched_count": len(matched_kws),
        "missing_count": len(missing_kws),
        "total_keywords": len(matched_kws) + len(missing_kws),
    }
