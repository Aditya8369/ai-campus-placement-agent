"""
Unit tests for Private Multi-Domain Saved Data Search Service (#324).
"""

import json
import pytest
from app import app
from utils.database import get_db_connection, init_db
from utils.saved_data_search_service import search_student_saved_data, highlight_snippet


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def setup_search_test_data():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()

    # Clean previous test entries
    cursor.execute("DELETE FROM interviews WHERE id LIKE 'srch-%'")
    cursor.execute("DELETE FROM analyses WHERE id LIKE 'srch-%'")
    cursor.execute("DELETE FROM job_applications WHERE student_id LIKE 'srch-%'")
    cursor.execute("DELETE FROM preparation_notes WHERE student_id LIKE 'srch-%'")

    # Seed records for student Alice
    cursor.execute(
        """
        INSERT INTO analyses (id, student_id, resume_filename, company_name, job_description, results_json)
        VALUES ('srch-ana-1', 'srch-student-alice', 'alice.pdf', 'Databricks', 'Spark and Data Infrastructure', '{"matched_skills": ["Spark", "DeltaLake"]}')
        """
    )
    cursor.execute(
        """
        INSERT INTO job_applications (id, student_id, company_name, role_title, status, application_date, location, notes)
        VALUES ('srch-app-1', 'srch-student-alice', 'Snowflake', 'Cloud Architect', 'Interviewing', '2026-11-10', 'Bay Area', 'Data warehouse round coming up')
        """
    )
    cursor.execute(
        """
        INSERT INTO preparation_notes (id, student_id, title, category, tags, content, created_at)
        VALUES ('srch-note-1', 'srch-student-alice', 'Spark Optimization', 'BigData', 'spark,memory', 'Tuning garbage collection and data skew in Spark queries', '2026-11-12')
        """
    )

    # Seed records for student Bob (isolated user)
    cursor.execute(
        """
        INSERT INTO analyses (id, student_id, resume_filename, company_name, job_description, results_json)
        VALUES ('srch-ana-2', 'srch-student-bob', 'bob.pdf', 'SecretDefense', 'Spark classified pipeline', '{}')
        """
    )
    conn.commit()
    conn.close()

    yield

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM interviews WHERE id LIKE 'srch-%'")
    cursor.execute("DELETE FROM analyses WHERE id LIKE 'srch-%'")
    cursor.execute("DELETE FROM job_applications WHERE student_id LIKE 'srch-%'")
    cursor.execute("DELETE FROM preparation_notes WHERE student_id LIKE 'srch-%'")
    conn.commit()
    conn.close()


def test_highlight_snippet():
    text = "The candidate demonstrated excellent experience with Kubernetes container orchestrator in production."
    res = highlight_snippet(text, "Kubernetes")
    assert "<mark>Kubernetes</mark>" in res

    empty = highlight_snippet("", "test")
    assert empty == ""


def test_search_student_saved_data_cross_domain():
    # Search for 'Spark' belonging to Alice
    res = search_student_saved_data(student_id="srch-student-alice", query="Spark")
    assert res["success"] is True
    assert res["total_count"] >= 2  # analysis and note
    titles = [r["title"] for r in res["results"]]
    assert any("Databricks" in t for t in titles)
    assert any("Spark Optimization" in t for t in titles)


def test_search_student_saved_data_multi_tenant_isolation():
    # Bob has 'SecretDefense' with Spark, Alice must NOT find it
    res = search_student_saved_data(student_id="srch-student-alice", query="SecretDefense")
    assert res["success"] is True
    assert res["total_count"] == 0

    # Searching as Bob finds his own
    res_bob = search_student_saved_data(student_id="srch-student-bob", query="SecretDefense")
    assert res_bob["total_count"] == 1
    assert "SecretDefense" in res_bob["results"][0]["title"]


def test_search_student_saved_data_category_filter():
    # Filter only to job applications
    res = search_student_saved_data(student_id="srch-student-alice", query="Data", filter_category="applications")
    assert res["success"] is True
    categories = [r["category"] for r in res["results"]]
    for c in categories:
        assert c == "Application"


def test_api_user_search_endpoint(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "srch-student-alice"

    res = client.get("/api/user/search?q=Snowflake")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["total_count"] == 1
    assert "Snowflake" in data["results"][0]["title"]


def test_search_page_route(client):
    res = client.get("/search?q=Databricks")
    assert res.status_code == 200
    assert "Search Your Saved Information" in res.data.decode("utf-8")
