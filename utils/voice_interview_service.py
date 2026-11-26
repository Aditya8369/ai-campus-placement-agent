"""
Voice Recording Mock Interview Service (#510)

Provides backend support and utilities for voice-driven mock interviews:
- Audio session management and speaking duration tracking
- Speech-to-text integration fallback (browser SpeechRecognition + server transcript ingestion)
- Client-side editable transcripts allowing students to inspect & adjust text before AI evaluation
- Audio metadata validation (duration limits, audio formats: webm, wav, mp3, ogg)
- Delivery of speaking speed (words per minute), filler sound estimation, and duration analytics
"""

import os
import json
import sqlite3
import datetime
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "instance", "placement_agent.db")


def _get_db_connection() -> sqlite3.Connection:
    db_path = DB_PATH
    try:
        from flask import current_app, has_app_context
        if has_app_context() and current_app.config.get("DATABASE"):
            db_path = current_app.config["DATABASE"]
    except Exception:
        pass
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_voice_interviews_table(conn: Optional[sqlite3.Connection] = None):
    """Initializes the database schema for voice-recorded interview submissions."""
    should_close = False
    if conn is None:
        conn = _get_db_connection()
        should_close = True
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS voice_interview_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    question_text TEXT NOT NULL,
                    duration_seconds REAL DEFAULT 0.0,
                    audio_format TEXT DEFAULT 'webm',
                    raw_transcript TEXT NOT NULL,
                    edited_transcript TEXT NOT NULL,
                    words_per_minute REAL DEFAULT 0.0,
                    filler_words_detected TEXT DEFAULT '[]',
                    confidence_score REAL DEFAULT 1.0,
                    status TEXT DEFAULT 'transcribed', -- transcribed, submitted, evaluated
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vis_user_sess ON voice_interview_submissions(user_id, session_id)")
    finally:
        if should_close:
            conn.close()


init_voice_interviews_table()


class VoiceInterviewService:
    """Manages voice audio recording metadata, transcript validation, and pacing metrics."""

    COMMON_FILLERS = ["um", "uh", "like", "you know", "actually", "basically", "literally", "sort of", "kind of"]

    @classmethod
    def process_voice_submission(
        cls,
        user_id: str,
        session_id: str,
        question_id: str,
        question_text: str,
        duration_seconds: float,
        raw_transcript: str,
        edited_transcript: Optional[str] = None,
        audio_format: str = "webm"
    ) -> Dict[str, Any]:
        """
        Processes a voice-recorded answer submission, computing pace and filler diagnostics.
        """
        final_text = (edited_transcript if edited_transcript is not None else raw_transcript).strip()
        if not final_text:
            raise ValueError("Transcript cannot be empty. Please speak clearly or type your answer.")

        if duration_seconds < 0.5:
            # Safe minimum threshold or fallback duration based on word count
            words_count = len(final_text.split())
            duration_seconds = max(1.0, round(words_count / 2.2, 1))

        # Pace calculation (Words Per Minute)
        words = final_text.split()
        word_count = len(words)
        minutes = max(duration_seconds / 60.0, 0.05)
        wpm = round(word_count / minutes, 1)

        # Detect filler words
        text_lower = final_text.lower()
        detected_fillers = []
        for filler in cls.COMMON_FILLERS:
            count = text_lower.count(filler)
            if count > 0:
                detected_fillers.append({"word": filler, "count": count})

        # Voice delivery assessment
        delivery_quality = "Optimal"
        if wpm < 100:
            delivery_quality = "Slow - Consider picking up the pace"
        elif wpm > 175:
            delivery_quality = "Fast - Consider slowing down for clarity"

        conn = _get_db_connection()
        try:
            init_voice_interviews_table(conn)
            with conn:
                cursor = conn.execute("""
                    INSERT INTO voice_interview_submissions (
                        user_id, session_id, question_id, question_text,
                        duration_seconds, audio_format, raw_transcript,
                        edited_transcript, words_per_minute, filler_words_detected,
                        status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'submitted', CURRENT_TIMESTAMP)
                """, (
                    user_id, session_id, question_id, question_text,
                    duration_seconds, audio_format, raw_transcript,
                    final_text, wpm, json.dumps(detected_fillers)
                ))
                record_id = cursor.lastrowid

            # Calculate speech metrics and actionable coaching tips (#758)
            try:
                from utils.speech_analysis_service import analyze_speech_metrics
                speech_analysis = analyze_speech_metrics(final_text, duration_seconds=duration_seconds)
                simple_tips = speech_analysis.get("simple_tips", [])
                pauses_data = speech_analysis.get("pauses", {})
            except Exception:
                simple_tips = [
                    f"Pace Tip: Speaking pace is {wpm} WPM ({delivery_quality}).",
                    f"Filler Tip: {len(detected_fillers)} filler word pattern(s) detected."
                ]
                pauses_data = {}

            return {
                "id": record_id,
                "session_id": session_id,
                "question_id": question_id,
                "word_count": word_count,
                "duration_seconds": duration_seconds,
                "words_per_minute": wpm,
                "delivery_quality": delivery_quality,
                "filler_words": detected_fillers,
                "final_transcript": final_text,
                "pauses": pauses_data,
                "simple_tips": simple_tips
            }
        finally:
            conn.close()

    @classmethod
    def get_session_voice_records(cls, user_id: str, session_id: str) -> List[Dict[str, Any]]:
        """Retrieves all voice submissions for an ongoing or past interview session."""
        conn = _get_db_connection()
        try:
            rows = conn.execute("""
                SELECT * FROM voice_interview_submissions
                WHERE user_id = ? AND session_id = ?
                ORDER BY created_at ASC
            """, (user_id, session_id)).fetchall()
            return [cls._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    @classmethod
    def get_delivery_summary(cls, user_id: str, session_id: str) -> Dict[str, Any]:
        """Calculates aggregated speaking analytics for an interview session."""
        records = cls.get_session_voice_records(user_id, session_id)
        if not records:
            return {
                "total_voice_answers": 0,
                "average_wpm": 0.0,
                "total_speaking_time_seconds": 0.0,
                "total_filler_words": 0
            }

        total_time = sum(r["duration_seconds"] for r in records)
        total_wpm = sum(r["words_per_minute"] for r in records)
        avg_wpm = round(total_wpm / len(records), 1)

        total_fillers = sum(
            sum(f["count"] for f in r.get("filler_words_detected", []))
            for r in records
        )

        return {
            "total_voice_answers": len(records),
            "average_wpm": avg_wpm,
            "total_speaking_time_seconds": round(total_time, 1),
            "total_filler_words": total_fillers
        }

    @classmethod
    def _row_to_dict(cls, row: sqlite3.Row) -> Dict[str, Any]:
        fillers = []
        if row["filler_words_detected"]:
            try:
                fillers = json.loads(row["filler_words_detected"])
            except Exception:
                fillers = []

        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "session_id": row["session_id"],
            "question_id": row["question_id"],
            "question_text": row["question_text"],
            "duration_seconds": row["duration_seconds"],
            "audio_format": row["audio_format"],
            "raw_transcript": row["raw_transcript"],
            "edited_transcript": row["edited_transcript"],
            "words_per_minute": row["words_per_minute"],
            "filler_words_detected": fillers,
            "status": row["status"],
            "created_at": str(row["created_at"])
        }
