"""
ATS-Style Resume Scoring Service with Section-Wise Breakdown (#494).
===================================================================
Provides a transparent, deterministic ATS resume scoring model out of a fixed
100-point total with comprehensive section breakdowns and hygiene checks:

1. Section-Wise Scoring (Fixed 100 Total):
   - Contact Info (15 pts)
   - Professional Summary (10 pts)
   - Technical Skills (20 pts)
   - Work Experience / Internships (20 pts)
   - Projects & Portfolio (20 pts)
   - Education & Qualifications (15 pts)

2. Core Resume Basics Checks:
   - Action Verbs (dynamic power verbs in bullets)
   - Quantified Achievements (metrics, scale, percentages)
   - Consistent Dates (standardized month/year formats)
   - Resume Length (word count evaluation for campus placement)

3. Weakest Section Identification ("Hurts Most"):
   - Pinpoints which part of the resume hurts the score most.
   - Provides an actionable, tailored suggestion for each weak section.

4. Determinism Guarantee:
   - The same resume text ALWAYS yields the exact same score.
   - Uses zero random seeds, floating point drifts, or LLM variance for the base score.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Fixed section weights summing to exactly 100 points
SECTION_WEIGHTS: Dict[str, int] = {
    "contact_info": 15,
    "summary": 10,
    "skills": 20,
    "experience": 20,
    "projects": 20,
    "education": 15,
}

# Standard section display names
SECTION_TITLES: Dict[str, str] = {
    "contact_info": "Contact Information",
    "summary": "Professional Summary",
    "skills": "Technical Skills",
    "experience": "Work Experience & Internships",
    "projects": "Projects & Portfolio",
    "education": "Education & Qualifications",
}

# Extensive catalog of strong action verbs for resume bullets
ACTION_VERBS: Set[str] = {
    "accelerated", "accomplished", "achieved", "administered", "advanced", "advised",
    "analyzed", "architected", "authored", "automated", "built", "centralized",
    "championed", "collaborated", "compiled", "composed", "configured", "constructed",
    "coordinated", "crafted", "created", "customized", "debugged", "decreased",
    "delivered", "deployed", "designed", "developed", "devised", "diagnosed",
    "directed", "discovered", "documented", "drafted", "eliminated", "enabled",
    "engineered", "enhanced", "established", "evaluated", "executed", "expanded",
    "expedited", "fabricated", "facilitated", "formulated", "founded", "generated",
    "guided", "headed", "implemented", "improved", "increased", "initiated",
    "innovated", "inspected", "installed", "instituted", "integrated", "introduced",
    "invented", "investigated", "launched", "lead", "led", "maintained", "managed",
    "maximized", "measured", "mentored", "migrated", "minimized", "modeled",
    "monitored", "negotiated", "operated", "optimized", "orchestrated", "organized",
    "overhauled", "oversaw", "performed", "pioneered", "planned", "prepared",
    "produced", "programmed", "proposed", "quantified", "re-engineered", "rebuilt",
    "reconciled", "redesigned", "reduced", "refactored", "refined", "remodeled",
    "reorganized", "resolved", "restructured", "revamped", "reviewed", "revised",
    "scaled", "scheduled", "secured", "simplified", "spearheaded", "standardized",
    "streamlined", "strengthened", "structured", "supervised", "synthesized",
    "systematized", "tested", "tracked", "trained", "transformed", "troubleshot",
    "upgraded", "utilized", "validated"
}

# Common technical placement skills across modern software engineering
COMMON_TECH_SKILLS: Set[str] = {
    "python", "java", "c++", "c", "c#", "javascript", "typescript", "go", "golang",
    "rust", "sql", "html", "css", "react", "react.js", "angular", "vue", "node",
    "node.js", "express", "django", "flask", "fastapi", "spring", "spring boot",
    "docker", "kubernetes", "k8s", "aws", "gcp", "azure", "git", "github", "gitlab",
    "linux", "bash", "postgresql", "postgres", "mysql", "mongodb", "sqlite",
    "redis", "graphql", "rest", "rest api", "rest apis", "ci/cd", "tailwind",
    "bootstrap", "pandas", "numpy", "tensorflow", "pytorch", "scikit-learn"
}


# ==============================================================================
# SECTION PARSING & EXTRACTION
# ==============================================================================

def extract_resume_sections(resume_text: str) -> Dict[str, str]:
    """
    Splits resume text into standardized sections based on common headings.
    Returns a dictionary mapping section keys to their extracted text.
    """
    if not resume_text or not isinstance(resume_text, str):
        return {k: "" for k in SECTION_WEIGHTS}

    clean_text = resume_text.strip()

    patterns = [
        ("contact_info", re.compile(r"(?:^|\n)\s*(?:[#*_\-~=]+\s*)?(?:contact(?:\s+information)?|personal\s+details|personal\s+info)(?:\s*[:\n]|\s*$)", re.IGNORECASE)),
        ("summary", re.compile(r"(?:^|\n)\s*(?:[#*_\-~=]+\s*)?(?:professional\s+summary|executive\s+summary|career\s+objective|about\s+me|summary|objective|profile)(?:\s*[:\n]|\s*$)", re.IGNORECASE)),
        ("education", re.compile(r"(?:^|\n)\s*(?:[#*_\-~=]+\s*)?(?:education|academic\s+background|academics|qualifications|academic\s+credentials|degrees?)(?:\s*[:\n]|\s*$)", re.IGNORECASE)),
        ("skills", re.compile(r"(?:^|\n)\s*(?:[#*_\-~=]+\s*)?(?:technical\s+skills|skills\s+&\s+tools|core\s+competencies|skills|technologies|tech\s+stack|key\s+skills|competencies)(?:\s*[:\n]|\s*$)", re.IGNORECASE)),
        ("experience", re.compile(r"(?:^|\n)\s*(?:[#*_\-~=]+\s*)?(?:work\s+experience|professional\s+experience|experience|employment\s+history|internships|work\s+history|career\s+history)(?:\s*[:\n]|\s*$)", re.IGNORECASE)),
        ("projects", re.compile(r"(?:^|\n)\s*(?:[#*_\-~=]+\s*)?(?:academic\s+projects|key\s+projects|personal\s+projects|portfolio\s+projects|projects)(?:\s*[:\n]|\s*$)", re.IGNORECASE)),
    ]

    found_matches: List[Dict[str, Any]] = []
    for sec_key, pattern in patterns:
        for match in pattern.finditer(clean_text):
            found_matches.append({
                "key": sec_key,
                "start": match.start(),
                "end": match.end(),
            })

    found_matches.sort(key=lambda m: m["start"])

    # Eliminate overlapping headers
    filtered_matches: List[Dict[str, Any]] = []
    last_end = 0
    for m in found_matches:
        if m["start"] >= last_end:
            filtered_matches.append(m)
            last_end = m["end"]

    sections: Dict[str, str] = {
        "contact_info": "",
        "summary": "",
        "skills": "",
        "experience": "",
        "projects": "",
        "education": "",
    }

    if not filtered_matches:
        # Default header text as contact/summary
        sections["contact_info"] = clean_text[:min(len(clean_text), 400)]
        sections["summary"] = clean_text
        return sections

    # Text before the first matched heading typically contains contact info / summary
    first_start = filtered_matches[0]["start"]
    if first_start > 0:
        intro_chunk = clean_text[:first_start].strip()
        sections["contact_info"] = intro_chunk
        # If there's no dedicated summary heading, check if the intro acts as one
        if not any(m["key"] == "summary" for m in filtered_matches) and len(intro_chunk.split()) > 15:
            sections["summary"] = intro_chunk

    for idx, match_info in enumerate(filtered_matches):
        sec_key = match_info["key"]
        content_start = match_info["end"]
        content_end = filtered_matches[idx + 1]["start"] if idx + 1 < len(filtered_matches) else len(clean_text)
        chunk = clean_text[content_start:content_end].strip()

        if chunk:
            if sections[sec_key]:
                sections[sec_key] += "\n" + chunk
            else:
                sections[sec_key] = chunk

    # If contact_info was not explicitly parsed via a header, scan top 600 chars of entire text
    if not sections["contact_info"]:
        sections["contact_info"] = clean_text[:600]

    return sections


# ==============================================================================
# SECTION-SPECIFIC EVALUATORS
# ==============================================================================

def score_contact_info(text: str, full_resume: str) -> Dict[str, Any]:
    """
    Scores Contact Information (Max 15 pts):
    - Email address: 4 pts
    - Phone number: 4 pts
    - LinkedIn URL / profile: 4 pts
    - GitHub / Portfolio URL: 3 pts
    """
    search_scope = (text + "\n" + full_resume[:800]).strip()
    score = 0
    missing: List[str] = []
    details: List[str] = []

    # 1. Email check
    email_pat = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    has_email = bool(re.search(email_pat, search_scope))
    if has_email:
        score += 4
        details.append("Valid email address detected")
    else:
        missing.append("Email address")

    # 2. Phone number check
    phone_pat = r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}|\+?\d{10,13}"
    has_phone = bool(re.search(phone_pat, search_scope))
    if has_phone:
        score += 4
        details.append("Phone number detected")
    else:
        missing.append("Phone number")

    # 3. LinkedIn check
    linkedin_pat = r"linkedin\.com/in/[a-zA-Z0-9_\-]+|linkedin"
    has_linkedin = bool(re.search(linkedin_pat, search_scope, re.IGNORECASE))
    if has_linkedin:
        score += 4
        details.append("LinkedIn profile link detected")
    else:
        missing.append("LinkedIn profile link")

    # 4. GitHub or Portfolio check
    github_pat = r"github\.com/[a-zA-Z0-9_\-]+|gitlab\.com|[a-zA-Z0-9_\-]+\.(?:github\.io|dev|tech|me|portfolio)|github"
    has_github = bool(re.search(github_pat, search_scope, re.IGNORECASE))
    if has_github:
        score += 3
        details.append("GitHub / portfolio link detected")
    else:
        missing.append("GitHub or personal portfolio link")

    max_score = SECTION_WEIGHTS["contact_info"]

    if missing:
        suggestion = f"Add {', '.join(missing)} in the header to ensure recruiters and ATS can easily connect."
    else:
        suggestion = "Complete contact information present with active links."

    return {
        "title": SECTION_TITLES["contact_info"],
        "score": score,
        "max_score": max_score,
        "lost_points": max_score - score,
        "earned_percentage": round((score / max_score) * 100),
        "status": "Strong" if score >= 12 else ("Fair" if score >= 8 else "Weak"),
        "is_weak": score < 12,
        "details": details,
        "missing": missing,
        "suggestion": suggestion,
    }


def score_summary(text: str, full_resume: str) -> Dict[str, Any]:
    """
    Scores Professional Summary / Objective (Max 10 pts):
    - Section present: 3 pts
    - Word count substance (20 - 120 words): 3 pts
    - Role focus / career intent: 2 pts
    - Highlights key technical domains/experience: 2 pts
    """
    score = 0
    details: List[str] = []
    content = text.strip()

    max_score = SECTION_WEIGHTS["summary"]

    if not content:
        # Check if introductory paragraph exists in full resume
        first_lines = "\n".join([line for line in full_resume.split("\n")[:8] if "@" not in line and "http" not in line]).strip()
        if len(first_lines.split()) >= 15:
            content = first_lines

    if not content:
        return {
            "title": SECTION_TITLES["summary"],
            "score": 0,
            "max_score": max_score,
            "lost_points": max_score,
            "earned_percentage": 0,
            "status": "Weak",
            "is_weak": True,
            "details": ["No professional summary or objective statement detected"],
            "suggestion": "Add a 2-3 sentence summary defining your target role, technical strengths, and graduation background.",
        }

    # 1. Section present
    score += 3
    details.append("Professional summary section present")

    # 2. Length check
    words = content.split()
    word_count = len(words)
    if 20 <= word_count <= 120:
        score += 3
        details.append(f"Ideal concise summary length ({word_count} words)")
    elif 10 <= word_count < 20 or 120 < word_count <= 180:
        score += 2
        details.append(f"Acceptable summary length ({word_count} words)")
    else:
        score += 1
        details.append(f"Summary length could be optimized ({word_count} words)")

    # 3. Role focus & career intent
    role_intent_pat = r"\b(?:software\s+(?:engineer|developer)|full\s*stack|backend|frontend|data\s+analyst|student|graduate|aspiring|seeking|engineer|developer|computer\s+science)\b"
    if re.search(role_intent_pat, content, re.IGNORECASE):
        score += 2
        details.append("Clear career objective or role focus identified")

    # 4. Technical / Domain highlights
    has_skills_mention = any(skill in content.lower() for skill in COMMON_TECH_SKILLS)
    if has_skills_mention or re.search(r"\b(?:technolog|scalable|systems|algorithms|web|cloud|database|pipeline)\b", content, re.IGNORECASE):
        score += 2
        details.append("Highlights key technical competency domains")

    if score < 7:
        suggestion = "Refine your summary to clearly state your target engineering role, key technical stack, and verifiable value proposition."
    elif score < max_score:
        suggestion = "Condense your summary to 2-3 high-impact lines featuring your primary programming language and target placement role."
    else:
        suggestion = "Well-crafted summary effectively communicating role alignment and key competencies."

    return {
        "title": SECTION_TITLES["summary"],
        "score": score,
        "max_score": max_score,
        "lost_points": max_score - score,
        "earned_percentage": round((score / max_score) * 100),
        "status": "Strong" if score >= 8 else ("Fair" if score >= 5 else "Weak"),
        "is_weak": score < 8,
        "details": details,
        "suggestion": suggestion,
    }


def score_skills(text: str, full_resume: str) -> Dict[str, Any]:
    """
    Scores Technical Skills (Max 20 pts):
    - Section presence: 4 pts
    - Breadth of technical skills: up to 8 pts
    - Categorization (Languages, Frameworks, Tools, etc.): 4 pts
    - Stack diversity (languages + databases/frameworks/cloud): 4 pts
    """
    score = 0
    details: List[str] = []
    content = text.strip() if text.strip() else full_resume

    max_score = SECTION_WEIGHTS["skills"]

    # 1. Section presence
    has_explicit_section = bool(text.strip())
    if has_explicit_section:
        score += 4
        details.append("Dedicated technical skills section detected")
    else:
        # Check if skills are present across document
        details.append("Skills evaluated from general resume context")

    # 2. Count detected skills
    found_skills: Set[str] = set()
    text_lower = content.lower()
    for s in COMMON_TECH_SKILLS:
        pattern = r"(?:^|\s|\b|[,\(])" + re.escape(s) + r"(?:\b|\s|[,\)])"
        if re.search(pattern, text_lower):
            found_skills.add(s)

    skill_count = len(found_skills)
    if skill_count >= 10:
        score += 8
        details.append(f"Strong skill breadth ({skill_count} relevant technical skills)")
    elif skill_count >= 6:
        score += 6
        details.append(f"Good skill count ({skill_count} relevant technical skills)")
    elif skill_count >= 3:
        score += 4
        details.append(f"Basic skill count ({skill_count} technical skills detected)")
    elif skill_count >= 1:
        score += 2
        details.append(f"Limited skill coverage ({skill_count} technical skill detected)")
    else:
        details.append("No common placement technical skills clearly detected")

    # 3. Categorization check
    category_pat = r"\b(?:languages|frameworks|developer\s+tools|tools|databases|cloud|web\s+technologies|libraries)\s*:"
    has_categories = bool(re.search(category_pat, text_lower))
    if has_categories:
        score += 4
        details.append("Skills cleanly categorized with subheadings (Languages, Tools, etc.)")
    elif has_explicit_section and ("," in text or "|" in text):
        score += 2
        details.append("Skills listed cleanly with delimiters")

    # 4. Stack diversity
    has_lang = any(l in found_skills for l in ["python", "java", "c++", "c", "c#", "javascript", "typescript", "go"])
    has_db_or_tool = any(d in found_skills for d in ["sql", "postgresql", "mysql", "mongodb", "docker", "git", "aws", "react", "node"])
    if has_lang and has_db_or_tool:
        score += 4
        details.append("Diverse tech stack (Core Languages + Databases/Tools/Frameworks)")
    elif has_lang or has_db_or_tool:
        score += 2
        details.append("Partial tech stack diversity")

    score = min(max_score, score)

    if score < 14:
        suggestion = "Group your technical skills into clear categories (e.g. Languages, Frameworks, Developer Tools, Databases) and include at least 8-10 core skills."
    elif score < max_score:
        suggestion = "Enhance skill section ATS readability by organizing skills into categorized bullets (Languages, Frameworks, Tools)."
    else:
        suggestion = "Robust technical skill section with excellent breadth and clear structural categorization."

    return {
        "title": SECTION_TITLES["skills"],
        "score": score,
        "max_score": max_score,
        "lost_points": max_score - score,
        "earned_percentage": round((score / max_score) * 100),
        "status": "Strong" if score >= 16 else ("Fair" if score >= 11 else "Weak"),
        "is_weak": score < 16,
        "details": details,
        "skills_detected_count": skill_count,
        "suggestion": suggestion,
    }


def score_experience(text: str, full_resume: str) -> Dict[str, Any]:
    """
    Scores Work Experience / Internships (Max 20 pts):
    - Section presence: 4 pts
    - Role title & organization: 4 pts
    - Bullet points with action verbs: 5 pts
    - Quantified achievements / metrics: 4 pts
    - Date ranges present: 3 pts
    """
    score = 0
    details: List[str] = []
    content = text.strip()

    max_score = SECTION_WEIGHTS["experience"]

    if not content:
        # Check if candidate is a fresher without formal corporate experience
        # If they have extensive projects in full_resume, provide constructive suggestion
        return {
            "title": SECTION_TITLES["experience"],
            "score": 0,
            "max_score": max_score,
            "lost_points": max_score,
            "earned_percentage": 0,
            "status": "Weak",
            "is_weak": True,
            "details": ["No work experience or internship section detected"],
            "suggestion": "Add an Experience or Internships section. Even for freshers, include virtual internships, open-source contributions, or campus leadership roles.",
        }

    # 1. Section presence
    score += 4
    details.append("Work experience section present")

    # 2. Role Title & Organization
    role_pat = r"\b(?:intern|internship|software\s+engineer|developer|analyst|trainee|associate|lead|contributor|assistant)\b"
    has_role = bool(re.search(role_pat, content, re.IGNORECASE))
    if has_role:
        score += 4
        details.append("Professional role title identified")
    else:
        score += 2
        details.append("Experience entries present without standard role titles")

    # 3. Action verbs in experience
    exp_words = set(re.findall(r"\b[a-z]{3,}\b", content.lower()))
    found_verbs = exp_words.intersection(ACTION_VERBS)
    if len(found_verbs) >= 3:
        score += 5
        details.append(f"Strong action verbs used in experience descriptions ({len(found_verbs)} found)")
    elif len(found_verbs) >= 1:
        score += 3
        details.append(f"Some action verbs present ({len(found_verbs)} found)")
    else:
        details.append("Lacks strong action verbs in bullet points")

    # 4. Quantified achievements
    metric_pat = r"\b\d+(?:\.\d+)?%|\b\d+\+?\s*(?:users|requests|ms|seconds|minutes|hours|qps|x|k|m|projects|clients|students|downloads)\b|\b[2-9]x\b|\$\d+"
    metrics = re.findall(metric_pat, content, re.IGNORECASE)
    if len(metrics) >= 2:
        score += 4
        details.append(f"Quantified achievements and metrics included ({len(metrics)} found)")
    elif len(metrics) == 1:
        score += 2
        details.append("Contains 1 quantified metric")
    else:
        details.append("Missing quantifiable outcomes or metrics")

    # 5. Date ranges
    date_pat = r"\b(?:\d{4}|present|current|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b"
    has_dates = bool(re.search(date_pat, content, re.IGNORECASE))
    if has_dates:
        score += 3
        details.append("Timeline and employment duration specified")

    score = min(max_score, score)

    if score < 13:
        suggestion = "Rewrite experience bullets to start with dynamic action verbs and include measurable results (e.g., 'Optimized pipeline throughput by 30%')."
    elif score < max_score:
        suggestion = "Add more quantitative metrics and specific performance outcomes to your work experience bullets."
    else:
        suggestion = "Compelling experience section with strong action verbs and quantified impact."

    return {
        "title": SECTION_TITLES["experience"],
        "score": score,
        "max_score": max_score,
        "lost_points": max_score - score,
        "earned_percentage": round((score / max_score) * 100),
        "status": "Strong" if score >= 15 else ("Fair" if score >= 10 else "Weak"),
        "is_weak": score < 15,
        "details": details,
        "suggestion": suggestion,
    }


def score_projects(text: str, full_resume: str) -> Dict[str, Any]:
    """
    Scores Projects & Portfolio (Max 20 pts):
    - Section presence: 4 pts
    - At least 2 distinct projects: 5 pts (1 project: 2 pts)
    - Technologies mentioned per project: 4 pts
    - Action verbs in implementation bullets: 4 pts
    - Measurable outcomes or repo/live links: 3 pts
    """
    score = 0
    details: List[str] = []
    content = text.strip()

    max_score = SECTION_WEIGHTS["projects"]

    if not content:
        return {
            "title": SECTION_TITLES["projects"],
            "score": 0,
            "max_score": max_score,
            "lost_points": max_score,
            "earned_percentage": 0,
            "status": "Weak",
            "is_weak": True,
            "details": ["No projects section detected"],
            "suggestion": "Add a dedicated Projects section with at least 2 significant software projects showing practical architecture skills.",
        }

    # 1. Section presence
    score += 4
    details.append("Projects section present")

    # 2. Number of projects
    # Detect project titles separated by headers, bullets, or pipe separators
    project_indicators = re.findall(r"(?:^|\n)\s*(?:[•\-*]|\d+\.|\bproject\s*\d*|\b[A-Z][A-Za-z0-9\s]{3,30}\s*\|)", content)
    # Also check tech delimiter lines (e.g. "E-Commerce App | React, Node.js")
    pipe_titles = re.findall(r"[A-Za-z0-9\s]{3,35}\s*\|\s*[A-Za-z0-9,\s]+", content)
    project_count = max(len(pipe_titles), len(project_indicators) // 2)

    if project_count >= 2 or len(content.split("\n\n")) >= 2 or len(content.split("\n")) >= 6:
        score += 5
        details.append("Multiple distinct projects documented")
    elif len(content.strip()) > 50:
        score += 2
        details.append("Single project documented; adding a second is recommended")

    # 3. Technologies mentioned
    tech_matches = [s for s in COMMON_TECH_SKILLS if s in content.lower()]
    if len(tech_matches) >= 3:
        score += 4
        details.append(f"Explicit tech stack associated with projects ({len(tech_matches)} technologies)")
    elif len(tech_matches) >= 1:
        score += 2
        details.append("Basic technology stack mentioned")

    # 4. Action verbs in project bullets
    proj_words = set(re.findall(r"\b[a-z]{3,}\b", content.lower()))
    found_verbs = proj_words.intersection(ACTION_VERBS)
    if len(found_verbs) >= 3:
        score += 4
        details.append(f"Active implementation verbs in project descriptions ({len(found_verbs)} found)")
    elif len(found_verbs) >= 1:
        score += 2
        details.append("Some action verbs present in project details")

    # 5. Measurable outcomes or repo/live links
    has_links = bool(re.search(r"github\.com|http|gitlab\.com|demo|deployed|live", content, re.IGNORECASE))
    has_metrics = bool(re.search(r"\b\d+%\b|\b\d+\+?\s*(?:users|ms|stars|requests|downloads|fps)\b", content, re.IGNORECASE))
    if has_links and has_metrics:
        score += 3
        details.append("Project includes both links and measurable impact")
    elif has_links or has_metrics:
        score += 2
        details.append("Project includes repository links or measurable outcomes")

    score = min(max_score, score)

    if score < 14:
        suggestion = "Detail at least 2 key projects with clear titles, full tech stacks, implementation action verbs, and quantifiable outcomes or live links."
    elif score < max_score:
        suggestion = "Include live demo or GitHub repository URLs and state measurable performance improvements for each project."
    else:
        suggestion = "Outstanding project section showcasing practical application, technology stacks, and tangible results."

    return {
        "title": SECTION_TITLES["projects"],
        "score": score,
        "max_score": max_score,
        "lost_points": max_score - score,
        "earned_percentage": round((score / max_score) * 100),
        "status": "Strong" if score >= 15 else ("Fair" if score >= 10 else "Weak"),
        "is_weak": score < 15,
        "details": details,
        "suggestion": suggestion,
    }


def score_education(text: str, full_resume: str) -> Dict[str, Any]:
    """
    Scores Education & Qualifications (Max 15 pts):
    - Section presence: 4 pts
    - Degree specified (B.Tech, B.S., M.S., etc.): 4 pts
    - University / College name: 4 pts
    - Graduation year and/or GPA/CGPA: 3 pts
    """
    score = 0
    details: List[str] = []
    content = text.strip() if text.strip() else full_resume

    max_score = SECTION_WEIGHTS["education"]

    has_explicit = bool(text.strip())
    if has_explicit:
        score += 4
        details.append("Dedicated education section present")
    else:
        details.append("Education evaluated from resume text")

    # 2. Degree check
    degree_pat = r"\b(?:bachelor|b\.tech|b\.e|bca|bsc|bs|master|m\.tech|mca|msc|ms|phd|diploma|degree|secondary)\b"
    has_degree = bool(re.search(degree_pat, content, re.IGNORECASE))
    if has_degree:
        score += 4
        details.append("Academic degree or credential clearly specified")
    else:
        missing_degree = True

    # 3. University / College name check
    uni_pat = r"\b(?:university|college|institute|school|academy|iit|nit|iiit|bits)\b"
    has_uni = bool(re.search(uni_pat, content, re.IGNORECASE))
    if has_uni:
        score += 4
        details.append("Educational institution name detected")

    # 4. Graduation year and/or GPA/CGPA
    year_pat = r"\b(?:201[5-9]|202[0-9]|2030)\b"
    gpa_pat = r"\b(?:cgpa|gpa|\b\d\.\d{1,2}(?:/4\.0|/10)?|\b(?:[6-9]\d(?:\.\d+)?%))\b"
    has_year = bool(re.search(year_pat, content, re.IGNORECASE))
    has_gpa = bool(re.search(gpa_pat, content, re.IGNORECASE))

    if has_year and has_gpa:
        score += 3
        details.append("Both graduation year and GPA/CGPA detected")
    elif has_year or has_gpa:
        score += 2
        details.append("Graduation year or GPA specified")

    score = min(max_score, score)

    if score < 11:
        suggestion = "List your official degree title (e.g. B.Tech in CS), university name, expected graduation year, and current CGPA/percentage."
    elif score < max_score:
        suggestion = "Ensure your graduation year and CGPA are clearly formatted for automated ATS parsing."
    else:
        suggestion = "Complete education credentials with degree, institution, timeline, and academic standing."

    return {
        "title": SECTION_TITLES["education"],
        "score": score,
        "max_score": max_score,
        "lost_points": max_score - score,
        "earned_percentage": round((score / max_score) * 100),
        "status": "Strong" if score >= 12 else ("Fair" if score >= 8 else "Weak"),
        "is_weak": score < 12,
        "details": details,
        "suggestion": suggestion,
    }


# ==============================================================================
# BASICS CHECKS (Action Verbs, Metrics, Dates, Length)
# ==============================================================================

def evaluate_basics_checks(resume_text: str) -> Dict[str, Any]:
    """
    Evaluates fundamental resume hygiene:
    1. Action Verbs: Presence of active verbs in descriptions
    2. Quantified Achievements: Metrics, numbers, and scale indicators
    3. Consistent Dates: Clear, consistent employment and education timelines
    4. Resume Length: Word count within 250-900 words
    """
    if not resume_text or not isinstance(resume_text, str):
        return {
            "action_verbs": {"passed": False, "count": 0, "sample": [], "suggestion": "Add dynamic action verbs to bullet points."},
            "quantified_achievements": {"passed": False, "count": 0, "sample": [], "suggestion": "Include metrics and percentages."},
            "consistent_dates": {"passed": False, "count": 0, "suggestion": "Specify timeline dates consistently."},
            "resume_length": {"passed": False, "word_count": 0, "verdict": "Empty", "suggestion": "Provide readable resume content."},
        }

    clean_text = resume_text.strip()
    words = clean_text.split()
    word_count = len(words)

    # 1. Action Verbs
    lowered_tokens = set(re.findall(r"\b[a-z]{3,}\b", clean_text.lower()))
    detected_verbs = sorted(list(lowered_tokens.intersection(ACTION_VERBS)))
    verb_count = len(detected_verbs)
    verbs_passed = verb_count >= 4

    if verbs_passed:
        verbs_sugg = f"Strong action-oriented phrasing ({verb_count} distinct action verbs detected)."
    elif verb_count >= 1:
        verbs_sugg = "Increase the variety of action verbs at the beginning of bullet points (e.g., Architected, Optimized, Spearheaded)."
    else:
        verbs_sugg = "Begin all experience and project bullet points with powerful action verbs instead of passive phrases."

    # 2. Quantified Achievements
    metric_pat = r"\b\d+(?:\.\d+)?%|\b\d+\+?\s*(?:users|requests|ms|seconds|minutes|hours|qps|x|k|m|projects|clients|students|downloads)\b|\b[2-9]x\b|\$\d+"
    metric_matches = re.findall(metric_pat, clean_text, re.IGNORECASE)
    metrics_count = len(metric_matches)
    metrics_passed = metrics_count >= 2

    if metrics_passed:
        metrics_sugg = f"Effective use of quantifiable evidence ({metrics_count} metrics identified)."
    elif metrics_count == 1:
        metrics_sugg = "Add additional numbers, percentages, or scale indicators to quantify the impact of your work."
    else:
        metrics_sugg = "Quantify your achievements with numbers, percentages, latency reductions, or user scale (e.g., 'reduced load times by 25%')."

    # 3. Consistent Dates
    month_year_pat = r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}\b"
    year_range_pat = r"\b\d{4}\s*[-–—]\s*(?:\d{4}|present|current)\b"
    slash_date_pat = r"\b\d{1,2}/\d{4}\b"

    month_matches = re.findall(month_year_pat, clean_text, re.IGNORECASE)
    range_matches = re.findall(year_range_pat, clean_text, re.IGNORECASE)
    slash_matches = re.findall(slash_date_pat, clean_text)

    total_date_indicators = len(month_matches) + len(range_matches) + len(slash_matches)
    # Check consistency: don't heavily mix incompatible formats
    is_consistent = not (len(month_matches) > 1 and len(slash_matches) > 1)
    dates_passed = total_date_indicators >= 2 and is_consistent

    if dates_passed:
        dates_sugg = "Timeline dates are clearly stated with consistent formatting."
    elif total_date_indicators >= 1:
        dates_sugg = "Standardize date notations across all sections to a single format (e.g., 'May 2023 – Aug 2023')."
    else:
        dates_sugg = "Add timeline dates to education and internship entries to give recruiters clear career chronology."

    # 4. Resume Length
    if 250 <= word_count <= 850:
        length_passed = True
        length_verdict = f"Optimal 1-Page Length ({word_count} words)"
        length_sugg = "Resume length is well-calibrated for campus recruitment."
    elif 150 <= word_count < 250:
        length_passed = False
        length_verdict = f"Slightly Brief ({word_count} words)"
        length_sugg = "Your resume is slightly short. Elaborate further on project responsibilities, technologies, and achievements."
    elif 850 < word_count <= 1200:
        length_passed = True
        length_verdict = f"2-Page Length ({word_count} words)"
        length_sugg = "Resume spans ~2 pages. Ensure all bullet points highlight high-priority placement accomplishments."
    elif word_count > 1200:
        length_passed = False
        length_verdict = f"Too Verbose ({word_count} words)"
        length_sugg = "Resume exceeds 1,200 words. Condense descriptions and remove redundant details to keep it concise."
    else:
        length_passed = False
        length_verdict = f"Incomplete ({word_count} words)"
        length_sugg = "Resume is too brief to effectively showcase your engineering background."

    return {
        "action_verbs": {
            "title": "Action Verbs",
            "passed": verbs_passed,
            "status": "Pass" if verbs_passed else "Needs Improvement",
            "count": verb_count,
            "sample": detected_verbs[:6],
            "suggestion": verbs_sugg,
        },
        "quantified_achievements": {
            "title": "Quantified Achievements",
            "passed": metrics_passed,
            "status": "Pass" if metrics_passed else "Needs Improvement",
            "count": metrics_count,
            "sample": metric_matches[:4],
            "suggestion": metrics_sugg,
        },
        "consistent_dates": {
            "title": "Consistent Dates",
            "passed": dates_passed,
            "status": "Pass" if dates_passed else "Needs Improvement",
            "date_count": total_date_indicators,
            "suggestion": dates_sugg,
        },
        "resume_length": {
            "title": "Resume Length",
            "passed": length_passed,
            "status": "Pass" if length_passed else "Needs Improvement",
            "word_count": word_count,
            "verdict": length_verdict,
            "suggestion": length_sugg,
        },
    }


# ==============================================================================
# MAIN SCORING ENGINE
# ==============================================================================

def evaluate_resume_ats_score(resume_text: str) -> Dict[str, Any]:
    """
    Computes a 100% deterministic ATS resume score and section-wise breakdown (#494).

    Guarantees:
    - Same input text ALWAYS produces the exact same score.
    - Zero random seeds or nondeterministic LLM variance.
    - Explicit section breakdown out of 100 points total.
    - Automatic detection of the section hurting the score most.
    - Actionable short suggestions for each weak section.
    """
    if not resume_text or not isinstance(resume_text, str) or not resume_text.strip():
        # Default zero-state for empty resume text
        empty_sections: Dict[str, Any] = {}
        for key, weight in SECTION_WEIGHTS.items():
            empty_sections[key] = {
                "title": SECTION_TITLES[key],
                "score": 0,
                "max_score": weight,
                "lost_points": weight,
                "earned_percentage": 0,
                "status": "Weak",
                "is_weak": True,
                "suggestion": f"Add the {SECTION_TITLES[key]} section.",
            }
        return {
            "total_score": 0,
            "rating": "Needs Rework",
            "sections": empty_sections,
            "hurts_most": {
                "section_key": "experience",
                "title": SECTION_TITLES["experience"],
                "score": 0,
                "max_score": 20,
                "lost_points": 20,
                "percentage_earned": 0,
                "suggestion": "Add complete resume sections with projects, skills, and education.",
                "impact_message": "Empty resume provides zero candidate evidence.",
            },
            "basics": evaluate_basics_checks(""),
            "weak_sections_count": len(SECTION_WEIGHTS),
            "recommendations": ["Upload a readable resume with complete student credentials."],
            "is_deterministic": True,
        }

    # 1. Parse sections cleanly
    parsed = extract_resume_sections(resume_text)

    # 2. Evaluate each section deterministically
    contact_res = score_contact_info(parsed.get("contact_info", ""), resume_text)
    summary_res = score_summary(parsed.get("summary", ""), resume_text)
    skills_res = score_skills(parsed.get("skills", ""), resume_text)
    experience_res = score_experience(parsed.get("experience", ""), resume_text)
    projects_res = score_projects(parsed.get("projects", ""), resume_text)
    education_res = score_education(parsed.get("education", ""), resume_text)

    sections = {
        "contact_info": contact_res,
        "summary": summary_res,
        "skills": skills_res,
        "experience": experience_res,
        "projects": projects_res,
        "education": education_res,
    }

    # 3. Sum total score (0 to 100)
    total_score = sum(s["score"] for s in sections.values())
    total_score = max(0, min(100, int(round(total_score))))

    # 4. Overall Rating
    if total_score >= 85:
        rating = "Excellent"
    elif total_score >= 70:
        rating = "Good"
    elif total_score >= 50:
        rating = "Fair"
    else:
        rating = "Needs Rework"

    # 5. Identify which section hurts the score most ("Hurts Most")
    # Ranked by lost points descending, then by percentage loss
    ranked_deficits = sorted(
        sections.items(),
        key=lambda item: (item[1]["lost_points"], (item[1]["lost_points"] / item[1]["max_score"])),
        reverse=True,
    )

    worst_key, worst_data = ranked_deficits[0]
    if worst_data["lost_points"] > 0:
        hurts_most = {
            "section_key": worst_key,
            "title": worst_data["title"],
            "score": worst_data["score"],
            "max_score": worst_data["max_score"],
            "lost_points": worst_data["lost_points"],
            "percentage_earned": worst_data["earned_percentage"],
            "suggestion": worst_data["suggestion"],
            "impact_message": (
                f"{worst_data['title']} is hurting your score most (-{worst_data['lost_points']} pts). "
                f"{worst_data['suggestion']}"
            ),
        }
    else:
        hurts_most = None

    # 6. Basics checks
    basics = evaluate_basics_checks(resume_text)

    # 7. Aggregate actionable recommendations for weak sections
    weak_sections = [s for s in sections.values() if s["is_weak"]]
    recommendations: List[str] = [s["suggestion"] for s in weak_sections]

    # Add basics recommendations if failed
    for b_key, b_info in basics.items():
        if not b_info["passed"] and b_info["suggestion"] not in recommendations:
            recommendations.append(b_info["suggestion"])

    return {
        "total_score": total_score,
        "rating": rating,
        "sections": sections,
        "hurts_most": hurts_most,
        "basics": basics,
        "weak_sections_count": len(weak_sections),
        "recommendations": recommendations,
        "is_deterministic": True,
    }
