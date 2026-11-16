import pytest
from app import app
from utils.report_watermark_service import ReportWatermarkService, report_watermark_service


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_generate_watermark_metadata():
    service = ReportWatermarkService()
    meta = service.generate_watermark_metadata(
        student_id="student_12345",
        document_type="Interview Feedback",
        custom_text="Confidential Placement Document"
    )

    assert meta["notice_text"] == "Confidential Placement Document"
    assert meta["document_type"] == "Interview Feedback"
    assert "ID-***2345" in meta["masked_student_id"]
    assert "Confidential Placement Document" in meta["full_caption"]
    assert "Interview Feedback" in meta["full_caption"]
    assert len(meta["verification_code"]) == 12


def test_verify_watermark_digest():
    service = ReportWatermarkService()
    meta = service.generate_watermark_metadata(
        student_id="std_998877",
        document_type="Placement Summary",
        custom_text="Unofficial Summary"
    )

    valid = service.verify_watermark_digest(
        masked_student_id=meta["masked_student_id"],
        timestamp_str=meta["timestamp"],
        document_type=meta["document_type"],
        notice_text=meta["notice_text"],
        verification_code=meta["verification_code"]
    )
    assert valid is True

    # Tampered code
    invalid = service.verify_watermark_digest(
        masked_student_id=meta["masked_student_id"],
        timestamp_str=meta["timestamp"],
        document_type=meta["document_type"],
        notice_text=meta["notice_text"],
        verification_code="TAMPERED1234"
    )
    assert invalid is False


def test_apply_watermark_to_plain_text():
    raw_text = "Overall Preparation Score: 85%\nStrengths: Algorithms, Communication"
    service = ReportWatermarkService()
    result = service.apply_watermark_to_plain_text(
        text_content=raw_text,
        student_id="std_99",
        document_type="Resume Analysis"
    )

    assert "[WATERMARK]" in result
    assert "Overall Preparation Score: 85%" in result
    assert "CONFIDENTIAL & UNOFFICIAL PREPARATION RECORD" in result
    assert "ID-***d_99" in result
    assert "Verification Code:" in result


def test_apply_watermark_to_full_html():
    service = ReportWatermarkService()
    html_page = "<html><head><title>Report</title></head><body><h1>Summary</h1><p>Good performance</p></body></html>"
    watermarked = service.apply_watermark_to_html(
        html_content=html_page,
        student_id="usr_5678",
        include_banner=True
    )

    assert "<style>" in watermarked
    assert "placement-watermark-overlay" in watermarked
    assert "placement-watermark-banner" in watermarked
    assert "Summary" in watermarked
    assert "usr_5678" not in watermarked  # student_id must be masked
    assert "ID-***5678" in watermarked
    assert "placement-watermark-footer-note" in watermarked


def test_apply_watermark_to_html_snippet():
    service = ReportWatermarkService()
    snippet = "<div><h3>Skills Breakdown</h3><ul><li>Python: Expert</li></ul></div>"
    watermarked = service.apply_watermark_to_html(
        html_content=snippet,
        student_id="42",
        include_banner=False
    )

    assert "placement-watermark-container" in watermarked
    assert '<div class="placement-watermark-banner"' not in watermarked
    assert "Python: Expert" in watermarked
    assert "Educational Notice:" in watermarked


def test_api_apply_report_watermark_endpoint(client):
    res = client.post("/api/reports/watermark", json={
        "content": "<p>Placement Readiness: High</p>",
        "format": "html",
        "document_type": "Readiness Audit",
        "custom_notice": "Strictly Internal"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "Strictly Internal" in data["watermarked_content"]
    assert data["metadata"]["notice_text"] == "Strictly Internal"
    assert "verification_code" in data["metadata"]


def test_api_apply_report_watermark_plain_text(client):
    res = client.post("/api/reports/watermark", json={
        "content": "Preparation tasks completed: 12",
        "format": "text",
        "document_type": "Progress Checklist",
        "student_id": "student_alpha"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "[WATERMARK]" in data["watermarked_content"]
    assert "Preparation tasks completed: 12" in data["watermarked_content"]
    assert "ID-***lpha" in data["watermarked_content"]


def test_api_apply_report_watermark_missing_content(client):
    res = client.post("/api/reports/watermark", json={
        "content": ""
    })
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert "error" in data
