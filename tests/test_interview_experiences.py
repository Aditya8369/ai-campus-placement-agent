import pytest
import json
import uuid
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    save_interview_experience,
    get_interview_experiences,
    report_interview_experience
)

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_experiences.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

def test_database_interview_experiences_crud(tmp_path):
    test_db = tmp_path / "test_exp_crud.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()

        # 1. Save experience
        exp_id = "exp-google-001"
        rounds = [
            {
                "round_number": 1,
                "category": "Coding",
                "description": "Online assessment on HackerRank",
                "questions": ["Two Sum variation", "Graph traversal"]
            },
            {
                "round_number": 2,
                "category": "Technical",
                "description": "Virtual onsite data structures round",
                "questions": ["Design an LRU Cache"]
            }
        ]
        save_interview_experience(
            exp_id=exp_id,
            student_id="student_alice",
            candidate_name="Alice CS'26",
            company_name="Google",
            role_title="Software Engineer Intern",
            interview_date="2026-03-01",
            rounds=rounds,
            overall_verdict="Offer",
            difficulty_level="Hard",
            tips_and_preparation="Practice LeetCode mediums and system fundamentals."
        )

        # 2. Retrieve experiences
        all_exp = get_interview_experiences()
        assert len(all_exp) == 1
        assert all_exp[0]["company_name"] == "Google"
        assert all_exp[0]["overall_verdict"] == "Offer"
        assert len(all_exp[0]["rounds"]) == 2

        # 3. Filter by company
        google_exp = get_interview_experiences(company_name="Google")
        assert len(google_exp) == 1
        meta_exp = get_interview_experiences(company_name="Meta")
        assert len(meta_exp) == 0

        # 4. Filter by round category
        coding_exp = get_interview_experiences(category_filter="Coding")
        assert len(coding_exp) == 1
        hr_exp = get_interview_experiences(category_filter="HR")
        assert len(hr_exp) == 0

        # 5. Report experience
        rep = report_interview_experience(exp_id, "Inappropriate test")
        assert rep is True

        # Reported posts are excluded by default
        visible_after_report = get_interview_experiences(include_reported=False)
        assert len(visible_after_report) == 0

        all_moderated = get_interview_experiences(include_reported=True)
        assert len(all_moderated) == 1
        assert all_moderated[0]["reported_flag"] == 1

def test_interview_experience_endpoints(client):
    # GET experiences page
    get_res = client.get("/interview-experiences")
    assert get_res.status_code == 200
    assert b"Company-Wise Interview Experiences" in get_res.data

    # POST submit experience
    post_res = client.post("/interview-experiences", data={
        "company_name": "Microsoft",
        "role_title": "SDE-1",
        "interview_date": "2026-03-05",
        "overall_verdict": "Offer",
        "difficulty_level": "Medium",
        "candidate_name": "CS Senior",
        "round_category[]": ["Coding", "Technical"],
        "round_description[]": ["Online Assessment", "System Architecture"],
        "round_questions[]": ["Binary Tree Inorder\nSubarray sum", "Design rate limiter"],
        "tips_and_preparation": "Review OS, DB concepts and clean coding practices."
    }, follow_redirects=True)
    assert post_res.status_code == 200
    assert b"Microsoft" in post_res.data
    assert b"Thank you! Your interview experience was shared successfully." in post_res.data

    # Fetch via JSON API
    api_res = client.get("/interview-experiences", headers={"X-Requested-With": "XMLHttpRequest"})
    assert api_res.status_code == 200
    data = json.loads(api_res.data)
    assert data["success"] is True
    assert len(data["experiences"]) >= 1
    exp_id = data["experiences"][0]["id"]

    # Report submission via API
    rep_res = client.post(f"/api/interview-experiences/{exp_id}/report", json={
        "reason": "Test reporting feature."
    })
    assert rep_res.status_code == 200
    rep_data = json.loads(rep_res.data)
    assert rep_data["success"] is True
