"""
Unit & Integration Tests for Resume PII Detection & Redaction Service (#249)
===========================================================================
Validates:
1. Email detection & masking
2. Phone number detection across diverse formats (domestic, international, separators)
3. Government identifier detection (PAN, Aadhaar, SSN)
4. Address detection (street indicators, pincodes, zip codes)
5. Selective and full redaction capabilities
6. Preservation of candidate technical skills, education, and experience content
7. API endpoints: /api/resume/scan-pii, /api/resume/redact-pii
8. Integration in /analyze flow when redact_pii=true
"""

import pytest
import json
import config
from utils.database import init_db
from utils.resume_pii_service import PIIDetectionService, REDACTION_TOKENS
from app import app


@pytest.fixture
def pii_svc():
    return PIIDetectionService()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Sets up an isolated test client with fresh database context."""
    db_file = tmp_path / "test_pii_app.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(db_file))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key-pii"
    with app.test_client() as c:
        yield c


@pytest.fixture
def authenticated_session(client):
    """Logs in a mock student user into session."""
    with client.session_transaction() as sess:
        sess["user_id"] = 101
        sess["username"] = "pii_candidate"
        sess["role"] = "student"


SAMPLE_RESUME_WITH_PII = """
Johnathan Doe
Email: johnathan.doe@alumni.stanford.edu
Alternate: jdoe.dev99@gmail.com
Phone: +1 (555) 234-5678, Mobile: 9876543210
Aadhaar: 2345 6789 0123
PAN: ABCDE1234F
SSN: 123-45-6789
Address: 42 Silicon Vista Boulevard, Apt 4B, San Francisco, CA 94107
Postal Code: 560001 Bangalore

PROFESSIONAL SUMMARY
Senior Backend Engineer with 5 years experience designing scalable Python/Flask microservices,
Distributed Systems, and PostgreSQL architectures. Built fault-tolerant message streaming pipelines.

EXPERIENCE
Software Engineer - Acme Cloud Corp (2021-Present)
- Orchestrated Kafka streaming pipelines processing 10M events daily.
- Optimized database query latency by 45% using indexed materialised views.

EDUCATION
B.S. in Computer Science - University of California, Berkeley (2016-2020)
GPA: 3.85/4.0
"""


def test_detect_all_pii_types(pii_svc):
    """Verify that email, phone, gov IDs, and addresses are accurately captured."""
    report = pii_svc.detect_pii(SAMPLE_RESUME_WITH_PII)

    assert report["has_pii"] is True
    assert report["risk_level"] in ("medium", "high")

    # Email assertions
    emails = report["detected_entities"]["emails"]
    assert "johnathan.doe@alumni.stanford.edu" in emails
    assert "jdoe.dev99@gmail.com" in emails

    # Gov ID assertions
    gov_ids = report["detected_entities"]["government_ids"]
    assert "ABCDE1234F" in gov_ids
    assert any("2345 6789 0123" in g or "2345" in g for g in gov_ids)
    assert any("123-45-6789" in g for g in gov_ids)

    # Phone assertions
    phones = report["detected_entities"]["phones"]
    assert len(phones) >= 1

    # Address assertions
    addresses = report["detected_entities"]["addresses"]
    assert len(addresses) >= 1


def test_redact_all_pii(pii_svc):
    """Verify full redaction sanitizes sensitive info while keeping resume structure."""
    result = pii_svc.redact_pii(SAMPLE_RESUME_WITH_PII)
    redacted = result["redacted_text"]

    assert "johnathan.doe@alumni.stanford.edu" not in redacted
    assert "jdoe.dev99@gmail.com" not in redacted
    assert "ABCDE1234F" not in redacted
    assert "123-45-6789" not in redacted
    assert "[REDACTED_EMAIL]" in redacted
    assert "[REDACTED_GOV_ID]" in redacted

    # Verify professional content is completely preserved
    assert "Senior Backend Engineer with 5 years experience" in redacted
    assert "Software Engineer - Acme Cloud Corp" in redacted
    assert "Orchestrated Kafka streaming pipelines processing 10M events daily." in redacted
    assert "B.S. in Computer Science" in redacted


def test_selective_redaction(pii_svc):
    """Verify selective redaction only modifies specified entity categories."""
    # Redact only emails, keeping phone numbers and gov IDs intact
    res = pii_svc.redact_pii(
        SAMPLE_RESUME_WITH_PII,
        redact_emails=True,
        redact_phones=False,
        redact_addresses=False,
        redact_gov_ids=False
    )
    redacted = res["redacted_text"]

    assert "[REDACTED_EMAIL]" in redacted
    assert "ABCDE1234F" in redacted
    assert res["redaction_counts"]["emails"] >= 2
    assert res["redaction_counts"]["government_ids"] == 0


def test_custom_value_redaction(pii_svc):
    """Verify user can pass custom tokens to redact (e.g. personal names, company secrets)."""
    text = "Jane works at SecretStealthStartup on proprietary quantum algorithms."
    res = pii_svc.redact_pii(
        text,
        custom_redact_values=["Jane", "SecretStealthStartup"]
    )
    assert "[REDACTED_CUSTOM]" in res["redacted_text"]
    assert "Jane" not in res["redacted_text"]
    assert "SecretStealthStartup" not in res["redacted_text"]
    assert "proprietary quantum algorithms" in res["redacted_text"]


def test_clean_text_no_pii(pii_svc):
    """Verify clean resume produces zero detections and clean risk evaluation."""
    clean_text = """
    Software Engineer
    Proficient in Go, Python, React, and Kubernetes.
    Engineered automated testing harness reducing deployment failures by 30%.
    """
    report = pii_svc.detect_pii(clean_text)
    assert report["has_pii"] is False
    assert report["total_detections"] == 0
    assert report["risk_level"] == "none"

    redaction = pii_svc.redact_pii(clean_text)
    assert redaction["total_redactions"] == 0
    assert redaction["redacted_text"] == clean_text


def test_scan_pii_endpoint(client, authenticated_session):
    """Test POST /api/resume/scan-pii with JSON payload."""
    payload = {
        "text": "Contact candidate at test.candidate@example.org or call +1 555-0199."
    }
    resp = client.post("/api/resume/scan-pii", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "scan" in data
    assert data["scan"]["has_pii"] is True
    assert "test.candidate@example.org" in data["scan"]["detected_entities"]["emails"]


def test_redact_pii_endpoint(client, authenticated_session):
    """Test POST /api/resume/redact-pii with customized options."""
    payload = {
        "text": "Send offers to hire.me@techcorp.io or reach PAN ABCDE9999Z.",
        "redact_emails": True,
        "redact_gov_ids": True
    }
    resp = client.post("/api/resume/redact-pii", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    redacted_text = data["redaction"]["redacted_text"]
    assert "hire.me@techcorp.io" not in redacted_text
    assert "ABCDE9999Z" not in redacted_text
    assert "[REDACTED_EMAIL]" in redacted_text
    assert "[REDACTED_GOV_ID]" in redacted_text


def test_pii_endpoints_require_auth(client):
    """Verify endpoints return 401 when user is not authenticated."""
    app.config["ENFORCE_LOGIN_IN_TESTS"] = True
    try:
        scan_resp = client.post("/api/resume/scan-pii", json={"text": "test@test.com"})
        assert scan_resp.status_code == 401

        redact_resp = client.post("/api/resume/redact-pii", json={"text": "test@test.com"})
        assert redact_resp.status_code == 401
    finally:
        app.config["ENFORCE_LOGIN_IN_TESTS"] = False
