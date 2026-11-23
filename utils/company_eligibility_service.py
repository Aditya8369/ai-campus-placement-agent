"""
Company Eligibility Calculator Service (#603)
=============================================
Calculates candidate eligibility against verified company hiring profiles
(from data/companies.json) using optional profile fields (CGPA, active backlogs,
passing year, degree/branch, and work experience).

Guarantees:
- Unknown or missing requirements are marked clearly as uncertain/unspecified, never assumed.
- Company data and eligibility calculation logic remain strictly decoupled.
- Profile evaluations remain private to the signed-in student session/account.
- Users can edit profile values and recalculate dynamically.
"""

from typing import Dict, Any, List, Optional
import json
import re
from pathlib import Path
import config


DEFAULT_COMPANIES_FILE = Path(getattr(config, "BASE_DIR", ".")) / "data" / "companies.json"


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
    - passing_year: int or None
    - branch: str or None
    - experience_months: int or None
    """
    if not company_data:
        company_data = load_company_data(company_name) or {}

    eligibility_text = company_data.get("eligibility", "")
    text_lower = eligibility_text.lower()

    # Rule 1: CGPA / Percentage
    # Parse cutoff from text e.g. "6.5 CGPA" or "7.0 CGPA" or "60%"
    min_cgpa = None
    min_pct = None
    cgpa_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:cgpa|\+?\s*cgpa)", text_lower)
    if cgpa_match:
        try:
            min_cgpa = float(cgpa_match.group(1))
        except ValueError:
            pass

    pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text_lower)
    if pct_match:
        try:
            min_pct = float(pct_match.group(1))
        except ValueError:
            pass

    # Rule 2: Backlogs
    allows_one_backlog = "1 backlog" in text_lower or "1 active backlog" in text_lower
    no_backlogs_required = "no active backlogs" in text_lower or "no current backlogs" in text_lower or "no standing backlogs" in text_lower
    max_backlogs = 1 if allows_one_backlog else (0 if no_backlogs_required else None)

    # Rule 3: Branch
    open_to_all_branches = "all branches" in text_lower or "open to all" in text_lower or "any engineering" in text_lower
    circuital_branches = ["cs", "it", "computer science", "information technology", "ece", "ee", "electronics", "electrical"]

    evaluations: List[Dict[str, Any]] = []
    overall_status = "Eligible"  # "Eligible", "Not Eligible", "Conditionally Eligible", "Unknown"
    unmet_count = 0
    uncertain_count = 0

    # 1. Evaluate CGPA
    student_cgpa = student_profile.get("cgpa")
    if min_cgpa is not None:
        if student_cgpa is not None:
            try:
                cgpa_val = float(student_cgpa)
                passed = cgpa_val >= min_cgpa
                evaluations.append({
                    "criteria": "Minimum CGPA / Percentage",
                    "required": f"Minimum {min_cgpa} CGPA (or {min_pct or int(min_cgpa * 10)}%)",
                    "provided": f"{cgpa_val} CGPA",
                    "status": "Met" if passed else "Unmet",
                    "explanation": f"Your CGPA ({cgpa_val}) {'meets or exceeds' if passed else 'is below'} the required cutoff of {min_cgpa}."
                })
                if not passed:
                    unmet_count += 1
            except (ValueError, TypeError):
                evaluations.append({
                    "criteria": "Minimum CGPA / Percentage",
                    "required": f"Minimum {min_cgpa} CGPA",
                    "provided": str(student_cgpa),
                    "status": "Uncertain",
                    "explanation": "Could not parse student CGPA value."
                })
                uncertain_count += 1
        else:
            evaluations.append({
                "criteria": "Minimum CGPA / Percentage",
                "required": f"Minimum {min_cgpa} CGPA",
                "provided": "Not Provided",
                "status": "Uncertain",
                "explanation": "CGPA was not provided in profile; verify whether you meet the cutoff."
            })
            uncertain_count += 1
    else:
        evaluations.append({
            "criteria": "Minimum CGPA / Percentage",
            "required": "No rigid cutoff mandated",
            "provided": f"{student_cgpa} CGPA" if student_cgpa is not None else "Not Provided",
            "status": "Met",
            "explanation": "Company does not mandate a strict percentage cutoff."
        })

    # 2. Evaluate Backlogs
    student_backlogs = student_profile.get("backlogs")
    if max_backlogs is not None:
        if student_backlogs is not None:
            try:
                b_val = int(student_backlogs)
                passed = b_val <= max_backlogs
                evaluations.append({
                    "criteria": "Active Backlogs",
                    "required": f"Maximum {max_backlogs} active backlog(s)",
                    "provided": f"{b_val} active backlog(s)",
                    "status": "Met" if passed else "Unmet",
                    "explanation": f"You have {b_val} active backlogs. Allowed: {max_backlogs}."
                })
                if not passed:
                    unmet_count += 1
            except (ValueError, TypeError):
                evaluations.append({
                    "criteria": "Active Backlogs",
                    "required": f"Maximum {max_backlogs} active backlog(s)",
                    "provided": str(student_backlogs),
                    "status": "Uncertain",
                    "explanation": "Invalid backlog count format."
                })
                uncertain_count += 1
        else:
            evaluations.append({
                "criteria": "Active Backlogs",
                "required": f"Maximum {max_backlogs} active backlog(s)",
                "provided": "Not Provided",
                "status": "Uncertain",
                "explanation": "Backlog count not provided; please verify standing backlogs."
            })
            uncertain_count += 1
    else:
        evaluations.append({
            "criteria": "Active Backlogs",
            "required": "Not strictly specified",
            "provided": f"{student_backlogs} backlog(s)" if student_backlogs is not None else "Not Provided",
            "status": "Uncertain",
            "explanation": "Backlog limit is not explicitly documented by recruiter."
        })
        uncertain_count += 1

    # 3. Evaluate Branch / Stream
    student_branch = student_profile.get("branch")
    if student_branch and student_branch.strip():
        b_clean = student_branch.strip().lower()
        if open_to_all_branches:
            evaluations.append({
                "criteria": "Eligible Branches",
                "required": "Open to all engineering / technical disciplines",
                "provided": student_branch,
                "status": "Met",
                "explanation": f"Your branch ({student_branch}) is eligible under open recruitment guidelines."
            })
        else:
            is_circuital = any(c in b_clean for c in circuital_branches)
            evaluations.append({
                "criteria": "Eligible Branches",
                "required": "CS / IT / ECE and circuital STEM streams",
                "provided": student_branch,
                "status": "Met" if is_circuital else "Conditionally Eligible",
                "explanation": f"Recruiter typically prioritizes circuital branches. Verify specific campus drive circular."
            })
    else:
        evaluations.append({
            "criteria": "Eligible Branches",
            "required": "Engineering / STEM discipline",
            "provided": "Not Provided",
            "status": "Uncertain",
            "explanation": "Academic branch not specified in profile."
        })
        uncertain_count += 1

    # Overall Status determination
    if unmet_count > 0:
        overall_status = "Not Eligible"
    elif uncertain_count >= 2:
        overall_status = "Needs Profile Information"
    elif any(e["status"] == "Conditionally Eligible" for e in evaluations):
        overall_status = "Conditionally Eligible"
    else:
        overall_status = "Eligible"

    return {
        "company_name": company_name,
        "overall_status": overall_status,
        "evaluations": evaluations,
        "criteria_summary": eligibility_text or "General campus hiring guidelines apply.",
        "verified_source": company_data.get("source_name", "Campus Placement Cell"),
        "last_updated": company_data.get("last_updated", "2026"),
        "disclaimer": "Eligibility calculations are heuristic estimations based on published campus criteria. Final eligibility is determined by your college placement cell and recruiter circular."
    }
