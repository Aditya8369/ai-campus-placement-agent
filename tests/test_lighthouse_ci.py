"""
tests/test_lighthouse_ci.py
Unit & Integration Tests for Lighthouse CI and Budget Enforcement (#859)

Validates:
1. lighthouserc.json loads correctly and extracts budget thresholds.
2. Heuristic audit engine correctly computes Accessibility, Best Practices, and Performance scores.
3. Violations trigger failing status when scores are below budget.
4. format_step_summary generates valid Markdown with table rows for all target pages.
5. run_audits succeeds on standard app pages and properly fails with exit code 1 if budget is unachieved.
"""

import json
import pytest

from utils.lighthouse_ci import (
    load_lighthouse_config,
    extract_budgets_from_config,
    compute_heuristic_scores,
    format_step_summary,
    run_audits,
    PageAuditResult,
)


def test_load_lighthouse_config_valid(tmp_path):
    """Test loading valid lighthouserc.json file."""
    config_file = tmp_path / "lighthouserc.json"
    config_data = {
        "ci": {
            "assert": {
                "assertions": {
                    "categories:performance": ["error", {"minScore": 0.75}],
                    "categories:accessibility": ["error", {"minScore": 0.95}],
                    "categories:best-practices": ["error", {"minScore": 0.88}],
                }
            }
        }
    }
    config_file.write_text(json.dumps(config_data), encoding="utf-8")

    loaded = load_lighthouse_config(str(config_file))
    assert "ci" in loaded
    perf, a11y, best = extract_budgets_from_config(loaded)
    assert perf == 0.75
    assert a11y == 0.95
    assert best == 0.88


def test_load_lighthouse_config_missing():
    """Test error handling when config file does not exist."""
    with pytest.raises(FileNotFoundError):
        load_lighthouse_config("non_existent_config.json")


def test_compute_heuristic_scores_perfect():
    """Test scores for well-formed accessible and performant HTML."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Test Page</title>
</head>
<body>
    <h1>Heading 1</h1>
    <label for="username">Username</label>
    <input id="username" type="text" />
    <button type="submit">Submit</button>
    <img src="/logo.png" alt="Company Logo" />
    <a href="https://example.com" target="_blank" rel="noopener noreferrer">External Link</a>
</body>
</html>"""

    perf, a11y, bp, details = compute_heuristic_scores(
        html=html,
        status_code=200,
        headers={"Content-Type": "text/html"},
        response_time_ms=50.0,
    )

    assert a11y == 1.0
    assert bp == 1.0
    assert perf == 1.0
    assert len(details["a11y_issues"]) == 0
    assert len(details["bp_issues"]) == 0


def test_compute_heuristic_scores_penalties():
    """Test penalties when accessibility or best practices criteria are omitted."""
    # Missing lang, missing input label, missing img alt, missing button text, missing charset, unsafe link
    html = """<html>
<head>
    <title>Incomplete Page</title>
</head>
<body>
    <input id="unlabeled-field" type="text" />
    <img src="/image.png" />
    <button></button>
    <a href="https://external.com" target="_blank">Unsafe link</a>
</body>
</html>"""

    perf, a11y, bp, details = compute_heuristic_scores(
        html=html,
        status_code=200,
        headers={"Content-Type": "text/html"},
        response_time_ms=600.0,
    )

    assert a11y < 1.0
    assert bp < 1.0
    assert any("lang" in issue.lower() for issue in details["a11y_issues"])
    assert any("label" in issue.lower() for issue in details["a11y_issues"])
    assert any("alt" in issue.lower() for issue in details["a11y_issues"])
    assert any("charset" in issue.lower() for issue in details["bp_issues"])
    assert any("noopener" in issue.lower() for issue in details["bp_issues"])


def test_format_step_summary_pass_and_fail():
    """Verify Markdown table generation for passed and failed audits."""
    results = [
        PageAuditResult(
            route="/",
            name="Landing Page",
            performance_score=0.95,
            accessibility_score=0.98,
            best_practices_score=0.92,
            performance_budget=0.70,
            accessibility_budget=0.90,
            best_practices_budget=0.85,
            passed=True,
            failures=[],
            details={},
        ),
        PageAuditResult(
            route="/broken",
            name="Broken Page",
            performance_score=0.50,
            accessibility_score=0.75,
            best_practices_score=0.60,
            performance_budget=0.70,
            accessibility_budget=0.90,
            best_practices_budget=0.85,
            passed=False,
            failures=[
                "Performance score 0.50 is below budget 0.70",
                "Accessibility score 0.75 is below budget 0.90",
            ],
            details={},
        ),
    ]

    summary = format_step_summary(results, config_path="lighthouserc.json")
    assert "## ⚡ Lighthouse CI Audit & Quality Budget Report" in summary
    assert "Landing Page" in summary
    assert "Broken Page" in summary
    assert "| Performance | Accessibility | Best Practices | Status |" in summary
    assert "❌ Below Budget" in summary
    assert "Performance score 0.50 is below budget 0.70" in summary


def test_run_audits_with_actual_config(tmp_path):
    """Verify run_audits execution passes on current codebase and writes summary file."""
    summary_file = tmp_path / "summary.md"
    exit_code = run_audits(config_path="lighthouserc.json", summary_file=str(summary_file))
    assert exit_code == 0
    assert summary_file.is_file()
    content = summary_file.read_text(encoding="utf-8")
    assert "Lighthouse CI Audit & Quality Budget Report" in content
    assert "Landing Page" in content
    assert "Login Page" in content
    assert "Dashboard Page" in content


def test_run_audits_fails_when_budget_is_unrealistically_high(tmp_path):
    """Verify run_audits returns exit code 1 when a budget threshold is not met."""
    strict_config_file = tmp_path / "strict_lighthouserc.json"
    strict_config = {
        "ci": {
            "assert": {
                "assertions": {
                    "categories:performance": ["error", {"minScore": 1.0}],
                    "categories:accessibility": ["error", {"minScore": 1.0}],  # Strict 1.0
                    "categories:best-practices": ["error", {"minScore": 1.0}],
                }
            }
        },
        "budgets": {
            "targets": {
                "/": {
                    "name": "Landing Page",
                    "authenticated": False,
                    "budgets": {
                        "performance": 1.0,
                        "accessibility": 1.0,
                        "best-practices": 1.0,
                    },
                }
            }
        },
    }
    strict_config_file.write_text(json.dumps(strict_config), encoding="utf-8")

    exit_code = run_audits(config_path=str(strict_config_file))
    assert exit_code == 1
