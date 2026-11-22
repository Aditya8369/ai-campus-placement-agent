"""
Job Description Quality Checker Service (#602)
==============================================
Evaluates pasted job descriptions to identify missing parts (skills, responsibilities,
qualifications), calculates a quality score, generates plain-language explanations,
and suggests example text to add.

Guarantees:
- Valid but short job descriptions are NOT blocked or rejected automatically.
- Users receive clear advisory warnings and can proceed whenever they choose.
- Job descriptions are never stored without explicit user consent.
"""

from typing import Dict, Any, List, Optional
import re


SKILL_KEYWORDS = [
    r"python", r"java\b", r"c\+\+", r"c#", r"javascript", r"typescript", r"sql",
    r"react", r"node", r"flask", r"django", r"aws", r"azure", r"docker", r"kubernetes",
    r"git", r"api", r"rest", r"html", r"css", r"machine learning", r"ai", r"data structures",
    r"algorithms", r"linux", r"nosql", r"mongodb", r"postgresql", r"devops", r"agile"
]

RESPONSIBILITY_KEYWORDS = [
    r"responsibilit", r"duties", r"you will", r"role", r"develop", r"build",
    r"maintain", r"design", r"collaborate", r"implement", r"deliver", r"lead",
    r"participate", r"troubleshoot", r"create", r"manage", r"work closely with"
]

QUALIFICATION_KEYWORDS = [
    r"qualification", r"requirements?", r"degree", r"bachelor", r"master",
    r"b\.?tech", r"m\.?tech", r"experience", r"years?", r"proficiency",
    r"familiarity", r"knowledge of", r"strong understanding", r"background in"
]

EXAMPLE_SNIPPETS = {
    "skills": (
        "Example Skills to add:\n"
        "- Proficient in Python, Java, or C++ with knowledge of relational databases (SQL).\n"
        "- Familiarity with Git version control, RESTful APIs, and basic cloud concepts (AWS/Docker)."
    ),
    "responsibilities": (
        "Example Responsibilities to add:\n"
        "- Design, develop, and test scalable web services and backend features.\n"
        "- Collaborate with cross-functional teams to debug, optimize, and maintain application stability."
    ),
    "qualifications": (
        "Example Qualifications to add:\n"
        "- Bachelor's or Master's degree in Computer Science, IT, or related technical discipline.\n"
        "- Strong problem-solving mindset and solid foundation in Data Structures and Algorithms."
    )
}


def evaluate_job_description_quality(text: str) -> Dict[str, Any]:
    """
    Evaluates quality of pasted job description.
    Returns:
    - quality_score: int (0 to 100)
    - quality_rating: 'Strong', 'Adequate', or 'Weak / Incomplete'
    - detected_sections: Dict[str, bool]
    - missing_sections: List[str]
    - warning_message: Optional[str]
    - suggested_examples: List[str]
    - word_count: int
    - char_count: int
    - allows_proceed: True (never blocks submission)
    """
    if not text or not text.strip():
        return {
            "quality_score": 0,
            "quality_rating": "Empty",
            "detected_sections": {"skills": False, "responsibilities": False, "qualifications": False},
            "missing_sections": ["skills", "responsibilities", "qualifications"],
            "warning_message": "Job description is empty. Pasting key requirements improves job match accuracy.",
            "plain_explanation": "An empty job description means the AI cannot calculate matching skills.",
            "suggested_examples": [EXAMPLE_SNIPPETS["skills"], EXAMPLE_SNIPPETS["responsibilities"]],
            "word_count": 0,
            "char_count": 0,
            "allows_proceed": True,
            "is_short": True
        }

    raw = text.strip()
    words = [w for w in raw.split() if w.strip()]
    word_count = len(words)
    char_count = len(raw)

    # Check components
    text_lower = raw.lower()
    has_skills = any(re.search(pat, text_lower) for pat in SKILL_KEYWORDS)
    has_resp = any(re.search(pat, text_lower) for pat in RESPONSIBILITY_KEYWORDS)
    has_qual = any(re.search(pat, text_lower) for pat in QUALIFICATION_KEYWORDS)

    # Scoring out of 100
    score = 0
    # Length points (max 30)
    if word_count >= 100:
        score += 30
    elif word_count >= 50:
        score += 20
    elif word_count >= 20:
        score += 10
    else:
        score += 5

    # Skills points (max 25)
    if has_skills:
        score += 25

    # Responsibilities points (max 25)
    if has_resp:
        score += 25

    # Qualifications points (max 20)
    if has_qual:
        score += 20

    score = min(100, score)

    missing = []
    suggested_examples = []
    if not has_skills:
        missing.append("Technical Skills & Tools")
        suggested_examples.append(EXAMPLE_SNIPPETS["skills"])
    if not has_resp:
        missing.append("Key Responsibilities & Duties")
        suggested_examples.append(EXAMPLE_SNIPPETS["responsibilities"])
    if not has_qual:
        missing.append("Education & Eligibility Qualifications")
        suggested_examples.append(EXAMPLE_SNIPPETS["qualifications"])

    is_short = word_count < 40

    if score >= 75 and not is_short:
        quality_rating = "Strong"
        warning_message = None
        plain_explanation = "This job description provides comprehensive skills, expectations, and role criteria."
    elif score >= 50:
        quality_rating = "Adequate"
        warning_message = f"Job description is usable, but missing clear {', '.join(missing)}." if missing else None
        plain_explanation = "Pasting additional details about requirements or day-to-day duties will produce more accurate AI match insights."
    else:
        quality_rating = "Weak / Incomplete"
        if is_short:
            warning_message = "The pasted text is very brief (e.g. only a job title or single sentence). Analysis may produce generic recommendations."
        else:
            warning_message = f"Missing key job components: {', '.join(missing)}."
        plain_explanation = "When crucial parts like skills or requirements are missing, your matching score will be less precise. You can still continue if you wish."

    return {
        "quality_score": score,
        "quality_rating": quality_rating,
        "detected_sections": {
            "skills": has_skills,
            "responsibilities": has_resp,
            "qualifications": has_qual
        },
        "missing_sections": missing,
        "warning_message": warning_message,
        "plain_explanation": plain_explanation,
        "suggested_examples": suggested_examples,
        "word_count": word_count,
        "char_count": char_count,
        "allows_proceed": True,
        "is_short": is_short
    }
