"""
Company-Specific Interview Preparation Service (#541)
=====================================================
Manages contributor-maintained company interview preparation guides, including
typical hiring rounds, commonly tested topics, preparation tips, and last-updated metadata.

Key Capabilities:
1. Contributor-maintained data file (data/company_interview_prep.json) loaded dynamically.
2. Acceptance Criterion 1: A new company can be added by editing the data file only.
3. Acceptance Criterion 2: Every entry has a last-updated date.
4. Acceptance Criterion 3: Unknown companies fall back to general tips.
5. All guides labeled as community-contributed.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config

logger = logging.getLogger(__name__)

# Fallback definition in case data file is missing or corrupted
DEFAULT_GENERAL_PREP: Dict[str, Any] = {
    "company_name": "General Placement",
    "typical_rounds": [
        "Round 1: Online Assessment (Quantitative Aptitude, Logical Reasoning & Foundational Coding)",
        "Round 2: Technical Interview 1 (Data Structures, Algorithms & Core Computer Science)",
        "Round 3: Technical Interview 2 (System Architecture, Tech Stack & Resume Project Deep-Dive)",
        "Round 4: HR & Behavioral Round (Cultural Fit, Situational Questions & Career Goals)",
    ],
    "commonly_tested_topics": [
        "Data Structures (Arrays, Strings, Linked Lists, Trees, Graphs, HashMaps)",
        "Object-Oriented Programming (Inheritance, Polymorphism, Encapsulation, Abstraction)",
        "Database Management Systems & SQL Queries (Joins, Indexing, Transactions)",
        "Operating Systems & Computer Networks (Threads, Deadlocks, TCP/IP, HTTP/S)",
        "Resume Project Architecture & Problem-Solving Trade-offs",
        "STAR Method Scenarios (Conflict Resolution, Team Leadership, Adaptability)",
    ],
    "preparation_tips": [
        "Clarify constraints, edge cases, and assumptions before writing any code.",
        "Analyze and state time and space complexity for both brute-force and optimized solutions.",
        "Thoroughly review every project, library, and metric stated on your resume.",
        "Structure behavioral responses using the Situation, Task, Action, Result (STAR) framework.",
        "Prepare 2-3 thoughtful questions for the interviewers about engineering culture and tech stack.",
    ],
    "last_updated": "2026-11-18",
    "community_contributed": True,
}

# Cache holder for mtime-based dynamic reload
_CACHE: Dict[str, Any] = {
    "mtime": 0.0,
    "path": None,
    "data": None,
}


def get_company_prep_file_path() -> Path:
    """Returns the default path to the contributor-maintained JSON data file."""
    return Path(config.BASE_DIR) / "data" / "company_interview_prep.json"


def load_company_prep_data(file_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Loads company interview prep data from the JSON file.
    Uses file mtime caching so updates to the JSON file on disk are reflected immediately
    without requiring application restarts (Acceptance Criterion 1).
    """
    path = Path(file_path) if file_path else get_company_prep_file_path()

    try:
        if not path.exists():
            logger.warning(f"Company interview prep file not found at {path}. Using default fallback.")
            return {"General": DEFAULT_GENERAL_PREP.copy()}

        current_mtime = os.path.getmtime(path)
        if _CACHE["data"] is not None and _CACHE["path"] == str(path) and _CACHE["mtime"] == current_mtime:
            return _CACHE["data"]

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            logger.error(f"Invalid format in {path}: expected JSON object. Using fallback.")
            return {"General": DEFAULT_GENERAL_PREP.copy()}

        # Ensure General fallback is always present
        if "General" not in data:
            data["General"] = DEFAULT_GENERAL_PREP.copy()

        _CACHE["mtime"] = current_mtime
        _CACHE["path"] = str(path)
        _CACHE["data"] = data
        return data

    except Exception as e:
        logger.error(f"Error reading company interview prep data from {path}: {e}")
        return {"General": DEFAULT_GENERAL_PREP.copy()}


def get_available_companies(file_path: Optional[Path] = None) -> List[str]:
    """
    Returns an alphabetically sorted list of company names available in the data file.
    'General' is positioned first for user convenience.
    """
    data = load_company_prep_data(file_path)
    companies = list(data.keys())

    # Sort case-insensitively, keeping 'General' first
    non_general = sorted([c for c in companies if c.lower() != "general"], key=lambda s: s.lower())
    result = ["General"] + non_general
    return result


def get_company_prep(company_name: Optional[str], file_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Retrieves interview preparation details for the specified company.
    If the company is unknown, None, or empty, falls back to general tips (Acceptance Criterion 3).
    Labels information as community-contributed and ensures last_updated is present (Acceptance Criterion 2).
    """
    data = load_company_prep_data(file_path)
    clean_name = (company_name or "").strip()

    # Exact match first
    if clean_name and clean_name in data:
        entry = dict(data[clean_name])
        entry["is_fallback"] = False
        entry["company_name"] = entry.get("company_name", clean_name)
        entry["community_contributed"] = True
        if "last_updated" not in entry or not entry["last_updated"]:
            entry["last_updated"] = "2026-11-18"
        return entry

    # Case-insensitive match
    if clean_name:
        clean_lower = clean_name.lower()
        for k, v in data.items():
            if k.lower() == clean_lower:
                entry = dict(v)
                entry["is_fallback"] = False
                entry["company_name"] = entry.get("company_name", k)
                entry["community_contributed"] = True
                if "last_updated" not in entry or not entry["last_updated"]:
                    entry["last_updated"] = "2026-11-18"
                return entry

    # Unknown company: Fall back to general tips (Acceptance Criterion 3)
    general_raw = data.get("General", DEFAULT_GENERAL_PREP)
    entry = dict(general_raw)
    entry["is_fallback"] = True
    entry["requested_company"] = clean_name if clean_name else "Unknown"
    entry["company_name"] = entry.get("company_name", "General Placement")
    entry["community_contributed"] = True
    if "last_updated" not in entry or not entry["last_updated"]:
        entry["last_updated"] = "2026-11-18"
    return entry


def validate_company_prep_entry(entry: Any) -> Tuple[bool, List[str]]:
    """
    Validates a company preparation dictionary entry against schema requirements.
    Ensures last_updated, typical_rounds, commonly_tested_topics, and preparation_tips exist and are valid.
    """
    errors: List[str] = []
    if not isinstance(entry, dict):
        return False, ["Entry must be a JSON dictionary."]

    # Validate last_updated date
    last_updated = entry.get("last_updated")
    if not last_updated or not isinstance(last_updated, str) or not last_updated.strip():
        errors.append("Entry is missing 'last_updated' date string.")
    else:
        try:
            datetime.strptime(last_updated.strip(), "%Y-%m-%d")
        except ValueError:
            errors.append(f"Invalid 'last_updated' date format '{last_updated}'. Expected YYYY-MM-DD.")

    # Validate typical_rounds
    typical_rounds = entry.get("typical_rounds")
    if not isinstance(typical_rounds, list) or len(typical_rounds) == 0:
        errors.append("Entry must have non-empty 'typical_rounds' list.")
    elif not all(isinstance(r, str) and r.strip() for r in typical_rounds):
        errors.append("All items in 'typical_rounds' must be non-empty strings.")

    # Validate commonly_tested_topics
    topics = entry.get("commonly_tested_topics")
    if not isinstance(topics, list) or len(topics) == 0:
        errors.append("Entry must have non-empty 'commonly_tested_topics' list.")
    elif not all(isinstance(t, str) and t.strip() for t in topics):
        errors.append("All items in 'commonly_tested_topics' must be non-empty strings.")

    # Validate preparation_tips
    tips = entry.get("preparation_tips")
    if not isinstance(tips, list) or len(tips) == 0:
        errors.append("Entry must have non-empty 'preparation_tips' list.")
    elif not all(isinstance(t, str) and t.strip() for t in tips):
        errors.append("All items in 'preparation_tips' must be non-empty strings.")

    return len(errors) == 0, errors


def format_last_updated_date(date_str: str) -> str:
    """Formats 'YYYY-MM-DD' into a human-readable display string, e.g. 'Nov 18, 2026'."""
    if not date_str:
        return "Unknown"
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return dt.strftime("%b %d, %Y")
    except Exception:
        return date_str
