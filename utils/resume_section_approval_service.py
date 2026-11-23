"""
Resume Section Approval Service (#601)
======================================
Parses extracted resume text into modular sections:
- Candidate Name / Header
- Education
- Experience / Internships
- Projects
- Skills
- Certifications / Additional

Provides validation, missing section warnings, section editing/approval,
and structured reassembly so user-approved section corrections are fed
into the AI analysis pipeline without altering the original file on disk.
"""

from typing import Dict, Any, List, Optional, Tuple
import re
from utils.pdf_reader import standardize_resume_sections
from utils.resume_info_extractor import extract_candidate_name


CANONICAL_SECTIONS = [
    {
        "key": "name",
        "title": "Candidate Name & Contact Header",
        "required": True,
        "description": "Full name and contact summary extracted from the header."
    },
    {
        "key": "education",
        "title": "Education & Academics",
        "required": True,
        "description": "Degrees, university/college, GPA/percentage, graduation dates."
    },
    {
        "key": "skills",
        "title": "Technical Skills & Competencies",
        "required": True,
        "description": "Programming languages, developer tools, libraries, frameworks."
    },
    {
        "key": "projects",
        "title": "Projects & Portfolio",
        "required": True,
        "description": "Academic and personal development projects, repositories, stack used."
    },
    {
        "key": "experience",
        "title": "Work Experience & Internships",
        "required": False,
        "description": "Professional roles, internships, responsibilities, accomplishments."
    },
    {
        "key": "certifications",
        "title": "Certifications & Achievements",
        "required": False,
        "description": "Professional certifications, competitive programming, awards."
    }
]


def parse_resume_for_approval(raw_resume_text: str) -> Dict[str, Any]:
    """
    Parses resume text into editable sections and provides completeness warnings.
    """
    if not raw_resume_text or not raw_resume_text.strip():
        return {
            "sections": {},
            "warnings": ["No text detected in resume."],
            "is_complete": False,
            "detected_count": 0,
            "total_count": len(CANONICAL_SECTIONS)
        }

    raw_text = raw_resume_text.strip()
    
    # 1. Extract Candidate Name & Header text
    candidate_name, header_text = extract_candidate_name(raw_text)
    if not header_text:
        # First 4 lines as header preview fallback
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        header_text = "\n".join(lines[:4]) if lines else candidate_name

    # 2. Extract Canonical Sections using standardize_resume_sections
    std_sections = standardize_resume_sections(raw_text)

    # 3. Assemble approval dict
    sections_out: Dict[str, Any] = {}
    warnings: List[str] = []

    for defn in CANONICAL_SECTIONS:
        key = defn["key"]
        content = ""
        if key == "name":
            content = f"{candidate_name}\n{header_text}".strip()
        else:
            content = (std_sections.get(key) or "").strip()

        detected = bool(content and len(content) > 10)
        warning = None
        if not detected:
            if defn["required"]:
                warning = f"Section '{defn['title']}' could not be detected automatically. You can add it manually before AI analysis."
                warnings.append(warning)
            else:
                warning = f"Optional section '{defn['title']}' was not detected. You can proceed without it or add it."

        sections_out[key] = {
            "key": key,
            "title": defn["title"],
            "required": defn["required"],
            "detected": detected,
            "content": content,
            "warning": warning,
            "description": defn["description"]
        }

    detected_count = sum(1 for s in sections_out.values() if s["detected"])
    required_missing = [s["title"] for s in sections_out.values() if s["required"] and not s["detected"]]

    return {
        "sections": sections_out,
        "warnings": warnings,
        "is_complete": len(required_missing) == 0,
        "detected_count": detected_count,
        "total_count": len(CANONICAL_SECTIONS),
        "required_missing": required_missing
    }


def reassemble_approved_resume(approved_sections: Dict[str, str], original_raw_text: str = "") -> str:
    """
    Reassembles approved/edited sections into a clean structured resume text for the AI service.
    Preserves existing original text if sections were partially provided.
    """
    if not approved_sections:
        return original_raw_text

    blocks = []
    
    # Name & Header
    if approved_sections.get("name"):
        blocks.append(f"# CANDIDATE INFORMATION\n{approved_sections['name'].strip()}")

    # Skills
    if approved_sections.get("skills"):
        blocks.append(f"# TECHNICAL SKILLS\n{approved_sections['skills'].strip()}")

    # Experience
    if approved_sections.get("experience"):
        blocks.append(f"# WORK EXPERIENCE & INTERNSHIPS\n{approved_sections['experience'].strip()}")

    # Projects
    if approved_sections.get("projects"):
        blocks.append(f"# PROJECTS\n{approved_sections['projects'].strip()}")

    # Education
    if approved_sections.get("education"):
        blocks.append(f"# EDUCATION\n{approved_sections['education'].strip()}")

    # Certifications
    if approved_sections.get("certifications"):
        blocks.append(f"# CERTIFICATIONS & ACHIEVEMENTS\n{approved_sections['certifications'].strip()}")

    assembled = "\n\n".join(blocks).strip()
    return assembled if len(assembled) > 30 else original_raw_text
