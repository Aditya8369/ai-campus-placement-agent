"""
Speech and delivery analysis service for interview responses.
Evaluates filler words, speech pauses/hesitations, and excessive repetitions
from transcript text without requiring raw audio uploads.
"""

import re
from typing import Dict, Any, List, Optional

COMMON_FILLER_WORDS = [
    "um", "uh", "er", "ah", "like", "you know", "basically",
    "actually", "literally", "sort of", "kind of", "i mean", "right"
]

def analyze_speech_metrics(
    transcript: str,
    pauses: List[Dict[str, Any]] = None,
    duration_seconds: Optional[float] = None
) -> Dict[str, Any]:
    """
    Analyzes filler words, pauses/hesitations, speaking pace (WPM), and repeated phrases
    from transcript text without requiring raw audio uploads (#758).
    Works entirely client/transcript-side without storing or uploading raw audio.
    """
    if not transcript or not isinstance(transcript, str):
        return {
            "success": False,
            "error": "Transcript text is required for speech analysis."
        }

    cleaned_text = transcript.strip()
    words = re.findall(r"\b[A-Za-z'-]+\b", cleaned_text.lower())
    total_words = len(words)

    if total_words == 0:
        return {
            "success": True,
            "total_words": 0,
            "duration_seconds": duration_seconds or 0.0,
            "words_per_minute": 0.0,
            "filler_words": {},
            "filler_count": 0,
            "filler_percentage": 0.0,
            "pauses": {
                "detected_count": 0,
                "unusually_long_pauses": 0,
                "notes": "No words or pauses detected."
            },
            "repetitions": [],
            "delivery_score": 100,
            "feedback": "No speech detected to evaluate.",
            "simple_tips": ["Speak clearly into your microphone to receive delivery feedback."],
            "privacy_notice": "Speech metrics are calculated without storing or uploading raw audio files."
        }

    # 1. Detect filler words
    filler_counts = {}
    total_fillers = 0

    lower_transcript = f" {cleaned_text.lower()} "
    for filler in COMMON_FILLER_WORDS:
        # Check multi-word or single-word fillers with word boundary
        pattern = r"\b" + re.escape(filler) + r"\b"
        matches = len(re.findall(pattern, lower_transcript))
        if matches > 0:
            filler_counts[filler] = matches
            total_fillers += matches

    filler_percentage = round((total_fillers / max(total_words, 1)) * 100, 1)

    # 2. Pause and hesitation measurement
    # We support explicit pause metadata (e.g. from speech recognition with duration)
    # as well as transcript markers like '...', '[pause]', '(silence)', '--'
    detected_pauses_count = 0
    unusually_long_pauses = 0

    if pauses and isinstance(pauses, list):
        for p in pauses:
            detected_pauses_count += 1
            duration = p.get("duration_seconds", 0)
            if duration >= 2.5:
                unusually_long_pauses += 1
    else:
        # Transcript-based pause/hesitation indicators
        pause_markers = re.findall(r"(\.{3,}|\[pause\]|\(pause\)|\(silence\)|\s-\s|--)", cleaned_text, flags=re.IGNORECASE)
        detected_pauses_count = len(pause_markers)
        # In text transcripts, ellipsis or explicit pause markers signify hesitation
        unusually_long_pauses = sum(1 for m in pause_markers if "silence" in m.lower() or len(m) >= 4)

    # 3. Excessive word repetitions (e.g., "I I", "the the", "we we went")
    repetitions = []
    for i in range(len(words) - 1):
        if words[i] == words[i+1]:
            rep_phrase = f"{words[i]} {words[i]}"
            if rep_phrase not in repetitions:
                repetitions.append(rep_phrase)

    # 4. Pace calculation (WPM)
    wpm = None
    if duration_seconds is not None and duration_seconds > 0.5:
        minutes = max(duration_seconds / 60.0, 0.05)
        wpm = round(total_words / minutes, 1)

    # 5. Delivery score calculation (0 - 100)
    # Deductions:
    # - Filler % above 3%: 5 pts per 1%
    # - Unusually long pauses: 4 pts each
    # - Repetitions: 3 pts each
    deductions = 0
    if filler_percentage > 3.0:
        deductions += int((filler_percentage - 3.0) * 5)
    deductions += unusually_long_pauses * 4
    deductions += len(repetitions) * 3

    delivery_score = max(20, min(100, 100 - deductions))

    # Formulate feedback
    feedback_points = []
    if filler_percentage <= 3.0 and total_fillers <= 2:
        feedback_points.append("Excellent clarity and minimal filler words.")
    else:
        top_fillers = sorted(filler_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        top_str = ", ".join([f"'{f}' ({c}x)" for f, c in top_fillers])
        feedback_points.append(f"Consider reducing filler words: {top_str}.")

    if unusually_long_pauses > 0:
        feedback_points.append(f"Detected {unusually_long_pauses} noticeably long pause(s) or hesitation points.")

    if repetitions:
        rep_str = ", ".join([f"'{r}'" for r in repetitions[:3]])
        feedback_points.append(f"Noticeable immediate word repetitions: {rep_str}.")

    # 6. Simple coaching tips (#758)
    simple_tips = []
    if wpm is not None:
        if wpm > 165:
            simple_tips.append(f"Pace Tip: Speaking a bit fast ({wpm} WPM). Try slowing down slightly and taking calm breaths between ideas.")
        elif wpm < 110 and total_words >= 5:
            simple_tips.append(f"Pace Tip: Speaking a bit slowly ({wpm} WPM). Try picking up the tempo to keep the interviewer engaged.")
        else:
            simple_tips.append(f"Pace Tip: Great speaking pace ({wpm} WPM). Your delivery tempo is balanced and easy to follow.")
    
    if total_fillers >= 3:
        simple_tips.append(f"Filler Tip: Frequent filler words detected ({total_fillers}x). Pause silently instead of using fillers while formulating thoughts.")
    elif total_fillers > 0:
        simple_tips.append(f"Filler Tip: Low filler word count ({total_fillers}x). Great verbal control.")
    else:
        simple_tips.append("Filler Tip: Clean articulation with zero filler words.")

    if unusually_long_pauses >= 2:
        simple_tips.append(f"Pause Tip: Detected {unusually_long_pauses} noticeably long pauses. Use transitional phrases like 'Let me break this down' to structure ideas without awkward silence.")
    elif unusually_long_pauses == 1:
        simple_tips.append("Pause Tip: Brief hesitation detected. Remember brief pauses to gather thoughts are completely normal.")
    else:
        simple_tips.append("Pause Tip: Smooth speech continuity.")

    return {
        "success": True,
        "total_words": total_words,
        "duration_seconds": duration_seconds,
        "words_per_minute": wpm if wpm is not None else 0.0,
        "filler_words": filler_counts,
        "filler_count": total_fillers,
        "filler_percentage": filler_percentage,
        "pauses": {
            "detected_count": detected_pauses_count,
            "unusually_long_pauses": unusually_long_pauses,
            "notes": "Hesitations and pauses detected purely from speech transcripts or markers."
        },
        "repetitions": repetitions,
        "delivery_score": delivery_score,
        "feedback": " ".join(feedback_points),
        "simple_tips": simple_tips,
        "privacy_notice": "Speech metrics are calculated without storing or uploading raw audio files."
    }
