"""
CTC to In-Hand Salary and Offer Comparison Calculator Service (#428).

Estimates monthly in-hand salary and provides multi-offer comparative analytics
based on configurable payroll assumptions stored in data/salary_calculator_assumptions.json:
- Standard Deduction (New Tax Regime: ₹75,000)
- Employee Provident Fund (EPF: 12% of basic, basic assumed 50% of fixed pay)
- Professional Tax (₹2,400/year, ₹200/month)
- New Tax Regime Slab Table (FY 2024-25 / FY 2025-26) with Section 87A rebate
- Side-by-side offer comparison highlighting Highest In-Hand and Highest Guaranteed Pay
- Rejection of invalid and negative inputs
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional, Tuple, Union

import config

logger = logging.getLogger(__name__)

ASSUMPTIONS_FILE_PATH = os.path.join(config.BASE_DIR, "data", "salary_calculator_assumptions.json")

# Fallback assumptions in case data file is unavailable
DEFAULT_ASSUMPTIONS: Dict[str, Any] = {
    "financial_year": "FY 2024-25 / FY 2025-26",
    "tax_regime": "New Tax Regime (Section 115BAC)",
    "standard_deduction": 75000,
    "basic_pay_percentage_of_fixed": 50.0,
    "employee_pf_rate": 12.0,
    "employer_pf_rate": 12.0,
    "professional_tax_annual": 2400,
    "professional_tax_monthly": 200,
    "health_and_education_cess_rate": 4.0,
    "tax_rebate_limit_87a": 700000,
    "tax_slabs": [
        {"from": 0, "to": 300000, "rate": 0.0, "label": "Up to ₹3,00,000"},
        {"from": 300000, "to": 700000, "rate": 5.0, "label": "₹3,00,001 - ₹7,00,000"},
        {"from": 700000, "to": 1000000, "rate": 10.0, "label": "₹7,00,001 - ₹10,00,000"},
        {"from": 1000000, "to": 1200000, "rate": 15.0, "label": "₹10,00,001 - ₹12,00,000"},
        {"from": 1200000, "to": 1500000, "rate": 20.0, "label": "₹12,00,001 - ₹15,00,000"},
        {"from": 1500000, "to": None, "rate": 30.0, "label": "Above ₹15,00,000"},
    ],
    "explanatory_notes": [
        "Fixed Pay represents guaranteed gross annual compensation.",
        "Basic Salary is assumed at 50% of annual fixed pay.",
        "Employee PF is calculated at 12% of basic salary.",
        "Employer PF is included in CTC by recruiters but is not part of monthly payout.",
        "Professional Tax is assumed at ₹200/month (₹2,400/year).",
        "Standard Deduction of ₹75,000 is applied under the default New Tax Regime.",
        "Section 87A rebate grants zero tax liability up to ₹7,00,000 taxable income.",
        "Health & Education Cess of 4% applies on computed income tax."
    ],
    "disclaimer": "These calculations are estimates provided for placement comparison purposes only and do not constitute certified tax, legal, or financial advice. Actual payroll deductions may vary."
}


def load_calculator_assumptions() -> Dict[str, Any]:
    """
    Loads configurable salary and tax assumptions from the data file.
    Falls back to DEFAULT_ASSUMPTIONS if file is missing or corrupted.
    """
    if os.path.exists(ASSUMPTIONS_FILE_PATH):
        try:
            with open(ASSUMPTIONS_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "tax_slabs" in data:
                    return data
        except Exception as e:
            logger.warning(f"Failed to read assumptions file from {ASSUMPTIONS_FILE_PATH}: {e}")

    return DEFAULT_ASSUMPTIONS.copy()


def format_inr_currency(amount: Union[int, float]) -> str:
    """
    Formats a numeric amount into Indian Currency representation (e.g. ₹12,50,000).
    """
    try:
        val = round(float(amount))
    except (ValueError, TypeError):
        return "₹0"

    is_negative = val < 0
    val_str = str(abs(val))

    if len(val_str) <= 3:
        formatted = val_str
    else:
        last_three = val_str[-3:]
        remaining = val_str[:-3]
        groups = []
        while len(remaining) > 2:
            groups.insert(0, remaining[-2:])
            remaining = remaining[:-2]
        if remaining:
            groups.insert(0, remaining)
        formatted = ",".join(groups) + "," + last_three

    return f"-₹{formatted}" if is_negative else f"₹{formatted}"


def parse_and_validate_component(
    val: Any,
    field_name: str,
    default: float = 0.0,
    required: bool = False
) -> float:
    """
    Parses and strictly validates a salary component.
    Rejects negative numbers, non-numeric values, or values exceeding limits.
    """
    if val is None or val == "":
        if required:
            raise ValueError(f"{field_name} is required and cannot be empty.")
        return default

    # If string, strip currency symbols, commas, and whitespace
    if isinstance(val, str):
        cleaned = val.replace("₹", "").replace(",", "").replace("$", "").replace(" ", "").strip()
        if not cleaned:
            if required:
                raise ValueError(f"{field_name} is required and cannot be empty.")
            return default
        try:
            num = float(cleaned)
        except ValueError:
            raise ValueError(f"Invalid numeric input for '{field_name}': '{val}'. Please enter a valid number.")
    elif isinstance(val, (int, float)):
        num = float(val)
    else:
        raise ValueError(f"Invalid type for '{field_name}'. Expected number or string.")

    # Reject NaN or Infinite
    if num != num or num in (float("inf"), float("-inf")):
        raise ValueError(f"Invalid numeric input for '{field_name}'.")

    # Strict rejection of negative amounts
    if num < 0:
        raise ValueError(f"'{field_name}' cannot be negative (received {val}). Please enter a non-negative amount.")

    # Maximum allowable ceiling (₹100 Crore)
    if num > 1_000_000_000:
        raise ValueError(f"'{field_name}' exceeds the maximum supported ceiling of ₹100 Crore.")

    return num


def calculate_tax_for_income(
    taxable_income: float,
    assumptions: Optional[Dict[str, Any]] = None
) -> Tuple[float, float, float, bool]:
    """
    Calculates income tax under the New Tax Regime.
    Returns: (slab_tax, cess, total_tax, rebate_applied)
    """
    if taxable_income <= 0:
        return 0.0, 0.0, 0.0, True

    asm = assumptions or load_calculator_assumptions()
    rebate_limit = float(asm.get("tax_rebate_limit_87a", 700000))
    cess_rate = float(asm.get("health_and_education_cess_rate", 4.0))
    slabs = asm.get("tax_slabs", DEFAULT_ASSUMPTIONS["tax_slabs"])

    # Section 87A rebate under New Regime: zero tax if taxable income <= rebate_limit
    if taxable_income <= rebate_limit:
        return 0.0, 0.0, 0.0, True

    slab_tax = 0.0
    for slab in slabs:
        s_from = float(slab.get("from", 0))
        s_to = slab.get("to")
        s_rate = float(slab.get("rate", 0))

        if taxable_income > s_from:
            if s_to is not None:
                s_to_val = float(s_to)
                taxable_in_slab = min(taxable_income, s_to_val) - s_from
            else:
                taxable_in_slab = taxable_income - s_from

            if taxable_in_slab > 0 and s_rate > 0:
                slab_tax += taxable_in_slab * (s_rate / 100.0)

    cess = slab_tax * (cess_rate / 100.0)
    total_tax = slab_tax + cess

    return round(slab_tax, 2), round(cess, 2), round(total_tax, 2), False


def calculate_single_offer(
    offer_input: Dict[str, Any],
    assumptions: Optional[Dict[str, Any]] = None,
    offer_index: int = 1
) -> Dict[str, Any]:
    """
    Performs complete breakdown calculation for a single offer.
    Validates components, computes deductions (PF, Professional Tax, TDS),
    and determines monthly in-hand and guaranteed pay.
    """
    if not isinstance(offer_input, dict):
        raise ValueError("Offer input must be a dictionary.")

    asm = assumptions or load_calculator_assumptions()

    company_name = str(offer_input.get("company_name") or f"Offer {offer_index}").strip()
    if not company_name:
        company_name = f"Offer {offer_index}"

    fixed_pay = parse_and_validate_component(offer_input.get("fixed_pay"), "Fixed Pay", required=True)
    variable_pay = parse_and_validate_component(offer_input.get("variable_pay"), "Variable Pay", default=0.0)
    joining_bonus = parse_and_validate_component(offer_input.get("joining_bonus"), "Joining Bonus", default=0.0)
    employer_pf = parse_and_validate_component(offer_input.get("employer_pf"), "Employer PF", default=0.0)

    # Configurable percentages and rates
    basic_pct = float(asm.get("basic_pay_percentage_of_fixed", 50.0))
    employee_pf_rate = float(asm.get("employee_pf_rate", 12.0))
    prof_tax_annual = float(asm.get("professional_tax_annual", 2400.0))
    prof_tax_monthly = round(prof_tax_annual / 12.0, 2)
    std_deduction = float(asm.get("standard_deduction", 75000.0))

    # Basic Pay & Employee PF
    basic_pay_annual = round(fixed_pay * (basic_pct / 100.0), 2)
    basic_pay_monthly = round(basic_pay_annual / 12.0, 2)

    employee_pf_annual = round(basic_pay_annual * (employee_pf_rate / 100.0), 2)
    employee_pf_monthly = round(employee_pf_annual / 12.0, 2)

    # Tax calculation based on guaranteed fixed pay
    taxable_income = max(0.0, round(fixed_pay - std_deduction, 2))
    slab_tax, cess, total_tax_annual, rebate_applied = calculate_tax_for_income(taxable_income, asm)
    tax_monthly = round(total_tax_annual / 12.0, 2)

    # Monthly Gross and In-Hand
    monthly_fixed_gross = round(fixed_pay / 12.0, 2)
    total_monthly_deductions = round(employee_pf_monthly + prof_tax_monthly + tax_monthly, 2)
    monthly_in_hand = max(0.0, round(monthly_fixed_gross - total_monthly_deductions, 2))
    annual_in_hand = round(monthly_in_hand * 12.0, 2)

    total_ctc = round(fixed_pay + variable_pay + joining_bonus + employer_pf, 2)
    first_year_gross_cash = round(fixed_pay + variable_pay + joining_bonus, 2)

    return {
        "offer_id": offer_input.get("offer_id") or f"offer_{offer_index}",
        "offer_index": offer_index,
        "company_name": company_name,
        "fixed_pay": fixed_pay,
        "variable_pay": variable_pay,
        "joining_bonus": joining_bonus,
        "employer_pf": employer_pf,
        "total_ctc": total_ctc,
        "first_year_gross_cash": first_year_gross_cash,
        "guaranteed_annual_pay": fixed_pay,
        "guaranteed_monthly_pay": monthly_in_hand,
        # Monthly breakdown
        "monthly_fixed_gross": monthly_fixed_gross,
        "basic_pay_monthly": basic_pay_monthly,
        "employee_pf_monthly": employee_pf_monthly,
        "prof_tax_monthly": prof_tax_monthly,
        "tax_monthly": tax_monthly,
        "total_monthly_deductions": total_monthly_deductions,
        "monthly_in_hand": monthly_in_hand,
        "annual_in_hand": annual_in_hand,
        # Annual breakdown
        "basic_pay_annual": basic_pay_annual,
        "employee_pf_annual": employee_pf_annual,
        "prof_tax_annual": prof_tax_annual,
        "std_deduction": std_deduction,
        "taxable_income": taxable_income,
        "slab_tax": slab_tax,
        "cess": cess,
        "total_tax_annual": total_tax_annual,
        "rebate_applied": rebate_applied,
        # Formatted currency representations
        "formatted": {
            "fixed_pay": format_inr_currency(fixed_pay),
            "variable_pay": format_inr_currency(variable_pay),
            "joining_bonus": format_inr_currency(joining_bonus),
            "employer_pf": format_inr_currency(employer_pf),
            "total_ctc": format_inr_currency(total_ctc),
            "monthly_fixed_gross": format_inr_currency(monthly_fixed_gross),
            "basic_pay_monthly": format_inr_currency(basic_pay_monthly),
            "employee_pf_monthly": format_inr_currency(employee_pf_monthly),
            "prof_tax_monthly": format_inr_currency(prof_tax_monthly),
            "tax_monthly": format_inr_currency(tax_monthly),
            "total_monthly_deductions": format_inr_currency(total_monthly_deductions),
            "monthly_in_hand": format_inr_currency(monthly_in_hand),
            "annual_in_hand": format_inr_currency(annual_in_hand),
            "taxable_income": format_inr_currency(taxable_income),
            "total_tax_annual": format_inr_currency(total_tax_annual),
        }
    }


def compare_offers(
    offers_input: List[Dict[str, Any]],
    assumptions: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Compares up to 3 job offers side-by-side.
    Validates all inputs, performs full deduction breakdowns, and highlights:
    - Highest In-Hand Pay (Monthly and Annual)
    - Highest Guaranteed Pay (Fixed component)
    - Highest Total CTC
    """
    if not isinstance(offers_input, list):
        raise ValueError("Offers input must be a list of offer dictionaries.")

    if not offers_input:
        raise ValueError("At least one offer must be provided for calculation.")

    # Limit to maximum of 3 offers
    valid_inputs = [o for o in offers_input[:3] if isinstance(o, dict)]

    if not valid_inputs:
        raise ValueError("Please provide at least one valid offer with fixed pay.")

    asm = assumptions or load_calculator_assumptions()
    calculated_offers: List[Dict[str, Any]] = []

    for idx, offer in enumerate(valid_inputs, start=1):
        # Calculate single offer (validates inputs, raises ValueError on negative or invalid)
        res = calculate_single_offer(offer, assumptions=asm, offer_index=idx)
        calculated_offers.append(res)

    if not calculated_offers:
        raise ValueError("No valid offers could be calculated.")

    # Determine Highlights
    highest_in_hand = max(calculated_offers, key=lambda x: x["monthly_in_hand"])
    highest_guaranteed = max(calculated_offers, key=lambda x: x["fixed_pay"])
    highest_ctc = max(calculated_offers, key=lambda x: x["total_ctc"])

    # Annotate highlights on each offer
    for off in calculated_offers:
        off["is_highest_in_hand"] = (off["monthly_in_hand"] == highest_in_hand["monthly_in_hand"] and off["monthly_in_hand"] > 0)
        off["is_highest_guaranteed"] = (off["fixed_pay"] == highest_guaranteed["fixed_pay"] and off["fixed_pay"] > 0)
        off["is_highest_ctc"] = (off["total_ctc"] == highest_ctc["total_ctc"] and off["total_ctc"] > 0)

    highlights = {
        "highest_in_hand_company": highest_in_hand["company_name"],
        "highest_in_hand_monthly": highest_in_hand["monthly_in_hand"],
        "highest_in_hand_formatted": format_inr_currency(highest_in_hand["monthly_in_hand"]),
        "highest_guaranteed_company": highest_guaranteed["company_name"],
        "highest_guaranteed_fixed": highest_guaranteed["fixed_pay"],
        "highest_guaranteed_formatted": format_inr_currency(highest_guaranteed["fixed_pay"]),
        "highest_ctc_company": highest_ctc["company_name"],
        "highest_ctc_amount": highest_ctc["total_ctc"],
        "highest_ctc_formatted": format_inr_currency(highest_ctc["total_ctc"]),
    }

    return {
        "success": True,
        "offers_count": len(calculated_offers),
        "offers": calculated_offers,
        "highlights": highlights,
        "assumptions": asm,
        "disclaimer": asm.get("disclaimer", DEFAULT_ASSUMPTIONS["disclaimer"])
    }
