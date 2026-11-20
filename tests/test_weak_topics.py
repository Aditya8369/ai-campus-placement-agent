"""
Tests for Weak-Topic Notebook (#559)
=====================================
Verifies:
- Topic name canonicalization, synonym mapping, and merging across varying casings.
- Aggregation across all 3 sources:
  1. Low-scored interview answers (score < 70)
  2. Missing skills from latest resume analysis
  3. Difficult coding practice (bookmarked Hard problems & failed submissions)
- Topic occurrence counting, evidence lists, and practice links (interview, coding, roadmap).
- Status transitions ('active', 'improving', 'resolved').
- Hiding resolved topics by default and recovering them via show_resolved.
- Empty states (no activity, or all topics resolved).
- Multi-tenant student privacy isolation (user A cannot see or mutate user B's topics).
- Web route and REST API endpoints.
"""

import pytest

import config
from app import app
from utils.database import (
    init_db,
    save_analysis,
    create_interview_session,
    update_interview_session,
    save_coding_bookmark,
)
from utils.weak_topics_service import (
    normalize_topic_name,
    get_student_weak_topics,
    update_weak_topic_status,
    ensure_weak_topic_status_table,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Initializes an isolated SQLite database for each test run."""
    test_db = str(tmp_path / "test_weak_topics.db")
    monkeypatch.setattr(config, "DATABASE_PATH", test_db)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()
    ensure_weak_topic_status_table()
    return test_db


@pytest.fixture
def client():
    """Configures a Flask test client with login enforcement enabled for permission tests."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


# ============================================================================
# 1. Topic Normalization and Merging Tests
# ============================================================================

def test_normalize_topic_name_synonyms():
    """Verifies synonyms and abbreviations map to canonical keys and display names."""
    # Dynamic Programming
    assert normalize_topic_name("dp") == ("dynamic_programming", "Dynamic Programming")
    assert normalize_topic_name("Dynamic Programming") == ("dynamic_programming", "Dynamic Programming")
    assert normalize_topic_name("dynamic_programming") == ("dynamic_programming", "Dynamic Programming")
    assert normalize_topic_name("  dynamic-programming  ") == ("dynamic_programming", "Dynamic Programming")

    # DSA
    assert normalize_topic_name("dsa") == ("data_structures_algorithms", "Data Structures & Algorithms")
    assert normalize_topic_name("data structures") == ("data_structures_algorithms", "Data Structures & Algorithms")

    # Database
    assert normalize_topic_name("dbms") == ("database_systems", "Database Systems")
    assert normalize_topic_name("database") == ("database_systems", "Database Systems")

    # Cloud & DevOps
    assert normalize_topic_name("docker") == ("docker", "Docker")
    assert normalize_topic_name(" Docker  ") == ("docker", "Docker")
    assert normalize_topic_name("k8s") == ("kubernetes", "Kubernetes")
    assert normalize_topic_name("kubernetes") == ("kubernetes", "Kubernetes")

    # Acronyms preservation
    key, display = normalize_topic_name("aws")
    assert key == "aws"
    assert display == "AWS"

    key, display = normalize_topic_name("ci/cd")
    assert display == "CI/CD"


def test_normalize_topic_name_fallback_formatting():
    """Verifies arbitrary topic names are cleanly formatted and slugified."""
    key, display = normalize_topic_name("Apache Kafka")
    assert key == "apache_kafka"
    assert display == "Apache Kafka"

    key, display = normalize_topic_name("")
    assert key == "general_technical"


# ============================================================================
# 2. Empty State Tests
# ============================================================================

def test_get_student_weak_topics_empty_state():
    """Verifies that a student with no records returns an empty topic list and zero counts."""
    data = get_student_weak_topics("student_fresh")
    assert data["student_id"] == "student_fresh"
    assert data["topics"] == []
    assert data["summary"]["total"] == 0
    assert data["summary"]["active"] == 0
    assert data["summary"]["improving"] == 0
    assert data["summary"]["resolved"] == 0
    assert data["summary"]["visible_count"] == 0


def test_weak_topics_web_and_api_empty_state(client):
    """Verifies web page and API return valid empty state structures for fresh student."""
    with client.session_transaction() as sess:
        sess["user_id"] = "student_fresh"

    # Web page view
    resp = client.get("/weak-topics")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Weak-Topic Notebook" in html
    assert "No Weak Topics Detected Yet" in html

    # API endpoint
    api_resp = client.get("/api/weak-topics")
    assert api_resp.status_code == 200
    json_data = api_resp.get_json()
    assert json_data["success"] is True
    assert json_data["data"]["topics"] == []
    assert json_data["data"]["summary"]["total"] == 0


# ============================================================================
# 3. Multi-Source Aggregation Tests
# ============================================================================

def test_aggregation_from_all_three_sources():
    """
    Verifies that signals from:
    1. Low-scored interview answer (< 70)
    2. Missing skill in latest analysis
    3. Bookmarked Hard coding challenge
    are all correctly detected and aggregated with counts and links.
    """
    student_id = "student_multi"

    # Source 1: Mock Interview with a low-scored answer (score = 55)
    analysis_id = "analysis_interview_test"
    save_analysis(
        analysis_id=analysis_id,
        resume_filename="resume.pdf",
        company_name="Google",
        job_description="Systems Engineer",
        results_dict={"match_score": 80},
        student_id=student_id,
    )
    sess_id = f"{analysis_id}_session"
    questions = [
        {"index": 0, "type": "Technical", "question": "Explain TCP three-way handshake."}
    ]
    create_interview_session(sess_id, analysis_id, questions)
    answers = [
        {
            "question_index": 0,
            "type": "Technical",
            "topic": "Computer Networking",
            "question": "Explain TCP three-way handshake.",
            "answer": "SYN, ACK.",
            "evaluation": {"score": 55}
        }
    ]
    update_interview_session(sess_id, 0, answers, completed=True)

    # Source 2: Latest Resume Analysis with skill gaps
    analysis_id_2 = "analysis_resume_gaps"
    save_analysis(
        analysis_id=analysis_id_2,
        resume_filename="resume_v2.pdf",
        company_name="Amazon",
        job_description="Cloud Engineer",
        results_dict={
            "skill_gap": [{"missing_skill": "Docker"}],
            "job_match": {"missing_skills": ["Kubernetes"]},
            "resume_analysis": {"missing_skills": [], "weaknesses": []}
        },
        student_id=student_id,
    )

    # Source 3: Bookmarked Hard coding question
    save_coding_bookmark(
        student_id=student_id,
        problem_id="dsa-05",
        problem_data={
            "id": "dsa-05",
            "title": "Trapping Rain Water",
            "topic": "Two Pointers",
            "difficulty": "Hard"
        }
    )

    # Run aggregation
    res = get_student_weak_topics(student_id)
    assert res["summary"]["total"] >= 3
    topics = {t["topic_name"]: t for t in res["topics"]}

    # Verify Computer Networking from Interview
    assert "Computer Networking" in topics
    net_topic = topics["Computer Networking"]
    assert net_topic["interview_count"] >= 1
    assert any("Low score (55/100)" in ev["text"] for ev in net_topic["evidence_list"])
    assert f"/interview/{analysis_id}" in net_topic["practice_links"]["interview_url"]

    # Verify Docker from Analysis
    assert "Docker" in topics
    doc_topic = topics["Docker"]
    assert doc_topic["analysis_count"] >= 1
    assert any("Missing skill" in ev["text"] for ev in doc_topic["evidence_list"])
    assert "Amazon" in doc_topic["evidence_list"][0]["text"]
    assert f"/dashboard/{analysis_id_2}#roadmapSection" in doc_topic["practice_links"]["roadmap_url"]

    # Verify Two Pointers from Coding Practice
    assert "Two Pointers" in topics
    tp_topic = topics["Two Pointers"]
    assert tp_topic["coding_count"] >= 1
    assert any("Trapping Rain Water" in ev["text"] for ev in tp_topic["evidence_list"])
    assert "coding-practice" in tp_topic["practice_links"]["coding_url"]


def test_topic_merging_across_all_three_sources():
    """
    Verifies that when the SAME topic appears across interviews, resume analysis,
    and coding practice with differing phrasings ('Dynamic Programming', 'dp', 'dynamic-programming'),
    they merge into ONE canonical topic with total_count = 3.
    """
    student_id = "student_merging"

    # Source 1: Interview low score with "Dynamic Programming"
    aid = "analysis_dp"
    save_analysis(aid, "resume.pdf", "Meta", "SWE", {"match_score": 75}, student_id=student_id)
    sess_id = f"{aid}_session"
    create_interview_session(sess_id, aid, [{"index": 0, "question": "Explain memoization in DP."}])
    update_interview_session(
        sess_id, 0,
        [{"question_index": 0, "topic": "Dynamic Programming", "question": "Explain memoization in DP.", "evaluation": {"score": 40}}],
        completed=True
    )

    # Source 2: Analysis skill gap with "dp"
    save_analysis(
        "analysis_dp_latest", "resume2.pdf", "Google", "SWE",
        {"skill_gap": [{"missing_skill": "dp"}]},
        student_id=student_id
    )

    # Source 3: Coding bookmark Hard with "dynamic-programming"
    save_coding_bookmark(
        student_id=student_id,
        problem_id="dsa-coin-change",
        problem_data={
            "id": "dsa-coin-change",
            "title": "Coin Change 2",
            "topic": "dynamic-programming",
            "difficulty": "Hard"
        }
    )

    res = get_student_weak_topics(student_id)
    topics = res["topics"]

    # There should only be 1 merged topic for Dynamic Programming
    assert len(topics) == 1
    dp_topic = topics[0]
    assert dp_topic["topic_key"] == "dynamic_programming"
    assert dp_topic["topic_name"] == "Dynamic Programming"
    assert dp_topic["total_count"] == 3
    assert dp_topic["interview_count"] == 1
    assert dp_topic["analysis_count"] == 1
    assert dp_topic["coding_count"] == 1
    assert len(dp_topic["evidence_list"]) == 3


def test_high_interview_scores_and_easy_problems_are_not_counted_as_weak():
    """Verifies passing interview scores (>=70) and non-hard bookmarks do not generate weak topics."""
    student_id = "student_strong"

    # Passing interview score (88/100)
    aid = "analysis_strong"
    save_analysis(aid, "resume.pdf", "Apple", "SWE", {}, student_id=student_id)
    sess = f"{aid}_sess"
    create_interview_session(sess, aid, [{"index": 0, "question": "Explain Binary Search."}])
    update_interview_session(
        sess, 0,
        [{"question_index": 0, "topic": "Binary Search", "question": "Explain Binary Search.", "evaluation": {"score": 88}}],
        completed=True
    )

    # Easy problem bookmark
    save_coding_bookmark(
        student_id=student_id,
        problem_id="dsa-01",
        problem_data={
            "id": "dsa-01",
            "title": "Two Sum",
            "topic": "Arrays & Hashing",
            "difficulty": "Easy"
        }
    )

    res = get_student_weak_topics(student_id)
    assert len(res["topics"]) == 0
    assert res["summary"]["total"] == 0


# ============================================================================
# 4. Status Transitions & Resolved Hiding / Recovery Tests
# ============================================================================

def test_status_transitions_and_hiding_resolved():
    """
    Verifies:
    1. Default status is 'active'.
    2. Student can mark a topic as 'improving'.
    3. Student can mark a topic as 'resolved', which hides it by default.
    4. Recovering resolved topics when include_resolved=True.
    5. Student can reactivate a resolved topic.
    """
    student_id = "student_status"

    # Create 1 weak topic via resume analysis
    save_analysis(
        "analysis_status_test", "resume.pdf", "Microsoft", "SWE",
        {"skill_gap": [{"missing_skill": "Docker"}]},
        student_id=student_id
    )

    # 1. Default status should be active
    res = get_student_weak_topics(student_id)
    assert len(res["topics"]) == 1
    assert res["topics"][0]["status"] == "active"
    assert res["summary"]["active"] == 1
    assert res["summary"]["resolved"] == 0

    # 2. Mark as improving
    ok, err = update_weak_topic_status(student_id, "docker", "improving")
    assert ok is True
    res2 = get_student_weak_topics(student_id)
    assert res2["topics"][0]["status"] == "improving"
    assert res2["summary"]["improving"] == 1

    # 3. Mark as resolved -> hidden by default
    ok, err = update_weak_topic_status(student_id, "docker", "resolved")
    assert ok is True
    res_hidden = get_student_weak_topics(student_id, include_resolved=False)
    assert len(res_hidden["topics"]) == 0
    assert res_hidden["summary"]["visible_count"] == 0
    assert res_hidden["summary"]["resolved"] == 1
    assert res_hidden["summary"]["total"] == 1

    # 4. Recoverable when include_resolved=True
    res_visible = get_student_weak_topics(student_id, include_resolved=True)
    assert len(res_visible["topics"]) == 1
    assert res_visible["topics"][0]["status"] == "resolved"

    # 5. Reactivate to active
    ok, err = update_weak_topic_status(student_id, "docker", "active")
    assert ok is True
    res_reactivated = get_student_weak_topics(student_id, include_resolved=False)
    assert len(res_reactivated["topics"]) == 1
    assert res_reactivated["topics"][0]["status"] == "active"


def test_invalid_status_rejection():
    """Verifies update_weak_topic_status rejects invalid statuses."""
    ok, err = update_weak_topic_status("student_1", "docker", "invalid_status")
    assert ok is False
    assert "Invalid status" in err

    ok, err = update_weak_topic_status("student_1", "", "active")
    assert ok is False
    assert "Topic key is required" in err


# ============================================================================
# 5. Student Data Isolation Tests
# ============================================================================

def test_student_data_isolation():
    """Verifies that Student A's weak topics and status changes are never visible to Student B."""
    student_a = "alice_uuid_101"
    student_b = "bob_uuid_202"

    # Seed weak topic for Alice only
    save_analysis(
        "analysis_alice", "resume.pdf", "Stripe", "SWE",
        {"skill_gap": [{"missing_skill": "PostgreSQL"}]},
        student_id=student_a
    )

    # Alice sees PostgreSQL
    alice_data = get_student_weak_topics(student_a)
    assert len(alice_data["topics"]) == 1
    assert alice_data["topics"][0]["topic_key"] == "postgresql"

    # Bob sees nothing
    bob_data = get_student_weak_topics(student_b)
    assert len(bob_data["topics"]) == 0
    assert bob_data["summary"]["total"] == 0

    # Bob updating PostgreSQL status does not alter Alice's PostgreSQL status
    update_weak_topic_status(student_b, "postgresql", "resolved")
    alice_check = get_student_weak_topics(student_a)
    assert alice_check["topics"][0]["status"] == "active"


# ============================================================================
# 6. Web Routes and REST API Endpoints Tests
# ============================================================================

def test_web_routes_and_status_post(client):
    """Verifies HTML views, session auth, and POST status updates with redirects."""
    student_id = "student_web_user"
    save_analysis(
        "analysis_web", "resume.pdf", "Netflix", "SWE",
        {"skill_gap": [{"missing_skill": "Redis"}]},
        student_id=student_id
    )

    with client.session_transaction() as sess:
        sess["user_id"] = student_id

    # GET /weak-topics
    resp = client.get("/weak-topics")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Redis" in html
    assert "Needs Practice" in html

    # POST /weak-topics/redis/status -> mark improving
    post_resp = client.post("/weak-topics/redis/status", data={"status": "improving"}, follow_redirects=True)
    assert post_resp.status_code == 200
    html2 = post_resp.get_data(as_text=True)
    assert "Improving" in html2

    # POST /weak-topics/redis/status -> mark resolved
    post_res_resolved = client.post("/weak-topics/redis/status", data={"status": "resolved"}, follow_redirects=True)
    assert post_res_resolved.status_code == 200
    html3 = post_res_resolved.get_data(as_text=True)
    # Since resolved topics are hidden by default, Redis should be hidden
    assert "All Identified Weak Topics Are Resolved" in html3 or "Show Resolved" in html3

    # Recover via show_resolved=1
    show_resp = client.get("/weak-topics?show_resolved=1")
    assert show_resp.status_code == 200
    html4 = show_resp.get_data(as_text=True)
    assert "Redis" in html4
    assert "Resolved" in html4


def test_api_endpoints_json(client):
    """Verifies REST API endpoints return proper JSON responses and handle errors."""
    student_id = "student_api_user"
    save_analysis(
        "analysis_api", "resume.pdf", "Google", "SWE",
        {"skill_gap": [{"missing_skill": "Kafka"}]},
        student_id=student_id
    )

    # Unauthenticated API call with login enforcement
    orig_enforce = app.config.get("ENFORCE_LOGIN_IN_TESTS", False)
    app.config["ENFORCE_LOGIN_IN_TESTS"] = True
    try:
        unauth_resp = client.get("/api/weak-topics")
        assert unauth_resp.status_code == 401
    finally:
        app.config["ENFORCE_LOGIN_IN_TESTS"] = orig_enforce

    with client.session_transaction() as sess:
        sess["user_id"] = student_id

    # Authenticated GET /api/weak-topics
    get_resp = client.get("/api/weak-topics")
    assert get_resp.status_code == 200
    data = get_resp.get_json()["data"]
    assert len(data["topics"]) == 1
    assert data["topics"][0]["topic_key"] == "apache_kafka" or "kafka" in data["topics"][0]["topic_key"]

    # Authenticated POST /api/weak-topics/<topic_key>/status
    t_key = data["topics"][0]["topic_key"]
    post_resp = client.post(
        f"/api/weak-topics/{t_key}/status",
        json={"status": "improving", "notes": "Studying Kafka partitions"}
    )
    assert post_resp.status_code == 200
    res_json = post_resp.get_json()
    assert res_json["success"] is True
    assert res_json["status"] == "improving"

    # Invalid status payload
    bad_resp = client.post(f"/api/weak-topics/{t_key}/status", json={"status": "unknown"})
    assert bad_resp.status_code == 400
    assert bad_resp.get_json()["success"] is False
