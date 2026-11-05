import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

TIER_1_COMPANIES = {
    "google", "amazon", "microsoft", "meta", "apple", "uber", "netflix",
    "adobe", "salesforce", "atlassian", "linkedin", "goldman sachs", "nvidia"
}
TIER_2_COMPANIES = {
    "flipkart", "swiggy", "zomato", "razorpay", "oracle", "cisco", "paypal",
    "intuit", "morgan stanley", "walmart", "paytm", "jpmorgan", "target", "zoho"
}
TIER_3_COMPANIES = {
    "tcs", "infosys", "wipro", "cognizant", "accenture", "capgemini",
    "hcl", "hcltech", "tech mahindra", "l&t", "mindtree", "deloitte"
}

def determine_company_tier(company_name: str) -> Dict[str, Any]:
    """
    Categorizes the target company into recruitment tiers with tailored
    ATS score and skill match benchmarks.
    """
    normalized = (company_name or "").strip().lower()
    for comp in TIER_1_COMPANIES:
        if comp in normalized:
            return {
                "tier": "Tier 1: Global Tech & Product Leaders",
                "target_ats": 80,
                "target_match": 75,
                "guidance": "High competition tier. Maintain rigorous focus on advanced data structures, system design fundamentals, and quantified metrics in past engineering projects."
            }
    for comp in TIER_2_COMPANIES:
        if comp in normalized:
            return {
                "tier": "Tier 2: High-Growth Product & FinTech",
                "target_ats": 72,
                "target_match": 65,
                "guidance": "Product-oriented tier. Prioritize end-to-end full stack execution, REST API integration, cloud deployment, and production problem-solving."
            }
    for comp in TIER_3_COMPANIES:
        if comp in normalized:
            return {
                "tier": "Tier 3: Enterprise IT & Consulting Services",
                "target_ats": 65,
                "target_match": 55,
                "guidance": "High-volume recruitment tier. Emphasize core programming language fundamentals (Java/Python/C++), SQL proficiency, and aptitude round readiness."
            }
    # General / Startup tier
    return {
        "tier": "General Tech & Startups",
        "target_ats": 70,
        "target_match": 60,
        "guidance": "Demonstrate proactive initiative, rapid technology adoption, practical open-source or hackathon projects, and versatile problem-solving."
    }

def compute_company_benchmark(company_name: str, match_percentage: int, ats_score: int = 70) -> Dict[str, Any]:
    """
    Compares candidate ATS and Job Match metrics against company tier benchmarks.
    """
    tier_info = determine_company_tier(company_name)
    target_ats = tier_info["target_ats"]
    target_match = tier_info["target_match"]

    ats_gap = ats_score - target_ats
    match_gap = match_percentage - target_match

    if ats_score >= target_ats and match_percentage >= target_match:
        status = "Benchmark Exceeded"
        badge = "success"
        assessment = f"Your profile exceeds typical campus recruitment thresholds for {company_name or 'this company'}."
    elif ats_score >= (target_ats - 7) and match_percentage >= (target_match - 7):
        status = "Benchmark Met"
        badge = "primary"
        assessment = f"Your profile meets standard campus recruitment baselines for {company_name or 'this company'}."
    else:
        status = "Below Benchmark"
        badge = "warning"
        assessment = f"Your profile is currently below typical recruitment baselines for {company_name or 'this company'}. Addressing the identified skill gaps will significantly improve selection probability."

    return {
        "company_name": company_name or "General",
        "tier_name": tier_info["tier"],
        "target_ats": target_ats,
        "target_match": target_match,
        "current_ats": ats_score,
        "current_match": match_percentage,
        "ats_gap": ats_gap,
        "match_gap": match_gap,
        "status": status,
        "badge": badge,
        "assessment": assessment,
        "guidance": tier_info["guidance"]
    }

class JobMatchAgent:
    """
    Agent responsible for processing, validating, and structuring the
    Job Match section of the coordinated JSON payload.
    """
    def __init__(self) -> None:
        pass

    def process(self, data: Dict[str, Any], company_name: str = "", ats_score: int = 70) -> Dict[str, Any]:
        """
        Accepts the job_match section from the coordinator JSON,
        validates values, calculates company tier benchmark metrics,
        and returns a clean dictionary.
        """
        logger.info("JobMatchAgent: Starting job match block validation.")
        
        if not isinstance(data, dict):
            logger.warning("JobMatchAgent received malformed or empty data. Creating defaults.")
            data = {}

        # Validate Match Percentage
        raw_percentage = data.get("match_percentage", 0)
        try:
            match_percentage = int(raw_percentage)
        except (ValueError, TypeError):
            logger.warning(f"JobMatchAgent: Invalid match percentage '{raw_percentage}'. Defaulting to 0.")
            match_percentage = 0
            
        match_percentage = max(0, min(100, match_percentage))

        # Calculate recruitment tier benchmarks
        benchmark = compute_company_benchmark(
            company_name=company_name,
            match_percentage=match_percentage,
            ats_score=ats_score
        )

        processed_data = {
            "match_percentage": match_percentage,
            "matched_skills": self._sanitize_string_list(data.get("matched_skills")),
            "missing_skills": self._sanitize_string_list(data.get("missing_skills")),
            "required_certifications": self._sanitize_string_list(data.get("required_certifications")),
            "recommended_improvements": self._sanitize_string_list(data.get("recommended_improvements")),
            "top_5_resume_changes": self._sanitize_string_list(data.get("top_5_resume_changes")),
            "company_benchmark": benchmark
        }

        # Fallback values if top 5 changes list is empty
        if not processed_data["top_5_resume_changes"]:
            processed_data["top_5_resume_changes"] = [
                "Tailor the resume header and summary to highlight relevant keywords.",
                "Explicitly list all matched technical skills in the skills section.",
                "Detail past projects that utilize the missing skills identified.",
                "Incorporate action verbs when describing role responsibilities.",
                "Showcase certifications that demonstrate expertise in core areas."
            ]
        # Keep maximum of 5 changes
        processed_data["top_5_resume_changes"] = processed_data["top_5_resume_changes"][:5]

        logger.info("JobMatchAgent: Job match processing completed.")
        return processed_data

    def _sanitize_string_list(self, raw_list: Any) -> List[str]:
        """
        Helper to sanitize input lists into string lists.
        """
        if isinstance(raw_list, list):
            return [str(item).strip() for item in raw_list if item and str(item).strip()]
        elif isinstance(raw_list, str) and raw_list.strip():
            return [raw_list.strip()]
        return []
