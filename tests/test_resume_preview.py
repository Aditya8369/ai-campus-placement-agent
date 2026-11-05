"""
Unit tests for resume upload preview before analysis (#133).
"""

from app import app


def test_index_page_contains_resume_preview_elements():
    """Verify that index template contains preview card, file meta badges, and action buttons."""
    with app.test_client() as client:
        res = client.get("/")
        assert res.status_code == 200
        html = res.data.decode("utf-8")

        # Preview card container
        assert 'id="resumePreviewCard"' in html
        assert 'id="previewFileName"' in html
        assert 'id="previewFileSize"' in html
        assert 'id="previewFileType"' in html
        assert 'id="previewFileIcon"' in html

        # Action controls
        assert 'id="btnChangeResumeFile"' in html
        assert 'id="btnDiscardResumePreview"' in html
        assert 'id="resumeEmptyNotice"' in html


def test_script_js_contains_preview_handlers():
    """Verify script.js binds preview updates and clear handlers."""
    with open("static/js/script.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "resumePreviewCard" in js
    assert "previewFileName" in js
    assert "previewFileSize" in js
    assert "btnChangeResumeFile" in js
    assert "btnDiscardResumePreview" in js
    assert "resumeEmptyNotice" in js
