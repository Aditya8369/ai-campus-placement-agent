"""
Comprehensive test suite for database online hot backup and PRAGMA integrity verification.

Tests:
- Atomic online database backup using sqlite3.backup API
- Verification that backup database contains exact records from source
- PRAGMA integrity_check verification reporting healthy status
- JSON API endpoints for integrity and backup operations
"""

import os
import tempfile
import sqlite3
from pathlib import Path
import pytest
from utils.database import (
    init_db,
    save_analysis,
    create_database_backup,
    verify_database_integrity,
)
from app import app
import config


@pytest.fixture
def mock_db_with_data(monkeypatch):
    """Sets up a temporary SQLite database with known analysis and interview rows."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "integrity_test.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db)
        monkeypatch.setattr(config, "BASE_DIR", tmpdir)
        init_db()

        aid = "test_integrity_analysis_1"
        sample_results = {
            "resume_analysis": {"ats_score": 85},
            "job_match": {"match_percentage": 78},
        }
        save_analysis(aid, "test_resume.pdf", "Microsoft", "SWE", sample_results)
        yield aid, str(test_db), tmpdir


def test_verify_database_integrity_healthy(mock_db_with_data):
    """Verify healthy SQLite database passes PRAGMA integrity checks."""
    result = verify_database_integrity()
    assert result["healthy"] is True
    assert result["status"] == "ok"
    assert "ok" in [m.lower() for m in result["messages"]]
    assert result["tables"]["analyses_count"] == 1
    assert result["journal_mode"].lower() == "wal"


def test_create_database_backup_online(mock_db_with_data):
    """Verify create_database_backup clones all tables and data into new file."""
    aid, src_db, tmpdir = mock_db_with_data
    backup_path = os.path.join(tmpdir, "backup_test.db")

    saved_path = create_database_backup(backup_path)
    assert os.path.exists(saved_path)
    assert os.path.getsize(saved_path) > 0

    # Read from the backup database directly
    b_conn = sqlite3.connect(saved_path)
    cursor = b_conn.cursor()
    cursor.execute("SELECT id, resume_filename, company_name FROM analyses WHERE id = ?", (aid,))
    row = cursor.fetchone()
    b_conn.close()

    assert row is not None
    assert row[0] == aid
    assert row[1] == "test_resume.pdf"
    assert row[2] == "Microsoft"


def test_api_database_integrity_endpoint(mock_db_with_data):
    """Verify GET /api/admin/database/integrity returns 200 with diagnostics."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/api/admin/database/integrity")
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["integrity"]["healthy"] is True
        assert data["integrity"]["tables"]["analyses_count"] == 1


def test_api_database_backup_endpoint(mock_db_with_data):
    """Verify POST /api/admin/database/backup creates a backup file and returns 200."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.post("/api/admin/database/backup")
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert "backup_filename" in data
        assert data["size_bytes"] > 0
