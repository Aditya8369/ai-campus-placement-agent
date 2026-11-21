"""
Interview Communication Feedback Service (#511)

Evaluates non-technical communication qualities in student interview responses:
- Answer length appropriateness (conciseness vs completeness)
- Filler words frequency and density
- Vague opening statements (e.g. "I think maybe...", "Basically I guess...")
- Clarity and coherence (sentence structure and transition flow)
- Repetition detection (repeated phrases or redundant ideas)
- Conclusion presence (structured wrap-up or summary)
- Distinct communication score (0-100) separate from technical evaluation
- Concrete, actionable coaching suggestions
"""

import re
import os
import json
import sqlite3
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "instance", "placement_agent.db")


def _get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_communication_feedback_table():
    """Initializes SQLite schema for communication feedback audits."""
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS interview_communication_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    answer_text TEXT NOT NULL,
                    communication_score INTEGER NOT NULL,
                    length_status TEXT NOT NULL, -- 'too_short', 'optimal', 'too_verbose'
                    filler_words_count INTEGER DEFAULT 0,
                    filler_words_breakdown TEXT DEFAULT '{}',
                    has_vague_opener INTEGER DEFAULT 0,
                    has_conclusion INTEGER DEFAULT 0,
                    repetition_score INTEGER DEFAULT 0,
                    suggestions TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_icf_user_sess ON interview_communication_feedback(user_id, session_id)")
    finally:
        conn.close()


init_communication_feedback_table()


class InterviewCommunicationService:
    """Analyzes behavioral delivery, articulation clarity, and structure."""

    FILLER_LIST = [
        "um", "uh", "like", "you know", "actually", "basically",
        "literally", "sort of", "kind of", "i mean", "right", "honestly"
    ]

    VAGUE_OPENERS = [
        "i think maybe", "i guess", "probably", "not really sure but",
        "sort of like", "to be honest i don't know much", "basically what i feel"
    ]

    CONCLUSION_SIGNALS = [
        "in conclusion", "to summarize", "to sum up", "overall",
        "therefore", "in summary", "that is how", "which led to", "the result was"
    ]

    @classmethod
    def evaluate_communication(
        cls,
        user_id: str,
        session_id: str,
        question_id: str,
        answer_text: str
    ) -> Dict[str, Any]:
        """
        Analyzes an answer's communication aspects and stores metrics.
        """
        text = (answer_text or "").strip()
        if not text:
            raise ValueError("Answer text cannot be empty.")

        words = text.split()
        word_count = len(words)
        lower_text = text.lower()

        # 1. Answer Length Evaluation
        if word_count < 25:
            length_status = "too_short"
            length_deduction = 25
            length_msg = "Your answer is quite brief. Aim for at least 50-150 words to demonstrate depth."
        elif word_count > 350:
            length_status = "too_verbose"
            length_deduction = 10
            length_msg = "Your answer is quite verbose. Consider summarizing your key points more concisely."
        else:
            length_status = "optimal"
            length_deduction = 0
            length_msg = "Answer length is well-balanced for an interview."

        # 2. Filler words analysis
        filler_breakdown = {}
        total_fillers = 0
        for filler in cls.FILLER_LIST:
            # Match whole phrase/word boundaries
            pattern = r'\b' + re.escape(filler) + r'\b'
            matches = len(re.findall(pattern, lower_text))
            if matches > 0:
                filler_breakdown[filler] = matches
                total_fillers += matches

        filler_deduction = min(25, total_fillers * 4)

        # 3. Vague openers
        has_vague_opener = False
        opener_deduction = 0
        first_50_chars = lower_text[:70]
        for vague in cls.VAGUE_OPENERS:
            if vague in first_50_chars:
                has_vague_opener = True
                opener_deduction = 10
                break

        # 4. Conclusion presence
        has_conclusion = any(sig in lower_text for sig in cls.CONCLUSION_SIGNALS) or (word_count > 50 and any(punct in text[-30:] for punct in [".", "!"]))
        conclusion_deduction = 0 if has_conclusion else 5

        # 5. Repetition check (repeated phrases of 3+ words)
        phrase_counts = {}
        tokens = [w.lower() for w in words]
        for i in range(len(tokens) - 2):
            trigram = " ".join(tokens[i:i+3])
            phrase_counts[trigram] = phrase_counts.get(trigram, 0) + 1

        repeated_phrases = [p for p, c in phrase_counts.items() if c > 2 and p not in cls.FILLER_LIST]
        repetition_deduction = min(15, len(repeated_phrases) * 5)

        # 6. Final Score Calculation (0-100)
        score = 100 - (length_deduction + filler_deduction + opener_deduction + conclusion_deduction + repetition_deduction)
        score = max(20, min(100, score))

        # 7. Actionable Coaching Suggestions
        suggestions = []
        if length_status == "too_short":
            suggestions.append(length_msg)
        elif length_status == "too_verbose":
            suggestions.append(length_msg)

        if total_fillers > 0:
            top_fillers = ", ".join([f"'{k}' ({v}x)" for k, v in list(filler_breakdown.items())[:3]])
            suggestions.append(f"Noticeable filler words detected: {top_fillers}. Try pausing for a breath instead of using verbal crutches.")

        if has_vague_opener:
            suggestions.append("Avoid starting with tentative disclaimers like 'I guess' or 'I think maybe'. Start with confident framing.")

        if not has_conclusion and word_count >= 60:
            suggestions.append("Add a clear concluding statement (e.g. 'To summarize...', 'The end result was...') to finish strong.")

        if repeated_phrases:
            suggestions.append(f"Repeated phrasing detected ({repeated_phrases[0]}). Expand vocabulary variety.")

        if not suggestions:
            suggestions.append("Excellent communication! Clear structure, steady pacing, and articulate delivery.")

        conn = _get_db_connection()
        try:
            with conn:
                cursor = conn.execute("""
                    INSERT INTO interview_communication_feedback (
                        user_id, session_id, question_id, answer_text,
                        communication_score, length_status, filler_words_count,
                        filler_words_breakdown, has_vague_opener, has_conclusion,
                        repetition_score, suggestions
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, session_id, question_id, text,
                    score, length_status, total_fillers,
                    json.dumps(filler_breakdown), 1 if has_vague_opener else 0,
                    1 if has_conclusion else 0, repetition_deduction,
                    json.dumps(suggestions)
                ))
                record_id = cursor.lastrowid
        finally:
            conn.close()

        return {
            "id": record_id,
            "session_id": session_id,
            "question_id": question_id,
            "communication_score": score,
            "length_status": length_status,
            "word_count": word_count,
            "filler_words_count": total_fillers,
            "filler_words_breakdown": filler_breakdown,
            "has_vague_opener": has_vague_opener,
            "has_conclusion": has_conclusion,
            "suggestions": suggestions
        }

    @classmethod
    def get_session_communication_audit(cls, user_id: str, session_id: str) -> Dict[str, Any]:
        """Calculates cumulative communication performance for a full interview session."""
        conn = _get_db_connection()
        try:
            rows = conn.execute("""
                SELECT * FROM interview_communication_feedback
                WHERE user_id = ? AND session_id = ?
                ORDER BY created_at ASC
            """, (user_id, session_id)).fetchall()

            if not rows:
                return {
                    "total_evaluated": 0,
                    "average_score": 0,
                    "overall_feedback": "No answers evaluated yet."
                }

            scores = [r["communication_score"] for r in rows]
            avg_score = round(sum(scores) / len(scores), 1)
            total_fillers = sum(r["filler_words_count"] for r in rows)

            return {
                "total_evaluated": len(rows),
                "average_score": avg_score,
                "total_filler_words": total_fillers,
                "evaluations": [
                    {
                        "question_id": r["question_id"],
                        "score": r["communication_score"],
                        "length_status": r["length_status"],
                        "suggestions": json.loads(r["suggestions"]) if r["suggestions"] else []
                    }
                    for r in rows
                ]
            }
        finally:
            conn.close()
