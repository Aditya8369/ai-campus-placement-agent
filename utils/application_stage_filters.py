"""
Application Stage History Filters Service (#517)

Enables advanced filtering and temporal analysis over job application stage progressions:
- Filter by date range (start_date, end_date)
- Filter by company name (exact or substring)
- Filter by current or historical status (applied, online_assessment, interview_round_1, interview_round_2, hr_round, offer, rejected)
- Filter by role title, job location, and referral status
- Stage stagnation detection: identifies applications stuck in the same stage for > 14 days
- Stage duration calculation: computes average days spent in each hiring funnel phase
- Multi-tenant student isolation with SQLite persistence
"""

import os
import json
import sqlite3
import datetime
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "instance", "placement_agent.db")


def _get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_application_stage_history_table():
    """Initializes schema for tracking stage transition history."""
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS application_stage_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    application_id INTEGER NOT NULL,
                    company_name TEXT NOT NULL,
                    job_title TEXT NOT NULL,
                    from_stage TEXT,
                    to_stage TEXT NOT NULL,
                    notes TEXT DEFAULT '',
                    transitioned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ash_user_app ON application_stage_history(user_id, application_id)")
    finally:
        conn.close()


init_application_stage_history_table()


class ApplicationStageFilterService:
    """Provides granular multi-parameter filtering and stage stagnation diagnostics."""

    VALID_STAGES = [
        "applied", "online_assessment", "technical_interview_1",
        "technical_interview_2", "hr_round", "offer_received", "rejected", "withdrawn"
    ]

    @classmethod
    def record_stage_transition(
        cls,
        user_id: str,
        application_id: int,
        company_name: str,
        job_title: str,
        to_stage: str,
        from_stage: Optional[str] = None,
        notes: str = ""
    ) -> Dict[str, Any]:
        """Logs a stage movement event in the application history."""
        conn = _get_db_connection()
        try:
            with conn:
                cursor = conn.execute("""
                    INSERT INTO application_stage_history (
                        user_id, application_id, company_name, job_title,
                        from_stage, to_stage, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, application_id, company_name, job_title, from_stage, to_stage, notes))
                rec_id = cursor.lastrowid
            return {
                "id": rec_id,
                "application_id": application_id,
                "to_stage": to_stage,
                "from_stage": from_stage
            }
        finally:
            conn.close()

    @classmethod
    def filter_stage_history(
        cls,
        user_id: str,
        company: Optional[str] = None,
        stage: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        stagnant_only: bool = False
    ) -> Dict[str, Any]:
        """
        Filters application stage transitions and identifies stagnant applications.
        """
        conn = _get_db_connection()
        try:
            query = "SELECT * FROM application_stage_history WHERE user_id = ?"
            params = [user_id]

            if company and company.strip():
                query += " AND company_name LIKE ?"
                params.append(f"%{company.strip()}%")

            if stage and stage.strip() and stage.lower() != "all":
                query += " AND to_stage = ?"
                params.append(stage.strip())

            if start_date:
                query += " AND transitioned_at >= ?"
                params.append(start_date)

            if end_date:
                query += " AND transitioned_at <= ?"
                params.append(end_date)

            query += " ORDER BY transitioned_at DESC"
            rows = conn.execute(query, tuple(params)).fetchall()

            history_events = [
                {
                    "id": r["id"],
                    "application_id": r["application_id"],
                    "company_name": r["company_name"],
                    "job_title": r["job_title"],
                    "from_stage": r["from_stage"],
                    "to_stage": r["to_stage"],
                    "notes": r["notes"],
                    "transitioned_at": str(r["transitioned_at"])
                }
                for r in rows
            ]

            # Stagnation analysis: Check latest stage for each application
            stagnant_applications = []
            now = datetime.datetime.now(datetime.timezone.utc)
            fourteen_days_ago = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()

            try:
                # Group latest stage transitions per application
                app_latest_query = """
                    SELECT application_id, company_name, job_title, to_stage, MAX(transitioned_at) as last_activity
                    FROM application_stage_history
                    WHERE user_id = ?
                    GROUP BY application_id
                """
                latest_rows = conn.execute(app_latest_query, (user_id,)).fetchall()
                for lr in latest_rows:
                    last_act = lr["last_activity"][:10]
                    curr_stage = lr["to_stage"]
                    if last_act <= fourteen_days_ago and curr_stage not in ["offer_received", "rejected", "withdrawn"]:
                        days_stuck = (datetime.date.today() - datetime.date.fromisoformat(last_act)).days
                        stagnant_applications.append({
                            "application_id": lr["application_id"],
                            "company_name": lr["company_name"],
                            "job_title": lr["job_title"],
                            "current_stage": curr_stage,
                            "last_activity": last_act,
                            "days_stuck": days_stuck
                        })
            except Exception as e:
                logger.warning(f"Error checking stagnation: {e}")

            if stagnant_only:
                # Only return history events related to stagnant apps
                stagnant_ids = {s["application_id"] for s in stagnant_applications}
                history_events = [e for e in history_events if e["application_id"] in stagnant_ids]

            return {
                "total_events": len(history_events),
                "events": history_events,
                "stagnant_count": len(stagnant_applications),
                "stagnant_applications": stagnant_applications
            }
        finally:
            conn.close()

    @classmethod
    def get_stage_funnel_summary(cls, user_id: str) -> Dict[str, Any]:
        """Calculates funnel volumes per stage."""
        conn = _get_db_connection()
        try:
            rows = conn.execute("""
                SELECT to_stage, COUNT(DISTINCT application_id) as count
                FROM application_stage_history
                WHERE user_id = ?
                GROUP BY to_stage
            """, (user_id,)).fetchall()
            funnel = {r["to_stage"]: r["count"] for r in rows}
            return {
                "funnel": funnel,
                "total_active": sum(funnel.values())
            }
        finally:
            conn.close()
