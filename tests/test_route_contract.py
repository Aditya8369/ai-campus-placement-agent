"""
Unit tests for Route Contract & Frontend URL Verification Engine (#554).
=========================================================================
Tests:
1. Every URL and url_for endpoint referenced in templates/ and static/js/
   resolves against app.url_map.
2. Removing a route used by the frontend makes verification fail with the
   route name.
3. The allow-list is minimal, documented, and justified.
4. Dynamic URL segments (e.g. /api/jobs/<id>) match correctly.
5. Untested routes are identified and reported as a warning.
6. The test runs in under a few seconds with no AI key or external network.
"""

import time
import pytest
from werkzeug.exceptions import NotFound
from app import app
from utils.route_contract import (
    RouteContractScanner,
    normalize_frontend_url,
    is_allowlisted,
    format_readable_diff,
    format_untested_routes_warning,
    ALLOWLIST_PATTERNS,
)


@pytest.fixture
def scanner():
    return RouteContractScanner(app=app)


def test_all_frontend_endpoints_and_urls_resolve(scanner):
    """
    Verify that all URLs and endpoints called by templates and JavaScript
    successfully resolve against Flask's registered URL rules.
    """
    result = scanner.verify_frontend_routes()

    if not result["valid"]:
        diff = format_readable_diff(result)
        pytest.fail(f"Route contract violations found:\n{diff}")

    assert result["total_url_for_endpoints"] > 0
    assert result["total_url_paths"] > 0
    assert len(result["missing_endpoints"]) == 0
    assert len(result["missing_paths"]) == 0


def test_route_removal_causes_test_failure_with_route_name(
    scanner, monkeypatch
):
    """
    Verify Acceptance Criterion: Removing a route used by the frontend
    makes the test fail with the route name.
    """
    # 1. Simulate removal of a URL route (e.g. /analyze)
    target_route = "/analyze"
    original_match = scanner.url_adapter.match

    def mock_match(path, method=None):
        if path == target_route or path == target_route + "/":
            raise NotFound()
        return original_match(path, method=method)

    monkeypatch.setattr(scanner.url_adapter, "match", mock_match)

    result = scanner.verify_frontend_routes()
    assert result["valid"] is False, "Expected failure after removing route"

    diff = format_readable_diff(result)
    assert target_route in diff, (
        f"Expected route name '{target_route}' in failure output:\n{diff}"
    )

    missing_paths = [p["raw_path"] for p in result["missing_paths"]]
    assert target_route in missing_paths

    # 2. Also simulate removal of an endpoint used in url_for
    monkeypatch.setattr(scanner.url_adapter, "match", original_match)
    monkeypatch.delitem(
        scanner.app.view_functions, "privacy_policy", raising=False
    )

    result_ep = scanner.verify_frontend_routes()
    assert result_ep["valid"] is False, (
        "Expected failure after removing endpoint"
    )

    diff_ep = format_readable_diff(result_ep)
    assert "privacy_policy" in diff_ep, (
        f"Expected endpoint name 'privacy_policy' in output:\n{diff_ep}"
    )


def test_dynamic_url_segments_matched_correctly():
    """
    Verify Acceptance Criterion: Dynamic URL segments (e.g., /api/jobs/<id>,
    /dashboard/<analysis_id>) are matched correctly.
    """
    # 1. Jinja variable expressions
    jinja_url = "/dashboard/{{ analysis_id }}"
    norm_jinja = normalize_frontend_url(jinja_url)
    assert norm_jinja == "/dashboard/1"

    # 2. JS template literal syntax
    js_template_url = "/api/applications/${appId}"
    norm_js = normalize_frontend_url(js_template_url)
    assert norm_js == "/api/applications/1"

    # 3. JS string concatenation
    js_concat_url = "/api/interview/session/' + sessionId"
    norm_concat = normalize_frontend_url(js_concat_url)
    assert norm_concat == "/api/interview/session/1"

    # 4. Jinja control blocks and query strings
    jinja_conditional_qs = "/admin/ai-metrics/export.csv{{ export_qs }}"
    norm_cond = normalize_frontend_url(jinja_conditional_qs)
    assert norm_cond == "/admin/ai-metrics/export.csv"

    # Test resolving dynamic URLs against real app url_map
    adapter = app.url_map.bind("localhost")
    matched_endpoint, _ = adapter.match("/dashboard/1", method="GET")
    assert matched_endpoint == "dashboard"


def test_allowlist_is_minimal_and_documented():
    """
    Verify Acceptance Criterion: The allow-list is small, documented,
    and reviewed in pull requests.
    """
    assert len(ALLOWLIST_PATTERNS) < 15, "Allow-list must remain small"

    for pattern, rationale in ALLOWLIST_PATTERNS.items():
        assert isinstance(pattern, str) and len(pattern) > 0
        assert isinstance(rationale, str) and len(rationale.strip()) > 10, (
            f"Allow-list entry '{pattern}' lacks sufficient rationale"
        )

    # Verify allowlist classification
    cdn_url = "https://cdnjs.cloudflare.com/ajax/libs/font-awesome.css"
    assert is_allowlisted(cdn_url)[0] is True
    assert is_allowlisted("#main-content")[0] is True
    assert is_allowlisted("/static/css/style.css")[0] is True
    assert is_allowlisted("/api/unregistered-route-xyz")[0] is False


def test_untested_routes_warning_report(scanner):
    """
    Verify Acceptance Criterion: Add a second check that lists every registered
    route and reports those not referenced by any test file, as a warning.
    """
    audit = scanner.audit_tested_routes()

    assert audit["total_registered_routes"] > 0
    assert audit["tested_routes_count"] > 0
    assert isinstance(audit["untested_routes_count"], int)

    warning_text = format_untested_routes_warning(audit, max_display=5)
    assert "ROUTE TEST COVERAGE AUDIT" in warning_text
    assert "[WARNING]" in warning_text
    assert "% coverage" in warning_text


def test_route_contract_execution_performance(scanner):
    """
    Verify Acceptance Criterion: The test runs in CI in under a few seconds
    with no AI key or network.
    """
    start_time = time.perf_counter()
    result = scanner.verify_frontend_routes()
    duration = time.perf_counter() - start_time

    assert result["valid"] is True
    assert duration < 5.0, (
        f"Route contract scan took too long: {duration:.2f}s (must be < 5.0s)"
    )
