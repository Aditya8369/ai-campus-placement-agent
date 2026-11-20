"""
Unit and integration tests for Resume Keyword Highlighter & Job Match Optimization (#430).

Verifies:
1. Matching: Matched keywords are highlighted with <mark class="resume-keyword-matched"> in the resume text.
2. Case-insensitivity: Matches keywords regardless of character casing in resume text.
3. Partial match prevention: Substring tokens (e.g. 'Java' inside 'JavaScript' or 'Go' in 'Google') are NOT highlighted.
4. XSS & HTML Escaping: Raw HTML or script tags (e.g., <script>alert(1)</script>) are escaped safely into &lt;script&gt;.
5. Empty keyword handling: Empty, whitespace-only, or None keyword lists return the escaped resume text without errors.
6. Empty resume text handling: Empty or None resume text returns empty string without errors.
7. Section suggestions: Missing keywords are correctly classified into 'skills', 'projects', or 'experience'.
8. Missing keywords listing: Missing keywords are returned separately with metadata and actionable recommendations.
9. Dashboard integration: Dashboard route and template render the keyword highlighter card, toggle switch, and missing keywords list.
10. JavaScript & CSS: Script and stylesheet declare the highlight class and toggle behavior.
"""

import html
import tempfile
from pathlib import Path
import pytest
from app import app
import config
from utils.database import init_db, save_analysis
from utils.resume_keyword_highlighter import (
    highlight_resume_keywords,
    suggest_section_for_keyword,
    get_section_metadata,
    extract_keywords_from_analysis,
    get_analysis_resume_text,
    prepare_keyword_highlight_data,
)


# ==============================================================================
# 1. Core Highlighting, Matching, and Partial Match Prevention
# ==============================================================================

def test_highlight_resume_keywords_basic_matching():
    """Verify matched keywords are wrapped in <mark class='resume-keyword-matched'> with original casing."""
    resume_text = "Proficient in Python, React, and SQL database design."
    keywords = ["Python", "SQL", "React"]

    result = highlight_resume_keywords(resume_text, keywords)

    assert '<mark class="resume-keyword-matched">Python</mark>' in result
    assert '<mark class="resume-keyword-matched">React</mark>' in result
    assert '<mark class="resume-keyword-matched">SQL</mark>' in result
    assert "database design." in result


def test_highlight_resume_keywords_case_insensitivity():
    """Verify keywords match case-insensitively while preserving original text casing."""
    resume_text = "Experienced in python, DOCKER, and FastApi frameworks."
    keywords = ["Python", "Docker", "FastAPI"]

    result = highlight_resume_keywords(resume_text, keywords)

    # Preserves the casing from the resume text
    assert '<mark class="resume-keyword-matched">python</mark>' in result
    assert '<mark class="resume-keyword-matched">DOCKER</mark>' in result
    assert '<mark class="resume-keyword-matched">FastApi</mark>' in result


def test_highlight_resume_keywords_no_partial_matches():
    """Verify that partial matches (e.g., 'Java' in 'JavaScript' or 'Go' in 'Django') are NOT highlighted."""
    resume_text = (
        "Core languages include JavaScript, Java, Django, Go, and C++.\n"
        "Engineered EnterpriseJavaBeans and PostgreSQL clusters."
    )
    keywords = ["Java", "Go", "C++"]

    result = highlight_resume_keywords(resume_text, keywords)

    # 'Java' alone should be highlighted
    assert 'JavaScript' in result
    assert '<mark class="resume-keyword-matched">Java</mark>Script' not in result
    assert '<mark class="resume-keyword-matched">JavaScript</mark>' not in result
    assert '<mark class="resume-keyword-matched">Java</mark>' in result

    # 'EnterpriseJavaBeans' must not match 'Java'
    assert 'EnterpriseJavaBeans' in result
    assert '<mark class="resume-keyword-matched">Java</mark>Beans' not in result

    # 'Go' must not match 'Django'
    assert 'Django' in result
    assert 'Djan<mark class="resume-keyword-matched">Go</mark>' not in result
    assert '<mark class="resume-keyword-matched">Go</mark>' in result

    # Symbol-bearing keyword 'C++' matches cleanly
    assert '<mark class="resume-keyword-matched">C++</mark>' in result


# ==============================================================================
# 2. XSS Safety & HTML Escaping
# ==============================================================================

def test_highlight_resume_keywords_xss_safety():
    """Verify resume text containing HTML or script tags is escaped safely before highlighting."""
    malicious_text = (
        "Developer with <script>alert('XSS')</script> experience.\n"
        "<img src=x onerror=alert(1)> and <b>Python</b> expertise."
    )
    keywords = ["Python", "Developer"]

    result = highlight_resume_keywords(malicious_text, keywords)

    # Raw script or img tags must never appear unescaped
    assert "<script>" not in result
    assert "<img" not in result
    assert "<b>" not in result

    # Escaped safe HTML representations
    assert "&lt;script&gt;alert(&#x27;XSS&#x27;)&lt;/script&gt;" in result or "&lt;script&gt;alert('XSS')&lt;/script&gt;" in result
    assert "&lt;img src=x onerror=alert(1)&gt;" in result
    assert "&lt;b&gt;" in result

    # Valid keyword is still highlighted
    assert '<mark class="resume-keyword-matched">Python</mark>' in result
    assert '<mark class="resume-keyword-matched">Developer</mark>' in result


# ==============================================================================
# 3. Empty & Edge Case Inputs
# ==============================================================================

def test_highlight_resume_keywords_empty_cases():
    """Verify handling of empty resume text, empty keyword list, None, and whitespace-only items."""
    sample_text = "Software Engineer with AWS and Docker experience."

    # Empty text
    assert highlight_resume_keywords("", ["AWS"]) == ""
    assert highlight_resume_keywords(None, ["AWS"]) == ""

    # Empty keywords list
    assert highlight_resume_keywords(sample_text, []) == html.escape(sample_text)
    assert highlight_resume_keywords(sample_text, None) == html.escape(sample_text)
    assert highlight_resume_keywords(sample_text, ["", "   ", None]) == html.escape(sample_text)


def test_highlight_multi_word_keywords():
    """Verify multi-word keywords (e.g. 'REST APIs', 'System Design') match with whole-word boundaries."""
    text = "Implemented REST APIs and conducted System Design reviews."
    keywords = ["REST APIs", "System Design"]

    result = highlight_resume_keywords(text, keywords)

    assert '<mark class="resume-keyword-matched">REST APIs</mark>' in result
    assert '<mark class="resume-keyword-matched">System Design</mark>' in result


# ==============================================================================
# 4. Section Suggestions & Taxonomy
# ==============================================================================

def test_suggest_section_for_keyword_taxonomy():
    """Verify keywords are categorized into skills, projects, or experience sections accurately."""
    # Skills section: languages, databases, foundational frameworks
    assert suggest_section_for_keyword("Python") == "skills"
    assert suggest_section_for_keyword("SQL") == "skills"
    assert suggest_section_for_keyword("React") == "skills"
    assert suggest_section_for_keyword("MongoDB") == "skills"

    # Projects section: architectural patterns, deployment systems, pipelines
    assert suggest_section_for_keyword("Distributed Systems") == "projects"
    assert suggest_section_for_keyword("System Design") == "projects"
    assert suggest_section_for_keyword("Microservices") == "projects"
    assert suggest_section_for_keyword("Kubernetes") == "projects"
    assert suggest_section_for_keyword("REST API") == "projects"

    # Experience section: workflow methodologies, team leadership, operations
    assert suggest_section_for_keyword("Agile") == "experience"
    assert suggest_section_for_keyword("Scrum") == "experience"
    assert suggest_section_for_keyword("Code Review") == "experience"
    assert suggest_section_for_keyword("CI/CD") == "experience"
    assert suggest_section_for_keyword("Cross-Functional Leadership") == "experience"

    # Fallback for unexpected or empty keyword
    assert suggest_section_for_keyword("") == "skills"
    assert suggest_section_for_keyword(None) == "skills"


def test_get_section_metadata():
    """Verify section metadata returns appropriate badge classes, icons, and guidance tips."""
    for sec_key in ("skills", "projects", "experience"):
        meta = get_section_metadata(sec_key)
        assert meta["section"] == sec_key
        assert meta["label"] in ("Skills", "Projects", "Experience")
        assert "badge_class" in meta
        assert "icon" in meta
        assert len(meta["tip"]) > 10


# ==============================================================================
# 5. Analysis Record Extraction & Preparation
# ==============================================================================

def test_extract_keywords_from_analysis_record():
    """Verify extraction of matched and missing keywords from JobMatchAgent payload."""
    analysis_record = {
        "results": {
            "job_match": {
                "matched_skills": ["Python", "Flask", "Docker"],
                "missing_skills": ["Kubernetes", "AWS", "System Design"],
            }
        }
    }

    matched, missing = extract_keywords_from_analysis(analysis_record)
    assert matched == ["Python", "Flask", "Docker"]
    assert missing == ["Kubernetes", "AWS", "System Design"]


def test_prepare_keyword_highlight_data_full_payload():
    """Verify prepare_keyword_highlight_data bundles highlighted HTML and structured missing keywords."""
    analysis_record = {
        "id": "test_aid_prep_430",
        "resume_text": "Experienced Python backend engineer with Docker skills.",
        "company_name": "Google",
        "results": {
            "job_match": {
                "matched_skills": ["Python", "Docker"],
                "missing_skills": ["Kubernetes", "Agile"],
            }
        }
    }

    data = prepare_keyword_highlight_data(analysis_record)

    assert data["has_resume_text"] is True
    assert data["matched_count"] == 2
    assert data["missing_count"] == 2
    assert '<mark class="resume-keyword-matched">Python</mark>' in data["highlighted_resume_html"]
    assert '<mark class="resume-keyword-matched">Docker</mark>' in data["highlighted_resume_html"]

    # Missing keywords must be listed separately with section suggestions
    missing_items = data["missing_keywords_with_sections"]
    assert len(missing_items) == 2

    k8s_item = next(item for item in missing_items if item["keyword"] == "Kubernetes")
    assert k8s_item["suggested_section"] == "projects"
    assert k8s_item["section_label"] == "Projects"

    agile_item = next(item for item in missing_items if item["keyword"] == "Agile")
    assert agile_item["suggested_section"] == "experience"
    assert agile_item["section_label"] == "Experience"


# ==============================================================================
# 6. Dashboard Route & Template Integration
# ==============================================================================

@pytest.fixture
def test_app_client(monkeypatch):
    """Test client configured with temporary sqlite database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_keywords.db"
        monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
        monkeypatch.setattr(config, "BASE_DIR", str(tmpdir))
        init_db()

        app.config["TESTING"] = True
        app.config["ENFORCE_LOGIN_IN_TESTS"] = False
        with app.test_client() as client:
            yield client


def test_dashboard_renders_keyword_highlight_section(test_app_client):
    """Verify dashboard route serves the keyword highlighter card, toggle switch, and preview container."""
    aid = "aid_keyword_test_430"
    sample_results = {
        "resume_analysis": {"ats_score": 85},
        "job_match": {
            "match_percentage": 78,
            "matched_skills": ["Python", "FastAPI"],
            "missing_skills": ["Kubernetes", "Distributed Systems", "Scrum"],
        },
        "extracted_resume_text": "Alex Chen\nSkilled Python and FastAPI developer building backend services.",
    }
    save_analysis(
        analysis_id=aid,
        resume_filename="alex_resume.pdf",
        company_name="Google",
        job_description="Looking for Python, FastAPI, Kubernetes, and Scrum engineers.",
        results_dict=sample_results,
        student_id="default_student"
    )

    response = test_app_client.get(f"/dashboard/{aid}")
    assert response.status_code == 200
    html_content = response.data.decode("utf-8")

    # Section card and navigation
    assert 'id="resumeKeywordHighlightSection"' in html_content
    assert 'id="toggleKeywordHighlights"' in html_content
    assert 'role="switch"' in html_content

    # Matched keywords badge and highlighted content container
    assert 'id="badgeMatchedKeywordsCount"' in html_content
    assert 'id="badgeMissingKeywordsCount"' in html_content
    assert 'id="resumeHighlightedContent"' in html_content
    assert '<mark class="resume-keyword-matched">Python</mark>' in html_content
    assert '<mark class="resume-keyword-matched">FastAPI</mark>' in html_content

    # Missing keywords list with section recommendations
    assert 'id="missingKeywordsList"' in html_content
    assert "Kubernetes" in html_content
    assert "Distributed Systems" in html_content
    assert "Scrum" in html_content
    assert "Projects" in html_content
    assert "Experience" in html_content


def test_script_js_contains_highlighter_toggle():
    """Verify script.js / dashboard.js binds the toggle switch for keyword highlights."""
    js_path = Path("static/js/modules/dashboard.js")
    if not js_path.exists():
        js_path = Path("static/js/script.js")
    js = js_path.read_text(encoding="utf-8")

    assert "initResumeKeywordHighlighter" in js
    assert "toggleKeywordHighlights" in js
    assert "resumeHighlightedContent" in js
    assert "highlights-hidden" in js


def test_style_css_contains_highlighter_rules():
    """Verify style.css declares highlight marks, dark mode, and toggle hidden state."""
    with open("static/css/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert ".resume-keyword-matched" in css
    assert ".highlights-hidden .resume-keyword-matched" in css
    assert ".resume-preview-box" in css
    assert ".missing-keyword-item" in css
