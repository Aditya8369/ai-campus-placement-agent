"""
Comprehensive tests for Voice-Based Mock Interview with Pace and Filler-Word Feedback (#758).

Verifies:
1. Real-time words per minute (WPM), filler words count, and long pause detection with simple tips.
2. Graceful fallback to text input when microphone is unavailable or unsupported in browser.
3. Unsupported browser messages and DOM safety.
4. Zero audio upload/storage constraint (privacy protection).
5. Voice submission and session delivery summary API endpoints.
"""

import io
import json
import pytest
from app import create_app
from utils.speech_analysis_service import analyze_speech_metrics
from utils.voice_interview_service import VoiceInterviewService, _get_db_connection


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


class TestVoicePaceAndFillerWordDiagnostics:
    """Tests words per minute, filler words, pause detection, and actionable tips."""

    def test_optimal_pace_and_clean_speech(self):
        # ~140 WPM: 28 words in 12.0 seconds -> (28 / 0.2) = 140 WPM
        text = "I developed a full stack application using Flask and PostgreSQL. We focused on database optimization and clean architectural patterns to ensure high availability and responsiveness under heavy load."
        res = analyze_speech_metrics(text, duration_seconds=12.0)
        assert res["success"] is True
        assert res["filler_count"] == 0
        assert 120 <= res["words_per_minute"] <= 165
        assert res["delivery_score"] >= 95
        assert any("Great speaking pace" in tip or "Pace Tip: Great" in tip for tip in res["simple_tips"])
        assert any("zero filler words" in tip or "Minimal filler" in tip for tip in res["simple_tips"])

    def test_fast_pace_warning_tip(self):
        # Fast speech: 40 words in 10 seconds -> 240 WPM
        words = ["word"] * 40
        fast_text = " ".join(words)
        res = analyze_speech_metrics(fast_text, duration_seconds=10.0)
        assert res["success"] is True
        assert res["words_per_minute"] > 165
        assert any("speaking slightly fast" in tip.lower() or "fast" in tip.lower() for tip in res["simple_tips"])

    def test_slow_pace_warning_tip(self):
        # Slow speech: 10 words in 15 seconds -> 40 WPM
        slow_text = "I believe that good software requires careful planning and testing."
        res = analyze_speech_metrics(slow_text, duration_seconds=15.0)
        assert res["success"] is True
        assert res["words_per_minute"] < 110
        assert any("slow" in tip.lower() for tip in res["simple_tips"])

    def test_filler_word_detection_and_tips(self):
        text = "Um, like, basically I built this API and you know, it was literally tough."
        res = analyze_speech_metrics(text, duration_seconds=10.0)
        assert res["success"] is True
        assert res["filler_count"] >= 4
        assert "um" in res["filler_words"]
        assert "like" in res["filler_words"]
        assert "basically" in res["filler_words"]
        assert any("frequent filler words" in tip.lower() or "filler" in tip.lower() for tip in res["simple_tips"])

    def test_long_pause_detection_and_tips(self):
        # Pauses with explicit duration >= 2.5s
        text = "First I analyzed the database requirements. Then I restructured the indexes."
        pauses = [
            {"duration_seconds": 3.2, "timestamp": 2.5},
            {"duration_seconds": 2.8, "timestamp": 6.0},
            {"duration_seconds": 0.8, "timestamp": 9.0}
        ]
        res = analyze_speech_metrics(text, pauses=pauses, duration_seconds=15.0)
        assert res["success"] is True
        assert res["pauses"]["detected_count"] == 3
        assert res["pauses"]["unusually_long_pauses"] == 2
        assert any("long pause" in tip.lower() for tip in res["simple_tips"])

    def test_transcript_pause_markers_detection(self):
        text = "I started by debugging... and [pause] then fixed the concurrency issue."
        res = analyze_speech_metrics(text)
        assert res["success"] is True
        assert res["pauses"]["detected_count"] >= 2


class TestZeroAudioStorageConstraint:
    """Verifies that no audio files are uploaded, stored, or accepted by the system."""

    def test_submit_rejects_audio_file_upload(self, client):
        # Attempt to upload a mock audio file should be rejected with 400
        data = {
            "session_id": "sess_audio_check",
            "question_id": "q1",
            "audio_file": (io.BytesIO(b"MOCK_WEBM_AUDIO_DATA"), "voice.webm")
        }
        resp = client.post(
            "/api/interview/voice/submit",
            data=data,
            content_type="multipart/form-data"
        )
        assert resp.status_code == 400
        res_data = json.loads(resp.data)
        assert "Audio file uploads are not permitted" in res_data.get("message", "")

    def test_speech_metrics_privacy_notice(self):
        res = analyze_speech_metrics("This is a clean test response.")
        assert "privacy_notice" in res
        assert "without storing or uploading raw audio" in res["privacy_notice"]


class TestVoiceInterviewAPIEndpoints:
    """Tests the /api/interview/voice/submit, summary, and feedback routes."""

    def test_voice_submission_and_summary_lifecycle(self, client):
        user_id = "test_voice_user_758"
        sess_id = "test_voice_sess_758"

        # Clean existing test records
        conn = _get_db_connection()
        with conn:
            conn.execute("DELETE FROM voice_interview_submissions WHERE user_id = ? AND session_id = ?", (user_id, sess_id))
        conn.close()

        with client.session_transaction() as s:
            s["user_id"] = user_id

        # 1. First voice answer submission
        payload1 = {
            "session_id": sess_id,
            "question_id": "q1",
            "question_text": "Tell me about your most challenging project.",
            "duration_seconds": 25.0,
            "raw_transcript": "Um basically I optimized a microservice that had severe query latency.",
            "edited_transcript": "I optimized a microservice that had severe query latency.",
            "audio_format": "webm"
        }

        resp1 = client.post("/api/interview/voice/submit", json=payload1)
        assert resp1.status_code == 201
        data1 = json.loads(resp1.data)
        assert data1["status"] == "success"
        analysis1 = data1["voice_analysis"]
        assert analysis1["final_transcript"] == "I optimized a microservice that had severe query latency."
        assert analysis1["words_per_minute"] > 0
        assert "simple_tips" in analysis1

        # 2. Second voice answer submission
        payload2 = {
            "session_id": sess_id,
            "question_id": "q2",
            "question_text": "How do you handle merge conflicts in Git?",
            "duration_seconds": 30.0,
            "raw_transcript": "I inspect the diff, talk with my teammate, and run automated unit tests.",
            "edited_transcript": "I inspect the diff, talk with my teammate, and run automated unit tests.",
            "audio_format": "webm"
        }
        resp2 = client.post("/api/interview/voice/submit", json=payload2)
        assert resp2.status_code == 201

        # 3. Retrieve session delivery summary
        sum_resp = client.get(f"/api/interview/voice/{sess_id}/summary")
        assert sum_resp.status_code == 200
        sum_data = json.loads(sum_resp.data)
        assert sum_data["status"] == "success"
        summary = sum_data["summary"]
        assert summary["total_voice_answers"] == 2
        assert summary["average_wpm"] > 0
        assert summary["total_speaking_time_seconds"] == 55.0

    def test_voice_feedback_route(self, client):
        resp = client.post("/api/interview/voice/feedback", json={
            "transcript": "Um, well like I said earlier, we used Redis for caching.",
            "duration_seconds": 8.0,
            "pauses": [{"duration_seconds": 3.0, "timestamp": 2.0}]
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["filler_count"] >= 2
        assert "simple_tips" in data
        assert len(data["simple_tips"]) >= 1


class TestBrowserFallbackAndTemplateUI:
    """Verifies UI template elements for unsupported browsers and microphone permission denials."""

    def test_interview_template_contains_fallback_and_coaching_elements(self):
        # Inspect interview.html template directly to confirm markup presence
        import os
        template_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "interview.html")
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()

        # 1. Unsupported browser fallback alert
        assert 'id="unsupportedBrowserNotice"' in html
        assert "Speech recognition not supported" in html

        # 2. Microphone denied fallback alert
        assert 'id="micDeniedNotice"' in html
        assert "Microphone unavailable or permission denied" in html

        # 3. Real-time pace and tips card
        assert 'id="voicePaceFeedbackCard"' in html
        assert 'id="voiceLiveWpm"' in html
        assert 'id="voiceLiveFillers"' in html
        assert 'id="voiceLivePauses"' in html
        assert 'id="voiceSimpleTipsText"' in html

        # 4. Zero audio upload privacy assurance
        assert "Audio is processed locally in your browser" in html
        assert "No voice audio is uploaded or stored" in html
