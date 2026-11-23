"""
Account data freshness and stale report indicator service (#628).
Tracks metadata fingerprints (resume upload timestamp, target role, JD hash)
to label whether an analysis report is current or outdated without modifying report content.
"""

from typing import Dict, Any, List

def check_report_freshness(report_meta: Dict[str, Any], current_profile: Dict[str, Any]) -> Dict[str, Any]:
    if not report_meta:
        return {
            "is_fresh": False,
            "stale_reasons": ["Missing report generation metadata."],
            "status_label": "Unknown"
        }

    stale_reasons = []

    # Check resume upload timestamp/version
    if report_meta.get("resume_version") != current_profile.get("resume_version"):
        stale_reasons.append("Resume has been updated since this report was generated.")

    # Check target role match
    report_role = (report_meta.get("target_role") or "").lower().strip()
    current_role = (current_profile.get("target_role") or "").lower().strip()
    if report_role and current_role and report_role != current_role:
        stale_reasons.append(f"Target role changed from '{report_meta.get('target_role')}' to '{current_profile.get('target_role')}'.")

    is_fresh = len(stale_reasons) == 0

    return {
        "success": True,
        "is_fresh": is_fresh,
        "status_label": "Current" if is_fresh else "Outdated",
        "stale_reasons": stale_reasons,
        "reanalysis_recommended": not is_fresh,
        "action_link": "/?reanalyze=true"
    }
