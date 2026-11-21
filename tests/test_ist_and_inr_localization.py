"""
Unit & Integration Tests for Regional IST Date/Time and INR Formatting (#650)
=============================================================================
Validates:
1. Indian Standard Time (IST) formatting: `format_date_ist`, `format_datetime_ist`, `format_time_ist`
2. Daylight-saving-free invariance (permanent UTC+05:30 offset across seasons)
3. Midnight boundary transitions between UTC and IST
4. Indian numbering digit grouping: values below 1 lakh, between 1 lakh and 1 crore, and above 1 crore
5. Compensation display: LPA, Crores, and currency symbols
6. Jinja2 template filter and context processor registration in Flask
7. Database UTC storage invariance
"""

import datetime as dt
import pytest
from flask import Flask, render_template_string
from utils.formatters import (
    format_date_ist,
    format_datetime_ist,
    format_time_ist,
    format_indian_number,
    format_inr,
    format_lpa,
    format_crore,
    format_inr_words,
    get_display_timezone,
    IST_TZ,
)
import config


# ============================================================================
# 1. Indian Date & DateTime Formatting Tests
# ============================================================================

def test_format_date_ist_standard():
    """Verify format_date_ist returns '21 Nov 2026' style representations."""
    # UTC timestamp representing 21 Nov 2026 at 13:00 UTC (18:30 IST)
    utc_iso = "2026-11-21T13:00:00Z"
    assert format_date_ist(utc_iso) == "21 Nov 2026"

    # SQL format string
    sql_timestamp = "2026-11-21 13:00:00"
    assert format_date_ist(sql_timestamp) == "21 Nov 2026"

    # Date-only string preserves the specified date without unwanted shifting
    date_only = "2026-11-21"
    assert format_date_ist(date_only) == "21 Nov 2026"

    # Datetime objects (both naive assumed UTC and timezone-aware)
    naive_dt = dt.datetime(2026, 11, 21, 13, 0, 0)
    assert format_date_ist(naive_dt) == "21 Nov 2026"

    aware_dt = dt.datetime(2026, 11, 21, 13, 0, 0, tzinfo=dt.timezone.utc)
    assert format_date_ist(aware_dt) == "21 Nov 2026"

    # Date object
    d_obj = dt.date(2026, 11, 21)
    assert format_date_ist(d_obj) == "21 Nov 2026"


def test_format_datetime_ist_standard():
    """Verify format_datetime_ist returns '21 Nov 2026, 6:30 PM IST' exactly."""
    utc_str = "2026-11-21 13:00:00"
    res = format_datetime_ist(utc_str)
    assert res == "21 Nov 2026, 6:30 PM IST"

    # With ISO Z suffix
    utc_iso = "2026-11-21T13:00:00Z"
    assert format_datetime_ist(utc_iso) == "21 Nov 2026, 6:30 PM IST"

    # Morning unpadded hour (e.g. 09:15 AM -> 9:15 AM IST)
    # 03:45 UTC + 05:30 = 09:15 IST
    morning_utc = "2026-11-21 03:45:00"
    assert format_datetime_ist(morning_utc) == "21 Nov 2026, 9:15 AM IST"


def test_format_time_ist():
    """Verify time-only extraction in IST."""
    assert format_time_ist("2026-11-21 13:00:00") == "6:30 PM IST"
    assert format_time_ist("18:30") == "6:30 PM IST"
    assert format_time_ist("09:15") == "9:15 AM IST"
    assert format_time_ist("00:00") == "12:00 AM IST"


def test_format_date_and_datetime_empty_and_invalid():
    """Verify graceful handling for None, empty, or unparseable date values."""
    assert format_date_ist(None) == ""
    assert format_date_ist("", default="—") == "—"
    assert format_datetime_ist(None) == ""
    assert format_datetime_ist("", default="Recent") == "Recent"
    assert format_time_ist(None, default="N/A") == "N/A"
    assert format_date_ist("invalid-date-string") == "invalid-date-string"


# ============================================================================
# 2. Midnight Boundaries and Day Transitions
# ============================================================================

def test_utc_to_ist_midnight_transitions():
    """
    Verify timezone conversion across midnight boundaries:
    UTC 18:30 on Nov 21 is EXACTLY midnight (00:00) Nov 22 in IST.
    """
    # 18:29:59 UTC -> Nov 21, 11:59 PM IST
    before_midnight_utc = dt.datetime(2026, 11, 21, 18, 29, 59, tzinfo=dt.timezone.utc)
    assert format_date_ist(before_midnight_utc) == "21 Nov 2026"
    assert format_datetime_ist(before_midnight_utc) == "21 Nov 2026, 11:59 PM IST"

    # Exactly 18:30:00 UTC -> Nov 22, 12:00 AM IST
    exact_midnight_utc = dt.datetime(2026, 11, 21, 18, 30, 0, tzinfo=dt.timezone.utc)
    assert format_date_ist(exact_midnight_utc) == "22 Nov 2026"
    assert format_datetime_ist(exact_midnight_utc) == "22 Nov 2026, 12:00 AM IST"

    # 20:00:00 UTC -> Nov 22, 1:30 AM IST
    after_midnight_utc = "2026-11-21 20:00:00"
    assert format_date_ist(after_midnight_utc) == "22 Nov 2026"
    assert format_datetime_ist(after_midnight_utc) == "22 Nov 2026, 1:30 AM IST"

    # Noon boundary: 06:30 UTC -> 12:00 PM IST
    noon_utc = dt.datetime(2026, 11, 21, 6, 30, 0, tzinfo=dt.timezone.utc)
    assert format_datetime_ist(noon_utc) == "21 Nov 2026, 12:00 PM IST"


# ============================================================================
# 3. Daylight Saving Free Invariant
# ============================================================================

def test_daylight_saving_free_ist_invariant():
    """
    Verify that IST has no daylight saving time (DST) shifts.
    Offset must remain strictly +05:30 across summer and winter dates.
    """
    summer_solstice = dt.datetime(2026, 6, 21, 12, 0, 0, tzinfo=IST_TZ)
    winter_solstice = dt.datetime(2026, 12, 21, 12, 0, 0, tzinfo=IST_TZ)

    # Both offsets must be identical: 5 hours and 30 minutes
    expected_offset = dt.timedelta(hours=5, minutes=30)
    assert summer_solstice.utcoffset() == expected_offset
    assert winter_solstice.utcoffset() == expected_offset

    # Timezone label must remain 'IST'
    assert summer_solstice.tzname() == "IST"
    assert winter_solstice.tzname() == "IST"

    # Test March and November US/UK DST transition dates
    us_spring_forward = dt.datetime(2026, 3, 8, 12, 0, tzinfo=IST_TZ)
    us_fall_back = dt.datetime(2026, 11, 1, 12, 0, tzinfo=IST_TZ)
    assert us_spring_forward.utcoffset() == expected_offset
    assert us_fall_back.utcoffset() == expected_offset


# ============================================================================
# 4. Indian Digit Grouping (format_indian_number & format_inr)
# ============================================================================

def test_indian_digit_grouping_below_one_lakh():
    """Values below 1,00,000 (hundreds and thousands)."""
    assert format_indian_number(0) == "0"
    assert format_indian_number(5) == "5"
    assert format_indian_number(50) == "50"
    assert format_indian_number(500) == "500"
    assert format_indian_number(999) == "999"
    assert format_indian_number(1000) == "1,000"
    assert format_indian_number(10000) == "10,000"
    assert format_indian_number(50000) == "50,000"
    assert format_indian_number(99999) == "99,999"


def test_indian_digit_grouping_between_one_lakh_and_one_crore():
    """Values from 1,00,000 up to 99,99,999 (Lakhs)."""
    assert format_indian_number(100000) == "1,00,000"
    assert format_indian_number(123456) == "1,23,456"
    assert format_indian_number(1234567) == "12,34,567"
    assert format_indian_number(1200000) == "12,00,000"
    assert format_indian_number(5000000) == "50,00,000"
    assert format_indian_number(9999999) == "99,99,999"


def test_indian_digit_grouping_one_crore_and_above():
    """Values of 1,00,00,000 and above (Crores)."""
    assert format_indian_number(10000000) == "1,00,00,000"
    assert format_indian_number(12345678) == "1,23,45,678"
    assert format_indian_number(123456789) == "12,34,56,789"
    assert format_indian_number(1234567890) == "1,23,45,67,890"


def test_format_inr_basic_and_symbols():
    """Verify format_inr with and without currency symbols and negative values."""
    assert format_inr(1234567) == "12,34,567"
    assert format_inr(1234567, symbol=True) == "₹12,34,567"
    assert format_inr(-1234567) == "-12,34,567"
    assert format_inr(-1234567, symbol=True) == "-₹12,34,567"
    assert format_inr(0) == "0"
    assert format_inr(None) == ""
    assert format_inr("", default="—") == "—"

    # Pre-formatted string inputs
    assert format_inr("₹12,34,567") == "12,34,567"
    assert format_inr("1234567") == "12,34,567"


def test_format_inr_lpa_and_crore_display():
    """Verify optional LPA and Crore display for placement packages."""
    # LPA display from raw numbers
    assert format_inr(1200000, lpa=True) == "12 LPA"
    assert format_inr(1250000, lpa=True) == "12.5 LPA"
    assert format_inr(800000, lpa=True) == "8 LPA"
    assert format_inr(1200000, lpa=True, symbol=True) == "₹12 LPA"

    # LPA display when already in lakhs (e.g. 12 or 14.5)
    assert format_inr(12, lpa=True) == "12 LPA"
    assert format_inr(14.5, lpa=True) == "14.5 LPA"

    # Shortcut helpers
    assert format_lpa(1200000) == "12 LPA"
    assert format_lpa(1500000, symbol=True) == "₹15 LPA"

    # Crore formatting
    assert format_inr(10000000, cr=True) == "1 Cr"
    assert format_inr(15000000, cr=True) == "1.5 Cr"
    assert format_crore(12000000) == "1.2 Cr"
    assert format_crore(10000000, symbol=True) == "₹1 Cr"

    # Friendly words formatting
    assert format_inr_words(10000000) == "1 Crore"
    assert format_inr_words(20000000) == "2 Crores"
    assert format_inr_words(1250000) == "12.5 Lakhs"
    assert format_inr_words(100000) == "1 Lakh"
    assert format_inr_words(50000) == "50 Thousand"


# ============================================================================
# 5. Configurable Timezone & Jinja2 Template Integration
# ============================================================================

def test_configurable_timezone():
    """Verify that DISPLAY_TIMEZONE in config is respected."""
    assert getattr(config, "DISPLAY_TIMEZONE", None) == "Asia/Kolkata"
    assert getattr(config, "TIMEZONE", None) == "Asia/Kolkata"

    tz_obj = get_display_timezone("Asia/Kolkata")
    assert tz_obj == IST_TZ

    tz_utc = get_display_timezone("UTC")
    assert tz_utc == dt.timezone.utc


def test_jinja_template_filter_rendering():
    """Verify filters work inside Jinja2 template rendering."""
    from routes import create_app
    app = create_app({"TESTING": True})

    with app.test_request_context("/"):
        # 1. Date filter
        tmpl_date = "{{ '2026-11-21T13:00:00Z' | format_date_ist }}"
        assert render_template_string(tmpl_date) == "21 Nov 2026"

        # 2. DateTime filter
        tmpl_datetime = "{{ '2026-11-21 13:00:00' | format_datetime_ist }}"
        assert render_template_string(tmpl_datetime) == "21 Nov 2026, 6:30 PM IST"

        # 3. Currency filter with Indian grouping
        tmpl_inr = "{{ 1234567 | format_inr }}"
        assert render_template_string(tmpl_inr) == "12,34,567"

        # 4. Currency filter with LPA
        tmpl_lpa = "{{ 1200000 | format_inr(lpa=True) }}"
        assert render_template_string(tmpl_lpa) == "12 LPA"

        # 5. Currency filter with symbol
        tmpl_sym = "{{ 1234567 | format_inr(symbol=True) }}"
        assert render_template_string(tmpl_sym) == "₹12,34,567"

        # 6. Context processor injection allows calling as functions
        tmpl_func = "{{ format_date_ist('2026-11-21') }} - {{ format_inr(50000) }}"
        assert render_template_string(tmpl_func) == "21 Nov 2026 - 50,000"
