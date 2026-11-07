import os
import sqlite3
import tempfile
import pytest
from pathlib import Path

import config
from utils.database import init_db, get_db_connection
from utils.backup_restoration import (
    get_backup_storage_directory,
    list_available_backups,
    validate_backup_file,
    create_pre_restoration_safety_snapshot,
    restore_database_from_backup,
    BackupRestorationError
)
from app import app


@pytest.fixture
def test_environment(tmp_path, monkeypatch):
    """Sets up an isolated database, backup folder, and app testing context."""
    db_file = tmp_path / "test_live_app.db"
    backup_folder = tmp_path / "backups"
    backup_folder.mkdir()

    monkeypatch.setattr(config, "DATABASE_PATH", str(db_file))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "BACKUP_DIR", str(backup_folder))
    monkeypatch.setattr(config, "ADMIN_SECRET_KEY", "test-secret-key-999")

    # Initialize live DB schema
    init_db()

    # Seed live test analysis
    conn = get_db_connection()
    conn.execute("INSERT INTO analyses (id, resume_filename, company_name, job_description, results_json) VALUES (?, ?, ?, ?, ?)",
                 ("analysis_original_live", "resume1.pdf", "Google", "SWE", "{}"))
    conn.commit()
    conn.close()

    app.config["TESTING"] = True
    with app.test_client() as client:
        yield {
            "client": client,
            "db_path": str(db_file),
            "backup_dir": str(backup_folder),
            "tmp_path": tmp_path
        }


def _create_sample_valid_backup(filepath: str, extra_records_count: int = 3):
    """Helper to create a structurally compliant backup sqlite database."""
    conn = sqlite3.connect(filepath)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT,
            email TEXT,
            password_hash TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id TEXT PRIMARY KEY,
            resume_filename TEXT NOT NULL,
            company_name TEXT NOT NULL,
            job_description TEXT,
            results_json TEXT NOT NULL,
            student_id TEXT DEFAULT 'default_student',
            version_number INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS interviews (
            id TEXT PRIMARY KEY,
            analysis_id TEXT NOT NULL,
            current_question_index INTEGER DEFAULT 0,
            answers_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Seed data
    for i in range(extra_records_count):
        cursor.execute("INSERT INTO analyses (id, resume_filename, company_name, results_json) VALUES (?, ?, ?, ?)",
                       (f"backup_rec_{i}", f"res_{i}.pdf", f"TargetCo_{i}", "{}"))
    conn.commit()
    conn.close()


def test_list_available_backups(test_environment):
    backup_dir = test_environment["backup_dir"]
    b1 = os.path.join(backup_dir, "backup_alpha.db")
    b2 = os.path.join(backup_dir, "backup_beta.db")
    _create_sample_valid_backup(b1)
    _create_sample_valid_backup(b2)

    # Put a non-db file to check filtering
    with open(os.path.join(backup_dir, "notes.txt"), "w") as f:
        f.write("ignore me")

    backups = list_available_backups()
    assert len(backups) == 2
    filenames = [b["filename"] for b in backups]
    assert "backup_alpha.db" in filenames
    assert "backup_beta.db" in filenames


def test_validate_backup_file_success(test_environment):
    backup_file = os.path.join(test_environment["backup_dir"], "valid_test_backup.db")
    _create_sample_valid_backup(backup_file, extra_records_count=5)

    res = validate_backup_file(backup_file)
    assert res["valid"] is True
    assert len(res["errors"]) == 0
    assert "analyses" in res["tables"]
    assert res["table_counts"]["analyses"] == 5


def test_validate_backup_corrupted_file(test_environment):
    # Test non-existent file
    assert validate_backup_file("/non/existent/path.db")["valid"] is False

    # Test corrupted random garbage file
    corrupt_file = os.path.join(test_environment["backup_dir"], "corrupt.db")
    with open(corrupt_file, "wb") as f:
        f.write(b"NOT A SQLITE HEADER AND TOTALLY INVALID BYTES" * 10)

    res = validate_backup_file(corrupt_file)
    assert res["valid"] is False
    assert any("header" in err.lower() or "sqlite" in err.lower() or "small" in err.lower() for err in res["errors"])


def test_validate_backup_missing_mandatory_schema(test_environment):
    incomplete_db = os.path.join(test_environment["backup_dir"], "incomplete.db")
    conn = sqlite3.connect(incomplete_db)
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    res = validate_backup_file(incomplete_db)
    assert res["valid"] is False
    assert any("mandatory table" in err.lower() for err in res["errors"])


def test_safety_snapshot_creation(test_environment):
    safety_path = create_pre_restoration_safety_snapshot()
    assert os.path.exists(safety_path)
    assert os.path.getsize(safety_path) > 0
    assert "safety_prerestore" in safety_path

    # Verify safety snapshot is valid database containing live record
    conn = sqlite3.connect(safety_path)
    row = conn.execute("SELECT id FROM analyses WHERE id = 'analysis_original_live'").fetchone()
    conn.close()
    assert row is not None


def test_successful_database_restoration(test_environment):
    backup_file = os.path.join(test_environment["backup_dir"], "full_restore_candidate.db")
    _create_sample_valid_backup(backup_file, extra_records_count=4)

    # Perform restoration
    outcome = restore_database_from_backup("full_restore_candidate.db", admin_user="super_admin")
    assert outcome["success"] is True
    assert outcome["restored_from"] == "full_restore_candidate.db"
    assert os.path.exists(outcome["safety_snapshot_path"])

    # Verify active live database was replaced with candidate data
    live_conn = get_db_connection()
    cursor = live_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM analyses")
    assert cursor.fetchone()[0] == 4
    cursor.execute("SELECT id FROM analyses WHERE id = 'backup_rec_0'")
    assert cursor.fetchone() is not None
    cursor.execute("SELECT id FROM analyses WHERE id = 'analysis_original_live'")
    assert cursor.fetchone() is None
    live_conn.close()


def test_restoration_rejected_on_corrupt_backup(test_environment):
    corrupt_backup = os.path.join(test_environment["backup_dir"], "bad_backup.db")
    with open(corrupt_backup, "wb") as f:
        f.write(b"GARBAGE_BYTES" * 50)

    with pytest.raises(BackupRestorationError) as exc_info:
        restore_database_from_backup("bad_backup.db")

    assert "Corrupt or incompatible backup file" in str(exc_info.value)

    # Verify live database remains untouched
    live_conn = get_db_connection()
    row = live_conn.execute("SELECT id FROM analyses WHERE id = 'analysis_original_live'").fetchone()
    live_conn.close()
    assert row is not None


def test_api_restoration_endpoints_authorization_and_flow(test_environment):
    client = test_environment["client"]
    backup_dir = test_environment["backup_dir"]
    sample_backup = os.path.join(backup_dir, "api_test_backup.db")
    _create_sample_valid_backup(sample_backup, extra_records_count=2)

    # 1. Unauthorized GET list backups
    unauth_resp = client.get("/api/admin/database/backups")
    assert unauth_resp.status_code == 403

    # 2. Authorized GET list backups via Admin Header
    auth_resp = client.get("/api/admin/database/backups", headers={"X-Admin-Key": "test-secret-key-999"})
    assert auth_resp.status_code == 200
    assert auth_resp.get_json()["count"] >= 1

    # 3. Unauthorized restore POST
    unauth_restore = client.post("/api/admin/database/restore", json={"backup_identifier": "api_test_backup.db"})
    assert unauth_restore.status_code == 403

    # 4. Authorized pre-validation endpoint
    val_resp = client.post(
        "/api/admin/database/backups/validate",
        headers={"X-Admin-Key": "test-secret-key-999"},
        json={"filename": "api_test_backup.db"}
    )
    assert val_resp.status_code == 200
    assert val_resp.get_json()["validation"]["valid"] is True

    # 5. Authorized restore POST execution
    restore_resp = client.post(
        "/api/admin/database/restore",
        headers={"X-Admin-Key": "test-secret-key-999"},
        json={"backup_identifier": "api_test_backup.db"}
    )
    assert restore_resp.status_code == 200
    assert restore_resp.get_json()["success"] is True
    assert restore_resp.get_json()["restored_from"] == "api_test_backup.db"
