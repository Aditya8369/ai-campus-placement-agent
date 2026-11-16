"""
Resume Section Completeness Validation Service
Analyzes uploaded resumes to verify presence of essential placement sections:
- Education (Degrees, GPA/CGPA, Graduation Year, University)
- Technical Skills (Programming, Frameworks, Tools)
- Projects (Titles, Descriptions, Tech Stack, URLs/GitHub)
- Work Experience / Internships (Role, Organization, Duration, Responsibilities)
- Contact Info (Email, Phone, LinkedIn/GitHub)
- Certifications / Achievements (Courses, Accreditations, Awards)

Provides non-blocking soft warnings and actionable tips so students can maximize
their ATS score and recruiter impression without blocking analysis.
"""

import re
from typing import Dict, Any, List, Set, Optional

# Regex patterns identifying standard sections
SECTION_PATTERNS = {
    "contact": {
        "title": "Contact Information",
        "required": True,
        "weight": 20,
        "patterns": [
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
            r"\blinkedin\.com\/in\/[a-zA-Z0-9_-]+\b",
            r"\bgithub\.com\/[a-zA-Z0-9_-]+\b"
        ],
        "tip": "Include an active email address, contact phone number, and LinkedIn or GitHub profile link."
    },
    "education": {
        "title": "Education",
        "required": True,
        "weight": 20,
        "patterns": [
            r"\b(education|academics|academic background|qualifications)\b",
            r"\b(bachelor|b\.tech|b\.e|bca|bsc|master|m\.tech|mca|msc|phd|diploma)\b",
            r"\b(university|college|institute|cgpa|gpa|percentage)\b"
        ],
        "tip": "List your degree, major/branch, university/college name, and graduation year or CGPA."
    },
    "skills": {
        "title": "Technical & Soft Skills",
        "required": True,
        "weight": 20,
        "patterns": [
            r"\b(skills|technical skills|technologies|proficiencies|competencies|tech stack)\b",
            r"\b(python|java|c\+\+|javascript|typescript|sql|html|css|react|node|docker|aws|git)\b"
        ],
        "tip": "Group your skills into categories like Languages, Frameworks, Developer Tools, and Databases."
    },
    "projects": {
        "title": "Projects",
        "required": True,
        "weight": 20,
        "patterns": [
            r"\b(projects|academic projects|personal projects|key projects|capstone)\b",
            r"\b(developed|built|designed|implemented|created|architected)\b"
        ],
        "tip": "Highlight at least 2 relevant projects with problem statement, technologies used, and outcomes."
    },
    "experience": {
        "title": "Experience / Internships",
        "required": False,
        "weight": 10,
        "patterns": [
            r"\b(experience|work experience|employment history|internship|internships|professional experience)\b",
            r"\b(software engineer intern|developer intern|trainee|analyst|associate)\b"
        ],
        "tip": "Even for freshers, mentioning internships, open source contributions, or virtual training boosts confidence."
    },
    "certifications": {
        "title": "Certifications & Achievements",
        "required": False,
        "weight": 10,
        "patterns": [
            r"\b(certifications|certificates|certified|achievements|awards|hackathon|publications|honors)\b",
            r"\b(aws certified|coursera|udemy|google cloud|oracle|nptel|leetcode)\b"
        ],
        "tip": "Include relevant certifications, competitive programming ranks, or hackathon achievements."
    }
}


class ResumeSectionValidator:
    """Evaluates the completeness of resume sections and yields guidance."""

    def __init__(self):
        self.sections = SECTION_PATTERNS

    def extract_detected_keywords(self, resume_text: str) -> Dict[str, List[str]]:
        """Extracts matched keyword samples per section for student transparency."""
        text_lower = resume_text.lower()
        keyword_map: Dict[str, List[str]] = {}
        for key, config in self.sections.items():
            found: Set[str] = set()
            for pat in config["patterns"]:
                matches = re.findall(pat, text_lower, re.IGNORECASE)
                for m in matches:
                    if isinstance(m, tuple):
                        found.update([item for item in m if item])
                    elif isinstance(m, str):
                        found.add(m)
            keyword_map[key] = sorted(list(found))[:6]
        return keyword_map

    def validate_sections(self, resume_text: str) -> Dict[str, Any]:
        """
        Scans resume text against standard sections, computes a completeness score (0-100),
        and returns detailed status and non-blocking warnings.
        """
        if not resume_text or not resume_text.strip():
            return {
                "completeness_score": 0,
                "status": "Incomplete",
                "is_complete": False,
                "sections": {},
                "missing_sections": list(self.sections.keys()),
                "warnings": ["The resume text appears empty. No sections could be verified."],
                "recommendations": ["Upload a readable resume with complete student credentials and project details."],
                "detected_keywords": {}
            }

        text_lower = resume_text.lower()
        section_results: Dict[str, Any] = {}
        missing_sections: List[str] = []
        warnings: List[str] = []
        recommendations: List[str] = []
        total_score = 0
        detected_keywords = self.extract_detected_keywords(resume_text)

        for key, config in self.sections.items():
            matched_patterns = 0
            for pat in config["patterns"]:
                if re.search(pat, text_lower, re.IGNORECASE):
                    matched_patterns += 1

            is_present = matched_patterns > 0
            score_earned = config["weight"] if is_present else 0
            total_score += score_earned

            section_results[key] = {
                "title": config["title"],
                "present": is_present,
                "required": config["required"],
                "weight": config["weight"],
                "matched_indicators": matched_patterns,
                "sample_matches": detected_keywords.get(key, []),
                "tip": config["tip"]
            }

            if not is_present:
                missing_sections.append(key)
                if config["required"]:
                    warnings.append(f"Missing recommended section: '{config['title']}'.")
                    recommendations.append(f"Add a '{config['title']}' section: {config['tip']}")
                else:
                    recommendations.append(f"Optional improvement: Add '{config['title']}' if available.")

        # Overall readiness status based on score
        if total_score >= 80:
            status = "Strong"
        elif total_score >= 60:
            status = "Adequate"
        elif total_score >= 40:
            status = "Needs Improvement"
        else:
            status = "Incomplete"

        # Check if all required sections are present
        has_all_required = all(
            section_results[key]["present"]
            for key, config in self.sections.items()
            if config["required"]
        )

        return {
            "completeness_score": total_score,
            "status": status,
            "is_complete": has_all_required,
            "sections": section_results,
            "missing_sections": missing_sections,
            "warnings": warnings,
            "recommendations": recommendations,
            "detected_keywords": detected_keywords
        }


resume_section_validator = ResumeSectionValidator()
