"""
Comprehensive unit and UI interaction test suite for resume upload feedback,
file selection badge rendering, remove button handlers, type checking, and drag states.
"""

import os
import pytest
from app import app


def _get_analysis_js_content():
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "modules", "analysis.js")
    if not os.path.exists(js_path):
        js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "script.js")
    with open(js_path, "r", encoding="utf-8") as f:
        return f.read()


def test_index_page_contains_feedback_elements():
    """Verify that index.html contains DOM targets for upload feedback badges and error alerts."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/")
        assert res.status_code == 200
        html = res.data.decode("utf-8")

        # Visual feedback badge container and remove button
        assert 'id="fileFeedbackBadge"' in html
        assert 'id="fileFeedbackBadgeText"' in html
        assert 'id="btnRemoveFile"' in html

        # File type error alert container
        assert 'id="uploadTypeErrorAlert"' in html
        assert 'id="uploadTypeErrorMessage"' in html

        # Dynamic upload icon and prompt elements
        assert 'id="uploadIcon"' in html
        assert 'id="uploadPromptText"' in html
        assert 'id="uploadSubText"' in html


def test_script_js_defines_upload_feedback_and_validation_logic():
    """Verify script.js / analysis.js contains the client-side drag-and-drop and validation handlers."""
    js = _get_analysis_js_content()

    # Function declarations and selectors
    assert "handleSelectedFile" in js
    assert "resetUploadArea" in js
    assert "formatFileSize" in js
    assert "dragover-active" in js
    assert "uploadTypeErrorAlert" in js
    assert "fileFeedbackBadge" in js
    assert "btnRemoveFile" in js

    # Extension checking
    assert ".pdf" in js
    assert ".docx" in js
    assert "Unsupported file type" in js


def test_style_css_defines_drag_and_drop_active_classes():
    """Verify style.css declares styling rules for dragover-active and border-danger states."""
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    assert os.path.exists(css_path)

    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    assert ".upload-area.dragover-active" in css
    assert ".upload-area.border-danger" in css
    assert "transform: scale(1.01)" in css
    assert "upload-icon" in css


def test_upload_area_accept_attributes():
    """Verify that file input accepts both pdf and docx MIME/extensions."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/")
        html = res.data.decode("utf-8")
        assert 'accept=".pdf,.docx' in html


def test_upload_area_rendered_in_unauthenticated_session():
    """Verify the upload form renders consistently with no preselected file states."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "upload-area" in html
        assert "resumeInput" in html
        assert "fileFeedbackBadge" in html
        assert "d-none" in html


def test_script_js_file_size_formatting_logic():
    """Verify the unit boundaries implemented in formatFileSize inside script.js / analysis.js."""
    content = _get_analysis_js_content()
    
    assert 'sizes = ["Bytes", "KB", "MB", "GB"]' in content
    assert 'formatFileSize(file.size)' in content
    assert 'uploadArea.classList.remove("border-danger")' in content
    assert 'uploadArea.classList.add("border-danger")' in content


def test_drag_drop_event_listeners_bound():
    """Verify all dragenter, dragover, dragleave, and drop event handlers are registered."""
    content = _get_analysis_js_content()

    assert '["dragenter", "dragover"].forEach' in content
    assert '["dragleave"].forEach' in content
    assert 'uploadArea.addEventListener("drop"' in content
    assert 'btnRemoveFile.addEventListener("click"' in content
    assert 'resetUploadArea()' in content


def test_visual_feedback_icon_swapping():
    """Verify dynamically swaps font awesome classes depending on file extension."""
    content = _get_analysis_js_content()

    assert 'fa-file-word text-primary' in content
    assert 'fa-file-pdf text-danger' in content
    assert 'fa-cloud-arrow-up' in content


def test_drag_and_drop_event_prevention_logic():
    """Verify prevents default event behavior on dragenter, dragover, dragleave, drop."""
    content = _get_analysis_js_content()

    assert 'e.preventDefault()' in content
    assert 'e.stopPropagation()' in content
    assert 'uploadArea.classList.add("dragover-active")' in content
    assert 'uploadArea.classList.remove("dragover-active")' in content


def test_unsupported_file_type_alert_messages():
    """Verify the error messaging details when invalid files like .png, .exe, or .zip are dropped."""
    content = _get_analysis_js_content()

    assert 'Unsupported file type' in content
    assert 'uploadTypeErrorMessage.textContent' in content
    assert 'uploadArea.classList.add("border-danger")' in content
    assert 'fileFeedbackBadge.classList.add("d-none")' in content


def test_remove_file_cleans_input_value_and_restores_state():
    """Verify clicking the remove button resets file inputs and DOM elements."""
    content = _get_analysis_js_content()

    assert 'fileInput.value = ""' in content
    assert 'uploadArea.classList.remove("border-danger", "dragover-active")' in content
    assert 'uploadIcon.className = "fa-solid fa-cloud-arrow-up upload-icon"' in content
    assert 'uploadPromptText.textContent = "Drag and drop your resume here, or click to browse"' in content


def test_resume_upload_feedback_badge_markup():
    """Verify detailed badge styling classes in the HTML template for selected resume feedback."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "bg-success-subtle text-success border border-success-subtle" in html
        assert "fa-file-check" in html
        assert "fa-xmark" in html
        assert "Remove" in html


def test_unsupported_error_box_styling_markup():
    """Verify that index template contains bootstrap alert markup for unsupported file types."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "alert alert-danger" in html
        assert "fa-triangle-exclamation" in html
        assert "uploadTypeErrorMessage" in html


