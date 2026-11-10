"""
Unit & Integration Tests for AI-Generated Answer Quality Checklist Engine (#257)
=================================================================================
Tests:
1. Complete empty answer auditing and graceful failure handling.
2. Direct question addressing detection (identifying alignment vs generic deflection).
3. Concrete examples & quantitative metric detection.
4. Unsupported claims and superlative buzzwords detection.
5. Technical internal mechanics and trade-off depth evaluation.
6. Clarity and structural flow scoring.
7. REST API endpoint /api/interview/answer-quality-audit.
"""

import pytest
import json

from utils.answer_quality_checklist import (
    CHECKLIST_ITEMS,
    audit_interview_answer_quality
)
from app import app


@pytest.fixture
def checklist_client():
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "checklist-secret-key"
    with app.test_client() as client:
        yield client


def test_empty_answer_quality_audit():
    """Verify empty response results in all FAIL checklist items with corrective guidance."""
    res = audit_interview_answer_quality(
        question="How does garbage collection work in Java?",
        answer=""
    )
    assert res["overall_quality_score"] == 0
    assert res["overall_status"] == "NEEDS_IMPROVEMENT"
    assert res["failed_items_count"] == len(CHECKLIST_ITEMS)
    assert any("Please submit an answer" in s for s in res["actionable_suggestions"])


def test_strong_technical_answer_audit():
    """Verify detailed technical answer passes key rubric checks."""
    question = "How would you optimize slow database queries in PostgreSQL?"
    answer = (
        "In my previous project, we had slow reporting queries taking over 4 seconds. "
        "First, I analyzed the query execution plan using EXPLAIN ANALYZE to identify sequential scans and high disk I/O cost. "
        "Because the filter on tenant_id and created_at was missing an index, we implemented a composite B-Tree index. "
        "Under the hood, this allowed logarithmic index scans instead of linear table scans, reducing latency from 4200ms to 85ms. "
        "We also evaluated the trade-off of additional write latency during inserts and tuned our vacuuming schedules."
    )
    res = audit_interview_answer_quality(question=question, answer=answer)

    assert res["overall_quality_score"] >= 80
    assert res["overall_status"] in ("GOOD", "EXCELLENT")

    item_map = {item["item_id"]: item for item in res["checklist"]}
    assert item_map["direct_address"]["status"] == "PASS"
    assert item_map["concrete_examples"]["status"] == "PASS"
    assert item_map["technical_explanation"]["status"] == "PASS"
    assert len(res["unsupported_claims_flagged"]) == 0


def test_unsupported_buzzwords_detection():
    """Verify unsupported superlative claims are flagged for verification."""
    question = "Describe a bug you fixed."
    answer = (
        "I wrote a completely solved architecture that had zero bugs. "
        "Our system was 100x faster than before because everything was automated with best practice always."
    )
    res = audit_interview_answer_quality(question=question, answer=answer)

    item_map = {item["item_id"]: item for item in res["checklist"]}
    assert item_map["supported_claims"]["status"] == "WARNING"
    assert len(res["unsupported_claims_flagged"]) >= 2
    assert any("justification" in s or "Replace superlative" in s for s in res["actionable_suggestions"])


def test_brief_unstructured_answer():
    """Verify brief answers receive clarity warnings and elaboration guidance."""
    question = "What is a deadlock in Operating Systems?"
    answer = "It is when processes wait forever for locks."
    res = audit_interview_answer_quality(question=question, answer=answer)

    item_map = {item["item_id"]: item for item in res["checklist"]}
    assert item_map["clarity_structure"]["status"] == "FAIL"
    assert item_map["concrete_examples"]["status"] == "FAIL"


def test_api_answer_quality_audit_endpoint(checklist_client):
    """Verify POST /api/interview/answer-quality-audit returns structured checklist payload."""
    payload = {
        "question": "Explain how HTTPS secures communications between client and server.",
        "answer": "HTTPS uses SSL/TLS encryption. Specifically, during the TLS handshake, asymmetric cryptography negotiates a shared symmetric session key."
    }
    resp = checklist_client.post("/api/interview/answer-quality-audit", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "audit" in data
    assert data["audit"]["overall_quality_score"] > 50
    assert len(data["audit"]["checklist"]) == 6
