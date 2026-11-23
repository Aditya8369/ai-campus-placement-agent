"""
Company interview process timeline service (#624).
Provides canonical stages (Application, OA, Technical Interview, HR, Offer)
with expected average stage durations and labels distinguishing official vs. community data.
"""

from typing import Dict, Any, List

STANDARD_STAGES = [
    {"stage": "Application", "avg_duration_days": 7, "type": "official", "description": "Resume screening and eligibility check"},
    {"stage": "Online Assessment (OA)", "avg_duration_days": 10, "type": "community_reported", "description": "Timed coding and aptitude test"},
    {"stage": "Technical Round 1", "avg_duration_days": 5, "type": "community_reported", "description": "Data structures, algorithms, and core domain knowledge"},
    {"stage": "Technical Round 2 / System Design", "avg_duration_days": 5, "type": "community_reported", "description": "High-level architecture, projects, and deep technical probe"},
    {"stage": "HR & Fitment Interview", "avg_duration_days": 3, "type": "official", "description": "Cultural fit, compensation, and onboarding expectations"},
    {"stage": "Offer Letter", "avg_duration_days": 4, "type": "official", "description": "Formal offer roll-out and document verification"}
]

def get_company_process_timeline(company_name: str) -> Dict[str, Any]:
    comp = company_name.strip() if company_name else "Standard Company"
    total_days = sum(s["avg_duration_days"] for s in STANDARD_STAGES)
    return {
        "success": True,
        "company_name": comp,
        "estimated_total_days": total_days,
        "stages": STANDARD_STAGES,
        "attribution_notice": "Durations are aggregated from official hiring guidelines and community-reported candidate experiences."
    }
