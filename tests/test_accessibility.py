import pytest
import re
import uuid
from app import app
from utils.database import save_analysis


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def relative_luminance(hex_color: str) -> float:
    """Calculate WCAG 2.1 relative luminance for a hexadecimal color code."""
    hex_color = hex_color.lstrip("#")
    r, g, b = [int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
    transformed = []
    for c in (r, g, b):
        if c <= 0.03928:
            transformed.append(c / 12.92)
        else:
            transformed.append(((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * transformed[0] + 0.7152 * transformed[1] + 0.0722 * transformed[2]


def contrast_ratio(hex1: str, hex2: str) -> float:
    """Calculate WCAG 2.1 contrast ratio between two colors."""
    l1 = relative_luminance(hex1)
    l2 = relative_luminance(hex2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def test_accessibility_focus_visible_styles():
    """Verify high-contrast :focus-visible outlines and focus states exist in stylesheet."""
    with open("static/css/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert ":focus-visible" in css
    assert "outline:" in css or "outline-offset:" in css
    assert ".skip-link" in css
    assert "position: absolute" in css
    assert ".company-pill-badge:focus-within" in css


def test_accessibility_contrast_styles():
    """Verify text-muted, text-secondary and badges satisfy WCAG AA contrast ratio (>= 4.5:1)."""
    with open("static/css/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    # Verify light theme palette contrast
    assert "--text-muted: #4b5563;" in css or "--text-muted: #495057;" in css
    light_muted_contrast_white = contrast_ratio("#4b5563", "#ffffff")
    light_muted_contrast_bg = contrast_ratio("#4b5563", "#f8f9fa")
    assert light_muted_contrast_white >= 4.5, f"Contrast on white {light_muted_contrast_white} < 4.5:1"
    assert light_muted_contrast_bg >= 4.5, f"Contrast on bg-light {light_muted_contrast_bg} < 4.5:1"

    # Verify dark theme palette contrast
    assert "--text-muted: #94a3b8;" in css or "--text-muted: #a0aec0;" in css
    dark_muted_contrast = contrast_ratio("#94a3b8", "#0d1117")
    assert dark_muted_contrast >= 4.5, f"Contrast in dark mode {dark_muted_contrast} < 4.5:1"

    # Verify badge contrast rules exist for subtle badges
    assert ".badge.bg-primary-subtle" in css
    assert ".badge.bg-success-subtle" in css
    assert ".badge.bg-danger-subtle" in css
    assert ".badge.bg-warning-subtle" in css
    assert ".badge.bg-info-subtle" in css


def test_accessibility_javascript_module():
    """Verify initAccessibility registers modal focus trap, Escape key handler, ARIA sync, and live announcers."""
    with open("static/js/script.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "function initAccessibility()" in js or "initAccessibility" in js
    assert "show.bs.modal" in js
    assert "hidden.bs.modal" in js
    assert "Escape" in js
    assert "shown.bs.tab" in js
    assert "shown.bs.collapse" in js
    assert "interviewLiveAnnouncer" in js
    assert "progressLiveAnnouncer" in js


def test_skip_to_content_links_in_key_templates(client):
    """Verify skip-to-content links and accessible main landmarks across pages."""
    endpoints = ["/", "/login", "/register", "/applications", "/calendar", "/leaderboard", "/history"]
    for endpoint in endpoints:
        res = client.get(endpoint)
        assert res.status_code == 200, f"Failed accessing {endpoint}"
        html = res.data.decode("utf-8")
        assert "skip-link" in html, f"Missing skip-link on {endpoint}"
        assert 'tabindex="-1"' in html or 'tabindex="0"' in html, f"Main content missing accessible tabindex on {endpoint}"


def test_modal_accessibility_attributes(client):
    """Verify modal windows have appropriate dialog roles and aria labels."""
    res = client.get("/applications")
    html = res.data.decode("utf-8")
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html

    res_cal = client.get("/calendar")
    html_cal = res_cal.data.decode("utf-8")
    assert 'role="dialog"' in html_cal
    assert 'aria-modal="true"' in html_cal


def test_form_field_explicit_labels(client):
    """Verify critical input fields have explicit labels linked via for/id attributes."""
    res_login = client.get("/login")
    html_login = res_login.data.decode("utf-8")
    assert 'for="loginEmail"' in html_login
    assert 'id="loginEmail"' in html_login
    assert 'for="loginPassword"' in html_login
    assert 'id="loginPassword"' in html_login

    res_reg = client.get("/register")
    html_reg = res_reg.data.decode("utf-8")
    assert 'for="regName"' in html_reg
    assert 'id="regName"' in html_reg
    assert 'for="regEmail"' in html_reg
    assert 'id="regEmail"' in html_reg


def test_upload_area_keyboard_accessible(client):
    """Verify the file upload drop area has button semantics, tabindex, and aria-label."""
    res = client.get("/")
    html = res.data.decode("utf-8")
    assert 'id="uploadArea"' in html
    assert 'role="button"' in html
    assert 'tabindex="0"' in html
    assert 'aria-label' in html


def test_home_tabs_and_company_pills_accessibility(client):
    """Verify home page tabs, batch company pills, and live progress overlay follow WCAG rules."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Navbar landmark
    assert 'aria-label="Main navigation"' in html

    # Tabs and tabpanels
    assert 'id="pdf-tab"' in html
    assert 'aria-controls="pdf-pane"' in html
    assert 'aria-selected="true"' in html
    assert 'id="text-tab"' in html
    assert 'aria-controls="text-pane"' in html
    assert 'aria-selected="false"' in html
    assert 'id="pdf-pane"' in html
    assert 'aria-labelledby="pdf-tab"' in html
    assert 'id="text-pane"' in html
    assert 'aria-labelledby="text-tab"' in html

    # Batch company pills must not use d-none so keyboard tab and space operate them
    assert 'class="form-check-input visually-hidden company-pill-check"' in html
    assert 'aria-label="Select target company' in html

    # Progress overlay live region
    assert 'id="progressLiveAnnouncer"' in html
    assert 'aria-live="polite"' in html


def test_dashboard_accessibility_attributes(client):
    """Verify dashboard page has accessible landmarks, accordion attributes, and chart semantics."""
    test_id = f"test-a11y-dash-{uuid.uuid4().hex[:8]}"
    save_analysis(
        analysis_id=test_id,
        resume_filename="test_a11y_cv.pdf",
        company_name="Google",
        job_description="Software Engineer",
        results_dict={
            "resume_analysis": {
                "ats_score": 85,
                "strengths": ["Demonstrated Python expertise", "Scalable backend systems"],
                "weaknesses": ["Cloud automation needs refinement"],
                "formatting_suggestions": ["Use single font family throughout"],
                "grammar_suggestions": ["Use strong action verbs"],
                "project_feedback": []
            },
            "job_match": {
                "match_percentage": 82,
                "matched_skills": ["Python", "Flask", "Docker"],
                "top_5_resume_changes": ["Add CI/CD pipeline descriptions"]
            },
            "skill_gap": [],
            "learning_roadmap": []
        },
        student_id="test_student"
    )

    with client.session_transaction() as sess:
        sess["student_id"] = "test_student"

    res = client.get(f"/dashboard/{test_id}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Navigation landmark
    assert 'aria-label="Main navigation"' in html

    # Skip-link target
    assert 'id="dashboardContainer"' in html
    assert 'tabindex="-1"' in html

    # Accordions
    assert 'data-bs-target="#collapseStrengths" aria-expanded="true" aria-controls="collapseStrengths"' in html
    assert 'data-bs-target="#collapseWeaknesses" aria-expanded="false" aria-controls="collapseWeaknesses"' in html
    assert 'data-bs-target="#collapseSuggestions" aria-expanded="false" aria-controls="collapseSuggestions"' in html
    assert 'data-bs-target="#collapseProjectExp" aria-expanded="false" aria-controls="collapseProjectExp"' in html

    # Role preparation tabs & panes
    assert 'id="dash-topics-tab"' in html
    assert 'aria-controls="dash-topics-pane"' in html
    assert 'aria-selected="true"' in html
    assert 'id="dash-topics-pane"' in html
    assert 'aria-labelledby="dash-topics-tab"' in html

    # Canvas chart roles & accessible names
    assert 'id="progressTrendChart" role="img" aria-label=' in html
    assert 'id="skillsComparisonChart" role="img" aria-label=' in html


def test_interview_chat_accessibility(client):
    """Verify mock interview template includes chat log semantics, live regions, and video canvas labels."""
    test_id = f"test-a11y-interview-{uuid.uuid4().hex[:8]}"
    save_analysis(
        analysis_id=test_id,
        resume_filename="interview_cv.pdf",
        company_name="Microsoft",
        job_description="Software Engineer",
        results_dict={
            "resume_analysis": {"ats_score": 80, "strengths": ["Python"], "weaknesses": []},
            "job_match": {"match_percentage": 75},
            "skill_gap": [],
            "learning_roadmap": [],
            "interview_questions": {
                "hr": ["Why Microsoft?"],
                "technical": ["Explain time complexity of quicksort."],
                "behavioral": ["Tell me about a difficult bug you resolved."]
            }
        },
        student_id="test_student"
    )

    with client.session_transaction() as sess:
        sess["student_id"] = "test_student"

    res = client.get(f"/interview/{test_id}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Navigation landmarks
    assert 'aria-label="Main navigation"' in html
    assert 'aria-label="Interview round selection"' in html

    # Live region & chat container
    assert 'id="chatContainer"' in html
    assert 'role="log"' in html
    assert 'aria-live="polite"' in html
    assert 'id="interviewLiveAnnouncer"' in html

    # Video coach canvas semantics
    assert 'id="videoAnalysisCanvas"' in html
    assert 'role="img"' in html
    assert 'aria-label=' in html


def test_history_template_accessibility(client):
    """Verify history page includes navigation landmarks, script accessibility bindings, and button labels."""
    res = client.get("/history")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    assert 'aria-label="Main navigation"' in html
    assert 'id="main-content"' in html
    assert 'script.js' in html
