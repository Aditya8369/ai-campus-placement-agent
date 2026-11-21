"""
Unit tests for Recruiter Contact & Follow-Up Tracking (#516).
"""

import json
import pytest
from app import create_app
from utils.recruiter_contact_service import RecruiterContactService


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_recruiter_contact_service_crud():
    user = "recruiter_student_516"

    # Create contact
    contact = RecruiterContactService.save_contact(
        user_id=user,
        recruiter_name="Sarah Jenkins",
        company_name="Google",
        email="sarah.jenkins@example.com",
        role_or_department="Campus Recruiter",
        interaction_channel="LinkedIn",
        status="in_discussion",
        next_followup_date="2026-12-01"
    )

    assert contact["recruiter_name"] == "Sarah Jenkins"
    assert contact["company_name"] == "Google"

    # List contacts
    contacts = RecruiterContactService.list_contacts(user)
    assert len(contacts) == 1

    # Overdue reminders check
    overdue = RecruiterContactService.get_followup_reminders(user)
    assert isinstance(overdue, list)

    # Delete contact
    deleted = RecruiterContactService.delete_contact(user, contact["id"])
    assert deleted is True


def test_recruiter_contact_email_validation():
    with pytest.raises(ValueError):
        RecruiterContactService.save_contact(
            user_id="u1",
            recruiter_name="John",
            company_name="Meta",
            email="invalid_email_format"
        )


def test_recruiter_contact_api_routes(client):
    test_user = "api_recruiter_student_516"
    with client.session_transaction() as s:
        s["user_id"] = test_user

    # 1. HTML View
    view_res = client.get("/tracker/recruiter-contacts")
    assert view_res.status_code == 200
    assert b"Recruiter Directory" in view_res.data

    # 2. POST API
    post_res = client.post("/api/recruiter-contacts", json={
        "recruiter_name": "David Miller",
        "company_name": "Microsoft",
        "email": "david.m@example.com",
        "interaction_channel": "Email"
    })
    assert post_res.status_code == 201
    p_data = json.loads(post_res.data)
    cid = p_data["contact"]["id"]

    # 3. GET API
    get_res = client.get("/api/recruiter-contacts")
    assert get_res.status_code == 200
    g_data = json.loads(get_res.data)
    assert g_data["count"] >= 1

    # 4. DELETE API
    del_res = client.delete(f"/api/recruiter-contacts/{cid}")
    assert del_res.status_code == 200
