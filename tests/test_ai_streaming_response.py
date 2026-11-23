"""
Tests for AI Streaming Response (#764).
========================================
Acceptance Criteria:
1. The first section appears before the whole response finishes.
2. Cancelling stops the underlying request.
3. Errors never discard content that was already shown.
4. Keep a non-streaming fallback.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from utils.gemini import (
    extract_completed_sections_from_buffer,
    stream_json_response_sections,
)
from agents.coordinator import CoordinatorAgent
from utils.async_pipeline import (
    AnalysisTask,
    create_analysis_task,
    get_analysis_task,
    _run_analysis_pipeline,
)


SAMPLE_RESUME_TEXT = "Jane Doe\nSkills: Python, Docker, SQL\nExperience: Software Engineer"
SAMPLE_JOB_DESC = "Seeking a Software Engineer skilled in Python and Docker."
SAMPLE_COMPANY = "Acme Corp"

MOCK_STREAM_CHUNKS = [
    '{\n  "resume_analysis": {\n    "candidate_name": "Jane Doe",\n    "ats_score": 85,\n',
    '    "strengths": ["Strong Python experience"],\n    "areas_for_improvement": ["Add cloud certification"]\n  },\n',
    '  "job_match": {\n    "match_score": 88,\n    "matching_skills": ["Python", "Docker"],\n    "missing_skills": ["Kubernetes"]\n  },\n',
    '  "skill_gap": {\n    "critical_missing_skills": ["Kubernetes"],\n    "recommended_upskilling": ["Docker Swarm to K8s"]\n  },\n',
    '  "learning_roadmap": {\n    "week_1": "Kubernetes fundamentals",\n    "week_2": "Deployments and Services"\n  },\n',
    '  "interview_questions": [\n    {"question": "Explain Docker networking", "category": "Technical"}\n  ],\n',
    '  "overall_recommendation_summary": "Strong candidate for backend engineering roles."\n}'
]


def test_extract_completed_sections_from_buffer():
    """Verify incremental extraction of sections from a partial JSON buffer."""
    completed = set()
    partial_buffer = (
        '{\n'
        '  "resume_analysis": {\n'
        '    "ats_score": 90,\n'
        '    "strengths": ["Python"]\n'
        '  },\n'
        '  "job_match": {\n'
        '    "match_score": 85'
    )
    new_sections = dict(extract_completed_sections_from_buffer(partial_buffer, completed))
    assert "resume_analysis" in new_sections
    assert new_sections["resume_analysis"]["ats_score"] == 90
    assert "job_match" not in new_sections  # still incomplete

    # Now add the rest of job_match
    completed.add("resume_analysis")
    full_buffer = partial_buffer + ',\n    "matching_skills": ["Python"]\n  }\n}'
    next_sections = dict(extract_completed_sections_from_buffer(full_buffer, completed))
    assert "job_match" in next_sections
    assert next_sections["job_match"]["match_score"] == 85


def test_first_section_appears_before_whole_response_finishes():
    """
    Acceptance Criterion 1: The first section appears before the whole response finishes.
    Verifies that early sections are yielded while subsequent chunks have not yet arrived.
    """
    mock_chunks = []
    for c in MOCK_STREAM_CHUNKS:
        mock_chunk = MagicMock()
        mock_chunk.text = c
        mock_chunks.append(mock_chunk)

    received_sections_order = []
    chunk_index_at_first_section = None

    def chunk_generator():
        nonlocal chunk_index_at_first_section
        for i, chunk in enumerate(mock_chunks):
            yield chunk
            if "resume_analysis" in received_sections_order and chunk_index_at_first_section is None:
                chunk_index_at_first_section = i

    mock_client = MagicMock()
    mock_client.models.generate_content_stream.return_value = chunk_generator()

    with patch("utils.gemini.get_gemini_client", return_value=mock_client):
        stream_gen = stream_json_response_sections(
            system_instruction="You are an expert placement analyst.",
            prompt="Analyze resume",
            feature="analysis"
        )

        for sec_name, sec_data in stream_gen:
            received_sections_order.append(sec_name)

        # Verify first section was received well before stream finished
        assert "resume_analysis" in received_sections_order
        assert received_sections_order[0] == "resume_analysis"
        assert chunk_index_at_first_section is not None
        assert chunk_index_at_first_section < len(mock_chunks) - 1
        assert "overall_recommendation_summary" in received_sections_order


def test_cancelling_stops_underlying_request():
    """
    Acceptance Criterion 2: Cancelling stops the underlying request.
    Verifies that when is_cancelled_fn returns True, the generator ceases reading chunks.
    """
    yield_count = 0

    def endless_chunks():
        nonlocal yield_count
        for c in MOCK_STREAM_CHUNKS:
            yield_count += 1
            mock_chunk = MagicMock()
            mock_chunk.text = c
            yield mock_chunk

    mock_client = MagicMock()
    mock_client.models.generate_content_stream.return_value = endless_chunks()

    cancelled = False

    def check_cancelled():
        return cancelled

    with patch("utils.gemini.get_gemini_client", return_value=mock_client):
        stream_gen = stream_json_response_sections(
            system_instruction="You are an expert placement analyst.",
            prompt="Analyze resume",
            is_cancelled_fn=check_cancelled,
            feature="analysis"
        )

        for sec_name, sec_data in stream_gen:
            if sec_name == "resume_analysis":
                # User clicks cancel when first section arrives
                cancelled = True

        assert cancelled is True
        # Ensure we stopped consuming chunks early
        assert yield_count < len(MOCK_STREAM_CHUNKS)


def test_errors_never_discard_content_already_shown():
    """
    Acceptance Criterion 3: Errors never discard content that was already shown.
    When a mid-stream network or provider error occurs after some sections have been yielded,
    all received sections must be preserved in the returned result.
    """
    def broken_stream():
        # First 2 chunks contain resume_analysis
        for c in MOCK_STREAM_CHUNKS[:2]:
            mock_chunk = MagicMock()
            mock_chunk.text = c
            yield mock_chunk
        # Mid-stream failure occurs
        raise RuntimeError("Mid-stream connection reset by peer")

    mock_client = MagicMock()
    mock_client.models.generate_content_stream.return_value = broken_stream()

    received_sections = []

    with patch("utils.gemini.get_gemini_client", return_value=mock_client):
        stream_gen = stream_json_response_sections(
            system_instruction="You are an expert placement analyst.",
            prompt="Analyze resume",
            feature="analysis"
        )

        events = []
        for sec_name, sec_data in stream_gen:
            events.append((sec_name, sec_data))
            if not sec_name.startswith("_"):
                received_sections.append(sec_name)

        # Crucial: Content already shown was NOT discarded!
        assert "resume_analysis" in received_sections
        event_names = [e[0] for e in events]
        assert "_stream_error" in event_names
        error_event = next(e[1] for e in events if e[0] == "_stream_error")
        assert "completed_sections" in error_event
        assert "resume_analysis" in error_event["completed_sections"]


def test_coordinator_analyze_stream_preserves_partial_on_error():
    """
    Verifies CoordinatorAgent.analyze_stream preserves sections received before an error.
    """
    coordinator = CoordinatorAgent()

    def failing_stream_gen(**kwargs):
        # Emits resume_analysis then yields _stream_error
        yield ("resume_analysis", {
            "candidate_name": "Jane Doe",
            "ats_score": 88,
            "strengths": ["Python"],
            "areas_for_improvement": ["Cloud"]
        })
        yield ("_stream_error", {
            "error": "Gemini rate limit exceeded mid-stream",
            "completed_sections": ["resume_analysis"]
        })

    with patch("agents.coordinator.stream_json_response_sections", side_effect=failing_stream_gen):
        result = coordinator.analyze_stream(
            resume_text=SAMPLE_RESUME_TEXT,
            job_description=SAMPLE_JOB_DESC,
            company_name=SAMPLE_COMPANY,
            use_fallback_on_failure=False
        )

        # resume_analysis must be preserved
        assert "resume_analysis" in result
        assert "Python" in result["resume_analysis"]["strengths"]
        assert "ats_score" in result["resume_analysis"]
        assert result.get("stream_error") is not None
        assert result.get("is_partial") is True


def test_non_streaming_fallback_when_stream_fails_initially():
    """
    Acceptance Criterion 4: Keep a non-streaming fallback.
    Verifies that if streaming fails before any section is received,
    the coordinator falls back seamlessly to non-streaming analyze().
    """
    coordinator = CoordinatorAgent()

    fallback_called = False

    def mock_analyze(resume_text, job_description, company_name, **kwargs):
        nonlocal fallback_called
        fallback_called = True
        return {
            "resume_analysis": {"ats_score": 90},
            "job_match": {"match_score": 85},
            "skill_gap": {"critical_missing_skills": []},
            "learning_roadmap": {},
            "interview_questions": [],
            "overall_recommendation_summary": "Fallback summary"
        }

    coordinator.analyze = mock_analyze

    # Streaming fails at startup with 0 sections
    def fail_immediately(**kwargs):
        yield ("_stream_error", {"error": "Streaming unsupported", "completed_sections": []})

    with patch("agents.coordinator.stream_json_response_sections", side_effect=fail_immediately):
        result = coordinator.analyze_stream(
            resume_text=SAMPLE_RESUME_TEXT,
            job_description=SAMPLE_JOB_DESC,
            company_name=SAMPLE_COMPANY,
            use_fallback_on_failure=True
        )

        assert fallback_called is True
        assert result["overall_recommendation_summary"] == "Fallback summary"
