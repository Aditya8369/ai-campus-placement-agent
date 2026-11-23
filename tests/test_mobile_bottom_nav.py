import pytest

def test_mobile_bottom_nav_rendered(client):
    res = client.get("/search")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Mobile Navigation" in html
    assert "fixed-bottom" in html
    assert "href=\"/applications\"" in html
    assert "href=\"/profile\"" in html
