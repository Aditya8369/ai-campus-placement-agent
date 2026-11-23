import pytest
from datetime import datetime, timezone, timedelta
from utils.streak_grace_service import calculate_streak_with_grace

def test_streak_with_grace_period():
    today = datetime.now(timezone.utc).date()
    # Active today, 2 days ago, and 3 days ago (missed yesterday)
    dates = [
        today.isoformat(),
        (today - timedelta(days=2)).isoformat(),
        (today - timedelta(days=3)).isoformat()
    ]
    res = calculate_streak_with_grace(dates, current_date_iso=today.isoformat(), grace_days_allowed=1)
    assert res["success"] is True
    assert res["current_streak"] == 3
    assert res["grace_used"] is True

def test_streak_grace_api(client):
    today = datetime.now(timezone.utc).date().isoformat()
    res = client.post("/api/preparation/streak", json={
        "activity_dates": [today]
    })
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"
    assert res.get_json()["streak"]["current_streak"] == 1
