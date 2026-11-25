"""
Unit tests for Security Activity & Audit Logging Service (#407).
"""

import pytest
from app import app
from utils.database import get_db_connection, init_db
from utils.security_activity_service import (
    anonymize_ip,
    mask_ip_address,
    extract_safe_device,
    record_security_event,
    get_user_security_activity
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def clean_security_log_table():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS security_activity_log")
    conn.commit()
    conn.close()
    yield
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS security_activity_log")
    conn.commit()
    conn.close()


def test_mask_ip_address():
    assert mask_ip_address("192.168.1.100") == "192.168.1.0/24"
    assert mask_ip_address("10.0.0.1") == "10.0.0.0/24"
    assert mask_ip_address("2001:0db8:85a3:0000:0000:8a2e:0370:7334") == "2001:db8:85a3::/48"
    assert mask_ip_address("::1") == "::/48"
    assert mask_ip_address(None) == "Unknown"
    assert mask_ip_address("") == "Unknown"
    assert mask_ip_address("invalid-ip") == "Unknown"


def test_extract_safe_device():
    chrome_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    assert extract_safe_device(chrome_ua) == "Chrome on Windows"

    firefox_mac = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/115.0"
    assert extract_safe_device(firefox_mac) == "Firefox on macOS"

    assert extract_safe_device(None) == "Browser / Web Client"


def test_record_and_get_security_activity():
    user_id = "student-sec-1"
    res1 = record_security_event(
        user_id=user_id,
        event_type="SIGN_IN",
        description="Successful login via web portal",
        ip_address="192.168.1.50",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/115.0"
    )
    assert res1["success"] is True
    assert res1["event_id"].startswith("sec-")

    res2 = record_security_event(
        user_id=user_id,
        event_type="PASSWORD_CHANGE",
        description="Password updated from Account Settings",
        ip_address="192.168.1.50"
    )
    assert res2["success"] is True

    events = get_user_security_activity(user_id)
    assert len(events) == 2
    # events are ordered DESC by created_at, so res1 is at index 1 or 0
    devices = [e["user_agent_safe"] for e in events]
    assert any("Chrome on Windows" in d for d in devices)
    assert all(e["ip_masked"] == "192.168.1.0/24" for e in events)


def test_security_activity_multi_tenant_isolation():
    record_security_event("student-alice", "SIGN_IN", "Alice logged in")
    record_security_event("student-bob", "SIGN_IN", "Bob logged in")

    alice_events = get_user_security_activity("student-alice")
    assert len(alice_events) == 1
    assert "Alice" in alice_events[0]["description"]

    bob_events = get_user_security_activity("student-bob")
    assert len(bob_events) == 1
    assert "Bob" in bob_events[0]["description"]


def test_api_security_activity_endpoints(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "student-api-sec"

    record_security_event("student-api-sec", "SIGN_IN", "Initial session start")

    res_api = client.get("/api/user/security-activity")
    assert res_api.status_code == 200
    data = res_api.get_json()
    assert data["success"] is True
    assert len(data["events"]) == 1

    res_page = client.get("/security-activity")
    assert res_page.status_code == 200
    assert "Account Security Activity" in res_page.data.decode("utf-8")


def test_anonymize_ip_ipv4_and_ipv6():
    """Regression test for #852: Validate IPv4 /24 and IPv6 /48 network truncation."""
    from utils.security_activity_service import anonymize_ip

    # IPv4 /24
    assert anonymize_ip("192.168.1.42") == "192.168.1.0/24"
    assert anonymize_ip("10.20.30.200") == "10.20.30.0/24"
    assert anonymize_ip("172.16.5.99") == "172.16.5.0/24"
    assert anonymize_ip("127.0.0.1") == "127.0.0.0/24"

    # IPv6 /48
    assert anonymize_ip("2001:0db8:85a3:0000:0000:8a2e:0370:7334") == "2001:db8:85a3::/48"
    assert anonymize_ip("2001:db8:abcd:0012::1") == "2001:db8:abcd::/48"
    assert anonymize_ip("::1") == "::/48"


def test_anonymize_ip_edge_cases():
    """Regression test for #852: Safe handling of malformed, missing, and CIDR inputs."""
    from utils.security_activity_service import anonymize_ip

    assert anonymize_ip(None) == "Unknown"
    assert anonymize_ip("") == "Unknown"
    assert anonymize_ip("   ") == "Unknown"
    assert anonymize_ip("not-an-ip") == "Unknown"
    assert anonymize_ip("999.999.999.999") == "Unknown"
    assert anonymize_ip(12345) == "Unknown"

    # Already truncated CIDR network inputs
    assert anonymize_ip("192.168.1.0/24") == "192.168.1.0/24"
    assert anonymize_ip("2001:db8:85a3::/48") == "2001:db8:85a3::/48"


def test_anonymize_ip_config_flag(monkeypatch):
    """Regression test for #852: ANONYMIZE_IPS = False preserves original cleaned IP."""
    import config
    from utils.security_activity_service import anonymize_ip

    monkeypatch.setattr(config, "ANONYMIZE_IPS", False)
    assert anonymize_ip("192.168.1.42") == "192.168.1.42"
    assert anonymize_ip("2001:0db8:85a3:0000:0000:8a2e:0370:7334") == "2001:0db8:85a3:0000:0000:8a2e:0370:7334"

    monkeypatch.setattr(config, "ANONYMIZE_IPS", True)
    assert anonymize_ip("192.168.1.42") == "192.168.1.0/24"


def test_security_activity_response_does_not_leak_raw_ip(client):
    """Regression test for #852: Verify security activity JSON response never exposes raw IP."""
    raw_ip = "203.0.113.195"
    record_security_event(
        user_id="student-privacy-check",
        event_type="SIGN_IN",
        description="Login check",
        ip_address=raw_ip,
    )

    with client.session_transaction() as sess:
        sess["user_id"] = "student-privacy-check"

    resp = client.get("/api/user/security-activity")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["success"] is True

    for event in payload["events"]:
        assert raw_ip not in event["ip_masked"]
        assert event["ip_masked"] == "203.0.113.0/24"
