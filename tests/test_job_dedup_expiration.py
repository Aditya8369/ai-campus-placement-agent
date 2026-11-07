import pytest
import time
from datetime import datetime, timezone

from utils.job_dedup_expiration import (
    normalize_title,
    normalize_company_name,
    normalize_url,
    parse_job_deadline,
    compute_job_duplicate_key,
    deduplicate_job_feed,
    process_jobs_feed_with_expiration_and_dedup
)
from app import app


SAMPLE_JOBS = [
    {
        "id": "job-1",
        "title": "Software Development Engineer - Campus 2026",
        "company": "Amazon Inc.",
        "apply_url": "https://amazon.jobs/en/jobs/12345?utm_source=linkedin",
        "deadline": "2026-12-31"
    },
    {
        "id": "job-2-dup",
        "title": "Software Development Engineer (Campus Hiring 2026)",
        "company": "Amazon",
        "apply_url": "https://www.amazon.jobs/en/jobs/12345",
        "deadline": "2026-12-31"
    },
    {
        "id": "job-3-expired",
        "title": "Frontend Engineer Intern",
        "company": "Flipkart Pvt Ltd",
        "apply_url": "https://careers.flipkart.com/jobs/99",
        "deadline": "2026-01-15"
    },
    {
        "id": "job-4-rolling",
        "title": "Data Analyst Graduate",
        "company": "Google",
        "apply_url": "https://careers.google.com/jobs/88",
        "deadline": "Active Drive - Rolling Basis"
    },
    {
        "id": "job-5-closing-soon",
        "title": "DevOps Engineer",
        "company": "Microsoft Corporation",
        "apply_url": "https://careers.microsoft.com/jobs/77",
        "deadline": "2026-06-02"
    }
]


def test_normalize_title_and_company():
    assert normalize_title("Software Engineer (2026 Batch Campus Drive)") == "software engineer"
    assert normalize_title("Graduate Software Engineer - Off Campus Hiring") == "software engineer"
    assert normalize_company_name("Amazon Inc.") == "amazon"
    assert normalize_company_name("Google LLC") == "google"
    assert normalize_company_name("Flipkart Pvt Ltd") == "flipkart"


def test_normalize_url():
    url1 = "https://www.amazon.jobs/en/jobs/12345?ref=campus&trk=123"
    url2 = "https://amazon.jobs/en/jobs/12345"
    assert normalize_url(url1) == normalize_url(url2)
    assert normalize_url(url1) == "amazon.jobs/en/jobs/12345"


def test_parse_job_deadline_variations():
    # Fixed reference time: 2026-06-01 12:00:00 UTC
    ref_ts = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()

    # 1. Expired date
    exp_res = parse_job_deadline("2026-05-20", reference_timestamp=ref_ts)
    assert exp_res["is_expired"] is True
    assert exp_res["status_badge"] == "Expired"
    assert exp_res["remaining_days"] == 0

    # 2. Closing soon (tomorrow: 2026-06-02)
    soon_res = parse_job_deadline("June 2, 2026", reference_timestamp=ref_ts)
    assert soon_res["is_expired"] is False
    assert soon_res["status_badge"] == "Closing Soon"
    assert soon_res["remaining_days"] == 1

    # 3. Active future date
    future_res = parse_job_deadline("2026-12-15", reference_timestamp=ref_ts)
    assert future_res["is_expired"] is False
    assert future_res["status_badge"] == "Active"
    assert future_res["remaining_days"] > 100

    # 4. Rolling deadline
    rolling_res = parse_job_deadline("Active Drive - Rolling Basis", reference_timestamp=ref_ts)
    assert rolling_res["is_expired"] is False
    assert rolling_res["is_rolling"] is True
    assert rolling_res["status_badge"] == "Rolling"

    # 5. Empty / missing deadline
    none_res = parse_job_deadline(None, reference_timestamp=ref_ts)
    assert none_res["is_expired"] is False
    assert none_res["is_rolling"] is True
    assert none_res["status_badge"] == "Rolling"


def test_deduplicate_job_feed():
    deduped, dup_count = deduplicate_job_feed(SAMPLE_JOBS)
    # job-1 and job-2-dup match the same normalized company + title + URL
    assert dup_count == 1
    assert len(deduped) == len(SAMPLE_JOBS) - 1
    ids = [j["id"] for j in deduped]
    assert "job-1" in ids
    assert "job-2-dup" not in ids
    # Merged sources list preserved
    job_1_merged = next(j for j in deduped if j["id"] == "job-1")
    assert "job-2-dup" in job_1_merged["merged_sources"]


def test_process_jobs_feed_with_expiration_and_dedup():
    ref_ts = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    result = process_jobs_feed_with_expiration_and_dedup(
        jobs=SAMPLE_JOBS,
        hide_expired=False,
        reference_timestamp=ref_ts
    )

    assert result["total_raw"] == 5
    assert result["duplicates_removed"] == 1
    assert result["deduplicated_count"] == 4
    assert result["expired_count"] == 1
    assert result["active_count"] == 3
    assert len(result["jobs"]) == 4

    # Now test with hide_expired=True
    filtered_result = process_jobs_feed_with_expiration_and_dedup(
        jobs=SAMPLE_JOBS,
        hide_expired=True,
        reference_timestamp=ref_ts
    )
    assert len(filtered_result["jobs"]) == 3
    assert not any(j["id"] == "job-3-expired" for j in filtered_result["jobs"])


def test_api_jobs_feed_dedup_endpoint():
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/api/jobs/feed/dedup")
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert "feed_summary" in data
        assert "jobs" in data
        assert len(data["jobs"]) > 0
