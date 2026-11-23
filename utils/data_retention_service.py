"""
Account data retention policy service (#629).
Configures student retention windows (30 days, 90 days, 1 year, indefinite)
for mock interview recordings, temporary drafts, and reports while maintaining mandatory security logs.
"""

from typing import Dict, Any, List

RETENTION_POLICIES = {
    "30_days": {"days": 30, "label": "30 Days", "description": "Purge drafts and audio records older than 30 days."},
    "90_days": {"days": 90, "label": "90 Days", "description": "Purge drafts and audio records older than 90 days."},
    "365_days": {"days": 365, "label": "1 Year", "description": "Purge drafts and audio records older than 1 year."},
    "indefinite": {"days": None, "label": "No Automatic Deletion", "description": "Keep all reports until manually deleted."}
}

DEFAULT_POLICY = "indefinite"

def validate_retention_policy(policy_key: str) -> Dict[str, Any]:
    clean_key = (policy_key or "").lower().strip()
    if clean_key not in RETENTION_POLICIES:
        return {
            "valid": False,
            "error": f"Invalid retention policy '{clean_key}'. Allowed: {list(RETENTION_POLICIES.keys())}"
        }
    cfg = RETENTION_POLICIES[clean_key]
    return {
        "valid": True,
        "policy_key": clean_key,
        "label": cfg["label"],
        "days": cfg["days"],
        "description": cfg["description"],
        "security_note": "Core account credentials and security audit logs are retained in accordance with institutional policy."
    }
