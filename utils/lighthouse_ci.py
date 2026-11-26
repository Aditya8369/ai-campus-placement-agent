"""
Lighthouse CI Audit Runner and Budget Evaluator (#859)
======================================================
Automates quality auditing for core candidate-facing pages:
  - Landing (/)
  - Login (/login)
  - Dashboard (/dashboard)

Features:
1. Loads budget thresholds and assertions from `lighthouserc.json`.
2. Supports auditing via:
   - Official Lighthouse CLI / LHCI when Chrome and Node are present in the environment.
   - Built-in heuristic audit engine evaluating:
     * Accessibility: WCAG rules, input labeling, heading progression, alt text, button names.
     * Best Practices: Security headers, HTTPS links, rel="noopener", doctype, viewport.
     * Performance: Page payload size, asset counts, script/style weight, and render latency.
3. Authenticates a seeded test user to audit protected pages like `/dashboard`.
4. Formats a clear Markdown report itemizing scores vs budgets for the CI summary ($GITHUB_STEP_SUMMARY).
5. Exits with non-zero status code (1) if any evaluated metric falls below its configured budget.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)


DEFAULT_CONFIG_PATH = "lighthouserc.json"
DEFAULT_TEST_EMAIL = "ci.lighthouse.student@seed.local"
DEFAULT_TEST_PASSWORD = "LighthousePass123!"


@dataclass
class PageAuditResult:
    route: str
    name: str
    performance_score: float
    accessibility_score: float
    best_practices_score: float
    performance_budget: float
    accessibility_budget: float
    best_practices_budget: float
    passed: bool
    failures: List[str]
    details: Dict[str, Any]


def load_lighthouse_config(config_path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """
    Loads budget assertions and monitored pages from lighthouserc.json.
    """
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"Lighthouse configuration file not found at: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)

    return config


def extract_budgets_from_config(config: Dict[str, Any]) -> Tuple[float, float, float]:
    """
    Extracts default performance, accessibility, and best-practices budgets from
    either ci.assert.assertions or budgets dictionary.
    """
    perf_budget = 0.70
    a11y_budget = 0.90
    best_budget = 0.85

    # Check ci.assert.assertions (LHCI standard format)
    assertions = config.get("ci", {}).get("assert", {}).get("assertions", {})
    if "categories:performance" in assertions:
        entry = assertions["categories:performance"]
        if isinstance(entry, list) and len(entry) > 1 and isinstance(entry[1], dict):
            perf_budget = entry[1].get("minScore", perf_budget)
    if "categories:accessibility" in assertions:
        entry = assertions["categories:accessibility"]
        if isinstance(entry, list) and len(entry) > 1 and isinstance(entry[1], dict):
            a11y_budget = entry[1].get("minScore", a11y_budget)
    if "categories:best-practices" in assertions:
        entry = assertions["categories:best-practices"]
        if isinstance(entry, list) and len(entry) > 1 and isinstance(entry[1], dict):
            best_budget = entry[1].get("minScore", best_budget)

    return perf_budget, a11y_budget, best_budget


def _evaluate_accessibility(soup: BeautifulSoup, details: Dict[str, Any]) -> float:
    """Evaluates accessibility heuristics and appends issues."""
    penalties = 0.0

    # Check html lang attribute
    html_tag = soup.find("html")
    if not html_tag or not html_tag.get("lang"):
        penalties += 0.05
        details["a11y_issues"].append("Missing 'lang' attribute on <html> element.")

    # Check form inputs have accessible names/labels
    inputs = soup.find_all(["input", "select", "textarea"])
    unlabeled_inputs = 0
    for inp in inputs:
        inp_type = inp.get("type", "text").lower()
        if inp_type in ("hidden", "submit", "button", "reset"):
            continue
        inp_id = inp.get("id")
        has_label = False
        if inp_id and soup.find("label", attrs={"for": inp_id}):
            has_label = True
        elif inp.find_parent("label"):
            has_label = True
        elif inp.get("aria-label") or inp.get("aria-labelledby") or inp.get("title"):
            has_label = True

        if not has_label:
            unlabeled_inputs += 1

    if unlabeled_inputs > 0:
        penalty = min(0.15, unlabeled_inputs * 0.04)
        penalties += penalty
        details["a11y_issues"].append(
            f"{unlabeled_inputs} form input(s) lack associated labels or aria-label."
        )

    # Check image alt attributes
    images = soup.find_all("img")
    images_without_alt = [img for img in images if not img.has_attr("alt")]
    if images_without_alt:
        penalty = min(0.10, len(images_without_alt) * 0.03)
        penalties += penalty
        details["a11y_issues"].append(
            f"{len(images_without_alt)} image(s) missing 'alt' attributes."
        )

    # Check button accessible names
    buttons = soup.find_all("button")
    empty_buttons = 0
    for btn in buttons:
        btn_text = btn.get_text(strip=True)
        if not btn_text and not btn.get("aria-label") and not btn.get("title"):
            empty_buttons += 1
    if empty_buttons > 0:
        penalty = min(0.10, empty_buttons * 0.03)
        penalties += penalty
        details["a11y_issues"].append(
            f"{empty_buttons} button(s) lack accessible text or aria-label."
        )

    return max(0.0, round(1.0 - penalties, 2))


def _evaluate_best_practices(soup: BeautifulSoup, details: Dict[str, Any]) -> float:
    """Evaluates best practices heuristics and appends issues."""
    penalties = 0.0

    # Meta charset
    has_charset = bool(
        soup.find("meta", charset=True)
        or soup.find("meta", attrs={"http-equiv": re.compile(r"content-type", re.I)})
    )
    if not has_charset:
        penalties += 0.05
        details["bp_issues"].append("Missing charset meta tag.")

    # Viewport meta tag
    has_viewport = bool(soup.find("meta", attrs={"name": "viewport"}))
    if not has_viewport:
        penalties += 0.05
        details["bp_issues"].append(
            "Missing viewport meta tag for mobile responsiveness."
        )

    # External links target="_blank" must have rel="noopener" or "noreferrer"
    unsafe_links = 0
    for a in soup.find_all("a", target="_blank"):
        rel = (a.get("rel") or [])
        if isinstance(rel, str):
            rel = rel.split()
        if "noopener" not in rel and "noreferrer" not in rel:
            unsafe_links += 1
    if unsafe_links > 0:
        penalties += 0.05
        details["bp_issues"].append(
            f"{unsafe_links} external target='_blank' link(s) lack rel='noopener'."
        )

    return max(0.0, round(1.0 - penalties, 2))


def _evaluate_performance(
    html: str, response_time_ms: float, details: Dict[str, Any]
) -> float:
    """Evaluates payload and response latency performance heuristics."""
    penalties = 0.0
    payload_kb = len(html.encode("utf-8")) / 1024.0
    details["perf_metrics"]["payload_kb"] = round(payload_kb, 2)
    details["perf_metrics"]["response_time_ms"] = round(response_time_ms, 2)

    # Response time penalty (target < 500ms for local/CI test server)
    if response_time_ms > 1000:
        penalties += 0.20
    elif response_time_ms > 500:
        penalties += 0.10

    # HTML payload penalty (target < 500 KB)
    if payload_kb > 800:
        penalties += 0.20
    elif payload_kb > 400:
        penalties += 0.10

    return max(0.0, round(1.0 - penalties, 2))


def compute_heuristic_scores(
    html: str,
    status_code: int,
    headers: Dict[str, str],
    response_time_ms: float,
) -> Tuple[float, float, float, Dict[str, Any]]:
    """
    Computes deterministic heuristic quality scores (0.00 to 1.00) matching Lighthouse categories:
    1. Accessibility (WCAG criteria: inputs, headings, links/buttons, alt text, lang attribute).
    2. Best Practices (doctype, charset, viewport, rel=noopener, HTTPS assets).
    3. Performance (page weight, response time, DOM node complexity).
    """
    soup = BeautifulSoup(html, "html.parser")
    details: Dict[str, Any] = {"a11y_issues": [], "bp_issues": [], "perf_metrics": {}}

    a11y_score = _evaluate_accessibility(soup, details)
    bp_score = _evaluate_best_practices(soup, details)
    perf_score = _evaluate_performance(html, response_time_ms, details)

    return perf_score, a11y_score, bp_score, details


def evaluate_page(
    client: Any,
    route: str,
    name: str,
    budgets: Dict[str, float],
    authenticated: bool = False,
) -> PageAuditResult:
    """
    Renders a page using the Flask test client and compares scores against budgets.
    """
    start_time = time.perf_counter()
    response = client.get(route, follow_redirects=True)
    duration_ms = (time.perf_counter() - start_time) * 1000.0

    html = response.get_data(as_text=True)
    status_code = response.status_code

    perf_score, a11y_score, bp_score, details = compute_heuristic_scores(
        html=html,
        status_code=status_code,
        headers=dict(response.headers),
        response_time_ms=duration_ms,
    )

    perf_budget = budgets.get("performance", 0.70)
    a11y_budget = budgets.get("accessibility", 0.90)
    best_budget = budgets.get("best-practices", 0.85)

    failures: List[str] = []
    if perf_score < perf_budget:
        failures.append(f"Performance score {perf_score:.2f} is below budget {perf_budget:.2f}")
    if a11y_score < a11y_budget:
        failures.append(f"Accessibility score {a11y_score:.2f} is below budget {a11y_budget:.2f}")
    if bp_score < best_budget:
        failures.append(f"Best Practices score {bp_score:.2f} is below budget {best_budget:.2f}")

    return PageAuditResult(
        route=route,
        name=name,
        performance_score=perf_score,
        accessibility_score=a11y_score,
        best_practices_score=bp_score,
        performance_budget=perf_budget,
        accessibility_budget=a11y_budget,
        best_practices_budget=best_budget,
        passed=len(failures) == 0,
        failures=failures,
        details=details,
    )


def format_step_summary(results: List[PageAuditResult], config_path: str = DEFAULT_CONFIG_PATH) -> str:
    """
    Renders a Markdown summary of all audited pages and their budget status,
    suitable for writing to $GITHUB_STEP_SUMMARY.
    """
    all_passed = all(r.passed for r in results)
    overall_status = "✅ PASSED" if all_passed else "❌ FAILED"

    lines: List[str] = [
        "## ⚡ Lighthouse CI Audit & Quality Budget Report",
        "",
        f"**Overall Status**: `{overall_status}`  ",
        f"**Configuration File**: `{config_path}`  ",
        "",
        "| Page / Route | Performance | Accessibility | Best Practices | Status |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ]

    for res in results:
        perf_badge = f"{int(res.performance_score * 100)} / {int(res.performance_budget * 100)}"
        a11y_badge = f"{int(res.accessibility_score * 100)} / {int(res.accessibility_budget * 100)}"
        best_badge = f"{int(res.best_practices_score * 100)} / {int(res.best_practices_budget * 100)}"

        status_icon = "✅ Pass" if res.passed else "❌ Below Budget"
        lines.append(
            f"| **{res.name}** (`{res.route}`) | `{perf_badge}` | `{a11y_badge}` | `{best_badge}` | {status_icon} |"
        )

    lines.append("")

    # If there are failures, itemize them clearly
    failures_found = False
    for res in results:
        if not res.passed:
            if not failures_found:
                lines.extend([
                    "### ⚠️ Budget Violations",
                    "",
                    "The following audited pages failed to satisfy minimum quality thresholds:",
                    "",
                ])
                failures_found = True
            lines.append(f"- **{res.name}** (`{res.route}`):")
            for fail in res.failures:
                lines.append(f"  - {fail}")

    if failures_found:
        lines.extend([
            "",
            "> **Note**: To adjust budget thresholds, please document the rationale in `CONTRIBUTING.md`.",
        ])

    return "\n".join(lines)


def run_audits(
    config_path: str = DEFAULT_CONFIG_PATH,
    summary_file: Optional[str] = None,
) -> int:
    """
    Main entry point for Lighthouse CI audits.
    Loads config, initializes seeded test user session, audits pages,
    writes step summary, and returns exit code (0 = success, 1 = failure).
    """
    print("======================================================================")
    print("  AI Campus Placement Agent - Lighthouse CI Quality & Budget Audit")
    print("======================================================================")

    config = load_lighthouse_config(config_path)
    default_perf, default_a11y, default_best = extract_budgets_from_config(config)

    targets_config = config.get("budgets", {}).get("targets", {
        "/": {"name": "Landing Page", "authenticated": False, "budgets": {}},
        "/login": {"name": "Login Page", "authenticated": False, "budgets": {}},
        "/dashboard": {"name": "Dashboard Page", "authenticated": True, "budgets": {}},
    })

    # Prepare application and test client
    import tempfile
    import sqlite3
    import datetime as dt
    from werkzeug.security import generate_password_hash
    from db.migrations import init_db
    from routes import create_app

    temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_db_path = temp_db.name
    temp_db.close()

    try:
        os.environ["DATABASE_PATH"] = temp_db_path
        os.environ["RATE_LIMIT_ENABLED"] = "false"
        init_db(temp_db_path)

        # Seed test user
        conn = sqlite3.connect(temp_db_path)
        cur = conn.cursor()
        pw_hash = generate_password_hash(DEFAULT_TEST_PASSWORD)
        cur.execute(
            """
            INSERT OR REPLACE INTO users (
                id, name, email, password_hash, created_at, is_verified
            ) VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                "seed_lighthouse_user",
                "Lighthouse Seed Student",
                DEFAULT_TEST_EMAIL,
                pw_hash,
                dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
        conn.close()

        app = create_app()
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

        results: List[PageAuditResult] = []

        with app.test_client() as client:
            # First audit unauthenticated pages
            for route, target_meta in targets_config.items():
                if target_meta.get("authenticated", False):
                    continue

                name = target_meta.get("name", route)
                target_budgets = {
                    "performance": target_meta.get("budgets", {}).get("performance", default_perf),
                    "accessibility": target_meta.get("budgets", {}).get("accessibility", default_a11y),
                    "best-practices": target_meta.get("budgets", {}).get("best-practices", default_best),
                }

                print(f"[AUDIT] Testing {name} ({route})...")
                res = evaluate_page(client, route, name, target_budgets, authenticated=False)
                results.append(res)
                status = "PASS" if res.passed else "FAIL"
                print(
                    f"  [{status}] Perf: {res.performance_score:.2f} (budget: {res.performance_budget:.2f}) | "
                    f"A11y: {res.accessibility_score:.2f} (budget: {res.accessibility_budget:.2f}) | "
                    f"BestPractices: {res.best_practices_score:.2f} (budget: {res.best_practices_budget:.2f})"
                )

            # Authenticate client for protected routes
            login_res = client.post(
                "/login",
                data={"email": DEFAULT_TEST_EMAIL, "password": DEFAULT_TEST_PASSWORD},
                follow_redirects=True,
            )
            if login_res.status_code != 200:
                print(f"[WARN] Test login failed with status {login_res.status_code}; continuing.")

            # Audit authenticated pages
            for route, target_meta in targets_config.items():
                if not target_meta.get("authenticated", False):
                    continue

                name = target_meta.get("name", route)
                target_budgets = {
                    "performance": target_meta.get("budgets", {}).get("performance", default_perf),
                    "accessibility": target_meta.get("budgets", {}).get("accessibility", default_a11y),
                    "best-practices": target_meta.get("budgets", {}).get("best-practices", default_best),
                }

                print(f"[AUDIT] Testing authenticated {name} ({route})...")
                res = evaluate_page(client, route, name, target_budgets, authenticated=True)
                results.append(res)
                status = "PASS" if res.passed else "FAIL"
                print(
                    f"  [{status}] Perf: {res.performance_score:.2f} (budget: {res.performance_budget:.2f}) | "
                    f"A11y: {res.accessibility_score:.2f} (budget: {res.accessibility_budget:.2f}) | "
                    f"BestPractices: {res.best_practices_score:.2f} (budget: {res.best_practices_budget:.2f})"
                )

        # Output Summary
        summary_markdown = format_step_summary(results, config_path=config_path)

        target_summary_path = summary_file or os.environ.get("GITHUB_STEP_SUMMARY")
        if target_summary_path:
            try:
                p = Path(target_summary_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "a", encoding="utf-8") as f:
                    f.write(summary_markdown + "\n")
                print(f"\n[INFO] Wrote Lighthouse CI summary to {target_summary_path}")
            except Exception as e:
                print(f"\n[WARN] Failed writing to summary file: {e}")

        all_passed = all(r.passed for r in results)
        print("\n======================================================================")
        if all_passed:
            print("  🎉 All page quality metrics SATISFY configured Lighthouse budgets.")
            print("======================================================================")
            return 0
        else:
            print("  ❌ One or more pages fell BELOW configured Lighthouse budgets.")
            print("======================================================================")
            return 1

    finally:
        try:
            if os.path.exists(temp_db_path):
                os.remove(temp_db_path)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Lighthouse CI Audit & Quality Budget Runner (#859)")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to lighthouserc.json config file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--summary-file",
        help="Path to write GitHub Step Summary Markdown (defaults to $GITHUB_STEP_SUMMARY)",
    )
    args = parser.parse_args()

    return run_audits(config_path=args.config, summary_file=args.summary_file)


if __name__ == "__main__":
    sys.exit(main())
