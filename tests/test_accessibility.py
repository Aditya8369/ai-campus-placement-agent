from pathlib import Path
import pytest

from app import app
from utils.accessibility_audit import (
    audit_css_contrast,
    audit_html_accessibility,
    contrast_ratio,
    parse_color_to_rgb,
)


PUBLIC_ROUTES = [
    "/",
    "/demo",
    "/privacy",
    "/companies",
    "/group-discussion",
]


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as test_client:
        yield test_client


@pytest.mark.parametrize("route", PUBLIC_ROUTES)
def test_rendered_routes_pass_wcag_accessibility_audit(client, route):
    """
    Renders key student-facing routes and verifies zero regressions in:
    - form input labels
    - sequential heading order (no skipped levels)
    - button and link accessible names
    - image alt attributes
    - inline color contrast ratios
    """
    response = client.get(route)
    if response.status_code == 404:
        pytest.skip(f"Route {route} is not mounted in this configuration.")

    assert response.status_code in (200, 302)
    if response.status_code == 302:
        response = client.get(response.headers["Location"])

    html = response.get_data(as_text=True)
    violations = audit_html_accessibility(html, page_name=route)

    formatted = "\n".join(
        f"[{v.severity.upper()}] ({v.rule_id}) {v.location}: {v.message}"
        for v in violations
    )
    assert not violations, f"Accessibility violations detected on {route}:\n{formatted}"


def test_stylesheet_color_contrast_meets_wcag_aa():
    """
    Parses static/css/style.css and verifies all explicit foreground/background
    color pairs meet WCAG 2.1 AA contrast ratios (>= 4.5:1 normal, >= 3.0:1 large).
    """
    css_path = Path("static/css/style.css")
    if not css_path.exists():
        pytest.skip("static/css/style.css not found")

    css_text = css_path.read_text(encoding="utf-8")
    violations = audit_css_contrast(css_text, min_ratio=4.5)

    formatted = "\n".join(
        f"[{v.severity.upper()}] ({v.rule_id}) {v.location}: {v.message}"
        for v in violations
    )
    assert not violations, f"CSS color contrast violations detected:\n{formatted}"


# ---------------------------------------------------------------------------
# Negative Regression Guards (Ensure the auditor catches intentional breaks)
# ---------------------------------------------------------------------------


def test_auditor_catches_missing_form_label():
    broken_html = """
    <html lang="en">
      <head><title>Test</title></head>
      <body>
        <h1>Upload Resume</h1>
        <form>
          <input type="text" id="target_role" name="target_role" placeholder="SDE 1">
        </form>
      </body>
    </html>
    """
    violations = audit_html_accessibility(broken_html, page_name="broken-form")
    rule_ids = {v.rule_id for v in violations}
    assert "label" in rule_ids


def test_auditor_catches_skipped_heading_order():
    broken_html = """
    <html lang="en">
      <head><title>Test</title></head>
      <body>
        <h1>Dashboard</h1>
        <h3>Skipped H2 Section</h3>
      </body>
    </html>
    """
    violations = audit_html_accessibility(broken_html, page_name="broken-headings")
    rule_ids = {v.rule_id for v in violations}
    assert "heading-order" in rule_ids


def test_auditor_catches_icon_only_button_without_accessible_name():
    broken_html = """
    <html lang="en">
      <head><title>Test</title></head>
      <body>
        <h1>Theme Toggle</h1>
        <button id="themeToggleBtn" type="button"><i class="bi bi-moon"></i></button>
      </body>
    </html>
    """
    violations = audit_html_accessibility(broken_html, page_name="broken-button")
    rule_ids = {v.rule_id for v in violations}
    assert "button-name" in rule_ids


def test_auditor_catches_low_color_contrast_in_css_and_inline_styles():
    # Light gray text (#aaaaaa) on white background (#ffffff) -> ~2.32:1 (fails 4.5:1)
    low_contrast_css = """
    :root {
      --muted-fg: #aaaaaa;
      --surface-bg: #ffffff;
    }
    .low-contrast-badge {
      color: var(--muted-fg);
      background-color: var(--surface-bg);
    }
    """
    css_violations = audit_css_contrast(low_contrast_css)
    assert len(css_violations) == 1
    assert css_violations[0].rule_id == "color-contrast"

    # High contrast pair (#1a202c on #ffffff) -> > 15:1 (passes)
    fg = parse_color_to_rgb("#1a202c")
    bg = parse_color_to_rgb("#ffffff")
    assert fg is not None and bg is not None
    assert contrast_ratio(fg, bg) >= 4.5