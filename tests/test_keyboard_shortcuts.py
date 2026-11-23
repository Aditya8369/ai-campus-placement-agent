import pytest
from utils.keyboard_shortcuts_service import get_keyboard_shortcuts

def test_keyboard_shortcuts():
    shortcuts = get_keyboard_shortcuts()
    assert len(shortcuts) >= 2
    assert any(cat["category"] == "Global Navigation" for cat in shortcuts)

def test_keyboard_shortcuts_api(client):
    res = client.get("/api/shortcuts")
    assert res.status_code == 200
    assert len(res.get_json()["shortcuts"]) >= 2
