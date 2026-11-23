"""
Table column visibility and layout preferences service (#636).
Manages customizable visible columns, order, and width preferences for data tables
(applications tracker, student lists, companies) with reset capability.
"""

from typing import Dict, Any, List

DEFAULT_APPLICATION_COLUMNS = [
    {"id": "company_name", "label": "Company", "visible": True, "essential": True},
    {"id": "role_title", "label": "Role", "visible": True, "essential": True},
    {"id": "status", "label": "Status", "visible": True, "essential": True},
    {"id": "application_date", "label": "Applied Date", "visible": True, "essential": False},
    {"id": "location", "label": "Location", "visible": False, "essential": False},
    {"id": "job_type", "label": "Job Type", "visible": False, "essential": False},
    {"id": "deadline_date", "label": "Deadline", "visible": True, "essential": False}
]

def get_table_column_preferences(user_preferences: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    if not user_preferences or not isinstance(user_preferences, dict):
        return [dict(col) for col in DEFAULT_APPLICATION_COLUMNS]

    customized = []
    for col in DEFAULT_APPLICATION_COLUMNS:
        item = dict(col)
        col_id = item["id"]
        if col_id in user_preferences:
            # Essential columns cannot be hidden
            if not item.get("essential"):
                item["visible"] = bool(user_preferences[col_id])
        customized.append(item)

    return customized
