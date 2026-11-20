"""
Unit tests for Application Offer Decision Notes (#515).
"""

import json
import pytest
from app import create_app
from utils.offer_decision_notes_service import OfferDecisionNotesService


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_offer_decision_notes_service_crud():
    user = "offer_student_515"

    # Create note
    note = OfferDecisionNotesService.save_offer_notes(
        user_id=user,
        company_name="Acme Tech",
        role_title="Software Engineer",
        ctc_lpa=16.5,
        work_location="Bangalore",
        bond_terms="No bond",
        bond_duration_months=0,
        probation_period_months=6,
        culture_and_team_notes="Great engineering culture, modern tech stack",
        concerns_and_risks="High living expenses in Bangalore"
    )

    assert note["company_name"] == "Acme Tech"
    assert note["ctc_lpa"] == 16.5
    assert note["bond_duration_months"] == 0

    # List notes
    notes = OfferDecisionNotesService.list_offer_notes(user)
    assert len(notes) == 1

    # Delete note
    deleted = OfferDecisionNotesService.delete_offer_note(user, note["id"])
    assert deleted is True


def test_offer_decision_notes_validation():
    with pytest.raises(ValueError):
        OfferDecisionNotesService.save_offer_notes(
            user_id="u1",
            company_name="",
            role_title="",
            ctc_lpa=10.0
        )


def test_offer_decision_notes_api(client):
    test_user = "api_offer_student_515"
    with client.session_transaction() as s:
        s["user_id"] = test_user

    # 1. HTML View
    view_res = client.get("/tracker/offer-notes")
    assert view_res.status_code == 200
    assert b"Private Offer Decision Notes" in view_res.data

    # 2. POST API
    post_res = client.post("/api/offer-notes", json={
        "company_name": "Initech Corp",
        "role_title": "Backend Developer",
        "ctc_lpa": 14.0,
        "work_location": "Hyderabad",
        "bond_duration_months": 12,
        "bond_terms": "1 year retention agreement"
    })
    assert post_res.status_code == 201
    p_data = json.loads(post_res.data)
    note_id = p_data["offer_note"]["id"]

    # 3. GET List API
    list_res = client.get("/api/offer-notes")
    assert list_res.status_code == 200
    l_data = json.loads(list_res.data)
    assert l_data["count"] >= 1

    # 4. DELETE API
    del_res = client.delete(f"/api/offer-notes/{note_id}")
    assert del_res.status_code == 200
