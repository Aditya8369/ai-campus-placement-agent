import pytest
from utils.speech_analysis_service import analyze_speech_metrics

def test_speech_metrics_empty():
    result = analyze_speech_metrics("")
    assert result["success"] is False
    assert "required" in result["error"]

def test_speech_metrics_clean_speech():
    transcript = "I designed and implemented a microservice architecture using Python and Docker."
    result = analyze_speech_metrics(transcript)
    assert result["success"] is True
    assert result["filler_count"] == 0
    assert result["delivery_score"] == 100
    assert "Excellent clarity" in result["feedback"]

def test_speech_metrics_filler_words_and_repetition():
    transcript = "Um, so basically, I I worked on the backend and like you know, it was literally challenging."
    result = analyze_speech_metrics(transcript)
    assert result["success"] is True
    assert result["filler_count"] >= 4
    assert "um" in result["filler_words"]
    assert "basically" in result["filler_words"]
    assert "i i" in result["repetitions"]
    assert result["delivery_score"] < 100

def test_speech_metrics_pause_markers():
    transcript = "First we gathered requirements... then [pause] we designed the database."
    result = analyze_speech_metrics(transcript)
    assert result["success"] is True
    assert result["pauses"]["detected_count"] >= 2

def test_speech_metrics_explicit_pauses():
    transcript = "I solved the problem."
    pauses = [
        {"duration_seconds": 3.0, "timestamp": 2.1},
        {"duration_seconds": 1.0, "timestamp": 5.0}
    ]
    result = analyze_speech_metrics(transcript, pauses=pauses)
    assert result["success"] is True
    assert result["pauses"]["detected_count"] == 2
    assert result["pauses"]["unusually_long_pauses"] == 1

def test_speech_metrics_route(client):
    response = client.post("/api/interview/speech-metrics", json={
        "transcript": "Um, well basically I built a web application using Flask."
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert "delivery_score" in data
    assert "filler_words" in data
