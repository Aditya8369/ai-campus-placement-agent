"""
Calendar conflict detection service (#622).
Detects overlapping preparation tasks and interviews, suggests free slots,
and handles all-day task exclusions and dismissed conflict states.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

def detect_schedule_conflicts(events: List[Dict[str, Any]], dismissed_conflict_keys: List[str] = None) -> Dict[str, Any]:
    dismissed = set(dismissed_conflict_keys or [])
    timed_events = []

    # 1. Parse and filter timed events (all-day tasks don't conflict with timed tasks)
    for ev in events:
        if ev.get("is_all_day"):
            continue
        try:
            start_dt = datetime.fromisoformat(ev["start_time"].replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(ev["end_time"].replace("Z", "+00:00"))
            if end_dt <= start_dt:
                end_dt = start_dt + timedelta(minutes=30)
            timed_events.append({
                "id": ev["id"],
                "title": ev.get("title", "Untitled Task"),
                "start": start_dt,
                "end": end_dt
            })
        except Exception:
            continue

    # 2. Check pairwise overlaps: startA < endB and startB < endA
    conflicts = []
    for i in range(len(timed_events)):
        for j in range(i + 1, len(timed_events)):
            e1 = timed_events[i]
            e2 = timed_events[j]
            pair_key = f"{min(e1['id'], e2['id'])}_{max(e1['id'], e2['id'])}"
            if pair_key in dismissed:
                continue

            if e1["start"] < e2["end"] and e2["start"] < e1["end"]:
                # Suggest alternate free block immediately following the later ending event
                suggested_start = max(e1["end"], e2["end"])
                suggested_end = suggested_start + timedelta(minutes=60)
                conflicts.append({
                    "conflict_key": pair_key,
                    "event_a": {"id": e1["id"], "title": e1["title"], "start": e1["start"].isoformat(), "end": e1["end"].isoformat()},
                    "event_b": {"id": e2["id"], "title": e2["title"], "start": e2["start"].isoformat(), "end": e2["end"].isoformat()},
                    "suggested_slot": {
                        "start_time": suggested_start.isoformat(),
                        "end_time": suggested_end.isoformat()
                    }
                })

    return {
        "success": True,
        "has_conflicts": len(conflicts) > 0,
        "conflict_count": len(conflicts),
        "conflicts": conflicts
    }
