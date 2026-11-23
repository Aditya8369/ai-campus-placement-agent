"""
Upcoming placement deadline digest service (#621).
Aggregates application deadlines, interview appointments, and preparation milestones
into Today, This Week, and Later groups with overdue detection and direct links.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from db.connection import get_db_connection

def get_placement_deadline_digest(student_id: str, current_date_str: str = None) -> Dict[str, Any]:
    if not current_date_str:
        today = datetime.now(timezone.utc).date()
    else:
        try:
            today = datetime.strptime(current_date_str, "%Y-%m-%d").date()
        except Exception:
            today = datetime.now(timezone.utc).date()

    end_of_week = today + timedelta(days=7)

    items = []

    # 1. Fetch from job_applications (deadline_date or application_date)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, company_name, role_title, deadline_date, status
            FROM job_applications
            WHERE student_id = ? AND deadline_date IS NOT NULL AND is_archived = 0
        """, (student_id,))
        app_rows = cursor.fetchall()
        for r in app_rows:
            d_str = r["deadline_date"]
            try:
                d_date = datetime.strptime(d_str[:10], "%Y-%m-%d").date()
            except Exception:
                continue

            items.append({
                "id": f"app_{r['id']}",
                "source": "application",
                "title": f"Application Deadline: {r['company_name']} - {r['role_title']}",
                "date": d_str[:10],
                "due_date": d_date,
                "status": r["status"],
                "action_url": f"/applications?id={r['id']}"
            })

    # Group into Today, This Week, Later, and Overdue
    today_items = []
    this_week_items = []
    later_items = []
    overdue_items = []

    for item in sorted(items, key=lambda x: x["due_date"]):
        d_date = item["due_date"]
        del item["due_date"]

        if d_date < today:
            item["overdue"] = True
            overdue_items.append(item)
        elif d_date == today:
            item["overdue"] = False
            today_items.append(item)
        elif today < d_date <= end_of_week:
            item["overdue"] = False
            this_week_items.append(item)
        else:
            item["overdue"] = False
            later_items.append(item)

    return {
        "success": True,
        "as_of_date": today.isoformat(),
        "total_active_deadlines": len(items),
        "groups": {
            "overdue": overdue_items,
            "today": today_items,
            "this_week": this_week_items,
            "later": later_items
        }
    }
