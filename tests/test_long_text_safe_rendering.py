"""
Unit Tests for Long-Text Safe Rendering and URL Sanitization (#Task).
====================================================================
Tests cover:
1. HTML-like text escaping (scripts, markup, email brackets, comparisons).
2. Long unbroken string chunking and layout break utilities.
3. URL validation and scheme whitelist enforcement (http, https, mailto).
4. Dangerous URL scheme rejection (javascript, data, vbscript, file, etc.).
5. Safe notes auto-linking with target="_blank" and rel="noopener noreferrer".
6. Integration with Jinja2 template filters registered on the Flask application.
"""

import pytest
from markupsafe import Markup
from routes import create_app
from utils.text_sanitizer import (
    ALLOWED_URL_SCHEMES,
    DANGEROUS_URL_SCHEMES,
    break_long_words,
    is_safe_url,
    render_safe_notes,
    sanitize_url,
)


class TestHtmlEscaping:
    """Verifies that HTML-like text and dangerous script tags are escaped properly."""

    def test_escape_script_tags(self):
        malicious = "<script>alert('xss')</script>"
        rendered = render_safe_notes(malicious)
        assert "<script>" not in rendered
        assert "</script>" not in rendered
        assert "&lt;script&gt;alert(&#039;xss&#039;)&lt;/script&gt;" in rendered or "&lt;script&gt;alert('xss')&lt;/script&gt;" in rendered

    def test_escape_html_attributes_and_tags(self):
        payload = '<img src=x onerror="alert(1)"> <div class="bold">Note content</div>'
        rendered = str(render_safe_notes(payload))
        assert "<img" not in rendered
        assert "<div" not in rendered
        assert "&lt;img" in rendered
        assert "&lt;div" in rendered

    def test_escape_email_brackets_and_comparisons(self):
        text = "Candidate <john.doe@example.com> scored when x < 10 and y > 20."
        rendered = str(render_safe_notes(text))
        assert "&lt;john.doe@example.com&gt;" in rendered
        assert "x &lt; 10" in rendered
        assert "y &gt; 20" in rendered
        assert "<john" not in rendered


class TestLongStringBreaking:
    """Verifies that continuous character strings break without overflowing containers."""

    def test_break_long_unbroken_words(self):
        long_hash = "a" * 150
        result = break_long_words(long_hash, max_chunk=50)
        assert "\u200B" in result
        chunks = result.split("\u200B")
        assert len(chunks) == 3
        assert all(len(c) <= 50 for c in chunks)

    def test_preserve_normal_words(self):
        normal_text = "This is a regular notes paragraph with reasonable words."
        result = break_long_words(normal_text, max_chunk=50)
        assert result == normal_text
        assert "\u200B" not in result

    def test_empty_and_none_string(self):
        assert break_long_words("") == ""
        assert break_long_words(None) == ""


class TestUrlValidation:
    """Verifies URL scheme whitelisting and rejection of dangerous protocols."""

    def test_allow_valid_http_and_https_urls(self):
        assert is_safe_url("https://www.google.com") is True
        assert is_safe_url("http://example.org/path/page.html?ref=1#top") is True
        assert is_safe_url("https://github.com/deepikagandla74/ai-campus-placement-agent") is True

    def test_allow_valid_mailto_urls(self):
        assert is_safe_url("mailto:student@college.edu") is True
        assert is_safe_url("mailto:recruiter.team@company.co.in") is True

    def test_reject_dangerous_schemes(self):
        assert is_safe_url("javascript:alert(1)") is False
        assert is_safe_url("javascript:void(0)") is False
        assert is_safe_url("JAVASCRIPT:alert('xss')") is False
        assert is_safe_url("data:text/html,<script>alert(1)</script>") is False
        assert is_safe_url("vbscript:msgbox('hello')") is False
        assert is_safe_url("file:///etc/passwd") is False
        assert is_safe_url("blob:https://example.com/uuid") is False

    def test_reject_protocol_relative_and_malformed_urls(self):
        assert is_safe_url("//evil.com/phish") is False
        assert is_safe_url("\\\\evil.com\\share") is False
        assert is_safe_url("https://") is False
        assert is_safe_url("") is False
        assert is_safe_url(None) is False

    def test_reject_urls_with_control_characters(self):
        assert is_safe_url("java\x00script:alert(1)") is False
        assert is_safe_url("java\nscript:alert(1)") is False
        assert is_safe_url("https://exam\rple.com") is False

    def test_allow_relative_urls_when_configured(self):
        assert is_safe_url("/dashboard/report/123", allow_relative=True) is True
        assert is_safe_url("/applications?stage=Interview", allow_relative=True) is True
        assert is_safe_url("/dashboard", allow_relative=False) is False

    def test_sanitize_url_helper(self):
        assert sanitize_url("https://example.com") == "https://example.com"
        assert sanitize_url("javascript:alert(1)", default="#") == "#"
        assert sanitize_url("http://example.com/test?a=1&b=2") == "http://example.com/test?a=1&amp;b=2"
        assert sanitize_url(None, default="/") == "/"


class TestNotesSafeRendering:
    """Verifies that user notes and comments are safely auto-linked and line-broken."""

    def test_autolink_valid_urls(self):
        note = "Official placement portal: https://careers.google.com/jobs for details."
        rendered = str(render_safe_notes(note))
        assert '<a href="https://careers.google.com/jobs"' in rendered
        assert 'target="_blank"' in rendered
        assert 'rel="noopener noreferrer"' in rendered
        assert 'class="safe-link safe-text-break"' in rendered
        # Trailing period should not be part of the href
        assert 'jobs."' not in rendered

    def test_block_dangerous_urls_from_autolinking(self):
        note = "Do not click javascript:alert('xss') or data:text/html,evil"
        rendered = str(render_safe_notes(note))
        assert "<a href=\"javascript:" not in rendered
        assert "<a href=\"data:" not in rendered
        assert "javascript:alert" in rendered

    def test_preserve_line_breaks(self):
        note = "Line 1: Key DSA notes\nLine 2: System design\r\nLine 3: HR STAR stories"
        rendered = str(render_safe_notes(note))
        assert "<br>" in rendered
        assert "Line 1: Key DSA notes<br>" in rendered
        assert "Line 2: System design<br>" in rendered

    def test_render_empty_and_none(self):
        assert render_safe_notes("") == Markup("")
        assert render_safe_notes(None) == Markup("")
        assert render_safe_notes("   ") == Markup("")


class TestJinjaFiltersIntegration:
    """Verifies that safe rendering filters are registered and functioning in Flask templates."""

    @pytest.fixture
    def app(self):
        test_app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
        return test_app

    def test_jinja_filters_registered(self, app):
        filters = app.jinja_env.filters
        assert "safe_notes" in filters
        assert "safe_text" in filters
        assert "safe_url" in filters
        assert "is_safe_url" in filters
        assert "safe_break" in filters

    def test_render_template_string_safe_notes(self, app):
        with app.app_context():
            tmpl = app.jinja_env.from_string("{{ note|safe_notes }}")
            result = tmpl.render(note="Check <script>alert(1)</script> & visit https://github.com")
            assert "<script>" not in result
            assert "&lt;script&gt;" in result
            assert '<a href="https://github.com"' in result
            assert 'rel="noopener noreferrer"' in result

    def test_render_template_string_safe_url(self, app):
        with app.app_context():
            tmpl = app.jinja_env.from_string('<a href="{{ target_url|safe_url }}">Link</a>')
            result_safe = tmpl.render(target_url="https://google.com")
            assert 'href="https://google.com"' in result_safe

            result_unsafe = tmpl.render(target_url="javascript:alert(1)")
            assert 'href="#"' in result_unsafe
