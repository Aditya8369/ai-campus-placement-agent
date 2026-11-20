"""
Unit tests for Frontend ES Module Architecture (#555).

Verifies that static/js/script.js has been split into feature modules in
static/js/modules/, script.js is reduced to a small bootstrap, templates
use <script type="module">, and utilities are properly exported.
"""

import re
from pathlib import Path

MODULES_DIR = Path("static/js/modules")
SCRIPT_JS_PATH = Path("static/js/script.js")
CONTRIBUTING_PATH = Path("CONTRIBUTING.md")

EXPECTED_MODULES = [
    "utils.js",
    "theme.js",
    "common.js",
    "analysis.js",
    "dashboard.js",
    "interview.js",
    "bookmarks.js",
    "tracker.js",
    "streaks.js",
    "auth.js",
    "self_intro.js",
    "project_deep_dive.js",
    "cover_letter.js",
]


def test_modules_directory_and_files_exist():
    """Verify that static/js/modules/ directory exists and contains modules."""
    assert MODULES_DIR.is_dir(), "static/js/modules/ directory missing"
    for module_file in EXPECTED_MODULES:
        file_path = MODULES_DIR / module_file
        assert file_path.is_file(), f"Module {module_file} missing"
        assert file_path.stat().st_size > 0, f"Module {module_file} empty"


def test_utils_module_exports():
    """Verify utils.js exports CSRF helpers, escaping, toasts, clipboards."""
    utils_path = MODULES_DIR / "utils.js"
    assert utils_path.is_file()
    content = utils_path.read_text(encoding="utf-8")

    expected_exports = [
        "getCsrfToken",
        "escapeHtml",
        "initCsrfFetch",
        "apiFetch",
        "showToast",
        "copyToClipboard",
        "countParas",
        "countWords",
    ]
    for fn in expected_exports:
        has_export = (
            f"export function {fn}" in content
            or f"export async function {fn}" in content
            or f"export const {fn}" in content
        )
        assert has_export, f"Expected {fn} exported from utils.js"

    # Check for window fallback
    assert "window.getCsrfToken" in content
    assert "window.escapeHtml" in content
    assert "window.showToast" in content
    assert "window.copyToClipboard" in content


def test_script_js_reduced_to_small_bootstrap():
    """Verify static/js/script.js is reduced to a concise bootstrap facade."""
    assert SCRIPT_JS_PATH.is_file(), "static/js/script.js not found"
    content = SCRIPT_JS_PATH.read_text(encoding="utf-8")
    line_count = len(content.splitlines())

    assert line_count < 200, f"script.js too large: {line_count} lines"

    # Verify that script.js imports from the modules
    assert 'from "./modules/utils.js"' in content
    assert 'from "./modules/theme.js"' in content
    assert 'from "./modules/common.js"' in content
    assert 'from "./modules/analysis.js"' in content
    assert 'from "./modules/dashboard.js"' in content
    assert 'from "./modules/interview.js"' in content


def test_templates_load_modules_with_type_module():
    """Verify that key templates load modules with <script type="module">."""
    templates_dir = Path("templates")
    key_templates = [
        ("index.html", ["common.js", "analysis.js"]),
        ("dashboard.html", ["common.js", "dashboard.js"]),
        ("interview.html", ["common.js", "interview.js", "bookmarks.js"]),
        ("coding_practice.html", ["common.js", "bookmarks.js"]),
        ("company_checklist.html", ["common.js", "tracker.js"]),
        ("cover_letter.html", ["common.js", "cover_letter.js"]),
        ("project_deep_dive.html", ["common.js", "project_deep_dive.js"]),
        ("streak.html", ["common.js", "streaks.js"]),
        ("login.html", ["common.js", "auth.js"]),
        ("register.html", ["common.js", "auth.js"]),
    ]

    for tpl_name, required_mods in key_templates:
        tpl_path = templates_dir / tpl_name
        assert tpl_path.is_file(), f"Template {tpl_name} not found"
        html = tpl_path.read_text(encoding="utf-8")

        for mod in required_mods:
            assert f"js/modules/{mod}" in html, (
                f"Template {tpl_name} does not reference js/modules/{mod}"
            )
            pattern = re.compile(
                rf'<script\s+[^>]*type=["\']module["\'][^>]*'
                rf'js/modules/{re.escape(mod)}[^>]*>',
                re.IGNORECASE,
            )
            assert pattern.search(html), (
                f"Template {tpl_name} does not load {mod} as type='module'"
            )


def test_no_module_pollutes_unexpected_globals():
    """Verify modules follow ES module standard and export named functions."""
    for module_file in EXPECTED_MODULES:
        file_path = MODULES_DIR / module_file
        content = file_path.read_text(encoding="utf-8")

        assert "export " in content, f"Module {module_file} missing exports"


def test_contributing_docs_frontend_architecture():
    """Verify CONTRIBUTING.md documents ES modules structure & conventions."""
    assert CONTRIBUTING_PATH.is_file()
    doc = CONTRIBUTING_PATH.read_text(encoding="utf-8")

    assert "Frontend JavaScript Architecture" in doc or "ES Modules" in doc
    assert "static/js/modules/" in doc
    assert "utils.js" in doc
    assert "common.js" in doc
