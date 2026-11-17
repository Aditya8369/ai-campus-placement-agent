import tempfile
from pathlib import Path

import config
from utils.database import (
    get_db_connection,
    init_db,
)


def test_database_indexes_exist(monkeypatch):
    """
    Verifies that all performance indexes for frequently queried columns exist.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db_path = Path(tmpdir) / "test_perf_indexes.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db_path)

        init_db()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name, tbl_name FROM sqlite_master WHERE type='index'")
        indexes_by_table = {}
        for row in cursor.fetchall():
            tbl = row["tbl_name"]
            idx = row["name"]
            indexes_by_table.setdefault(tbl, set()).add(idx)
        conn.close()

        # Analyses indexes
        assert "idx_analyses_created_at" in indexes_by_table.get("analyses", set())
        assert "idx_analyses_student_version" in indexes_by_table.get("analyses", set())
        assert "idx_analyses_student_created" in indexes_by_table.get("analyses", set())
        assert "idx_analyses_student_company" in indexes_by_table.get("analyses", set())

        # Job applications indexes
        assert "idx_job_applications_student" in indexes_by_table.get("job_applications", set())
        assert "idx_job_apps_student_status" in indexes_by_table.get("job_applications", set())
        assert "idx_job_apps_student_appdate" in indexes_by_table.get("job_applications", set())
        assert "idx_job_apps_company" in indexes_by_table.get("job_applications", set())
        assert "idx_job_apps_resume_analysis" in indexes_by_table.get("job_applications", set())

        # Interviews indexes
        assert "idx_interviews_analysis_id" in indexes_by_table.get("interviews", set())
        assert "idx_interviews_analysis_completed" in indexes_by_table.get("interviews", set())

        # Interview preparation notes indexes
        assert "idx_prep_notes_student_created" in indexes_by_table.get("interview_preparation_notes", set())
        assert "idx_prep_notes_student_category" in indexes_by_table.get("interview_preparation_notes", set())
        assert "idx_prep_notes_student_updated" in indexes_by_table.get("interview_preparation_notes", set())
        assert "idx_prep_notes_student_cat_updated" in indexes_by_table.get("interview_preparation_notes", set())

        # Preparation activity log indexes
        assert "idx_prep_act_student_date" in indexes_by_table.get("preparation_activity_log", set())
        assert "idx_prep_act_student_date_desc" in indexes_by_table.get("preparation_activity_log", set())
        assert "idx_prep_act_student_created" in indexes_by_table.get("preparation_activity_log", set())
        assert "idx_prep_act_activity_type" in indexes_by_table.get("preparation_activity_log", set())

        # Interview experiences indexes
        assert "idx_experiences_company" in indexes_by_table.get("interview_experiences", set())
        assert "idx_experiences_reported_date" in indexes_by_table.get("interview_experiences", set())
        assert "idx_experiences_student" in indexes_by_table.get("interview_experiences", set())

        # Auth sessions indexes
        assert "idx_auth_sessions_user" in indexes_by_table.get("auth_sessions", set())
        assert "idx_auth_sessions_active" in indexes_by_table.get("auth_sessions", set())

        # Cohort benchmarks indexes
        assert "idx_cohort_overall" in indexes_by_table.get("cohort_benchmarks", set())
        assert "idx_cohort_dept_year" in indexes_by_table.get("cohort_benchmarks", set())
        assert "idx_cohort_dept_score" in indexes_by_table.get("cohort_benchmarks", set())

        # Saved JD indexes
        assert "idx_saved_jd_student_updated" in indexes_by_table.get("saved_job_descriptions", set())
        assert "idx_saved_jd_student_company" in indexes_by_table.get("saved_job_descriptions", set())

        # Calendar events & coding submissions
        assert "idx_calendar_student_completed" in indexes_by_table.get("preparation_calendar_events", set())
        assert "idx_coding_subs_analysis" in indexes_by_table.get("coding_submissions", set())


def test_explain_query_plan_uses_indexes(monkeypatch):
    """
    Verifies through SQLite EXPLAIN QUERY PLAN that frequently run queries
    utilize the newly created indexes rather than doing full table scans.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db_path = Path(tmpdir) / "test_query_plans.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db_path)

        init_db()

        conn = get_db_connection()
        cursor = conn.cursor()

        def get_plan(query: str, params: tuple = ()) -> str:
            cursor.execute(f"EXPLAIN QUERY PLAN {query}", params)
            rows = cursor.fetchall()
            return " ".join(r["detail"] for r in rows)

        # 1. User analyses history query
        plan_analyses = get_plan(
            "SELECT * FROM analyses WHERE student_id = ? ORDER BY created_at DESC",
            ("student_1",)
        )
        assert "idx_analyses_student_created" in plan_analyses

        # 2. Student versions for company query
        plan_versions = get_plan(
            "SELECT * FROM analyses WHERE student_id = ? AND company_name = ? ORDER BY created_at DESC",
            ("student_1", "Google")
        )
        assert ("idx_analyses_student_company" in plan_versions or
                "idx_analyses_student_created" in plan_versions or
                "idx_analyses_student_version" in plan_versions)

        # 3. Job applications filtered by status
        plan_apps_status = get_plan(
            "SELECT * FROM job_applications WHERE student_id = ? AND status = ?",
            ("student_1", "Interview")
        )
        assert "idx_job_apps_student_status" in plan_apps_status

        # 4. Job applications ordered by application date
        plan_apps_date = get_plan(
            "SELECT * FROM job_applications WHERE student_id = ? ORDER BY application_date DESC, created_at DESC",
            ("student_1",)
        )
        assert "idx_job_apps_student_appdate" in plan_apps_date

        # 5. Interview preparation notes ordered by updated_at
        plan_notes = get_plan(
            "SELECT * FROM interview_preparation_notes WHERE student_id = ? ORDER BY updated_at DESC, created_at DESC",
            ("student_1",)
        )
        assert "idx_prep_notes_student_updated" in plan_notes

        # 6. Preparation activities ordered by activity_date DESC
        plan_activities = get_plan(
            "SELECT * FROM preparation_activity_log WHERE student_id = ? ORDER BY activity_date DESC, created_at DESC",
            ("student_1",)
        )
        assert "idx_prep_act_student_date_desc" in plan_activities

        # 7. Active auth sessions
        plan_sessions = get_plan(
            "SELECT * FROM auth_sessions WHERE user_id = ? AND revoked_at IS NULL AND last_seen_at >= ? ORDER BY last_seen_at DESC",
            ("user_1", 1000.0)
        )
        assert "idx_auth_sessions_active" in plan_sessions or "idx_auth_sessions_user" in plan_sessions

        # 8. Department cohort leaderboard
        plan_cohort = get_plan(
            "SELECT * FROM cohort_benchmarks WHERE department = ? ORDER BY overall_score DESC",
            ("Computer Science",)
        )
        assert "idx_cohort_dept_score" in plan_cohort

        conn.close()


def test_init_db_idempotency(monkeypatch):
    """
    Verifies that calling init_db repeatedly does not cause duplicate index or table errors.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db_path = Path(tmpdir) / "test_idempotent.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db_path)

        # Call init_db multiple times
        init_db()
        init_db()
        init_db()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS cnt FROM sqlite_master WHERE type='index'")
        count = cursor.fetchone()["cnt"]
        conn.close()

        assert count > 0
