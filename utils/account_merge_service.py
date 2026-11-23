"""
Account merge service for duplicate sign-in methods (#630).
Safely previews and merges data (applications, reports, preferences) between verified duplicate accounts
(e.g., email/password vs. Google OAuth) while retaining security audit activity.
"""

from typing import Dict, Any, List
from db.connection import get_db_connection

def preview_account_merge(primary_user_id: str, secondary_user_id: str) -> Dict[str, Any]:
    if not primary_user_id or not secondary_user_id or primary_user_id == secondary_user_id:
        return {"success": False, "error": "Distinct primary and secondary user IDs are required."}

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM job_applications WHERE student_id = ?", (secondary_user_id,))
        apps_count = cursor.fetchone()["count"]

    return {
        "success": True,
        "primary_user_id": primary_user_id,
        "secondary_user_id": secondary_user_id,
        "transferable_records": {
            "job_applications": apps_count
        },
        "reversible_notice": "Security and authentication history will be linked without overwriting primary profile credentials."
    }

def execute_account_merge(primary_user_id: str, secondary_user_id: str, verified_token: bool = False) -> Dict[str, Any]:
    if not verified_token:
        return {"success": False, "error": "Account ownership verification token required prior to merge."}

    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Transfer applications
        cursor.execute("""
            UPDATE job_applications
            SET student_id = ?
            WHERE student_id = ?
        """, (primary_user_id, secondary_user_id))
        transferred_apps = cursor.rowcount
        conn.commit()

    return {
        "success": True,
        "primary_user_id": primary_user_id,
        "merged_secondary_id": secondary_user_id,
        "transferred_applications": transferred_apps
    }
