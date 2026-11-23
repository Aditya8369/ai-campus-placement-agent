"""
Unit tests for Preparation progress snapshots (#607)
"""

import pytest
from utils.prep_snapshot_service import (
    create_progress_snapshot,
    list_student_snapshots,
    delete_student_snapshot,
    compare_two_snapshots
)


def test_create_and_list_snapshots():
    student_id = "test_student_snap_1"
    s1 = create_progress_snapshot(
        student_id=student_id,
        label="Day 1 Baseline",
        ats_score=60,
        coding_score=45,
        interview_score=50,
        skill_gaps_count=6,
        matched_skills_count=4
    )
    assert s1["id"].startswith("snap_")
    assert s1["label"] == "Day 1 Baseline"

    snapshots = list_student_snapshots(student_id)
    assert len(snapshots) >= 1
    assert snapshots[0]["student_id"] == student_id


def test_compare_two_snapshots():
    snap_a = {
        "id": "s1",
        "label": "Week 1",
        "data": {
            "ats_score": 60,
            "coding_score": 50,
            "interview_score": 40,
            "skill_gaps_count": 5,
            "matched_skills_count": 4
        }
    }
    snap_b = {
        "id": "s2",
        "label": "Week 4",
        "data": {
            "ats_score": 80,
            "coding_score": 75,
            "interview_score": 70,
            "skill_gaps_count": 2,
            "matched_skills_count": 7
        }
    }
    comp = compare_two_snapshots(snap_a, snap_b)
    assert len(comp["comparisons"]) == 5
    ats_comp = next(c for c in comp["comparisons"] if c["metric"] == "ATS Score")
    assert ats_comp["delta"] == 20
    assert ats_comp["status"] == "improved"

    gap_comp = next(c for c in comp["comparisons"] if c["metric"] == "Skill Gaps Remaining")
    assert gap_comp["delta"] == -3
    assert gap_comp["status"] == "improved"


def test_compare_snapshots_unavailable_metrics():
    snap_a = {
        "id": "s1",
        "label": "Incomplete Snap",
        "data": {"ats_score": 70, "coding_score": None}
    }
    snap_b = {
        "id": "s2",
        "label": "Complete Snap",
        "data": {"ats_score": 75, "coding_score": 80}
    }
    comp = compare_two_snapshots(snap_a, snap_b)
    coding_comp = next(c for c in comp["comparisons"] if c["metric"] == "Coding Assessment")
    assert coding_comp["is_available"] is False
    assert coding_comp["status"] == "unavailable"


def test_api_snapshots_lifecycle(client):
    # 1. POST Create snapshot
    resp = client.post(
        "/api/snapshots",
        json={
            "label": "Mid-Prep Check",
            "ats_score": 72,
            "coding_score": 65,
            "interview_score": 60,
            "skill_gaps_count": 4,
            "matched_skills_count": 5
        }
    )
    assert resp.status_code == 201
    created = resp.get_json()["snapshot"]
    snap_id = created["id"]

    # 2. GET snapshots
    get_resp = client.get("/api/snapshots")
    assert get_resp.status_code == 200
    snaps = get_resp.get_json()["snapshots"]
    assert any(s["id"] == snap_id for s in snaps)

    # 3. DELETE snapshot
    del_resp = client.delete(f"/api/snapshots/{snap_id}")
    assert del_resp.status_code == 200
