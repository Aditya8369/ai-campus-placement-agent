"""
Personal preparation burnout warning service (#625).
Evaluates study hours across consecutive days, detects heavy workloads,
and provides gentle recommendations for recovery without framing as medical diagnoses.
Users can disable or dismiss burnout warnings at any time.
"""

from typing import Dict, Any, List

def evaluate_burnout_risk(daily_hours_last_7_days: List[float], max_daily_threshold: float = 7.0, reminders_enabled: bool = True) -> Dict[str, Any]:
    if not reminders_enabled or not daily_hours_last_7_days:
        return {
            "success": True,
            "reminders_enabled": reminders_enabled,
            "warning_triggered": False,
            "recommendation": "Burnout reminders are disabled or no study data is recorded."
        }

    valid_hours = [float(h) for h in daily_hours_last_7_days if h is not None]
    if not valid_hours:
        return {
            "success": True,
            "reminders_enabled": reminders_enabled,
            "warning_triggered": False,
            "recommendation": "No recent preparation sessions recorded."
        }

    total_hours = sum(valid_hours)
    avg_hours = round(total_hours / len(valid_hours), 1)
    heavy_days_count = sum(1 for h in valid_hours if h >= max_daily_threshold)

    # Trigger warning if >= 4 heavy days or consecutive 3 days > max_daily_threshold
    warning_triggered = (heavy_days_count >= 4) or (len(valid_hours) >= 3 and all(h >= max_daily_threshold for h in valid_hours[-3:]))

    if warning_triggered:
        recommendation = (
            f"You have prepared for {avg_hours} hours/day recently across {heavy_days_count} high-intensity sessions. "
            "Consider scheduling a lighter recovery day or a relaxed review session to recharge."
        )
    else:
        recommendation = "Your preparation pace is steady and sustainable."

    return {
        "success": True,
        "reminders_enabled": True,
        "warning_triggered": warning_triggered,
        "total_study_hours": round(total_hours, 1),
        "average_daily_hours": avg_hours,
        "heavy_days_count": heavy_days_count,
        "recommendation": recommendation,
        "disclaimer": "This study cadence notice is an educational productivity tool, not a medical or psychological diagnosis."
    }
