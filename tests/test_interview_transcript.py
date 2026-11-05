"""
Unit tests for downloadable mock interview transcript generator and endpoint (#161).

Verifies:
- Standalone PDF transcript compilation with full Q&A pairs, scores, and feedback.
- Safe escaping of special characters and XML/HTML tags in user responses.
- Plain-text / Markdown transcript generation.
- Download endpoint enforcement: requires at least one submitted answer.
- Interview template rendering of 'Download transcript' button and disabled/enabled states.
"""

import os
import tempfile
from pathlib import Path
import pytest
from app import app
import config
from utils.database import (
    init_db,
    save_analysis,
    create_interview_session,
    update_interview_session,
)
from utils.report_generator import (
    generate_interview_transcript_pdf,
    generate_interview_transcript_markdown,
)


@pytest.fixture
def sample_session_data():
    return {
        "analysis_id": "test_aid_161",
        "company_name": "Google",
        "answers": [
            {
                "question_index": 0,
                "type": "HR",
                "question": "Tell me about yourself and your career goals.",
                "answer": "I am a computer science graduate focused on scalable backend systems and distributed databases.",
                "evaluation": {
                    "technical_accuracy": 85,
                    "communication_score": 90,
                    "confidence_score": 88,
                    "verbal_clarity_score": 90,
                    "feedback": "Strong and articulate introduction with clear professional focus.",
                    "suggestions": [
                        "Mention specific distributed frameworks like Kafka or gRPC.",
                        "Quantify past project milestones.",
                    ],
                    "star_method_analysis": {
                        "used_star": True,
                        "feedback": "Clear progression from educational background to career goals.",
                    },
                    "filler_words_detected": [],
                    "filler_word_count": 0,
                },
            },
            {
                "question_index": 1,
                "type": "Technical",
                "question": "Explain the difference between TCP and UDP protocols.",
                "answer": "TCP is connection-oriented and reliable with three-way handshakes, while UDP is connectionless and lightweight.",
                "evaluation": {
                    "technical_accuracy": 92,
                    "communication_score": 85,
                    "confidence_score": 80,
                    "verbal_clarity_score": 85,
                    "feedback": "Accurate distinction highlighting connection semantics and overhead.",
                    "suggestions": [
                        "Include examples of real-world use cases (e.g. video streaming for UDP).",
                    ],
                    "filler_words_detected": ["um"],
                    "filler_word_count": 1,
                },
            },
        ],
    }


def test_generate_interview_transcript_pdf_with_data(sample_session_data):
    """Verify PDF transcript generation containing all Q&A pairs, scores, and feedback."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_pdf = os.path.join(tmp_dir, "transcript.pdf")
        res_path = generate_interview_transcript_pdf(
            session_data=sample_session_data,
            output_path=out_pdf,
            company_name="Google",
        )
        assert os.path.exists(res_path)
        assert os.path.getsize(res_path) > 1000


def test_generate_interview_transcript_pdf_xml_escaping():
    """Verify user text containing XML/HTML tags and special chars is escaped safely without ExpatError."""
    malicious_session = {
        "analysis_id": "test_escape_161",
        "company_name": "AT&T <Global Tech & Software>",
        "answers": [
            {
                "question_index": 0,
                "type": "Technical",
                "question": "What is the runtime of binary search when N < 100 & M > 20?",
                "answer": "<script>alert('xss')</script> & <b>bold response</b> with unescaped <tags> & 'quotes' & \"double\".",
                "evaluation": {
                    "technical_accuracy": 70,
                    "communication_score": 65,
                    "confidence_score": 60,
                    "verbal_clarity_score": 65,
                    "feedback": "Review time complexity <O(log N)> & space overhead.",
                    "suggestions": [
                        "Avoid raw HTML tags like <div> in answers.",
                        "Express complexity as O(log N) & explain boundaries.",
                    ],
                    "star_method_analysis": {
                        "used_star": False,
                        "feedback": "Structure using <Situation> & <Result>.",
                    },
                    "filler_words_detected": ["<like>", "&um"],
                    "filler_word_count": 2,
                },
            }
        ],
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_pdf = os.path.join(tmp_dir, "escaped_transcript.pdf")
        res_path = generate_interview_transcript_pdf(
            session_data=malicious_session,
            output_path=out_pdf,
            company_name=malicious_session["company_name"],
        )
        assert os.path.exists(res_path)
        assert os.path.getsize(res_path) > 1000


def test_generate_interview_transcript_pdf_empty_session():
    """Verify PDF generation functions gracefully when no answers are submitted."""
    empty_session = {
        "analysis_id": "test_empty_161",
        "company_name": "Microsoft",
        "answers": [],
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_pdf = os.path.join(tmp_dir, "empty_transcript.pdf")
        res_path = generate_interview_transcript_pdf(
            session_data=empty_session,
            output_path=out_pdf,
            company_name="Microsoft",
        )
        assert os.path.exists(res_path)
        assert os.path.getsize(res_path) > 1000


def test_generate_interview_transcript_markdown(sample_session_data):
    """Verify plain-text / Markdown export includes Q&A pairs, scores, and feedback."""
    md_content = generate_interview_transcript_markdown(
        session_data=sample_session_data,
        company_name="Google",
    )
    assert "# AI Mock Interview Session Transcript — Google" in md_content
    assert "Tell me about yourself and your career goals." in md_content
    assert "computer science graduate focused on scalable backend" in md_content
    assert "Explain the difference between TCP and UDP protocols." in md_content
    assert "Technical Accuracy: **85/100**" in md_content
    assert "Communication Score: **90/100**" in md_content
    assert "Strong and articulate introduction" in md_content
    assert "Executive Performance Summary" in md_content


def test_download_transcript_requires_at_least_one_answer(monkeypatch):
    """Verify endpoint rejects transcript download when zero answers have been submitted."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db = Path(tmp_dir) / "test_transcript_zero.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db)
        init_db()

        aid = "aid_zero_answers"
        save_analysis(aid, "test.pdf", "Amazon", "SDE", {})
        create_interview_session(
            interview_id=aid,
            analysis_id=aid,
            questions_list=[{"index": 0, "type": "HR", "question": "Why Amazon?"}],
        )

        app.config["TESTING"] = True
        with app.test_client() as client:
            # HTML / browser request redirects with warning flash
            res = client.get(f"/interview/{aid}/transcript")
            assert res.status_code == 302
            assert f"/interview/{aid}" in res.location

            # JSON / API request returns 400 error
            json_res = client.get(
                f"/interview/{aid}/transcript",
                headers={"Accept": "application/json"},
            )
            assert json_res.status_code == 400
            assert "No answers recorded yet" in json_res.get_json()["error"]


def test_download_transcript_success_endpoints(monkeypatch, sample_session_data):
    """Verify PDF and Markdown transcript downloads succeed when at least one answer exists."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db = Path(tmp_dir) / "test_transcript_success.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db)
        monkeypatch.setattr(config, "REPORT_FOLDER", str(Path(tmp_dir) / "reports"))
        init_db()

        aid = sample_session_data["analysis_id"]
        save_analysis(aid, "test.pdf", "Google", "SWE", {})
        create_interview_session(
            interview_id=aid,
            analysis_id=aid,
            questions_list=[{"index": 0, "type": "HR", "question": "Intro"}],
        )
        update_interview_session(
            interview_id=aid,
            current_question_index=2,
            answers_list=sample_session_data["answers"],
            completed=True,
        )

        app.config["TESTING"] = True
        with app.test_client() as client:
            # 1. Default PDF download
            pdf_res = client.get(f"/interview/{aid}/transcript")
            assert pdf_res.status_code == 200
            assert pdf_res.mimetype == "application/pdf"
            assert "attachment;" in pdf_res.headers.get("Content-Disposition", "")
            assert len(pdf_res.data) > 1000
            pdf_res.close()

            # 2. Markdown download
            md_res = client.get(f"/interview/{aid}/transcript?format=markdown")
            assert md_res.status_code == 200
            assert md_res.mimetype == "text/markdown"
            assert "attachment;" in md_res.headers.get("Content-Disposition", "")
            assert b"AI Mock Interview Session Transcript" in md_res.data
            md_res.close()

            # 3. Plain text download
            txt_res = client.get(f"/interview/{aid}/transcript?format=txt")
            assert txt_res.status_code == 200
            assert txt_res.mimetype == "text/plain"
            assert "attachment;" in txt_res.headers.get("Content-Disposition", "")
            assert b"Candidate Response:" in txt_res.data
            txt_res.close()

            # 4. Route alias /download/interview-transcript/<aid>
            alias_res = client.get(f"/download/interview-transcript/{aid}")
            assert alias_res.status_code == 200
            assert alias_res.mimetype == "application/pdf"
            alias_res.close()


def test_interview_template_contains_download_transcript_controls():
    """Verify interview.html template contains the Download Transcript button and formats."""
    with open("templates/interview.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert "btnDownloadTranscript" in html
    assert "Download" in html
    assert "Transcript" in html
    assert "/interview/{{ analysis_id }}/transcript" in html
    assert "linkDownloadTranscriptPdf" in html
    assert "linkDownloadTranscriptMd" in html
