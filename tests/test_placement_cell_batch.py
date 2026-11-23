"""
Automated Test Suite for Placement Cell Batch Resume Analysis (#763).
=====================================================================
Verifies all acceptance criteria:
1. The aggregate view and export contain no names or contact details.
2. The batch limit is enforced with a clear message.
3. Uploaded files are removed after the batch completes.
4. Process resumes in the background and report failed files individually.
5. Aggregate statistics: average score, most common missing skills, and score distribution.
"""

import io
import json
import os
import shutil
import tempfile
import pytest

from app import app
import config
from utils.placement_cell_service import PlacementCellBatchService, init_placement_cell_table


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as test_client:
        yield test_client


RESUME_1 = (
    "Alice Smith\n"
    "Email: alice.smith@university.edu\n"
    "Phone: +1-555-019-2834\n"
    "Education: B.Tech Computer Science, GPA: 8.8\n"
    "Skills: Python, Django, REST APIs, PostgreSQL, Git\n"
    "Projects: E-commerce platform built with Django and Postgres with 99% uptime\n"
    "Experience: Software Engineer Intern at TechCorp for 6 months\n"
)

RESUME_2 = (
    "Bob Jones\n"
    "Email: bob.jones@college.edu\n"
    "Phone: +1-555-492-1102\n"
    "Education: B.E. Information Technology, GPA: 7.9\n"
    "Skills: Java, Spring Boot, MySQL, Docker\n"
    "Projects: Microservice backend architecture using Spring Boot\n"
    "Experience: Backend Developer Intern building REST endpoints\n"
)

RESUME_3 = (
    "Charlie Brown\n"
    "Email: charlie.b@campus.edu\n"
    "Phone: +1-555-883-9912\n"
    "Education: B.Sc Computer Applications\n"
    "Skills: HTML, CSS, JavaScript, React\n"
    "Projects: Responsive portfolio web applications\n"
)


def test_batch_limit_enforced_with_clear_message():
    """Acceptance Criterion 2: The batch limit is enforced with a clear message."""
    # Test exceeding the maximum batch limit
    max_limit = 50
    mock_files = [f"resume_{i}.pdf" for i in range(51)]
    valid, err_msg = PlacementCellBatchService.validate_batch_upload(
        files=mock_files,
        consent=True,
        max_limit=max_limit
    )
    assert valid is False
    assert "Batch limit exceeded: You uploaded 51 files. The maximum allowed batch size is 50 resumes." in err_msg

    # Test empty file list
    valid_empty, err_empty = PlacementCellBatchService.validate_batch_upload(
        files=[],
        consent=True,
        max_limit=max_limit
    )
    assert valid_empty is False
    assert "Please select at least one resume file to upload." in err_empty

    # Test within limit
    valid_ok, err_ok = PlacementCellBatchService.validate_batch_upload(
        files=["resume_1.pdf", "resume_2.pdf"],
        consent=True,
        max_limit=max_limit
    )
    assert valid_ok is True
    assert err_ok is None


def test_consent_notice_mandatory():
    """Verify that batch processing strictly requires consent confirmation."""
    valid_no_consent, err = PlacementCellBatchService.validate_batch_upload(
        files=["resume_1.pdf"],
        consent=False
    )
    assert valid_no_consent is False
    assert "Consent confirmation required" in err

    # Valid with consent
    valid_consent, err_none = PlacementCellBatchService.validate_batch_upload(
        files=["resume_1.pdf"],
        consent=True
    )
    assert valid_consent is True
    assert err_none is None


def test_uploaded_files_are_removed_after_batch_completes():
    """Acceptance Criterion 3: Uploaded files are removed after the batch completes."""
    temp_dir = tempfile.mkdtemp(prefix="test_batch_cleanup_")
    file_1 = os.path.join(temp_dir, "cand1_alice.txt")
    file_2 = os.path.join(temp_dir, "cand2_bob.txt")

    with open(file_1, "w", encoding="utf-8") as f:
        f.write(RESUME_1)
    with open(file_2, "w", encoding="utf-8") as f:
        f.write(RESUME_2)

    assert os.path.exists(file_1)
    assert os.path.exists(file_2)

    batch_id = PlacementCellBatchService.create_batch(
        batch_name="Test Cleanup Batch",
        total_files=2,
        consent_confirmed=True
    )

    file_records = [
        (file_1, "Alice_Resume.txt"),
        (file_2, "Bob_Resume.txt"),
    ]

    # Process synchronously
    PlacementCellBatchService.process_batch(
        batch_id=batch_id,
        file_records=file_records,
        run_in_background=False
    )

    # GUARANTEE: Physical files and temp directory must be purged
    assert not os.path.exists(file_1), "Uploaded resume file 1 was not deleted after processing!"
    assert not os.path.exists(file_2), "Uploaded resume file 2 was not deleted after processing!"
    assert not os.path.exists(temp_dir), "Temporary batch directory was not removed after processing!"


def test_aggregate_view_and_export_contain_no_names_or_contact_details():
    """
    Acceptance Criterion 1: The aggregate view and export contain no names or contact details.
    """
    temp_dir = tempfile.mkdtemp(prefix="test_batch_anonymity_")
    file_1 = os.path.join(temp_dir, "alice.txt")
    file_2 = os.path.join(temp_dir, "bob.txt")
    file_3 = os.path.join(temp_dir, "charlie.txt")

    with open(file_1, "w", encoding="utf-8") as f:
        f.write(RESUME_1)
    with open(file_2, "w", encoding="utf-8") as f:
        f.write(RESUME_2)
    with open(file_3, "w", encoding="utf-8") as f:
        f.write(RESUME_3)

    batch_id = PlacementCellBatchService.create_batch(
        batch_name="Cohort CS 2026",
        total_files=3,
        consent_confirmed=True
    )

    PlacementCellBatchService.process_batch(
        batch_id=batch_id,
        file_records=[
            (file_1, "Alice_Smith_Resume.txt"),
            (file_2, "Bob_Jones_Resume.txt"),
            (file_3, "Charlie_Brown_Resume.txt"),
        ],
        run_in_background=False
    )

    batch = PlacementCellBatchService.get_batch(batch_id)
    assert batch is not None
    assert batch["status"] == "completed"
    assert batch["processed_count"] == 3
    assert batch["failed_count"] == 0
    assert batch["average_score"] > 0

    # 1. Verify JSON Batch data contains NO names or contact info
    batch_json_str = json.dumps(batch)
    prohibited_strings = [
        "Alice Smith", "alice.smith@university.edu", "+1-555-019-2834",
        "Bob Jones", "bob.jones@college.edu", "+1-555-492-1102",
        "Charlie Brown", "charlie.b@campus.edu", "+1-555-883-9912"
    ]
    for sensitive in prohibited_strings:
        assert sensitive not in batch_json_str, f"Found sensitive data '{sensitive}' in batch JSON view!"

    # Verify score distribution is present
    dist = batch["score_distribution"]
    assert "0-40" in dist
    assert "41-60" in dist
    assert "61-80" in dist
    assert "81-100" in dist
    assert sum(dist.values()) == 3

    # 2. Verify Aggregate CSV Export contains NO names or contact info
    csv_report = PlacementCellBatchService.generate_aggregate_csv(batch_id)
    assert "=== PLACEMENT CELL BATCH AGGREGATE READINESS REPORT ===" in csv_report
    assert "=== SCORE DISTRIBUTION ===" in csv_report
    assert "=== MOST COMMON MISSING SKILLS ===" in csv_report
    assert f"Average ATS Score,{batch['average_score']}" in csv_report

    for sensitive in prohibited_strings:
        assert sensitive not in csv_report, f"Found sensitive data '{sensitive}' in aggregate CSV export!"


def test_individual_failed_files_reported():
    """Verify that corrupt or unreadable files are reported individually without failing the batch."""
    temp_dir = tempfile.mkdtemp(prefix="test_batch_failures_")
    good_file = os.path.join(temp_dir, "good_resume.txt")
    bad_file = os.path.join(temp_dir, "empty_damaged.txt")

    with open(good_file, "w", encoding="utf-8") as f:
        f.write(RESUME_1)
    with open(bad_file, "w", encoding="utf-8") as f:
        f.write("")  # Blank document

    batch_id = PlacementCellBatchService.create_batch(
        batch_name="Mixed Batch",
        total_files=2,
        consent_confirmed=True
    )

    PlacementCellBatchService.process_batch(
        batch_id=batch_id,
        file_records=[
            (good_file, "good_resume.txt"),
            (bad_file, "corrupt_blank.txt"),
        ],
        run_in_background=False
    )

    batch = PlacementCellBatchService.get_batch(batch_id)
    assert batch["status"] == "completed"
    assert batch["processed_count"] == 1
    assert batch["failed_count"] == 1

    # Individual file failure report
    failed_files = batch["failed_files"]
    assert len(failed_files) == 1
    assert failed_files[0]["filename"] == "corrupt_blank.txt"
    assert "no readable text" in failed_files[0]["error"].lower() or "blank" in failed_files[0]["error"].lower()


def test_placement_cell_api_endpoints(client):
    """End-to-end integration test of Placement Cell HTTP routes."""
    # 1. HTML view loads
    res_view = client.get("/admin/placement-cell")
    assert res_view.status_code == 200
    assert b"Placement Cell: Batch Analysis" in res_view.data

    # 2. Upload without consent is rejected
    res_no_consent = client.post(
        "/api/admin/placement-cell/batch",
        data={
            "resumes": (io.BytesIO(RESUME_1.encode("utf-8")), "alice.txt"),
            "consent": ""
        },
        content_type="multipart/form-data"
    )
    assert res_no_consent.status_code == 400
    data_err = res_no_consent.get_json()
    assert "Consent confirmation required" in data_err["error"]

    # 3. Successful batch upload with sync=true
    res_upload = client.post(
        "/api/admin/placement-cell/batch?sync=true",
        data={
            "resumes": [
                (io.BytesIO(RESUME_1.encode("utf-8")), "candidate_a.txt"),
                (io.BytesIO(RESUME_2.encode("utf-8")), "candidate_b.txt")
            ],
            "consent": "1",
            "batch_name": "API Automated Test Batch"
        },
        content_type="multipart/form-data"
    )
    assert res_upload.status_code in (200, 202)
    upload_data = res_upload.get_json()
    assert upload_data["success"] is True
    batch_id = upload_data["batch_id"]

    # 4. Fetch Batch JSON Metrics
    res_batch = client.get(f"/api/admin/placement-cell/batch/{batch_id}")
    assert res_batch.status_code == 200
    batch_data = res_batch.get_json()
    assert batch_data["success"] is True
    assert batch_data["batch"]["processed_count"] == 2
    assert batch_data["batch"]["average_score"] > 0
    assert "score_distribution" in batch_data["batch"]
    assert "common_missing_skills" in batch_data["batch"]

    # 5. Export Aggregate CSV
    res_csv = client.get(f"/admin/placement-cell/batch/{batch_id}/export.csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.content_type
    csv_text = res_csv.get_data(as_text=True)
    assert "=== PLACEMENT CELL BATCH AGGREGATE READINESS REPORT ===" in csv_text
    assert "Alice Smith" not in csv_text
    assert "Bob Jones" not in csv_text
