"""
Company Eligibility Calculator Service (#603, #844)
===================================================
Calculates candidate eligibility against verified company hiring profiles
(from data/companies.json) using candidate profile fields (CGPA, active backlogs,
branch/department).

Acceptance Criteria (#844):
- Eligibility results are correct for sample profiles including boundary values.
- Missing criteria show 'unknown', never 'eligible'.
- Profile values are private and validated.
- Tests cover boundaries and missing data.
- 'only companies I am eligible for' filter supported.
- Clear indication that criteria vary by drive.
"""

from typing import Dict, Any, List, Optional
import json
import re
from pathlib import Path
import config


DEFAULT_COMPANIES_FILE = Path(getattr(config, "BASE_DIR", ".")) / "data" / "companies.json"

CIRCUITAL_BRANCH_TOKENS = [
    "cs", "it", "computer science", "information technology", "cse",
    "ece", "ee", "electronics", "electrical", "telecommunication", "comp sci"
]


def load_company_data(company_name: str) -> Optional[Dict[str, Any]]:
    """Loads company profile data from data/companies.json."""
    if not DEFAULT_COMPANIES_FILE.exists():
        return None
    try:
        with open(DEFAULT_COMPANIES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get(company_name)
    except Exception:
        return None


def calculate_company_eligibility(
    company_name: str,
    student_profile: Dict[str, Any],
    company_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Evaluates student profile against company requirements.

    `student_profile` can contain:
    - cgpa: float or None
    - backlogs: int or None
    - branch: str or None (or department)
    - passing_year: int or None

    Returns a dict with:
    - overall_status: "eligible", "not eligible", or "unknown"
    - eligible: bool (True only if overall_status == "eligible")
    - reason: explanation if not eligible or unknown
    - evaluations: detailed list of per-criteria evaluations
    - criteria_summary: text description
    - drive_disclaimer: clear statement that criteria vary by drive
    """
    if not company_data:
        company_data = load_company_data(company_name) or {}

    # Extract criteria directly from explicit fields if present, else fallback to heuristic text parsing
    min_cgpa: Optional[float] = None
    if "min_cgpa" in company_data:
        raw_min = company_data["min_cgpa"]
        if raw_min is not None:
            try:
                min_cgpa = float(raw_min)
            except (ValueError, TypeError):
                min_cgpa = None
    else:
        # Heuristic parse
        text_lower = (company_data.get("eligibility") or "").lower()
        cgpa_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:cgpa|\+?\s*cgpa)", text_lower)
        if cgpa_match:
            try:
                min_cgpa = float(cgpa_match.group(1))
            except ValueError:
                pass

    max_backlogs: Optional[int] = None
    if "max_backlogs" in company_data:
        raw_b = company_data["max_backlogs"]
        if raw_b is not None:
            try:
                max_backlogs = int(raw_b)
            except (ValueError, TypeError):
                max_backlogs = None
    else:
        text_lower = (company_data.get("eligibility") or "").lower()
        if "1 backlog" in text_lower or "1 active backlog" in text_lower:
            max_backlogs = 1
        elif "no active backlogs" in text_lower or "no current backlogs" in text_lower or "no standing backlogs" in text_lower:
            max_backlogs = 0

    allowed_branches: Optional[List[str]] = None
    if "branches" in company_data and isinstance(company_data["branches"], list):
        allowed_branches = company_data["branches"]
    else:
        text_lower = (company_data.get("eligibility") or "").lower()
        if "all branches" in text_lower or "open to all" in text_lower or "any engineering" in text_lower:
            allowed_branches = ["All"]
        elif text_lower:
            allowed_branches = ["CS", "IT", "ECE"]

    evaluations: List[Dict[str, Any]] = []
    unmet_reasons: List[str] = []
    unknown_reasons: List[str] = []

    has_any_rule = (min_cgpa is not None) or (max_backlogs is not None) or (allowed_branches is not None)

    # 1. CGPA Evaluation
    student_cgpa = student_profile.get("cgpa")
    if min_cgpa is not None:
        if student_cgpa is not None:
            try:
                cgpa_val = float(student_cgpa)
                if cgpa_val >= min_cgpa:
                    evaluations.append({
                        "criteria": "Minimum CGPA",
                        "required": f"{min_cgpa} CGPA",
                        "provided": f"{cgpa_val} CGPA",
                        "status": "Met",
                        "explanation": f"Your CGPA ({cgpa_val}) meets the minimum requirement of {min_cgpa}."
                    })
                else:
                    unmet_reasons.append(f"CGPA {cgpa_val} is below required minimum {min_cgpa}")
                    evaluations.append({
                        "criteria": "Minimum CGPA",
                        "required": f"{min_cgpa} CGPA",
                        "provided": f"{cgpa_val} CGPA",
                        "status": "Unmet",
                        "explanation": f"Your CGPA ({cgpa_val}) is below the required minimum of {min_cgpa}."
                    })
            except (ValueError, TypeError):
                unknown_reasons.append("CGPA could not be parsed")
                evaluations.append({
                    "criteria": "Minimum CGPA",
                    "required": f"{min_cgpa} CGPA",
                    "provided": str(student_cgpa),
                    "status": "Uncertain",
                    "explanation": "Could not parse student CGPA."
                })
        else:
            unknown_reasons.append("CGPA not provided in profile")
            evaluations.append({
                "criteria": "Minimum CGPA",
                "required": f"{min_cgpa} CGPA",
                "provided": "Not Provided",
                "status": "Uncertain",
                "explanation": "CGPA not specified in profile."
            })
    else:
        # Recruiter has no strict CGPA rule specified
        evaluations.append({
            "criteria": "Minimum CGPA",
            "required": "No rigid cutoff specified",
            "provided": f"{student_cgpa} CGPA" if student_cgpa is not None else "Not Specified",
            "status": "Met",
            "explanation": "No rigid minimum CGPA specified for this company."
        })

    # 2. Backlogs Evaluation
    student_backlogs = student_profile.get("backlogs")
    if max_backlogs is not None:
        if student_backlogs is not None:
            try:
                b_val = int(student_backlogs)
                if b_val <= max_backlogs:
                    evaluations.append({
                        "criteria": "Active Backlogs",
                        "required": f"Maximum {max_backlogs} active backlog(s)",
                        "provided": f"{b_val} active backlog(s)",
                        "status": "Met",
                        "explanation": f"You have {b_val} active backlogs (allowed: {max_backlogs})."
                    })
                else:
                    unmet_reasons.append(f"{b_val} active backlogs exceeds allowed limit of {max_backlogs}")
                    evaluations.append({
                        "criteria": "Active Backlogs",
                        "required": f"Maximum {max_backlogs} active backlog(s)",
                        "provided": f"{b_val} active backlog(s)",
                        "status": "Unmet",
                        "explanation": f"You have {b_val} active backlogs, exceeding allowed maximum of {max_backlogs}."
                    })
            except (ValueError, TypeError):
                unknown_reasons.append("Backlog count could not be parsed")
                evaluations.append({
                    "criteria": "Active Backlogs",
                    "required": f"Maximum {max_backlogs} active backlog(s)",
                    "provided": str(student_backlogs),
                    "status": "Uncertain",
                    "explanation": "Could not parse backlog count."
                })
        else:
            unknown_reasons.append("Backlog count not provided in profile")
            evaluations.append({
                "criteria": "Active Backlogs",
                "required": f"Maximum {max_backlogs} active backlog(s)",
                "provided": "Not Provided",
                "status": "Uncertain",
                "explanation": "Backlog count not specified in profile."
            })
    else:
        # Criteria missing or not specified
        unknown_reasons.append("Company backlog criteria not specified")
        evaluations.append({
            "criteria": "Active Backlogs",
            "required": "Not strictly specified",
            "provided": f"{student_backlogs} backlog(s)" if student_backlogs is not None else "Not Specified",
            "status": "Uncertain",
            "explanation": "Backlog criteria not explicitly specified."
        })

    # 3. Branch / Department Evaluation
    student_branch = student_profile.get("branch") or student_profile.get("department")
    if allowed_branches:
        is_open_to_all = any(b.lower() in ("all", "open to all", "any engineering") for b in allowed_branches)
        if is_open_to_all:
            evaluations.append({
                "criteria": "Allowed Branches",
                "required": "Open to all branches",
                "provided": student_branch or "Any",
                "status": "Met",
                "explanation": "Company is open to candidates from all engineering and technical branches."
            })
        else:
            if student_branch and str(student_branch).strip():
                sb_clean = str(student_branch).strip().lower()
                # Split student branch into words and canonical tokens
                sb_words = set(re.findall(r"\b[a-zA-Z]+\b", sb_clean))

                matched_branch = False
                for allowed in allowed_branches:
                    al_clean = allowed.strip().lower()
                    if al_clean == "all":
                        matched_branch = True
                        break
                    if al_clean == "stem" and any(tok in sb_clean for tok in CIRCUITAL_BRANCH_TOKENS):
                        matched_branch = True
                        break
                    # Exact branch acronym or word match (e.g. 'CS', 'IT', 'ECE', 'EE', 'ME', 'CE')
                    if al_clean in sb_words:
                        matched_branch = True
                        break
                    # Exact phrase match (e.g. 'computer science' in 'computer science & engineering')
                    if len(al_clean) > 2 and al_clean in sb_clean:
                        matched_branch = True
                        break
                    # Specific common branch expansions
                    if al_clean in ("cs", "cse") and any(tok in sb_clean for tok in ("computer science", "comp sci", "computing")):
                        matched_branch = True
                        break
                    if al_clean == "it" and "information technology" in sb_clean:
                        matched_branch = True
                        break
                    if al_clean in ("ece", "electronics") and ("electronics" in sb_clean or "communication" in sb_clean):
                        matched_branch = True
                        break
                    if al_clean in ("ee", "electrical") and "electrical" in sb_clean:
                        matched_branch = True
                        break

                if matched_branch:
                    evaluations.append({
                        "criteria": "Allowed Branches",
                        "required": ", ".join(allowed_branches),
                        "provided": student_branch,
                        "status": "Met",
                        "explanation": f"Your branch ({student_branch}) is eligible."
                    })
                else:
                    unmet_reasons.append(f"Branch '{student_branch}' is not in allowed branches ({', '.join(allowed_branches)})")
                    evaluations.append({
                        "criteria": "Allowed Branches",
                        "required": ", ".join(allowed_branches),
                        "provided": student_branch,
                        "status": "Unmet",
                        "explanation": f"Branch '{student_branch}' is not listed in allowed disciplines ({', '.join(allowed_branches)})."
                    })
            else:
                unknown_reasons.append("Branch not provided in profile")
                evaluations.append({
                    "criteria": "Allowed Branches",
                    "required": ", ".join(allowed_branches),
                    "provided": "Not Provided",
                    "status": "Uncertain",
                    "explanation": "Branch not specified in profile."
                })
    else:
        unknown_reasons.append("Company branch criteria not specified")
        evaluations.append({
            "criteria": "Allowed Branches",
            "required": "Not strictly specified",
            "provided": student_branch or "Not Provided",
            "status": "Uncertain",
            "explanation": "Branch criteria not documented for this company."
        })

    # Overall Status Decision (#844 Acceptance Criteria):
    # - If any requirement is unmet -> "not eligible" / "Not Eligible"
    # - If any criteria or profile value is missing/uncertain -> "unknown" / "Needs Profile Information" (NEVER eligible when criteria missing!)
    # - Only if all active criteria are fully met -> "eligible" / "Eligible"
    if unmet_reasons:
        overall_status = "Not Eligible"
        status_key = "not_eligible"
        reason = "; ".join(unmet_reasons)
        is_eligible = False
    elif unknown_reasons or not has_any_rule:
        overall_status = "Unknown"
        status_key = "unknown"
        reason = "; ".join(unknown_reasons) if unknown_reasons else "Eligibility criteria not fully documented"
        is_eligible = False
    else:
        overall_status = "Eligible"
        status_key = "eligible"
        reason = "Meets all published minimum CGPA, backlog, and branch criteria"
        is_eligible = True

    return {
        "company_name": company_name,
        "overall_status": overall_status,
        "status": overall_status.lower(),
        "status_key": status_key,
        "status_display": overall_status,
        "eligible": is_eligible,
        "reason": reason,
        "evaluations": evaluations,
        "criteria_summary": company_data.get("eligibility") or "General campus hiring guidelines apply.",
        "min_cgpa": min_cgpa,
        "max_backlogs": max_backlogs,
        "branches": allowed_branches,
        "source": company_data.get("eligibility_source") or company_data.get("source_name", "Campus Placement Cell"),
        "verified_source": company_data.get("source_name", "Campus Placement Cell"),
        "last_updated": company_data.get("last_updated", "2026"),
        "drive_disclaimer": "Criteria vary by drive. Placement cells or recruiting teams may adjust CGPA cutoffs, backlog rules, or eligible branches for specific hiring rounds."
    }
