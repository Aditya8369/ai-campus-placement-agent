"""
Preparation streak grace period service (#626).
Protects preparation streaks when a candidate misses an isolated day due to illness or emergency.
Limits grace periods to prevent repeated exploitation and preserves authentic date history.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Set

def calculate_streak_with_grace(activity_dates_iso: List[str], current_date_iso: str = None, grace_days_allowed: int = 1) -> Dict[str, Any]:
    if not current_date_iso:
        today = datetime.now(timezone.utc).date()
    else:
        try:
            today = datetime.strptime(current_date_iso[:10], "%Y-%m-%d").date()
        except Exception:
            today = datetime.now(timezone.utc).date()

    date_set: Set = set()
    for d_str in activity_dates_iso:
        try:
            date_set.add(datetime.strptime(d_str[:10], "%Y-%m-%d").date())
        except Exception:
            pass

    if not date_set:
        return {
            "success": True,
            "current_streak": 0,
            "grace_used": False,
            "streak_at_risk": False,
            "message": "No activity recorded yet."
        }

    # Count consecutive backwards
    streak = 0
    grace_used = False
    grace_remaining = max(0, min(2, grace_days_allowed))

    check_date = today
    # If student didn't practice today, check if yesterday was active
    if check_date not in date_set:
        if (check_date - timedelta(days=1)) in date_set:
            streak_at_risk = True
            check_date = check_date - timedelta(days=1)
        else:
            # Check if grace period covers yesterday
            if grace_remaining > 0 and (check_date - timedelta(days=2)) in date_set:
                grace_used = True
                grace_remaining -= 1
                streak_at_risk = True
                check_date = check_date - timedelta(days=2)
            else:
                return {
                    "success": True,
                    "current_streak": 0,
                    "grace_used": False,
                    "streak_at_risk": False,
                    "message": "Streak reset due to inactive days exceeding grace allowance."
                }
    else:
        streak_at_risk = False

    while True:
        if check_date in date_set:
            streak += 1
            check_date -= timedelta(days=1)
        elif grace_remaining > 0 and not grace_used and (check_date - timedelta(days=1)) in date_set:
            grace_used = True
            grace_remaining -= 1
            check_date -= timedelta(days=1)
        else:
            break

    return {
        "success": True,
        "current_streak": streak,
        "grace_used": grace_used,
        "streak_at_risk": streak_at_risk,
        "message": f"Active streak of {streak} days." + (" (Grace period applied for 1 missed day)" if grace_used else "")
    }
