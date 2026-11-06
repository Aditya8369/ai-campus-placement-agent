import pytest
import os
import sqlite3
import json
from unittest.mock import patch
import config
from app import app
from utils.migrations import (
    ensure_migration_table,
    get_applied_migrations,
    get_available_migrations,
    apply_migration,
    run_database_migrations,
    get_migration_status
)


@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_migration_app.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client


def test_migration_table_creation_and_discovery(tmp_path):
    test_db = tmp_path / "mig_test.db"
    conn = sqlite3.connect(str(test_db))

    # 1. Ensure table created
    ensure_migration_table(conn)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
    assert cursor.fetchone() is not None

    # 2. Initially empty
    applied = get_applied_migrations(conn)
    assert applied == []
    conn.close()

    # 3. Available migrations discovered from project migrations folder
    available = get_available_migrations()
    assert len(available) >= 2
    versions = [m["version"] for m in available]
    assert "001_initial_schema" in versions
    assert "002_placement_modules" in versions


def test_custom_migration_execution_and_idempotence(tmp_path):
    mig_dir = tmp_path / "custom_migrations"
    mig_dir.mkdir(parents=True, exist_ok=True)
    test_db = str(tmp_path / "custom_app.db")

    # Create dummy migration 001
    file_1 = mig_dir / "001_create_students_archive.sql"
    file_1.write_text("""
        CREATE TABLE students_archive (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """, encoding="utf-8")

    # Create dummy migration 002
    file_2 = mig_dir / "002_add_email_to_archive.sql"
    file_2.write_text("""
        ALTER TABLE students_archive ADD COLUMN email TEXT;
    """, encoding="utf-8")

    # Run migrations first time
    res1 = run_database_migrations(db_path=test_db, migrations_directory=str(mig_dir))
    assert res1["status"] == "success"
    assert res1["applied_count"] == 2
    assert "001_create_students_archive" in res1["applied_versions"]
    assert "002_add_email_to_archive" in res1["applied_versions"]

    # Verify table and columns exist
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(students_archive)")
    cols = [col[1] for col in cursor.fetchall()]
    assert "id" in cols
    assert "name" in cols
    assert "email" in cols
    conn.close()

    # Run migrations second time (idempotent: 0 applied)
    res2 = run_database_migrations(db_path=test_db, migrations_directory=str(mig_dir))
    assert res2["status"] == "success"
    assert res2["applied_count"] == 0
    assert res2["total_versions"] == 2


def test_migration_failure_rollback(tmp_path):
    mig_dir = tmp_path / "failing_migrations"
    mig_dir.mkdir(parents=True, exist_ok=True)
    test_db = str(tmp_path / "failing_app.db")

    # Valid migration 001
    (mig_dir / "001_valid.sql").write_text("CREATE TABLE test_tab (id INT);", encoding="utf-8")
    # Invalid migration 002 with intentional syntax error
    (mig_dir / "002_broken.sql").write_text("INVALID SQL SYNTAX HERE FAIL;", encoding="utf-8")

    with pytest.raises(Exception):
        run_database_migrations(db_path=test_db, migrations_directory=str(mig_dir))

    # Check status: 001 applied, 002 not applied
    conn = sqlite3.connect(test_db)
    applied = get_applied_migrations(conn)
    assert "001_valid" in applied
    assert "002_broken" not in applied
    conn.close()


def test_migration_status_and_api_endpoints(client, tmp_path):
    test_db = str(tmp_path / "api_test.db")
    with patch.object(config, "DATABASE_PATH", test_db):
        # 1. Check status via API before running
        res_status = client.get("/api/migrations/status")
        assert res_status.status_code == 200
        data_status = json.loads(res_status.data)
        assert data_status["status"] == "success"
        info = data_status["migration_info"]
        assert info["pending_count"] >= 2

        # 2. Run migrations via API
        res_run = client.post("/api/migrations/run")
        assert res_run.status_code == 200
        data_run = json.loads(res_run.data)
        assert data_run["status"] == "success"
        assert data_run["applied_count"] >= 2

        # 3. Check status again (pending should be 0)
        res_status_2 = client.get("/api/migrations/status")
        assert res_status_2.status_code == 200
        data_status_2 = json.loads(res_status_2.data)
        assert data_status_2["migration_info"]["pending_count"] == 0
