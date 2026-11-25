"""
tests/test_seed_data.py
Unit & Integration Tests for Reproducible Local Development Seed Command (#task-seed-command).

Validates:
1. Database resolution targets an isolated development database by default.
2. Seeding populates realistic synthetic data across users, student profiles,
   analyses (with multi-version ATS progression), interviews (with STAR answers),
   and job applications (spanning Applied, Screening, Interviewing, Offer, Rejected).
3. Seed data is clearly distinguished from real user data ([SEED] tags, seed_* IDs, @seed.local domain).
4. Safe reset purges ONLY synthetic seed records, leaving user-created records untouched.
5. Seed status reporting accurately tallies seed vs user records.
"""

import sqlite3
from pathlib import Path
import pytest
from werkzeug.security import check_password_hash

from utils.seed_data import (
    resolve_target_database,
    seed_development_data,
    reset_seed_data,
    get_seed_status,
    DEFAULT_STUDENT_EMAIL,
    DEFAULT_STUDENT_PASSWORD,
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_PASSWORD,
    SEED_ID_PREFIX,
    SEED_EMAIL_DOMAIN,
    SEED_TAG,
)


def test_resolve_target_database_defaults_to_dev(tmp_path):
    """Verify target database defaults to isolated development database."""
    target_dev = resolve_target_database(use_dev=True)
    assert target_dev.name == "placement_agent_dev.db"

    custom = tmp_path / "custom_test.db"
    target_custom = resolve_target_database(db_path=custom)
    assert target_custom == custom


def test_seed_development_data_populates_all_tables(tmp_path):
    """Verify seeding creates full synthetic dataset for dashboards, applications, interviews, and notes."""
    test_db = tmp_path / "test_seed.db"
    result = seed_development_data(db_path=test_db, reset_first=True, quiet=True)

    assert result["status"] == "success"
    counts = result["seeded_counts"]
    assert counts["users"] == 2
    assert counts["analyses"] >= 4
    assert counts["interviews"] >= 3
    assert counts["job_applications"] >= 5

    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Verify Users & Password Hashes
    cursor.execute("SELECT * FROM users WHERE email = ?", (DEFAULT_STUDENT_EMAIL,))
    student = cursor.fetchone()
    assert student is not None
    assert SEED_TAG in student["name"]
    assert check_password_hash(student["password_hash"], DEFAULT_STUDENT_PASSWORD)

    cursor.execute("SELECT * FROM users WHERE email = ?", (DEFAULT_ADMIN_EMAIL,))
    admin = cursor.fetchone()
    assert admin is not None
    assert check_password_hash(admin["password_hash"], DEFAULT_ADMIN_PASSWORD)

    # 2. Verify Analyses (Historical Revisions for Trend Line Progression)
    cursor.execute("SELECT id, company_name, version_number FROM analyses WHERE student_id = 'seed_student_demo' ORDER BY version_number ASC")
    analyses = cursor.fetchall()
    assert len(analyses) >= 3
    assert analyses[0]["version_number"] == 1
    assert analyses[1]["version_number"] == 2
    assert analyses[2]["version_number"] == 3

    # 3. Verify Job Applications Across Pipeline Stages
    cursor.execute("SELECT DISTINCT status FROM job_applications WHERE student_id = 'seed_student_demo'")
    statuses = {row["status"] for row in cursor.fetchall()}
    assert "Offer" in statuses
    assert "Applied" in statuses
    assert "Screening" in statuses
    assert "Technical Interview" in statuses
    assert "Rejected" in statuses

    # 4. Verify Completed and In-Progress Mock Interviews
    cursor.execute("SELECT id, completed FROM interviews WHERE id LIKE 'seed_%'")
    interviews = cursor.fetchall()
    assert len(interviews) >= 3
    completed_flags = {row["completed"] for row in interviews}
    assert 1 in completed_flags  # Completed interview session
    assert 0 in completed_flags  # In-progress draft session

    conn.close()


def test_seed_data_clearly_distinguished(tmp_path):
    """Verify every synthetic seed item carries explicit unambiguous markers."""
    test_db = tmp_path / "test_markers.db"
    seed_development_data(db_path=test_db, reset_first=True, quiet=True)

    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Check ID prefixes
    for table in ["analyses", "interviews", "job_applications", "interview_preparation_notes"]:
        cursor.execute(f"SELECT id FROM {table}")
        for row in cursor.fetchall():
            assert row["id"].startswith(SEED_ID_PREFIX), f"Record {row['id']} in {table} must start with {SEED_ID_PREFIX}"

    # Check Email Domains
    cursor.execute("SELECT email FROM users")
    for row in cursor.fetchall():
        assert row["email"].endswith(SEED_EMAIL_DOMAIN)

    # Check Job Application Notes
    cursor.execute("SELECT notes FROM job_applications")
    for row in cursor.fetchall():
        assert SEED_TAG in row["notes"]

    conn.close()


def test_safe_reset_removes_only_seed_data(tmp_path):
    """Verify that reset_seed_data() purges seed data while preserving real user data."""
    test_db = tmp_path / "test_safe_reset.db"
    seed_development_data(db_path=test_db, reset_first=True, quiet=True)

    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()

    # Insert genuine user records
    cursor.execute("""
        INSERT INTO users (id, name, email, password_hash)
        VALUES ('real_user_123', 'Real Student Jane', 'jane.doe@university.edu', 'hashed_pw_xyz')
    """)
    cursor.execute("""
        INSERT INTO analyses (id, resume_filename, company_name, results_json, student_id)
        VALUES ('real_analysis_999', 'jane_real_resume.pdf', 'Apple', '{}', 'real_user_123')
    """)
    cursor.execute("""
        INSERT INTO job_applications (id, student_id, company_name, role_title, application_date)
        VALUES ('real_app_555', 'real_user_123', 'Apple', 'iOS Engineer', '2026-11-20')
    """)
    conn.commit()
    conn.close()

    # Perform safe reset
    reset_result = reset_seed_data(db_path=test_db, reset_all=False)
    assert reset_result["deleted_seed_records"] > 0

    # Verify seed records are gone, but real user data remains
    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Real user must still exist
    cursor.execute("SELECT * FROM users WHERE id = 'real_user_123'")
    assert cursor.fetchone() is not None

    # Real analysis must still exist
    cursor.execute("SELECT * FROM analyses WHERE id = 'real_analysis_999'")
    assert cursor.fetchone() is not None

    # Real application must still exist
    cursor.execute("SELECT * FROM job_applications WHERE id = 'real_app_555'")
    assert cursor.fetchone() is not None

    # All seed records must be gone
    cursor.execute("SELECT COUNT(*) FROM analyses WHERE id LIKE 'seed_%'")
    assert cursor.fetchone()[0] == 0

    cursor.execute("SELECT COUNT(*) FROM job_applications WHERE id LIKE 'seed_%'")
    assert cursor.fetchone()[0] == 0

    cursor.execute("SELECT COUNT(*) FROM users WHERE email LIKE '%@seed.local'")
    assert cursor.fetchone()[0] == 0

    conn.close()


def test_seed_status_reporting(tmp_path):
    """Verify get_seed_status accurately differentiates seed from user records."""
    test_db = tmp_path / "test_status.db"
    seed_development_data(db_path=test_db, reset_first=True, quiet=True)

    # Insert 1 user record
    conn = sqlite3.connect(test_db)
    conn.execute("INSERT INTO users (id, name, email, password_hash) VALUES ('usr_1', 'John', 'john@test.edu', 'pw')")
    conn.commit()
    conn.close()

    status = get_seed_status(db_path=test_db)
    assert status["database_exists"] is True
    counts = status["counts"]
    assert counts["users"]["seed"] == 2
    assert counts["users"]["user_created"] == 1
    assert counts["users"]["total"] == 3
    assert counts["job_applications"]["seed"] >= 5
    assert counts["job_applications"]["user_created"] == 0
