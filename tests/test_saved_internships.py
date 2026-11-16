"""
Unit tests for Saved Internships Service (#357).
"""

import pytest
from app import app
from utils.database import get_db_connection, init_db
from utils.saved_internships_service import (
    save_internship,
    get_saved_internships,
    remove_saved_internship,
    update_saved_internship_note,
    convert_saved_internship_to_application
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def clean_saved_internships_table():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS saved_internships")
    cursor.execute("DELETE FROM job_applications WHERE student_id LIKE 'test-si-%'")
    conn.commit()
    conn.close()
    yield
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS saved_internships")
    cursor.execute("DELETE FROM job_applications WHERE student_id LIKE 'test-si-%'")
    conn.commit()
    conn.close()


def test_save_and_retrieve_internships():
    student_id = "test-si-student-1"
    res1 = save_internship(
        student_id=student_id,
        company_name="Google",
        title="Software Engineering Intern",
        internship_id="goog-swe-2027",
        location="Mountain View, CA",
        stipend="$50/hr",
        notes="Requires strong algorithms background."
    )
    assert res1["success"] is True
    assert res1["saved_id"].startswith("si-")

    res2 = save_internship(
        student_id=student_id,
        company_name="Microsoft",
        title="Explore Intern",
        location="Redmond, WA",
        notes="Early career opportunity"
    )
    assert res2["success"] is True

    items = get_saved_internships(student_id)
    assert len(items) == 2
    google_item = next(i for i in items if i["company_name"] == "Google")
    assert google_item["stipend"] == "$50/hr"
    assert "algorithms" in google_item["notes"]


def test_saved_internships_multi_tenant_isolation():
    # Save for student A
    save_internship("test-si-alice", "Apple", "Hardware Intern")
    # Save for student B
    save_internship("test-si-bob", "Meta", "Production Engineering Intern")

    alice_items = get_saved_internships("test-si-alice")
    assert len(alice_items) == 1
    assert alice_items[0]["company_name"] == "Apple"

    bob_items = get_saved_internships("test-si-bob")
    assert len(bob_items) == 1
    assert bob_items[0]["company_name"] == "Meta"


def test_update_note_and_remove_internship():
    student_id = "test-si-student-2"
    saved = save_internship(student_id, "Stripe", "Backend Intern", notes="Initial note")
    sid = saved["saved_id"]

    updated = update_saved_internship_note(student_id, sid, "Updated note: referral requested")
    assert updated is True

    items = get_saved_internships(student_id)
    assert items[0]["notes"] == "Updated note: referral requested"

    # Remove
    deleted = remove_saved_internship(student_id, sid)
    assert deleted is True
    assert len(get_saved_internships(student_id)) == 0


def test_convert_saved_internship_to_job_application():
    student_id = "test-si-student-3"
    saved = save_internship(student_id, "Amazon", "SDE Intern", location="Seattle", notes="Interview in Dec")
    sid = saved["saved_id"]

    converted = convert_saved_internship_to_application(student_id, sid)
    assert converted["success"] is True
    assert converted["company_name"] == "Amazon"
    assert converted["role_title"] == "SDE Intern"

    # Verify record in job_applications
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM job_applications WHERE student_id = ?", (student_id,))
    rows = cursor.fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["company_name"] == "Amazon"
    assert "Converted from saved internship" in rows[0]["notes"]


def test_api_saved_internships_endpoints(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "test-si-api-user"

    # 1. POST save
    res = client.post(
        "/api/internships/saved",
        json={"company_name": "Netflix", "title": "Platform Engineering Intern", "notes": "Apply next week"}
    )
    assert res.status_code == 201
    saved_id = res.get_json()["saved_id"]

    # 2. GET list
    res_list = client.get("/api/internships/saved")
    assert res_list.status_code == 200
    assert len(res_list.get_json()["saved_internships"]) == 1

    # 3. PUT note
    res_put = client.put(f"/api/internships/saved/{saved_id}", json={"notes": "Deadline extended"})
    assert res_put.status_code == 200

    # 4. POST convert
    res_conv = client.post(f"/api/internships/saved/{saved_id}/convert")
    assert res_conv.status_code == 200
    assert res_conv.get_json()["success"] is True

    # 5. DELETE
    res_del = client.delete(f"/api/internships/saved/{saved_id}")
    assert res_del.status_code == 200
