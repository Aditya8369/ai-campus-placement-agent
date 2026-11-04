"""
Unit tests for improved mock interview chat message styling and evaluation visual hierarchy (#137).
"""

from app import app


def test_interview_template_contains_distinct_chat_bubble_classes():
    """Verify that interview template renders dedicated question, response, and evaluation classes."""
    with open("templates/interview.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert "chat-bubble-question" in html
    assert "chat-bubble-evaluation" in html
    assert "chat-bubble-user" in html
    assert "Question" in html
    assert "AI Feedback" in html


def test_css_contains_chat_bubble_variants():
    """Verify style.css declares distinct color accents and borders for question, user, and evaluation."""
    with open("static/css/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert ".chat-bubble-question" in css
    assert ".chat-bubble-evaluation" in css
    assert ".chat-bubble-user" in css
    assert "[data-bs-theme=\"dark\"] .chat-bubble-question" in css
    assert "[data-bs-theme=\"dark\"] .chat-bubble-evaluation" in css


def test_script_js_appends_typed_bubbles():
    """Verify script.js assigns question and evaluation classes dynamically."""
    with open("static/js/script.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert 'appendChatBubble(feedbackText, "evaluation")' in js
    assert 'appendChatBubble(nextBubbleHtml, "question")' in js
