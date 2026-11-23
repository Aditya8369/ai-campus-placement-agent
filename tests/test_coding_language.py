import pytest
from utils.coding_language_service import (
    get_supported_languages,
    is_language_supported,
    get_language_config,
    SUPPORTED_LANGUAGES
)

def test_supported_languages():
    langs = get_supported_languages()
    assert len(langs) == 4
    assert is_language_supported("python") is True
    assert is_language_supported("javascript") is True
    assert is_language_supported("rust") is False

def test_language_config():
    cfg = get_language_config("cpp")
    assert cfg["extension"] == ".cpp"
    assert "main" in cfg["default_boilerplate"]

def test_coding_language_api(client):
    res = client.get("/api/coding/languages")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert len(data["languages"]) == 4

    switch_res = client.post("/api/coding/switch-language", json={
        "problem_id": "prob_1",
        "language": "javascript",
        "code": "function solve() { return 42; }"
    })
    assert switch_res.status_code == 200
    assert switch_res.get_json()["status"] == "success"

    # Unsupported language
    bad_res = client.post("/api/coding/switch-language", json={
        "problem_id": "prob_1",
        "language": "unsupported_lang"
    })
    assert bad_res.status_code == 400
