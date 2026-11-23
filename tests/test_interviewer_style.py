import pytest
from utils.interviewer_style_service import (
    get_available_styles,
    get_style_config,
    format_prompt_for_style,
    INTERVIEWER_STYLES
)

def test_available_styles():
    styles = get_available_styles()
    assert len(styles) >= 3
    ids = [s["id"] for s in styles]
    assert "friendly" in ids
    assert "technical" in ids
    assert "panel" in ids

def test_get_style_config_fallback():
    cfg = get_style_config("invalid_persona")
    assert cfg["id"] == "friendly"

def test_format_prompt_for_style():
    formatted = format_prompt_for_style("Explain OOP polymorphism", "technical")
    assert "Strict Technical Architect" in formatted
    assert "Explain OOP polymorphism" in formatted

def test_interviewer_styles_api(client):
    res = client.get("/api/interview/interviewer-styles")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert len(data["styles"]) >= 3

    # Save preference
    post_res = client.post("/api/interview/interviewer-style", json={"style": "panel"})
    assert post_res.status_code == 200
    assert post_res.get_json()["selected_style"] == "panel"
