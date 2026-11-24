"""
Property-Based Tests with Hypothesis (#692).
============================================
Tests pure platform functions against randomized, unpredictable, and edge-case inputs:
1. Resume text cleaning & artifact normalization (utils.text_cleaner)
2. Skill extraction, normalization & matching (utils.role_skill_gap_service, utils.resume_info_extractor)
3. ATS & match score calculations (utils.ats_score_service, agents.job_recommendation_agent, agents.bullet_agent)
4. Regional date & salary parsers/formatters (utils.formatters)
5. Filename sanitization & path traversal security (utils.file_validation_service)
6. Input length & text validators (utils.input_validator)

Guarantees:
- Zero network or API key dependencies.
- Fast execution in CI (max_examples tuned for CI speed, complete suite runs in seconds).
- Explicit regression tests for edge cases discovered during property testing.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import re
from typing import Any, List, Set

import pytest
from hypothesis import given, settings, strategies as st

# Pure functions under test
from utils.text_cleaner import (
    normalize_resume_text,
    expand_ligatures,
    join_hyphenated_line_breaks,
    normalize_bullets,
    collapse_whitespace,
    LIGATURE_MAPPING,
)
from utils.role_skill_gap_service import (
    normalize_skill_name,
    skills_match,
    extract_candidate_skills,
    SKILL_ALIASES,
)
from utils.ats_score_service import evaluate_resume_ats_score
from agents.job_recommendation_agent import JobRecommendationAgent
from agents.bullet_agent import BulletOptimizerAgent
from utils.formatters import (
    parse_utc_datetime,
    format_date_ist,
    format_datetime_ist,
    format_indian_number,
    format_inr,
    format_lpa,
)
from utils.file_validation_service import sanitize_filename, WINDOWS_RESERVED_NAMES
from utils.input_validator import (
    validate_string,
    sanitize_text,
    ValidationError,
)


# ==============================================================================
# CUSTOM HYPOTHESIS STRATEGIES
# ==============================================================================

# Unicode text including ligatures, bullets, fullwidth, and multi-line breaks
realistic_text_strategy = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),  # exclude lone surrogates
        min_codepoint=32,
    ),
    max_size=1500,
)

bullet_sample_strategy = st.sampled_from(["•", "‣", "⁃", "◦", "▪", "●", "★", "➢", "\uf0b7", "\ue000"])

known_ligature_strategy = st.sampled_from(list(LIGATURE_MAPPING.keys()))

known_alias_strategy = st.sampled_from(list(SKILL_ALIASES.keys()))


# ==============================================================================
# 1. RESUME TEXT CLEANING & NORMALIZATION PROPERTIES
# ==============================================================================

class TestResumeTextCleaningProperties:
    """Property-based tests for resume text normalization in utils.text_cleaner."""

    @settings(max_examples=50, deadline=None)
    @given(text=realistic_text_strategy)
    def test_normalize_resume_text_never_crashes_and_returns_string(self, text: str):
        """Property: normalize_resume_text always returns a string without crashing."""
        result = normalize_resume_text(text, store_raw=False)
        assert isinstance(result, str)

    @settings(max_examples=50, deadline=None)
    @given(text=realistic_text_strategy)
    def test_normalize_resume_text_is_deterministic(self, text: str):
        """Property: Running normalization twice on identical input produces identical output."""
        res1 = normalize_resume_text(text, store_raw=False)
        res2 = normalize_resume_text(text, store_raw=False)
        assert res1 == res2

    @settings(max_examples=50, deadline=None)
    @given(text=realistic_text_strategy)
    def test_normalize_resume_text_is_idempotent(self, text: str):
        """Property: Normalizing already-normalized text produces identical output."""
        first_pass = normalize_resume_text(text, store_raw=False)
        second_pass = normalize_resume_text(first_pass, store_raw=False)
        assert first_pass == second_pass

    @settings(max_examples=40, deadline=None)
    @given(
        prefix=st.text(min_size=0, max_size=30),
        ligature=known_ligature_strategy,
        suffix=st.text(min_size=0, max_size=30),
    )
    def test_ligature_expansion_eliminates_target_ligature(self, prefix: str, ligature: str, suffix: str):
        """Property: expand_ligatures always substitutes known typographic ligatures."""
        composed = f"{prefix}{ligature}{suffix}"
        expanded = expand_ligatures(composed)
        assert ligature not in expanded
        assert LIGATURE_MAPPING[ligature] in expanded


# ==============================================================================
# 2. SKILL EXTRACTION & NORMALIZATION PROPERTIES
# ==============================================================================

class TestSkillExtractionProperties:
    """Property-based tests for skill extraction, normalization and matching."""

    @settings(max_examples=50, deadline=None)
    @given(skill=st.text(max_size=100))
    def test_normalize_skill_name_never_crashes_and_is_idempotent(self, skill: str):
        """Property: normalize_skill_name returns a string and is idempotent."""
        norm1 = normalize_skill_name(skill)
        assert isinstance(norm1, str)
        norm2 = normalize_skill_name(norm1)
        assert norm1 == norm2

    @settings(max_examples=40, deadline=None)
    @given(alias=known_alias_strategy)
    def test_known_skill_aliases_resolve_to_canonical(self, alias: str):
        """Property: Known skill aliases in various casings map to canonical form."""
        canonical = SKILL_ALIASES[alias]
        assert normalize_skill_name(alias.upper()) == canonical
        assert normalize_skill_name(f"  {alias}  ") == canonical

    @settings(max_examples=50, deadline=None)
    @given(skill=st.text(min_size=1, max_size=50))
    def test_skills_match_is_reflexive_for_valid_skills(self, skill: str):
        """Property: If skill resolves to a non-empty canonical form, it must match itself."""
        norm = normalize_skill_name(skill)
        if norm:
            assert skills_match(skill, skill) is True

    @settings(max_examples=40, deadline=None)
    @given(skills_input=st.lists(st.text(min_size=1, max_size=40), max_size=15))
    def test_extract_candidate_skills_invariants(self, skills_input: List[str]):
        """Property: extract_candidate_skills produces sorted deduplicated non-empty strings."""
        extracted = extract_candidate_skills(skills_input)
        assert isinstance(extracted, list)
        assert all(isinstance(s, str) and s.strip() for s in extracted)
        # Deduplicated check
        assert len(extracted) == len(set(extracted))
        # Sorted check
        assert extracted == sorted(extracted)


# ==============================================================================
# 3. SCORE CALCULATION PROPERTIES (ALWAYS 0-100 & DETERMINISTIC)
# ==============================================================================

class TestScoreCalculationProperties:
    """Property-based tests ensuring scores are strictly clamped in [0, 100] and deterministic."""

    @settings(max_examples=40, deadline=None)
    @given(resume_text=realistic_text_strategy)
    def test_ats_score_strictly_clamped_and_deterministic(self, resume_text: str):
        """
        Property: evaluate_resume_ats_score always yields a total_score in [0, 100]
        and identical results across consecutive runs for the exact same input text.
        """
        res1 = evaluate_resume_ats_score(resume_text)
        assert isinstance(res1, dict)
        score1 = res1.get("total_score")
        assert isinstance(score1, int)
        assert 0 <= score1 <= 100

        # Verify sections bounds
        for sec_key, sec_data in res1.get("sections", {}).items():
            s = sec_data.get("score", 0)
            ms = sec_data.get("max_score", 0)
            assert 0 <= s <= ms

        # Determinism check
        res2 = evaluate_resume_ats_score(resume_text)
        assert res1["total_score"] == res2["total_score"]
        assert res1["rating"] == res2["rating"]

    @settings(max_examples=50, deadline=None)
    @given(bullet=st.text(max_size=300))
    def test_calculate_bullet_score_clamped_and_deterministic(self, bullet: str):
        """Property: calculate_bullet_score produces an integer strictly in [0, 100]."""
        score = BulletOptimizerAgent.calculate_bullet_score(bullet)
        assert isinstance(score, int)
        assert 0 <= score <= 100
        # Deterministic
        assert BulletOptimizerAgent.calculate_bullet_score(bullet) == score

    @settings(max_examples=40, deadline=None)
    @given(
        ats_score=st.integers(min_value=-500, max_value=500),
        req_count=st.integers(min_value=0, max_value=8),
        pref_count=st.integers(min_value=0, max_value=5),
        target_company=st.text(max_size=30),
    )
    def test_score_job_match_strictly_clamped(
        self, ats_score: int, req_count: int, pref_count: int, target_company: str
    ):
        """Property: score_job_match percentage is strictly clamped between 0 and 100."""
        agent = JobRecommendationAgent()
        job = {
            "title": "Software Engineer",
            "company": "Tech Corp",
            "required_skills": [f"skill_req_{i}" for i in range(req_count)],
            "preferred_skills": [f"skill_pref_{i}" for i in range(pref_count)],
        }
        candidate_skills = {"skill_req_0", "python", "sql"}
        result = agent.score_job_match(
            job=job,
            candidate_skills=candidate_skills,
            ats_score=ats_score,
            target_company=target_company,
        )
        pct = result.get("match_percentage")
        assert isinstance(pct, int)
        assert 0 <= pct <= 100


# ==============================================================================
# 4. DATE AND SALARY PARSING & FORMATTING PROPERTIES
# ==============================================================================

class TestDateAndSalaryFormattingProperties:
    """Property-based tests for regional date and salary formatters in utils.formatters."""

    @settings(max_examples=50, deadline=None)
    @given(
        val=st.one_of(
            st.text(max_size=60),
            st.integers(min_value=-10**10, max_value=10**10),
            st.floats(allow_nan=True, allow_infinity=True),
            st.none(),
        )
    )
    def test_parse_utc_datetime_never_crashes(self, val: Any):
        """Property: parse_utc_datetime returns (datetime, bool) with UTC tz or (None, False)."""
        dt_val, has_time = parse_utc_datetime(val)
        if dt_val is not None:
            assert isinstance(dt_val, dt.datetime)
            assert dt_val.tzinfo == dt.timezone.utc
            assert isinstance(has_time, bool)
        else:
            assert has_time is False

    @settings(max_examples=50, deadline=None)
    @given(
        num=st.one_of(
            st.integers(min_value=-10**14, max_value=10**14),
            st.floats(allow_nan=True, allow_infinity=True),
        ),
        decimals=st.one_of(st.none(), st.integers(min_value=0, max_value=4)),
    )
    def test_format_indian_number_never_crashes_and_invariants(
        self, num: int | float, decimals: int | None
    ):
        """Property: format_indian_number never crashes on extreme numbers or NaN/Inf."""
        res = format_indian_number(num, decimals=decimals)
        assert isinstance(res, str)
        if isinstance(num, float) and (math.isnan(num) or not math.isfinite(num)):
            assert str(num) in res
        elif isinstance(num, int) and num >= 1000:
            # Positive integer >= 1000 must contain comma digit grouping
            assert "," in res

    @settings(max_examples=50, deadline=None)
    @given(
        val=st.one_of(
            st.integers(min_value=-10**12, max_value=10**12),
            st.floats(allow_nan=True, allow_infinity=True),
            st.text(max_size=30),
            st.none(),
        ),
        lpa=st.booleans(),
        symbol=st.booleans(),
        cr=st.booleans(),
    )
    def test_format_inr_never_crashes(self, val: Any, lpa: bool, symbol: bool, cr: bool):
        """Property: format_inr returns string representation without unhandled exceptions."""
        res = format_inr(val, lpa=lpa, symbol=symbol, cr=cr)
        assert isinstance(res, str)

    @settings(max_examples=40, deadline=None)
    @given(val=st.one_of(st.text(max_size=40), st.none()))
    def test_format_date_ist_never_crashes(self, val: Any):
        """Property: format_date_ist handles arbitrary inputs gracefully."""
        res = format_date_ist(val)
        assert isinstance(res, str)


# ==============================================================================
# 5. FILENAME SANITIZATION PROPERTIES
# ==============================================================================

class TestFilenameSanitizingProperties:
    """Property-based tests for filename sanitization in utils.file_validation_service."""

    @settings(max_examples=50, deadline=None)
    @given(
        raw_name=st.one_of(st.text(max_size=300), st.none()),
        max_length=st.integers(min_value=10, max_value=200),
    )
    def test_sanitize_filename_security_and_length_invariants(
        self, raw_name: str | None, max_length: int
    ):
        """
        Property: sanitize_filename invariants:
        - Never raises an unhandled exception.
        - Result is a non-empty string with length <= max_length.
        - Contains no directory traversal components ('..', '/', '\\') or null bytes ('\\x00').
        - Never matches any Windows reserved device stems (CON, PRN, AUX, etc.).
        - Is idempotent.
        """
        clean = sanitize_filename(raw_name, max_length=max_length)
        assert isinstance(clean, str)
        assert len(clean) > 0
        assert len(clean) <= max_length

        # No path traversal or illegal separators
        assert "/" not in clean
        assert "\\" not in clean
        assert "\x00" not in clean
        assert ".." not in clean

        # No Windows reserved device stems
        stem, _ = os.path.splitext(clean)
        assert stem.upper() not in WINDOWS_RESERVED_NAMES

        # Idempotence property
        assert sanitize_filename(clean, max_length=max_length) == clean


# ==============================================================================
# 6. INPUT LENGTH & STRING VALIDATOR PROPERTIES
# ==============================================================================

class TestInputValidatorProperties:
    """Property-based tests for input validation and sanitization in utils.input_validator."""

    @settings(max_examples=50, deadline=None)
    @given(
        raw_text=st.text(max_size=300),
        min_len=st.integers(min_value=1, max_value=10),
        max_len=st.integers(min_value=11, max_value=100),
    )
    def test_validate_string_length_contract(self, raw_text: str, min_len: int, max_len: int):
        """Property: validate_string strictly enforces [min_len, max_len] boundaries."""
        stripped = raw_text.strip()
        if min_len <= len(stripped) <= max_len:
            result = validate_string(raw_text, "test_field", min_length=min_len, max_length=max_len, required=True)
            assert result == stripped
        else:
            with pytest.raises(ValidationError):
                validate_string(raw_text, "test_field", min_length=min_len, max_length=max_len, required=True)

    @settings(max_examples=50, deadline=None)
    @given(
        text=st.text(max_size=400),
        max_len=st.integers(min_value=5, max_value=150),
    )
    def test_sanitize_text_length_and_html_invariants(self, text: str, max_len: int):
        """Property: sanitize_text enforces maximum length and escapes HTML."""
        sanitized = sanitize_text(text, strip_html=True, max_len=max_len)
        assert isinstance(sanitized, str)
        assert len(sanitized) <= max_len
        # No raw unescaped HTML opening tags
        assert not re.search(r"<[a-zA-Z]+>", sanitized)


# ==============================================================================
# 7. REGRESSION TESTS FOR FAILING EXAMPLES FOUND DURING PROPERTY TESTING
# ==============================================================================

class TestHypothesisDiscoveredRegressions:
    """
    Acceptance criterion: Commit failing examples Hypothesis finds as regular regression tests.
    """

    def test_regression_format_indian_number_nan_inf_with_decimals(self):
        """
        Regression: format_indian_number with decimals crashed on float('nan') and float('inf')
        with ValueError ('not enough values to unpack') and OverflowError.
        """
        assert format_indian_number(float("nan"), decimals=2) == "nan"
        assert format_indian_number(float("inf"), decimals=2) == "inf"
        assert format_indian_number(-float("inf"), decimals=2) == "-inf"

    def test_regression_format_indian_number_decimals_zero(self):
        """
        Regression: format_indian_number with decimals=0 crashed because f'{num:.0f}'
        contains no decimal dot '.', raising ValueError when unpacking split('.').
        """
        assert format_indian_number(0, decimals=0) == "0"
        assert format_indian_number(1234567, decimals=0) == "12,34,567"
        assert format_indian_number(1234567.89, decimals=0) == "12,34,568"

    def test_regression_format_inr_nan_inf(self):
        """
        Regression: format_inr crashed on float('nan') when formatted with decimals.
        """
        assert format_inr(float("nan"), decimals=2) == "nan"
        assert format_inr(float("inf"), decimals=2) == "inf"

    def test_regression_sanitize_filename_traversal_and_reserved_names(self):
        """
        Regression: Filenames with path traversal, null bytes, or Windows reserved device stems.
        """
        # Directory traversal
        assert sanitize_filename("../../../etc/passwd") == "passwd.pdf"
        assert sanitize_filename("..\\..\\boot.ini") == "boot.ini"
        # Null bytes
        assert sanitize_filename("resume\x00evil.pdf") == "resumeevil.pdf"
        # Windows reserved names
        assert sanitize_filename("CON.pdf") == "file_CON.pdf"
        assert sanitize_filename("aux.txt") == "file_aux.txt"
        assert sanitize_filename("NUL") == "file_NUL.pdf"
        # Whitespace and empty
        assert sanitize_filename("   ") == "document.pdf"
        assert sanitize_filename(None) == "document.pdf"
