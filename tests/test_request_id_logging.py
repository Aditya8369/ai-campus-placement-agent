"""
Unit test for X-Request-ID propagation and correlation tracing headers.
"""

from app import app


def test_request_id_generated_if_missing():
    """Verify an X-Request-ID is automatically generated and returned when not supplied."""
    with app.test_client() as client:
        res = client.get("/")
        assert "X-Request-ID" in res.headers
        assert len(res.headers["X-Request-ID"]) > 10


def test_request_id_preserved_when_supplied():
    """Verify an incoming X-Request-ID header is echoed directly in response headers."""
    custom_id = "test-custom-trace-id-12345"
    with app.test_client() as client:
        res = client.get("/", headers={"X-Request-ID": custom_id})
        assert "X-Request-ID" in res.headers
        assert res.headers["X-Request-ID"] == custom_id
