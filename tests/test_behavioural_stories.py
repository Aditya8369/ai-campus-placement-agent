"""
Unit and integration tests for Behavioural Story Bank (#687).
Covers:
- Story creation, retrieval, updating, and deletion (CRUD)
- Strict student ownership isolation and permission checks
- STAR completeness calculation (0/4 to 4/4)
- Word count calculations and length benchmark guidance (150-300 words)
- Competency tag normalization and tagging
- Behavioral interview question tag matching and relevance ranking
- Web routes (/stories, /stories/<id>/edit, /stories/<id>/delete)
- REST API endpoints (/api/stories, /api/stories/<id>, /api/stories/match)
"""

import json
import uuid
import pytest
from app import app
from utils.behavioural_story_service import (
    behavioural_story_service,
    calculate_completeness,
    calculate_word_count,
    normalize_tag,
    normalize_tags_list,
    CORE_COMPETENCY_TAGS,
)


@pytest.fixture
def unique_student_ids():
    """Generates two unique student IDs for isolated testing."""
    return f"student_{uuid.uuid4().hex[:8]}", f"student_{uuid.uuid4().hex[:8]}"


# ==============================================================================
# Service & Logic Tests
# ==============================================================================

def test_create_and_get_story(unique_student_ids):
    """Verify that a story is created with all fields and retrieved by owner."""
    student_a, _ = unique_student_ids

    story = behavioural_story_service.create_story(
        student_id=student_a,
        title="Migrated Microservices to Kubernetes",
        situation="Our monolithic application suffered from frequent outages during traffic surges.",
        task="I was tasked with migrating our core payment pipeline into containerized microservices.",
        action="I wrote Dockerfiles, configured Helm charts, established CI/CD deploy gates, and load-tested with k6.",
        result="Reduced latency by 45%, eliminated downtime during peak sales, and saved $15,000/month.",
        tags=["leadership", "problem solving", "cloud architecture"],
    )

    assert story["story_id"].startswith("story-")
    assert story["student_id"] == student_a
    assert story["title"] == "Migrated Microservices to Kubernetes"
    assert "leadership" in story["tags"]
    assert "problem solving" in story["tags"]
    assert "cloud architecture" in story["tags"]
    assert story["completeness"]["is_complete"] is True
    assert story["completeness"]["score"] == 4
    assert story["word_count"]["total_words"] > 0

    # Retrieve story
    retrieved = behavioural_story_service.get_story(story["story_id"], student_a)
    assert retrieved is not None
    assert retrieved["title"] == story["title"]


def test_completeness_indicator_reflects_filled_parts():
    """Verify that completeness tracks each of the 4 STAR components."""
    # 0/4 Empty
    c0 = calculate_completeness("", "", "", "")
    assert c0["score"] == 0
    assert c0["percent"] == 0
    assert c0["status"] == "Empty"
    assert c0["is_complete"] is False
    assert len(c0["missing_parts"]) == 4

    # 1/4 Situation only
    c1 = calculate_completeness("A high-stakes campus hackathon.", "", "", "")
    assert c1["score"] == 1
    assert c1["percent"] == 25
    assert c1["status"] == "In Progress"
    assert c1["situation_filled"] is True
    assert c1["task_filled"] is False
    assert c1["missing_parts"] == ["task", "action", "result"]

    # 2/4 Situation + Task
    c2 = calculate_completeness("Situation here", "Task here", "", "")
    assert c2["score"] == 2
    assert c2["percent"] == 50
    assert c2["status"] == "In Progress"
    assert c2["situation_filled"] is True
    assert c2["task_filled"] is True
    assert c2["action_filled"] is False

    # 3/4 Situation + Task + Action
    c3 = calculate_completeness("Situation", "Task", "Action taken", "")
    assert c3["score"] == 3
    assert c3["percent"] == 75
    assert c3["status"] == "In Progress"
    assert c3["result_filled"] is False

    # 4/4 Complete
    c4 = calculate_completeness("Situation", "Task", "Action", "Result achieved")
    assert c4["score"] == 4
    assert c4["percent"] == 100
    assert c4["status"] == "Complete"
    assert c4["is_complete"] is True
    assert len(c4["missing_parts"]) == 0


def test_word_count_calculation_and_benchmarks():
    """Verify word count calculations and recommended length assessments."""
    # Empty
    w0 = calculate_word_count("", "", "", "")
    assert w0["total_words"] == 0
    assert w0["assessment"] == "Empty"

    # Brief (< 80 words)
    w_brief = calculate_word_count("Quick situation", "Quick task", "Quick action", "Good result")
    assert w_brief["total_words"] < 80
    assert w_brief["assessment"] == "Brief"
    assert w_brief["is_ideal"] is False

    # Developing (80 - 149 words)
    medium_text = "word " * 25
    w_dev = calculate_word_count(medium_text, medium_text, medium_text, medium_text)
    assert 80 <= w_dev["total_words"] < 150
    assert w_dev["assessment"] == "Developing"

    # Ideal (150 - 300 words)
    ideal_text = "word " * 50
    w_ideal = calculate_word_count(ideal_text, ideal_text, ideal_text, ideal_text)
    assert 150 <= w_ideal["total_words"] <= 300
    assert w_ideal["assessment"] == "Ideal"
    assert w_ideal["is_ideal"] is True

    # Detailed (> 300 words)
    long_text = "word " * 85
    w_long = calculate_word_count(long_text, long_text, long_text, long_text)
    assert w_long["total_words"] > 300
    assert w_long["assessment"] == "Detailed"


def test_story_owner_permission_isolation(unique_student_ids):
    """
    CRITICAL: Verify that stories are strictly private.
    Student B cannot view, update, or delete Student A's story.
    """
    student_a, student_b = unique_student_ids

    story_a = behavioural_story_service.create_story(
        student_id=student_a,
        title="Student A Confidential Leadership Example",
        situation="Confidential project details",
        tags=["leadership"],
    )
    story_id = story_a["story_id"]

    # Student B cannot get Student A's story
    assert behavioural_story_service.get_story(story_id, student_id=student_b) is None

    # Student B cannot update Student A's story
    update_result = behavioural_story_service.update_story(
        story_id=story_id,
        student_id=student_b,
        title="Hacked Title",
    )
    assert update_result is None

    # Verify story unchanged in DB
    refreshed = behavioural_story_service.get_story(story_id, student_id=student_a)
    assert refreshed["title"] == "Student A Confidential Leadership Example"

    # Student B cannot delete Student A's story
    deleted = behavioural_story_service.delete_story(story_id=story_id, student_id=student_b)
    assert deleted is False

    # Story still exists for Student A
    assert behavioural_story_service.get_story(story_id, student_id=student_a) is not None

    # Student B's list does not include Student A's story
    b_stories = behavioural_story_service.list_stories(student_id=student_b)
    assert not any(s["story_id"] == story_id for s in b_stories)

    # Student A can delete their own story
    assert behavioural_story_service.delete_story(story_id=story_id, student_id=student_a) is True
    assert behavioural_story_service.get_story(story_id, student_id=student_a) is None


def test_competency_tag_normalization():
    """Verify that tags are normalized to lowercase and de-duplicated."""
    raw = ["Leadership", "PROBLEM_SOLVING", "teamwork", "leadership", "  Initiative  "]
    normalized = normalize_tags_list(raw)
    assert normalized == ["leadership", "problem solving", "teamwork", "initiative"]


# ==============================================================================
# Interview Question Tag Matching Tests
# ==============================================================================

def test_tag_matching_for_interview_questions(unique_student_ids):
    """Verify that stories are matched and ranked by question competency keywords."""
    student_id, _ = unique_student_ids

    # Create 3 stories with different competencies
    story_team = behavioural_story_service.create_story(
        student_id=student_id,
        title="Handling Team Disagreement on Architecture",
        situation="Two engineers disagreed on whether to use GraphQL or REST.",
        task="Mediate the technical debate.",
        action="Created an evaluation matrix comparing latency and developer velocity.",
        result="Unified team behind GraphQL.",
        tags=["teamwork"],
    )

    story_lead = behavioural_story_service.create_story(
        student_id=student_id,
        title="Mentoring Junior Interns on Open Source",
        situation="Three new interns joined our team during summer.",
        task="Lead their onboarding program.",
        action="Set up daily standups and code review pair sessions.",
        result="All three interns shipped features within 3 weeks.",
        tags=["leadership"],
    )

    story_fail = behavioural_story_service.create_story(
        student_id=student_id,
        title="Server Outage From Bad Migration Script",
        situation="A database migration locked the users table in production.",
        task="Resolve the outage and fix the deployment checklist.",
        action="Rolled back immediately and introduced blue-green migration practices.",
        result="Learned to always run non-blocking migrations with dry-run verification.",
        tags=["failure", "problem solving"],
    )

    # 1. Question about leading a team -> should rank leadership and teamwork first
    matches_lead = behavioural_story_service.match_stories_for_question(
        student_id=student_id,
        question_text="Tell me about a time you led a team project and had to manage a peer conflict.",
    )
    assert len(matches_lead) == 3
    # Top two should be matched (leadership and teamwork)
    top_matches = [m["story"]["title"] for m in matches_lead if m["is_match"]]
    assert "Mentoring Junior Interns on Open Source" in top_matches
    assert "Handling Team Disagreement on Architecture" in top_matches

    # 2. Question about failure/mistake
    matches_fail = behavioural_story_service.match_stories_for_question(
        student_id=student_id,
        question_text="Describe a significant failure or mistake you made in a technical project.",
    )
    assert matches_fail[0]["story"]["title"] == "Server Outage From Bad Migration Script"
    assert "failure" in matches_fail[0]["matched_tags"]

    # 3. Question about complex problem troubleshooting
    matches_prob = behavioural_story_service.match_stories_for_question(
        student_id=student_id,
        question_text="Give an example of an analytical challenge or difficult bug you had to solve.",
    )
    assert matches_prob[0]["story"]["title"] == "Server Outage From Bad Migration Script"
    assert "problem solving" in matches_prob[0]["matched_tags"]


def test_matching_with_no_stories(unique_student_ids):
    """Verify that match_stories_for_question handles empty story bank gracefully."""
    _, empty_student = unique_student_ids
    matches = behavioural_story_service.match_stories_for_question(
        student_id=empty_student,
        question_text="Tell me about a time you showed initiative.",
    )
    assert matches == []


# ==============================================================================
# Web Routes Tests
# ==============================================================================

def test_web_routes_stories_view_and_filtering(unique_student_ids):
    """Verify GET /stories, tag filter, and search view."""
    student_id, _ = unique_student_ids
    client = app.test_client()

    # Pre-populate two stories
    behavioural_story_service.create_story(
        student_id=student_id,
        title="Story Alpha Teamwork",
        situation="Situation A",
        tags=["teamwork"],
    )
    behavioural_story_service.create_story(
        student_id=student_id,
        title="Story Beta Leadership",
        situation="Situation B",
        tags=["leadership"],
    )

    with client.session_transaction() as sess:
        sess["user_id"] = student_id

    # GET all
    resp = client.get("/stories")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Story Alpha Teamwork" in html
    assert "Story Beta Leadership" in html

    # GET filter by tag
    resp_filtered = client.get("/stories?tag=teamwork")
    assert resp_filtered.status_code == 200
    html_f = resp_filtered.get_data(as_text=True)
    assert "Story Alpha Teamwork" in html_f
    assert "Story Beta Leadership" not in html_f


def test_web_route_create_and_delete(unique_student_ids):
    """Verify POST /stories creates a story and POST /stories/<id>/delete removes it."""
    student_id, _ = unique_student_ids
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["user_id"] = student_id

    # Create via web form
    resp = client.post(
        "/stories",
        data={
            "title": "Created via Web Form",
            "situation": "Initial situation",
            "task": "Initial task",
            "action": "Initial action",
            "result": "Initial result",
            "tags": '["initiative"]',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Created via Web Form" in html

    # Find created story ID
    stories = behavioural_story_service.list_stories(student_id)
    target = next(s for s in stories if s["title"] == "Created via Web Form")
    story_id = target["story_id"]

    # Delete via web form
    del_resp = client.post(f"/stories/{story_id}/delete", follow_redirects=True)
    assert del_resp.status_code == 200
    assert behavioural_story_service.get_story(story_id, student_id) is None


def test_cross_student_web_route_unauthorized_edit_and_delete(unique_student_ids):
    """Verify Student B cannot edit or delete Student A's story via web routes."""
    student_a, student_b = unique_student_ids
    client = app.test_client()

    story_a = behavioural_story_service.create_story(
        student_id=student_a,
        title="Student A Authentic Story",
        situation="Situation A",
    )
    story_id = story_a["story_id"]

    # Student B logs in
    with client.session_transaction() as sess:
        sess["user_id"] = student_b

    # Student B tries to edit Student A's story
    edit_resp = client.post(
        f"/stories/{story_id}/edit",
        data={"title": "Unauthorized Modification Attempt"},
        follow_redirects=True,
    )
    assert edit_resp.status_code == 200
    # Story should remain untouched
    refreshed = behavioural_story_service.get_story(story_id, student_a)
    assert refreshed["title"] == "Student A Authentic Story"

    # Student B tries to delete Student A's story
    del_resp = client.post(f"/stories/{story_id}/delete", follow_redirects=True)
    assert del_resp.status_code == 200
    # Story still exists for Student A
    assert behavioural_story_service.get_story(story_id, student_a) is not None


# ==============================================================================
# REST API Endpoint Tests
# ==============================================================================

def test_api_stories_crud_and_permissions(unique_student_ids):
    """Verify /api/stories and /api/stories/<id> REST operations and privacy."""
    student_a, student_b = unique_student_ids
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["user_id"] = student_a

    # 1. Create via API
    create_resp = client.post(
        "/api/stories",
        json={
            "title": "API Created Story",
            "situation": "Prod issue",
            "task": "Mitigate",
            "action": "Patched bug",
            "result": "Zero downtime",
            "tags": ["problem solving"],
        },
    )
    assert create_resp.status_code == 201
    story = create_resp.get_json()["story"]
    story_id = story["story_id"]
    assert story["title"] == "API Created Story"

    # 2. Get via API as owner
    get_resp = client.get(f"/api/stories/{story_id}")
    assert get_resp.status_code == 200
    assert get_resp.get_json()["story"]["title"] == "API Created Story"

    # 3. Switch to Student B -> Should get 404 unauthorized
    with client.session_transaction() as sess:
        sess["user_id"] = student_b

    get_b_resp = client.get(f"/api/stories/{story_id}")
    assert get_b_resp.status_code == 404

    put_b_resp = client.put(f"/api/stories/{story_id}", json={"title": "Hacked"})
    assert put_b_resp.status_code == 404

    del_b_resp = client.delete(f"/api/stories/{story_id}")
    assert del_b_resp.status_code == 404

    # 4. Switch back to Student A -> Update and Delete succeed
    with client.session_transaction() as sess:
        sess["user_id"] = student_a

    put_a_resp = client.put(f"/api/stories/{story_id}", json={"title": "Updated Title"})
    assert put_a_resp.status_code == 200
    assert put_a_resp.get_json()["story"]["title"] == "Updated Title"

    del_a_resp = client.delete(f"/api/stories/{story_id}")
    assert del_a_resp.status_code == 200


def test_api_match_stories_endpoint(unique_student_ids):
    """Verify /api/stories/match returns ranked candidate stories for interview prompts."""
    student_id, _ = unique_student_ids
    client = app.test_client()

    behavioural_story_service.create_story(
        student_id=student_id,
        title="Proactive Refactoring",
        situation="Technical debt slowed releases.",
        task="Clean up legacy code.",
        action="Took initiative to modernize the build pipeline.",
        result="Build speed improved by 60%.",
        tags=["initiative", "problem solving"],
    )

    with client.session_transaction() as sess:
        sess["user_id"] = student_id

    resp = client.get("/api/stories/match?question=Can+you+share+a+time+you+took+initiative+without+being+asked?")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "initiative" in data["detected_competencies"]
    assert data["match_count"] >= 1
    assert data["matches"][0]["story"]["title"] == "Proactive Refactoring"
    assert "initiative" in data["matches"][0]["matched_tags"]
