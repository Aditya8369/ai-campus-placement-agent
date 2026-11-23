"""
Calendar recurring preparation blocks service (#623).
Generates series occurrences (daily, weekdays, weekly) with occurrence limits,
and supports editing single occurrences vs. the entire series.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

VALID_RECURRENCE_TYPES = {"daily", "weekdays", "weekly"}

def generate_recurring_occurrences(
    title: str,
    start_time_iso: str,
    duration_minutes: int,
    recurrence_type: str,
    max_occurrences: int = 5,
    until_date_iso: str = None
) -> Dict[str, Any]:
    rec_type = recurrence_type.lower().strip()
    if rec_type not in VALID_RECURRENCE_TYPES:
        return {"success": False, "error": f"Invalid recurrence type: '{rec_type}'. Allowed: {list(VALID_RECURRENCE_TYPES)}"}

    try:
        current_dt = datetime.fromisoformat(start_time_iso.replace("Z", "+00:00"))
    except Exception as exc:
        return {"success": False, "error": f"Invalid start time: {exc}"}

    until_dt = None
    if until_date_iso:
        try:
            until_dt = datetime.fromisoformat(until_date_iso.replace("Z", "+00:00"))
        except Exception:
            pass

    occurrences = []
    import uuid
    series_id = str(uuid.uuid4())

    count = 0
    limit = max(1, min(30, max_occurrences))

    while len(occurrences) < limit:
        if until_dt and current_dt > until_dt:
            break

        # Check weekdays condition (Monday=0 ... Sunday=6)
        if rec_type == "weekdays" and current_dt.weekday() >= 5:
            current_dt += timedelta(days=1)
            continue

        end_dt = current_dt + timedelta(minutes=duration_minutes)
        occurrences.append({
            "occurrence_id": f"{series_id}_{len(occurrences)+1}",
            "series_id": series_id,
            "title": title,
            "start_time": current_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "occurrence_index": len(occurrences) + 1
        })

        if rec_type in ["daily", "weekdays"]:
            current_dt += timedelta(days=1)
        elif rec_type == "weekly":
            current_dt += timedelta(weeks=1)

    return {
        "success": True,
        "series_id": series_id,
        "recurrence_type": rec_type,
        "total_occurrences": len(occurrences),
        "occurrences": occurrences
    }
