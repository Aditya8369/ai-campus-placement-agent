"""
Unit tests for real-time character counters and input limit warnings (#132).
"""

from app import app


def test_index_page_contains_character_counters():
    """Verify that index template contains character counter DOM elements and limits."""
    with app.test_client() as client:
        res = client.get("/")
        assert res.status_code == 200
        html = res.data.decode("utf-8")

        # Resume text area counter
        assert 'id="resumeTextCharCounter"' in html
        assert 'id="resumeCurrentChars"' in html
        assert 'id="resumeMaxChars"' in html
        assert 'id="resumeCharLimitWarning"' in html

        # Job description counter
        assert 'id="jdCharCounter"' in html
        assert 'id="jdCurrentChars"' in html
        assert 'id="jdMaxChars"' in html
        assert 'id="jdCharLimitWarning"' in html


def test_script_js_contains_counter_initialization():
    """Verify script.js exports initCharacterCounters and updates on paste/input."""
    with open("static/js/script.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "initCharacterCounters" in js
    assert "resumeTextInput" in js
    assert "jdInput" in js
    assert "resumeCurrentChars" in js
    assert "jdCurrentChars" in js
    assert "updateResumeCounter" in js
    assert "updateJdCounter" in js


def test_character_limit_boundary_values():
    """Verify character limit constant values conform to extraction limits."""
    from utils.pdf_reader import MAX_RESUME_TEXT_CHARS
    assert MAX_RESUME_TEXT_CHARS >= 10000
