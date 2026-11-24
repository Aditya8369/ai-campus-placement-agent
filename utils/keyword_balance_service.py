"""
Keyword Balance and Stuffing Detection Service (#685).
======================================================
Detects keyword stuffing, unnatural buzzword repetition, and long comma-separated
skill dumps in candidate resumes.

Modern ATS and recruiters penalize candidates who copy-paste entire skill lists or
repeat keywords unnaturally to game match percentages. This service adds an objective,
rule-based check that:
1. Counts the frequency of each technical skill and keyword across the resume.
2. Flags terms repeated unusually often (threshold: > 5 times per resume).
3. Flags excessively long comma-separated skill dumps (threshold: > 40 items).
4. Recommends natural keyword distribution ("mention it once in skills and once with evidence in a project").
5. Applies a non-blocking, capped score penalty (maximum 5 points total deduction)
   documented clearly in the score breakdown.

All thresholds are centralized constants in this module for straightforward tuning and testing.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

# ==============================================================================
# CONFIGURABLE THRESHOLDS & CONSTANTS (#685)
# ==============================================================================

MAX_KEYWORD_REPETITION_THRESHOLD: int = 5
MAX_SKILL_LIST_ITEMS_THRESHOLD: int = 40
PENALTY_PER_REPEATED_KEYWORD: int = 1
PENALTY_FOR_SKILL_DUMP: int = 2
MAX_KEYWORD_BALANCE_PENALTY: int = 5

DEFAULT_REPETITION_SUGGESTION: str = (
    "Mention it once in skills and once with evidence in a project."
)

DEFAULT_SKILL_DUMP_SUGGESTION: str = (
    "Avoid dumping long comma-separated skill lists (> 40 items); focus on your core "
    "15-20 competencies backed by concrete project evidence."
)

# Core technical skills to inspect for unnatural repetition
INSPECTED_TECH_SKILLS: List[str] = [
    "Python", "Java", "C++", "C#", "C", "JavaScript", "TypeScript", "Go", "Rust", "Ruby",
    "PHP", "Swift", "Kotlin", "HTML", "CSS", "SQL", "React", "Angular", "Vue", "Next.js",
    "Node.js", "Express", "Django", "Flask", "FastAPI", "Spring Boot", "Docker", "Kubernetes",
    "AWS", "GCP", "Azure", "Git", "GitHub", "GitLab", "Linux", "PostgreSQL", "MySQL",
    "MongoDB", "Redis", "SQLite", "GraphQL", "REST", "REST APIs", "CI/CD", "Tailwind",
    "Bootstrap", "Pandas", "NumPy", "TensorFlow", "PyTorch", "Scikit-Learn", "Microservices",
    "Agile", "Scrum", "DevOps", "Jira", "Selenium", "Postman", "Kafka", "RabbitMQ"
]

COMMON_STOPWORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any",
    "are", "aren't", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "can", "can't", "cannot", "could", "did", "do",
    "does", "doing", "don't", "down", "during", "each", "few", "for", "from", "further",
    "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him",
    "himself", "his", "how", "i", "if", "in", "into", "is", "isn't", "it", "its",
    "itself", "let's", "me", "more", "most", "my", "myself", "no", "nor", "not", "of",
    "off", "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves",
    "out", "over", "own", "same", "she", "should", "so", "some", "such", "than", "that",
    "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they",
    "this", "those", "through", "to", "too", "under", "until", "up", "very", "was",
    "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why",
    "with", "won't", "would", "you", "your", "yours", "yourself", "yourselves",
    # Resume structure words
    "resume", "curriculum", "vitae", "summary", "education", "experience", "projects",
    "skills", "work", "technical", "personal", "details", "contact", "email", "phone",
    "name", "date", "year", "years", "month", "months", "role", "developed", "building",
    "using", "used", "worked", "created", "responsible", "university", "college", "school"
}


def count_keyword_occurrences(text: str, keyword: str) -> int:
    """
    Counts occurrences of a keyword in text using word boundaries.
    Properly handles punctuation symbols such as C++, C#, and .NET.
    """
    if not text or not keyword:
        return 0

    escaped = re.escape(keyword.strip())
    # For very short symbols (e.g. C, R), require uppercase word boundary to prevent false positives
    if len(keyword.strip()) == 1:
        pattern = r"\b" + escaped + r"\b"
        return len(re.findall(pattern, text))

    # General word-boundary pattern supporting punctuation like ++ and #
    pattern = r"(?<![a-zA-Z0-9])" + escaped + r"(?![a-zA-Z0-9])"
    return len(re.findall(pattern, text, re.IGNORECASE))


def detect_skill_dumps(
    resume_text: str,
    skills_text: str = "",
    dump_threshold: int = MAX_SKILL_LIST_ITEMS_THRESHOLD,
) -> Tuple[bool, int]:
    """
    Detects if the resume contains an excessively long comma-separated skill dump.
    Returns (skill_dump_detected, item_count).
    """
    max_items_found = 0

    # 1. Inspect explicit skills section if provided
    if skills_text and skills_text.strip():
        # Split on commas, semicolons, bullets, and pipes
        tokens = [
            t.strip()
            for t in re.split(r"[,;\n•|]+", skills_text)
            if t.strip() and len(t.strip()) <= 40 and not t.strip().endswith(":")
        ]
        if len(tokens) > max_items_found:
            max_items_found = len(tokens)

    # 2. Inspect lines or comma-separated paragraphs across the entire resume text
    if resume_text and resume_text.strip():
        for line in resume_text.splitlines():
            if "," in line:
                comma_parts = [p.strip() for p in line.split(",") if p.strip()]
                if len(comma_parts) > max_items_found:
                    max_items_found = len(comma_parts)

        # Also inspect full resume for contiguous comma dumps
        paragraphs = resume_text.split("\n\n")
        for p in paragraphs:
            if p.count(",") >= dump_threshold:
                parts = [p_item.strip() for p_item in p.split(",") if p_item.strip()]
                if len(parts) > max_items_found:
                    max_items_found = len(parts)

    is_dump = max_items_found > dump_threshold
    return is_dump, max_items_found


def extract_candidate_skill_terms(resume_text: str, skills_text: str = "") -> List[str]:
    """
    Extracts candidate skill terms to inspect, combining standard tech catalog with
    explicit skills listed in the candidate's skills section.
    """
    terms_set: Set[str] = set()

    # Add core tech catalog
    for s in INSPECTED_TECH_SKILLS:
        terms_set.add(s)

    # Add items found in skills section
    source_skills = skills_text or resume_text
    if source_skills:
        raw_items = re.split(r"[,;\n•|/]+", source_skills)
        for raw in raw_items:
            clean = raw.strip()
            # Valid skill token heuristic
            if clean and 2 <= len(clean) <= 35 and clean.lower() not in COMMON_STOPWORDS:
                # Exclude strings containing colon (likely headings)
                if ":" not in clean and not clean.startswith(("#", "*", "-")):
                    terms_set.add(clean)

    return sorted(list(terms_set), key=lambda x: len(x), reverse=True)


def check_keyword_balance(
    resume_text: str,
    skills_text: str = "",
    repetition_threshold: int = MAX_KEYWORD_REPETITION_THRESHOLD,
    dump_threshold: int = MAX_SKILL_LIST_ITEMS_THRESHOLD,
    max_penalty: int = MAX_KEYWORD_BALANCE_PENALTY,
) -> Dict[str, Any]:
    """
    Performs a deterministic, rule-based check on keyword frequency and skill dumps.

    Returns:
        Dict containing:
        - has_warnings: bool
        - status: 'Balanced' | 'Warning'
        - flagged_terms: List[Dict[str, Any]] with term, count, threshold, suggestion
        - repeated_keywords_count: int
        - skill_dump_detected: bool
        - skill_dump_count: int
        - score_penalty: int (0 to max_penalty)
        - max_penalty_cap: int
        - repetition_threshold: int
        - dump_threshold: int
        - suggestion: str
        - documentation: str
    """
    if not resume_text or not resume_text.strip():
        return {
            "has_warnings": False,
            "status": "Balanced",
            "flagged_terms": [],
            "repeated_keywords_count": 0,
            "skill_dump_detected": False,
            "skill_dump_count": 0,
            "score_penalty": 0,
            "max_penalty_cap": max_penalty,
            "repetition_threshold": repetition_threshold,
            "dump_threshold": dump_threshold,
            "suggestion": "No keyword balance issues detected.",
            "documentation": (
                f"Rule-based keyword balance check flags terms repeated > {repetition_threshold} times "
                f"and skill dumps with > {dump_threshold} items. Score impact is capped at {max_penalty} pts."
            ),
        }

    # 1. Count occurrences for inspected terms
    candidate_terms = extract_candidate_skill_terms(resume_text, skills_text)
    flagged_terms: List[Dict[str, Any]] = []
    seen_normalized: Set[str] = set()

    for term in candidate_terms:
        norm_key = term.lower()
        if norm_key in seen_normalized:
            continue

        count = count_keyword_occurrences(resume_text, term)
        if count > repetition_threshold:
            seen_normalized.add(norm_key)
            flagged_terms.append({
                "term": term,
                "count": count,
                "threshold": repetition_threshold,
                "suggestion": DEFAULT_REPETITION_SUGGESTION,
            })

    # Sort flagged terms descending by count
    flagged_terms.sort(key=lambda x: x["count"], reverse=True)

    # 2. Check for long comma-separated skill list dumps
    is_dump, dump_count = detect_skill_dumps(resume_text, skills_text, dump_threshold)

    # 3. Calculate score penalty (capped at max_penalty)
    raw_penalty = (len(flagged_terms) * PENALTY_PER_REPEATED_KEYWORD) + (
        PENALTY_FOR_SKILL_DUMP if is_dump else 0
    )
    score_penalty = min(raw_penalty, max_penalty)

    has_warnings = bool(flagged_terms or is_dump)

    if has_warnings:
        suggestion_parts = []
        if flagged_terms:
            terms_preview = ", ".join(f"{t['term']} ({t['count']}x)" for t in flagged_terms[:3])
            if len(flagged_terms) > 3:
                terms_preview += f" and {len(flagged_terms) - 3} others"
            suggestion_parts.append(
                f"Unusually frequent repetition of {terms_preview}. {DEFAULT_REPETITION_SUGGESTION}"
            )
        if is_dump:
            suggestion_parts.append(
                f"Detected a skill list of {dump_count} items (exceeds threshold of {dump_threshold}). "
                f"{DEFAULT_SKILL_DUMP_SUGGESTION}"
            )
        general_suggestion = " ".join(suggestion_parts)
    else:
        general_suggestion = (
            "Keyword balance is healthy. Skills and keywords are integrated naturally across project and experience bullets."
        )

    documentation = (
        f"Rule-based keyword balance check flags terms repeated > {repetition_threshold} times "
        f"and skill dumps with > {dump_threshold} items. Score penalty is capped at a maximum of "
        f"{max_penalty} points to maintain non-blocking evaluation."
    )

    return {
        "has_warnings": has_warnings,
        "status": "Warning" if has_warnings else "Balanced",
        "flagged_terms": flagged_terms,
        "repeated_keywords_count": len(flagged_terms),
        "skill_dump_detected": is_dump,
        "skill_dump_count": dump_count,
        "score_penalty": score_penalty,
        "max_penalty_cap": max_penalty,
        "repetition_threshold": repetition_threshold,
        "dump_threshold": dump_threshold,
        "suggestion": general_suggestion,
        "documentation": documentation,
    }
