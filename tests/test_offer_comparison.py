"""
Unit tests for Private Job Offers Comparison Service (#330).
"""

import pytest
from app import app
from utils.database import get_db_connection, init_db
from utils.offer_comparison_service import (
    create_job_offer,
    get_student_offers,
    compare_job_offers
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def clean_offers_table():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS student_job_offers")
    conn.commit()
    conn.close()
    yield
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS student_job_offers")
    conn.commit()
    conn.close()


def test_create_and_get_student_offers():
    res1 = create_job_offer(
        student_id="student-offer-a",
        company_name="Google",
        role_title="Software Engineer",
        base_salary=140000,
        bonus=20000,
        equity_annual=40000,
        work_mode="Hybrid"
    )
    assert res1["success"] is True
    assert res1["offer_id"].startswith("off-")

    res2 = create_job_offer(
        student_id="student-offer-a",
        company_name="Amazon",
        role_title="SDE II",
        base_salary=150000,
        bonus=30000,
        equity_annual=35000,
        work_mode="On-site"
    )
    assert res2["success"] is True

    offers = get_student_offers("student-offer-a")
    assert len(offers) == 2
    # Verify computed total comp
    google_offer = next(o for o in offers if o["company_name"] == "Google")
    assert google_offer["total_compensation"] == 200000


def test_compare_job_offers_side_by_side():
    o1 = create_job_offer("student-a", "Stripe", "Backend", 160000, 20000, 50000)
    o2 = create_job_offer("student-a", "Netflix", "Senior SWE", 240000, 0, 0)

    comparison = compare_job_offers("student-a", [o1["offer_id"], o2["offer_id"]])
    assert comparison["success"] is True
    matrix = comparison["comparison"]
    assert matrix["insights"]["count"] == 2
    assert matrix["insights"]["top_total_comp"] == "Netflix"
    assert len(matrix["attributes"]) >= 10


def test_compare_job_offers_multi_tenant_isolation():
    o_alice = create_job_offer("student-alice", "CompanyA", "RoleA", 100000)
    o_bob = create_job_offer("student-bob", "CompanyB", "RoleB", 120000)

    # Alice trying to compare with Bob's offer
    with pytest.raises(KeyError):
        compare_job_offers("student-alice", [o_alice["offer_id"], o_bob["offer_id"]])


def test_api_offers_endpoints(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "student-api"

    # Create offer 1
    res1 = client.post(
        "/api/offers",
        json={
            "company_name": "Apple",
            "role_title": "iOS Engineer",
            "base_salary": 135000,
            "bonus": 15000,
            "equity_annual": 25000
        }
    )
    assert res1.status_code == 201
    off1_id = res1.get_json()["offer_id"]

    # Create offer 2
    res2 = client.post(
        "/api/offers",
        json={
            "company_name": "Meta",
            "role_title": "Fullstack Engineer",
            "base_salary": 145000,
            "bonus": 20000,
            "equity_annual": 30000
        }
    )
    assert res2.status_code == 201
    off2_id = res2.get_json()["offer_id"]

    # Compare API
    res_cmp = client.post(
        "/api/offers/compare",
        json={"offer_ids": [off1_id, off2_id]}
    )
    assert res_cmp.status_code == 200
    assert res_cmp.get_json()["success"] is True


def test_offers_compare_page_route(client):
    res = client.get("/offers/compare")
    assert res.status_code == 200
    assert "Private Job Offers Comparison" in res.data.decode("utf-8")
