"""
Session-Based Resume Revision Comparison Service (#535)
=======================================================
Allows students to upload a second version of their resume in the same session
to see whether iterative changes actually helped.

Key Features & Acceptance Criteria:
1. In-Memory Session Storage:
   - Both resume versions (V1 and V2) are kept strictly in memory for the session only.
   - Zero persistence to SQLite database (no database writes).
2. Side-by-Side Comparison Summary:
   - Score: Before (V1) vs After (V2), Delta (+/- points).
   - Detected Skills: V1 vs V2, with added skills and removed skills highlighted.
   - Missing Skills: V1 vs V2, with resolved missing skills highlighted.
3. Section Change Detection:
   - Identifies and highlights resume sections that were added, removed, or retained
     (e.g., Education, Experience, Projects, Skills, Certifications, Contact).
4. Improvements and Regressions Clearly Marked:
   - Explicit markers, badge styles, and categorized summaries for positive iterations
     and potential regressions/omissions.
5. Identical Files Handling:
   - Exact same files/texts show a prominent "no changes found" message.
"""

from __future__ import annotations

import re
import time
import logging
from typing import Dict, Any, List, Set, Optional, Tuple

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# In-Memory Session Cache
# -----------------------------------------------------------------------------
# Keyed by flask session ID or client token to guarantee zero disk persistence
_SESSION_COMPARISON_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 3600 * 4  # 4 hours eviction window


def _evict_stale_cache_entries() -> None:
    """Removes in-memory session comparisons older than TTL."""
    now = time.time()
    stale_keys = [k for k, v in _SESSION_COMPARISON_CACHE.items() if (now - v.get("updated_at", 0)) > _CACHE_TTL_SECONDS]
    for k in stale_keys:
        _SESSION_COMPARISON_CACHE.pop(k, None)


def store_session_comparison(session_key: str, comparison_data: Dict[str, Any]) -> None:
    """
    Stores comparison state strictly in memory for the active session.
    Never persists to disk or SQLite database (#535).
    """
    _evict_stale_cache_entries()
    if not session_key:
        return
    _SESSION_COMPARISON_CACHE[session_key] = {
        "comparison": comparison_data,
        "updated_at": time.time(),
    }


def get_session_comparison(session_key: str) -> Optional[Dict[str, Any]]:
    """Retrieves the active in-memory comparison for a session if present."""
    if not session_key:
        return None
    entry = _SESSION_COMPARISON_CACHE.get(session_key)
    if not entry:
        return None
    return entry.get("comparison")


def clear_session_comparison(session_key: str) -> bool:
    """Clears in-memory comparison state for the given session."""
    if not session_key:
        return False
    return _SESSION_COMPARISON_CACHE.pop(session_key, None) is not None


# -----------------------------------------------------------------------------
# Standard Resume Section Patterns
# -----------------------------------------------------------------------------
STANDARD_SECTIONS: Dict[str, Dict[str, Any]] = {
    "contact": {
        "title": "Contact Information",
        "patterns": [
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
            r"\blinkedin\.com\/in\/[a-zA-Z0-9_-]+\b",
            r"\bgithub\.com\/[a-zA-Z0-9_-]+\b"
        ],
        "weight": 15
    },
    "education": {
        "title": "Education",
        "patterns": [
            r"\b(education|academic background|academics|qualifications)\b",
            r"\b(bachelor|b\.tech|b\.e|bca|bsc|master|m\.tech|mca|msc|phd|diploma|degree)\b",
            r"\b(university|college|institute|cgpa|gpa|percentage)\b"
        ],
        "weight": 20
    },
    "skills": {
        "title": "Technical Skills",
        "patterns": [
            r"\b(skills|technical skills|technologies|proficiencies|core competencies|tech stack)\b",
            r"\b(programming languages|frameworks|developer tools|databases)\b"
        ],
        "weight": 25
    },
    "experience": {
        "title": "Work Experience / Internships",
        "patterns": [
            r"\b(experience|work experience|employment history|internship|internships|professional experience)\b",
            r"\b(software engineer intern|developer intern|trainee|analyst|associate|co-op)\b"
        ],
        "weight": 20
    },
    "projects": {
        "title": "Projects",
        "patterns": [
            r"\b(projects|academic projects|personal projects|key projects|capstone projects)\b",
            r"\b(developed|built|designed|implemented|architected|created)\b"
        ],
        "weight": 15
    },
    "certifications": {
        "title": "Certifications & Achievements",
        "patterns": [
            r"\b(certifications|certificates|certified|achievements|awards|hackathons|publications|honors)\b",
            r"\b(aws certified|coursera|udemy|google cloud|oracle|nptel|leetcode|codeforces)\b"
        ],
        "weight": 5
    }
}

# -----------------------------------------------------------------------------
# Curated Technical Skills Taxonomy
# -----------------------------------------------------------------------------
COMPREHENSIVE_SKILL_CATALOG: Dict[str, str] = {
    # Core Languages
    "python": "Python", "java": "Java", "c++": "C++", "c#": "C#", "c": "C",
    "javascript": "JavaScript", "typescript": "TypeScript", "go": "Go", "rust": "Rust",
    "kotlin": "Kotlin", "swift": "Swift", "ruby": "Ruby", "php": "PHP",
    "sql": "SQL", "html": "HTML", "css": "CSS", "bash": "Bash/Shell",
    "r": "R", "scala": "Scala", "dart": "Dart",

    # Web & Application Frameworks
    "react": "React", "react.js": "React", "angular": "Angular", "vue": "Vue.js",
    "vue.js": "Vue.js", "next.js": "Next.js", "node.js": "Node.js", "node": "Node.js",
    "express": "Express.js", "express.js": "Express.js", "django": "Django",
    "flask": "Flask", "fastapi": "FastAPI", "spring": "Spring", "spring boot": "Spring Boot",
    "asp.net": "ASP.NET", "flutter": "Flutter", "react native": "React Native",
    "bootstrap": "Bootstrap", "tailwind css": "Tailwind CSS", "tailwind": "Tailwind CSS",

    # Databases & Caching
    "postgresql": "PostgreSQL", "postgres": "PostgreSQL", "mysql": "MySQL",
    "sqlite": "SQLite", "mongodb": "MongoDB", "redis": "Redis", "cassandra": "Cassandra",
    "dynamodb": "DynamoDB", "oracle": "Oracle DB", "elasticsearch": "Elasticsearch",
    "firebase": "Firebase",

    # Cloud, DevOps & Tools
    "docker": "Docker", "kubernetes": "Kubernetes", "aws": "AWS", "azure": "Azure",
    "google cloud": "GCP", "gcp": "GCP", "ci/cd": "CI/CD", "github actions": "GitHub Actions",
    "jenkins": "Jenkins", "terraform": "Terraform", "linux": "Linux", "git": "Git",
    "github": "GitHub", "nginx": "Nginx", "microservices": "Microservices",
    "serverless": "Serverless", "graphql": "GraphQL", "rest apis": "REST APIs",
    "rest api": "REST APIs", "rest": "REST APIs", "kafka": "Apache Kafka",

    # Machine Learning & Data
    "machine learning": "Machine Learning", "deep learning": "Deep Learning",
    "pandas": "Pandas", "numpy": "NumPy", "scikit-learn": "Scikit-Learn",
    "tensorflow": "TensorFlow", "pytorch": "PyTorch", "nlp": "NLP",
    "computer vision": "Computer Vision",

    # Core CS & Testing
    "data structures": "Data Structures", "algorithms": "Algorithms",
    "system design": "System Design", "oop": "OOP", "object oriented programming": "OOP",
    "unit testing": "Unit Testing", "pytest": "Pytest", "agile": "Agile", "scrum": "Scrum"
}

# Role Benchmark Requirements (used to determine missing skills)
ROLE_BENCHMARK_SKILLS: Dict[str, List[str]] = {
    "software engineer": ["Python", "Java", "SQL", "Git", "Data Structures", "Algorithms", "REST APIs", "Docker", "Linux"],
    "backend developer": ["Python", "SQL", "PostgreSQL", "REST APIs", "Docker", "Git", "Redis", "Linux", "FastAPI"],
    "frontend developer": ["JavaScript", "TypeScript", "React", "HTML", "CSS", "Tailwind CSS", "Git", "REST APIs"],
    "full stack developer": ["JavaScript", "Python", "React", "Node.js", "SQL", "PostgreSQL", "Docker", "Git", "REST APIs"],
    "data scientist": ["Python", "SQL", "Pandas", "NumPy", "Scikit-Learn", "Machine Learning", "Git", "Data Structures"],
    "cloud engineer": ["Linux", "Docker", "Kubernetes", "AWS", "CI/CD", "Terraform", "Git", "Python", "Networking"],
}


def extract_detected_skills(text: str) -> List[str]:
    """
    Extracts and standardizes technical skills present in raw resume text
    using word boundary regex against the curated catalog.
    """
    if not text or not text.strip():
        return []

    text_lower = text.lower()
    cleaned = re.sub(r"[^\w\s\+\#\./-]", " ", text_lower)
    detected: Set[str] = set()

    for raw_skill, canonical in COMPREHENSIVE_SKILL_CATALOG.items():
        pattern = r"(?:^|\s|\b)" + re.escape(raw_skill) + r"(?:\b|\s|$)"
        if re.search(pattern, cleaned):
            detected.add(canonical)

    return sorted(list(detected))


def extract_resume_sections(text: str) -> Dict[str, Dict[str, Any]]:
    """
    Identifies presence, matched patterns, and weights of standard resume sections.
    """
    if not text or not text.strip():
        return {
            sec_id: {
                "title": cfg["title"],
                "present": False,
                "status": "absent",
                "weight": cfg["weight"]
            }
            for sec_id, cfg in STANDARD_SECTIONS.items()
        }

    text_lower = text.lower()
    results: Dict[str, Dict[str, Any]] = {}

    for sec_id, cfg in STANDARD_SECTIONS.items():
        present = False
        for pat in cfg["patterns"]:
            if re.search(pat, text_lower, re.IGNORECASE):
                present = True
                break
        results[sec_id] = {
            "title": cfg["title"],
            "present": present,
            "status": "present" if present else "absent",
            "weight": cfg["weight"]
        }

    return results


def calculate_resume_readiness_score(
    text: str,
    detected_skills: List[str],
    sections: Dict[str, Dict[str, Any]]
) -> int:
    """
    Calculates a deterministic 0-100 ATS readiness score based on:
    - Section completeness (up to 45 pts)
    - Skill breadth & volume (up to 35 pts)
    - Action verbs and metrics (up to 10 pts)
    - Formatting & length balance (up to 10 pts)
    """
    if not text or not text.strip():
        return 0

    score = 0

    # 1. Section Completeness (up to 45 points)
    section_score = 0
    for sec in sections.values():
        if sec.get("present"):
            section_score += sec.get("weight", 0)
    score += min(45, int(section_score * 0.45))

    # 2. Technical Skill Breadth (up to 35 points)
    # 1 skill ~ 3.5 pts, reaching max 35 at 10+ skills
    num_skills = len(detected_skills)
    skill_score = min(35, int(num_skills * 3.5))
    score += skill_score

    # 3. Action Verbs & Metrics (up to 10 points)
    action_verbs = [
        "built", "developed", "designed", "architected", "implemented", "optimized",
        "engineered", "spearheaded", "accelerated", "reduced", "increased", "deployed"
    ]
    text_lower = text.lower()
    verb_count = 0
    for v in action_verbs:
        if re.search(rf"\b{v}\b", text_lower):
            verb_count += 1
    verb_score = min(10, int(verb_count * 2.0))
    score += verb_score

    # 4. Word count & formatting balance (up to 10 points)
    words = len(text.split())
    if 250 <= words <= 900:
        length_score = 10
    elif 150 <= words < 250:
        length_score = 6
    elif words > 900:
        length_score = 7
    else:
        length_score = 3
    score += length_score

    return min(100, max(15, score))


def determine_missing_skills(
    detected_skills: List[str],
    target_role: Optional[str] = None,
    job_description: Optional[str] = None
) -> List[str]:
    """
    Determines missing competencies against target role benchmarks
    or required skills mentioned in a pasted job description.
    """
    detected_lower = {s.lower() for s in detected_skills}
    required_skills: Set[str] = set()

    # If job description is provided, extract requirements
    if job_description and job_description.strip():
        jd_skills = extract_detected_skills(job_description)
        required_skills.update(jd_skills)

    # If target role is provided, add role benchmarks
    norm_role = (target_role or "software engineer").strip().lower()
    benchmarks = ROLE_BENCHMARK_SKILLS.get(norm_role) or ROLE_BENCHMARK_SKILLS["software engineer"]
    required_skills.update(benchmarks)

    # Calculate missing
    missing = [skill for skill in sorted(required_skills) if skill.lower() not in detected_lower]
    return missing


def compare_resume_versions(
    text_v1: str,
    text_v2: str,
    filename_v1: str = "Version 1",
    filename_v2: str = "Version 2",
    target_role: str = "Software Engineer",
    job_description: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Computes a comprehensive, deterministic side-by-side comparison of two resume versions (#535).
    Evaluates:
    - Score delta and status (improvement / regression / no changes)
    - Detected skills (added vs removed)
    - Missing skills (resolved vs newly introduced)
    - Section presence (added vs removed sections)
    - Identical file handling (prominent 'no changes found' state)
    """
    clean_v1 = (text_v1 or "").strip()
    clean_v2 = (text_v2 or "").strip()

    # -------------------------------------------------------------------------
    # 1. Identical Files / Text Check
    # -------------------------------------------------------------------------
    is_identical = bool(clean_v1 and clean_v2 and clean_v1 == clean_v2)

    # Extract detected skills for both versions
    skills_v1 = extract_detected_skills(clean_v1)
    skills_v2 = extract_detected_skills(clean_v2)

    # Extract sections for both versions
    sections_v1 = extract_resume_sections(clean_v1)
    sections_v2 = extract_resume_sections(clean_v2)

    # Calculate scores
    score_v1 = calculate_resume_readiness_score(clean_v1, skills_v1, sections_v1)
    score_v2 = calculate_resume_readiness_score(clean_v2, skills_v2, sections_v2) if not is_identical else score_v1
    score_delta = score_v2 - score_v1

    # Missing skills before and after
    missing_v1 = determine_missing_skills(skills_v1, target_role, job_description)
    missing_v2 = determine_missing_skills(skills_v2, target_role, job_description) if not is_identical else list(missing_v1)

    # -------------------------------------------------------------------------
    # Case A: Identical files / No changes
    # -------------------------------------------------------------------------
    if is_identical:
        return {
            "success": True,
            "is_identical": True,
            "filename_v1": filename_v1,
            "filename_v2": filename_v2,
            "target_role": target_role,
            "score_v1": score_v1,
            "score_v2": score_v2,
            "score_delta": 0,
            "overall_status": "no_changes",
            "badge_class": "secondary",
            "badge_text": "No Changes Found (0 pts)",
            "message": "No changes found. Both resume versions are identical.",
            "summary": "Both uploaded versions contain identical text, structure, and technical competencies. No changes found.",
            "detected_skills_v1": skills_v1,
            "detected_skills_v2": skills_v2,
            "skills_added": [],
            "skills_removed": [],
            "skills_retained": skills_v1,
            "missing_skills_v1": missing_v1,
            "missing_skills_v2": missing_v2,
            "missing_skills_resolved": [],
            "missing_skills_introduced": [],
            "sections_v1": sections_v1,
            "sections_v2": sections_v2,
            "sections_added": [],
            "sections_removed": [],
            "sections_retained": [sec["title"] for sec in sections_v1.values() if sec["present"]],
            "improvements": [],
            "regressions": [],
            "word_count_v1": len(clean_v1.split()),
            "word_count_v2": len(clean_v2.split()),
            "word_count_delta": 0,
        }

    # -------------------------------------------------------------------------
    # Case B: Differentiated versions
    # -------------------------------------------------------------------------
    v1_skills_lower = {s.lower() for s in skills_v1}
    v2_skills_lower = {s.lower() for s in skills_v2}

    skills_added = [s for s in skills_v2 if s.lower() not in v1_skills_lower]
    skills_removed = [s for s in skills_v1 if s.lower() not in v2_skills_lower]
    skills_retained = [s for s in skills_v2 if s.lower() in v1_skills_lower]

    v1_missing_lower = {m.lower() for m in missing_v1}
    v2_missing_lower = {m.lower() for m in missing_v2}

    # Resolved missing skills: was missing in V1, but acquired in V2
    missing_skills_resolved = [m for m in missing_v1 if m.lower() not in v2_missing_lower]
    # Introduced missing skills: was not missing in V1, but now missing in V2 (e.g. dropped skill)
    missing_skills_introduced = [m for m in missing_v2 if m.lower() not in v1_missing_lower]

    # Section differentials
    sections_added = []
    sections_removed = []
    sections_retained = []

    for sec_id, cfg in STANDARD_SECTIONS.items():
        v1_pres = sections_v1.get(sec_id, {}).get("present", False)
        v2_pres = sections_v2.get(sec_id, {}).get("present", False)
        title = cfg["title"]

        if v2_pres and not v1_pres:
            sections_added.append(title)
        elif v1_pres and not v2_pres:
            sections_removed.append(title)
        elif v1_pres and v2_pres:
            sections_retained.append(title)

    # Improvements & Regressions Catalogs
    improvements: List[str] = []
    regressions: List[str] = []

    # Score evaluations
    if score_delta > 0:
        improvements.append(f"ATS Readiness Score increased by +{score_delta} points (from {score_v1} to {score_v2}).")
    elif score_delta < 0:
        regressions.append(f"ATS Readiness Score decreased by {abs(score_delta)} points (from {score_v1} to {score_v2}).")

    # Skill evaluations
    if skills_added:
        improvements.append(f"Added {len(skills_added)} new technical proficiencies: {', '.join(skills_added[:5])}{'...' if len(skills_added) > 5 else ''}.")
    if skills_removed:
        regressions.append(f"Removed {len(skills_removed)} skills present in previous version: {', '.join(skills_removed[:5])}{'...' if len(skills_removed) > 5 else ''}.")

    # Missing skill resolutions
    if missing_skills_resolved:
        improvements.append(f"Successfully resolved {len(missing_skills_resolved)} missing competencies: {', '.join(missing_skills_resolved[:4])}.")
    if missing_skills_introduced:
        regressions.append(f"Created {len(missing_skills_introduced)} new missing requirement gaps: {', '.join(missing_skills_introduced[:4])}.")

    # Section additions and omissions
    if sections_added:
        improvements.append(f"Added {len(sections_added)} essential resume section(s): {', '.join(sections_added)}.")
    if sections_removed:
        regressions.append(f"Omitted {len(sections_removed)} previously included section(s): {', '.join(sections_removed)}.")

    # Determine overall status
    if score_delta > 0 or (len(skills_added) > len(skills_removed) and not sections_removed and score_delta >= 0):
        overall_status = "improvement"
        badge_class = "success"
        badge_text = f"+{score_delta} pts Improvement" if score_delta > 0 else "Overall Improvement"
        summary_msg = f"Version 2 demonstrates clear improvements (+{score_delta} pts) with {len(skills_added)} added skills."
    elif score_delta < 0 or (len(skills_removed) > len(skills_added) and score_delta <= 0) or sections_removed:
        overall_status = "regression"
        badge_class = "danger"
        badge_text = f"{score_delta} pts Regression" if score_delta < 0 else "Profile Regression"
        summary_msg = f"Version 2 shows potential regressions ({score_delta} pts). Review omitted skills or sections."
    else:
        overall_status = "neutral"
        badge_class = "secondary"
        badge_text = "Maintained Profile (0 pts)"
        summary_msg = "Both versions show comparable readiness. Small phrasing refinements without major structural shifts."

    words_v1 = len(clean_v1.split())
    words_v2 = len(clean_v2.split())

    return {
        "success": True,
        "is_identical": False,
        "filename_v1": filename_v1,
        "filename_v2": filename_v2,
        "target_role": target_role,
        "score_v1": score_v1,
        "score_v2": score_v2,
        "score_delta": score_delta,
        "overall_status": overall_status,
        "badge_class": badge_class,
        "badge_text": badge_text,
        "message": summary_msg,
        "summary": summary_msg,
        "detected_skills_v1": skills_v1,
        "detected_skills_v2": skills_v2,
        "skills_added": skills_added,
        "skills_removed": skills_removed,
        "skills_retained": skills_retained,
        "missing_skills_v1": missing_v1,
        "missing_skills_v2": missing_v2,
        "missing_skills_resolved": missing_skills_resolved,
        "missing_skills_introduced": missing_skills_introduced,
        "sections_v1": sections_v1,
        "sections_v2": sections_v2,
        "sections_added": sections_added,
        "sections_removed": sections_removed,
        "sections_retained": sections_retained,
        "improvements": improvements,
        "regressions": regressions,
        "word_count_v1": words_v1,
        "word_count_v2": words_v2,
        "word_count_delta": words_v2 - words_v1,
    }
