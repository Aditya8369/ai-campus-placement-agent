"""
Unit and integration tests for CTC to In-Hand Salary and Offer Comparison Calculator (#428).

Verifies:
1. Loading configurable assumptions from data/salary_calculator_assumptions.json.
2. Accurate Indian payroll calculations (EPF, Professional Tax, Standard Deduction, Section 87A rebate, TDS slabs, 4% Cess).
3. Monthly in-hand and guaranteed pay estimation.
4. Side-by-side offer comparison highlighting highest monthly in-hand and highest guaranteed pay.
5. Strict rejection of negative inputs, non-numeric values, and out-of-range figures.
6. Web route GET /ctc-calculator serving assumptions, disclaimer, and comparison form.
7. API route POST /api/ctc-calculator/compare with validation and error responses.
"""

import json
import pytest
from app import app
from utils.ctc_calculator_service import (
    load_calculator_assumptions,
    calculate_tax_for_income,
    calculate_single_offer,
    compare_offers,
    format_inr_currency,
    parse_and_validate_component,
)


@pytest.fixture
def client():
    """Configures a Flask test client."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as test_client:
        yield test_client


# ==============================================================================
# 1. Assumptions Loading
# ==============================================================================

def test_load_calculator_assumptions_from_data_file():
    """Verify assumptions load from data/salary_calculator_assumptions.json with required keys."""
    asm = load_calculator_assumptions()
    assert isinstance(asm, dict)
    assert asm["standard_deduction"] == 75000
    assert asm["basic_pay_percentage_of_fixed"] == 50.0
    assert asm["employee_pf_rate"] == 12.0
    assert asm["professional_tax_annual"] == 2400
    assert asm["health_and_education_cess_rate"] == 4.0
    assert asm["tax_rebate_limit_87a"] == 700000
    assert isinstance(asm["tax_slabs"], list)
    assert len(asm["tax_slabs"]) >= 6
    assert "disclaimer" in asm
    assert "explanatory_notes" in asm
    assert len(asm["explanatory_notes"]) > 0


# ==============================================================================
# 2. Tax Calculation & Slabs
# ==============================================================================

def test_calculate_tax_rebate_under_7_lakh():
    """Verify Section 87A tax rebate grants zero tax liability up to ₹7,00,000 taxable income."""
    slab_tax, cess, total_tax, rebate = calculate_tax_for_income(600000)
    assert slab_tax == 0.0
    assert cess == 0.0
    assert total_tax == 0.0
    assert rebate is True

    slab_tax, cess, total_tax, rebate = calculate_tax_for_income(700000)
    assert total_tax == 0.0
    assert rebate is True


def test_calculate_tax_above_7_lakh():
    """
    Verify tax slab calculation for taxable income of ₹9,25,000 (Gross ₹10L - ₹75k Std Ded):
    - 0 to 3L: 0
    - 3L to 7L (4L @ 5%): ₹20,000
    - 7L to 9.25L (2.25L @ 10%): ₹22,500
    - Slab tax = ₹42,500
    - Cess @ 4% = ₹1,700
    - Total tax = ₹44,200
    """
    slab_tax, cess, total_tax, rebate = calculate_tax_for_income(925000)
    assert slab_tax == 42500.0
    assert cess == 1700.0
    assert total_tax == 44200.0
    assert rebate is False


def test_calculate_tax_high_income_bracket():
    """Verify 30% slab rate for taxable income above ₹15,00,000."""
    # Taxable income = ₹20,00,000
    # 0 - 3L: 0
    # 3L - 7L (4L @ 5%): 20,000
    # 7L - 10L (3L @ 10%): 30,000
    # 10L - 12L (2L @ 15%): 30,000
    # 12L - 15L (3L @ 20%): 60,000
    # Above 15L (5L @ 30%): 150,000
    # Slab tax = 290,000
    # Cess @ 4% = 11,600
    # Total tax = 301,600
    slab_tax, cess, total_tax, rebate = calculate_tax_for_income(2000000)
    assert slab_tax == 290000.0
    assert cess == 11600.0
    assert total_tax == 301600.0


# ==============================================================================
# 3. Single Offer Breakdown
# ==============================================================================

def test_calculate_single_offer_breakdown():
    """Verify single offer calculation with all deductions and in-hand salary."""
    offer_input = {
        "company_name": "Acme Corp",
        "fixed_pay": 1200000,
        "variable_pay": 200000,
        "joining_bonus": 100000,
        "employer_pf": 72000,
    }

    res = calculate_single_offer(offer_input)

    assert res["company_name"] == "Acme Corp"
    assert res["fixed_pay"] == 1200000.0
    assert res["variable_pay"] == 200000.0
    assert res["joining_bonus"] == 100000.0
    assert res["employer_pf"] == 72000.0
    assert res["total_ctc"] == 1572000.0

    # Monthly gross fixed = 12,00,000 / 12 = 1,00,000
    assert res["monthly_fixed_gross"] == 100000.0

    # Basic = 50% of 12L = 6,00,000. Monthly basic = 50,000
    assert res["basic_pay_annual"] == 600000.0
    assert res["basic_pay_monthly"] == 50000.0

    # Employee PF = 12% of 6L = 72,000. Monthly PF = 6,000
    assert res["employee_pf_annual"] == 72000.0
    assert res["employee_pf_monthly"] == 6000.0

    # Professional Tax = 2,400 / year = 200 / month
    assert res["prof_tax_annual"] == 2400.0
    assert res["prof_tax_monthly"] == 200.0

    # Taxable income = 12,00,000 - 75,000 = 11,25,000
    assert res["taxable_income"] == 1125000.0
    # Tax: 0-3L (0) + 3-7L (20k) + 7-10L (30k) + 10-11.25L (1.25L @ 15% = 18,750) = 68,750
    # Cess 4% = 2,750 -> Total = 71,500. Monthly TDS = 71,500 / 12 = 5,958.33
    assert res["slab_tax"] == 68750.0
    assert res["total_tax_annual"] == 71500.0
    assert res["tax_monthly"] == 5958.33

    # Total monthly deductions = 6000 + 200 + 5958.33 = 12158.33
    assert res["total_monthly_deductions"] == 12158.33

    # Monthly in-hand = 100000 - 12158.33 = 87841.67
    assert res["monthly_in_hand"] == 87841.67
    assert res["guaranteed_annual_pay"] == 1200000.0
    assert res["guaranteed_monthly_pay"] == 87841.67


# ==============================================================================
# 4. Input Validation & Negative Rejection
# ==============================================================================

def test_parse_and_validate_component_rejection():
    """Verify negative and invalid numeric inputs are strictly rejected."""
    # Negative values
    with pytest.raises(ValueError, match="cannot be negative"):
        parse_and_validate_component(-50000, "Fixed Pay")

    with pytest.raises(ValueError, match="cannot be negative"):
        parse_and_validate_component("-1000", "Variable Pay")

    # Non-numeric strings
    with pytest.raises(ValueError, match="Invalid numeric input"):
        parse_and_validate_component("one lakh", "Fixed Pay")

    with pytest.raises(ValueError, match="Invalid numeric input"):
        parse_and_validate_component("NaN", "Joining Bonus")

    # Ceiling overflow
    with pytest.raises(ValueError, match="exceeds the maximum supported ceiling"):
        parse_and_validate_component(2_000_000_000, "Fixed Pay")


def test_calculate_single_offer_rejects_negative():
    """Verify calculate_single_offer raises ValueError when negative component is passed."""
    with pytest.raises(ValueError, match="cannot be negative"):
        calculate_single_offer({
            "company_name": "Bad Offer",
            "fixed_pay": 1000000,
            "variable_pay": -200000,
        })


def test_calculate_single_offer_requires_fixed_pay():
    """Verify calculate_single_offer raises ValueError when fixed_pay is missing or zero."""
    with pytest.raises(ValueError, match="Fixed Pay is required"):
        calculate_single_offer({
            "company_name": "Empty Offer",
            "fixed_pay": None,
        })


# ==============================================================================
# 5. Side-by-Side Offer Comparison Logic
# ==============================================================================

def test_compare_offers_highlights_highest_in_hand_and_guaranteed():
    """
    Verify side-by-side comparison accurately identifies:
    - Highest Monthly In-Hand
    - Highest Guaranteed Pay
    - Cases where a high-CTC offer with large variable component produces lower monthly take-home.
    """
    offers_input = [
        # Offer A: 12 LPA Fixed + 3 LPA Variable = 15 LPA CTC
        {
            "company_name": "Startup Alpha",
            "fixed_pay": 1200000,
            "variable_pay": 300000,
            "joining_bonus": 100000,
            "employer_pf": 72000,
        },
        # Offer B: 14 LPA Fixed + 1 LPA Variable = 15 LPA CTC (Higher Guaranteed & In-Hand)
        {
            "company_name": "Enterprise Beta",
            "fixed_pay": 1400000,
            "variable_pay": 100000,
            "joining_bonus": 0,
            "employer_pf": 84000,
        },
        # Offer C: 10 LPA Fixed + 10 LPA Variable = 20 LPA CTC (Highest CTC, but lowest in-hand)
        {
            "company_name": "Company Gamma",
            "fixed_pay": 1000000,
            "variable_pay": 1000000,
            "joining_bonus": 200000,
            "employer_pf": 60000,
        },
    ]

    result = compare_offers(offers_input)

    assert result["success"] is True
    assert result["offers_count"] == 3
    offers = result["offers"]

    # Highlights
    highlights = result["highlights"]
    # Enterprise Beta has highest fixed (14L) and highest monthly in-hand
    assert highlights["highest_in_hand_company"] == "Enterprise Beta"
    assert highlights["highest_guaranteed_company"] == "Enterprise Beta"
    # Company Gamma has highest headline CTC (22.6 LPA including bonus & pf)
    assert highlights["highest_ctc_company"] == "Company Gamma"

    # Specific offer flags
    assert offers[1]["is_highest_in_hand"] is True
    assert offers[1]["is_highest_guaranteed"] is True
    assert offers[2]["is_highest_ctc"] is True

    # Offer B monthly in-hand must be higher than Offer C monthly in-hand
    assert offers[1]["monthly_in_hand"] > offers[2]["monthly_in_hand"]


def test_compare_offers_rejects_empty_list():
    """Verify compare_offers rejects empty offer arrays."""
    with pytest.raises(ValueError, match="At least one offer must be provided"):
        compare_offers([])


# ==============================================================================
# 6. Currency Formatter
# ==============================================================================

def test_format_inr_currency():
    """Verify Indian numbering format representation."""
    assert format_inr_currency(1000) == "₹1,000"
    assert format_inr_currency(100000) == "₹1,00,000"
    assert format_inr_currency(1250000) == "₹12,50,000"
    assert format_inr_currency(0) == "₹0"
    assert format_inr_currency(-5000) == "-₹5,000"


# ==============================================================================
# 7. Web Route & Template Rendering
# ==============================================================================

def test_ctc_calculator_web_view(client):
    """Verify GET /ctc-calculator loads assumptions, slab table, and disclaimer note."""
    response = client.get("/ctc-calculator")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    # Page Header
    assert "CTC to In-Hand Salary &amp; Offer Comparison Calculator" in html or "CTC to In-Hand Salary" in html
    # Visible Disclaimer
    assert "Estimates Only — Not Tax or Legal Advice" in html
    # Assumptions container
    assert 'id="assumptionsPanel"' in html
    assert "Standard Deduction" in html
    assert "Basic Salary %" in html
    assert "Employee PF Rate" in html
    assert "Professional Tax" in html
    # Tax slabs table
    assert "Up to ₹3,00,000" in html
    assert "Above ₹15,00,000" in html


# ==============================================================================
# 8. API Endpoint Validation
# ==============================================================================

def test_api_ctc_calculator_compare_happy_path(client):
    """Verify POST /api/ctc-calculator/compare computes comparison for valid offers."""
    payload = {
        "offers": [
            {
                "company_name": "Google",
                "fixed_pay": 1800000,
                "variable_pay": 200000,
                "joining_bonus": 300000,
                "employer_pf": 108000
            },
            {
                "company_name": "Microsoft",
                "fixed_pay": 1600000,
                "variable_pay": 250000,
                "joining_bonus": 200000,
                "employer_pf": 96000
            }
        ]
    }

    response = client.post("/api/ctc-calculator/compare", json=payload)
    assert response.status_code == 200
    data = response.get_json()

    assert data["success"] is True
    assert data["offers_count"] == 2
    assert data["highlights"]["highest_in_hand_company"] == "Google"
    assert data["highlights"]["highest_guaranteed_company"] == "Google"


def test_api_ctc_calculator_compare_negative_rejected(client):
    """Verify POST /api/ctc-calculator/compare rejects negative numbers with 400 Bad Request."""
    payload = {
        "offers": [
            {
                "company_name": "Negative Corp",
                "fixed_pay": -500000,
                "variable_pay": 100000
            }
        ]
    }

    response = client.post("/api/ctc-calculator/compare", json=payload)
    assert response.status_code == 400
    data = response.get_json()
    assert data["success"] is False
    assert "cannot be negative" in data["error"]


def test_api_ctc_calculator_compare_empty_payload(client):
    """Verify POST /api/ctc-calculator/compare rejects empty offers list with 400 Bad Request."""
    response = client.post("/api/ctc-calculator/compare", json={"offers": []})
    assert response.status_code == 400
    data = response.get_json()
    assert data["success"] is False
    assert "required" in data["error"]
