"""
Mock Interview Answer Retry & Attempt Comparison Service (#467).

Enables candidates to retry mock interview answers (up to 2 retries per question):
- Stores each attempt with its scores, candidate answer, feedback, and timestamp.
- Computes a side-by-side comparison in code (zero extra AI calls) comparing
  the previous attempt with the new attempt.
- Tracks score deltas (diff) and status (improved, declined, unchanged) for every criterion:
  1. Technical Accuracy
  2. Communication Clarity
  3. Confidence Indicator
  4. Verbal Articulation
  5. STAR Story Score (for behavioral questions)
- Identifies addressed feedback points (score gains, reduced filler words, eliminated fillers,
  strengthened STAR components, expanded length/depth).
- Ensures latest (final) attempt is used for session summary calculations while preserving
  all previous attempts for transcript exports.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

MAX_RETRIES_PER_QUESTION = 2

CRITERIA_METADATA = [
    ("technical_accuracy", "Technical Accuracy"),
    ("communication_score", "Communication Clarity"),
    ("confidence_score", "Confidence Indicator"),
    ("verbal_clarity_score", "Verbal Articulation"),
]


def compare_answer_attempts(
    prev_eval: Dict[str, Any],
    current_eval: Dict[str, Any],
    prev_answer: str = "",
    current_answer: str = "",
) -> Dict[str, Any]:
    """
    Computes a deterministic side-by-side comparison between two answer attempts in code.
    No extra AI call is made.

    Args:
        prev_eval: Evaluation dictionary of the preceding attempt.
        current_eval: Evaluation dictionary of the new attempt.
        prev_answer: Candidate text of the preceding attempt.
        current_answer: Candidate text of the new attempt.

    Returns:
        Structured comparison dictionary with per-criterion differences, overall delta,
        addressed feedback points, and a human-readable verdict.
    """
    if not isinstance(prev_eval, dict):
        prev_eval = {}
    if not isinstance(current_eval, dict):
        current_eval = {}

    criteria_comparison: Dict[str, Dict[str, Any]] = {}
    prev_scores_sum = 0
    curr_scores_sum = 0
    total_criteria_count = 0

    # 1. Compare standard evaluation criteria
    for crit_key, crit_label in CRITERIA_METADATA:
        prev_score = int(prev_eval.get(crit_key) if prev_eval.get(crit_key) is not None else 50)
        curr_score = int(current_eval.get(crit_key) if current_eval.get(crit_key) is not None else 50)
        diff = curr_score - prev_score

        if diff > 0:
            status = "improved"
        elif diff < 0:
            status = "declined"
        else:
            status = "unchanged"

        criteria_comparison[crit_key] = {
            "key": crit_key,
            "label": crit_label,
            "prev_score": prev_score,
            "current_score": curr_score,
            "diff": diff,
            "status": status,
        }

        prev_scores_sum += prev_score
        curr_scores_sum += curr_score
        total_criteria_count += 1

    # Optional STAR score comparison if present in either attempt
    prev_star = prev_eval.get("star_score") or (prev_eval.get("star_evaluation") or {}).get("star_score")
    curr_star = current_eval.get("star_score") or (current_eval.get("star_evaluation") or {}).get("star_score")
    if prev_star is not None or curr_star is not None:
        p_star = int(prev_star or 50)
        c_star = int(curr_star or 50)
        star_diff = c_star - p_star
        if star_diff > 0:
            s_status = "improved"
        elif star_diff < 0:
            s_status = "declined"
        else:
            s_status = "unchanged"

        criteria_comparison["star_score"] = {
            "key": "star_score",
            "label": "STAR Story Structure",
            "prev_score": p_star,
            "current_score": c_star,
            "diff": star_diff,
            "status": s_status,
        }
        prev_scores_sum += p_star
        curr_scores_sum += c_star
        total_criteria_count += 1

    # 2. Overall score change
    prev_overall = int(round(prev_scores_sum / max(1, total_criteria_count)))
    curr_overall = int(round(curr_scores_sum / max(1, total_criteria_count)))
    overall_diff = curr_overall - prev_overall
    if overall_diff > 0:
        overall_status = "improved"
    elif overall_diff < 0:
        overall_status = "declined"
    else:
        overall_status = "unchanged"

    overall_block = {
        "prev_score": prev_overall,
        "current_score": curr_overall,
        "diff": overall_diff,
        "status": overall_status,
    }

    # 3. Detect addressed feedback points
    addressed_points: List[str] = []
    unaddressed_points: List[str] = []

    # Criteria improvements
    if criteria_comparison["technical_accuracy"]["diff"] > 0:
        d = criteria_comparison["technical_accuracy"]["diff"]
        addressed_points.append(f"Strengthened Technical Accuracy (+{d} pts: {criteria_comparison['technical_accuracy']['prev_score']}% \u2192 {criteria_comparison['technical_accuracy']['current_score']}%).")
    elif criteria_comparison["technical_accuracy"]["diff"] < 0:
        d = abs(criteria_comparison["technical_accuracy"]["diff"])
        unaddressed_points.append(f"Technical Accuracy dropped by -{d} pts; ensure core domain concepts are clearly addressed.")

    if criteria_comparison["communication_score"]["diff"] > 0:
        d = criteria_comparison["communication_score"]["diff"]
        addressed_points.append(f"Improved Communication Clarity (+{d} pts: {criteria_comparison['communication_score']['prev_score']}% \u2192 {criteria_comparison['communication_score']['current_score']}%).")

    if criteria_comparison["confidence_score"]["diff"] > 0:
        d = criteria_comparison["confidence_score"]["diff"]
        addressed_points.append(f"Boosted Confidence Indicator (+{d} pts: {criteria_comparison['confidence_score']['prev_score']}% \u2192 {criteria_comparison['confidence_score']['current_score']}%).")

    if criteria_comparison["verbal_clarity_score"]["diff"] > 0:
        d = criteria_comparison["verbal_clarity_score"]["diff"]
        addressed_points.append(f"Enhanced Verbal Articulation (+{d} pts: {criteria_comparison['verbal_clarity_score']['prev_score']}% \u2192 {criteria_comparison['verbal_clarity_score']['current_score']}%).")

    # Filler words reduction
    prev_fillers = prev_eval.get("filler_words_detected") or []
    curr_fillers = current_eval.get("filler_words_detected") or []
    prev_fc = prev_eval.get("filler_word_count", len(prev_fillers))
    curr_fc = current_eval.get("filler_word_count", len(curr_fillers))

    if isinstance(prev_fc, int) and isinstance(curr_fc, int):
        if curr_fc < prev_fc:
            addressed_points.append(f"Reduced filler words from {prev_fc} to {curr_fc}.")
        elif curr_fc > prev_fc:
            unaddressed_points.append(f"Filler word count increased ({prev_fc} \u2192 {curr_fc}); speak with deliberate pauses.")

    if prev_fillers and isinstance(prev_fillers, list) and isinstance(curr_fillers, list):
        eliminated = set(str(f).lower() for f in prev_fillers) - set(str(f).lower() for f in curr_fillers)
        if eliminated:
            addressed_points.append(f"Eliminated filler words: {', '.join(sorted(eliminated))}.")

    # Behavioral STAR structure improvements
    prev_star_block = prev_eval.get("star_analysis") or {}
    curr_star_block = current_eval.get("star_analysis") or {}
    if isinstance(prev_star_block, dict) and isinstance(curr_star_block, dict):
        for part in ["situation", "task", "action", "result"]:
            p_stat = str(prev_star_block.get(part, "")).lower()
            c_stat = str(curr_star_block.get(part, "")).lower()
            if p_stat in ("missing", "weak") and c_stat == "present":
                addressed_points.append(f"Covered STAR {part.capitalize()} component (was {p_stat}).")

    # Length / depth expansion if previous attempt was too brief
    prev_words = len(prev_answer.split()) if prev_answer else 0
    curr_words = len(current_answer.split()) if current_answer else 0
    if prev_words < 25 and curr_words >= 35:
        addressed_points.append(f"Expanded response depth ({prev_words} words \u2192 {curr_words} words).")

    # 4. Summary verdict
    if overall_status == "improved":
        verdict = f"Great improvement! Overall score increased by +{overall_diff} points."
    elif overall_status == "declined":
        verdict = f"Performance declined by {overall_diff} points compared to the earlier attempt."
    else:
        verdict = "Overall score was unchanged. Scores matched the earlier attempt across evaluated criteria."

    return {
        "overall": overall_block,
        "criteria": criteria_comparison,
        "addressed_points": addressed_points,
        "unaddressed_points": unaddressed_points,
        "verdict": verdict,
    }


def process_retry_answer(
    past_answer_record: Dict[str, Any],
    candidate_response: str,
    evaluation_results: Dict[str, Any],
    additional_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Dict[str, Any], Optional[str]]:
    """
    Validates and attaches a retry attempt to an existing question answer record.

    Enforces the 2-retries limit per question (maximum 3 total attempts).
    Returns (success, updated_record, error_message).
    """
    if not isinstance(past_answer_record, dict):
        return False, {}, "Existing answer record not found."

    # Retrieve existing attempts
    existing_attempts: List[Dict[str, Any]] = list(past_answer_record.get("attempts", []))

    # Backward compatibility: if record didn't have `attempts` yet, populate from base
    if not existing_attempts:
        existing_attempts = [{
            "attempt_number": 1,
            "answer": past_answer_record.get("answer", ""),
            "evaluation": past_answer_record.get("evaluation", {}),
            "time_display": past_answer_record.get("time_display"),
            "time_taken_seconds": past_answer_record.get("time_taken_seconds"),
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }]

    # Check retry count: retry_count = len(existing_attempts) - 1
    current_retry_count = len(existing_attempts) - 1
    if current_retry_count >= MAX_RETRIES_PER_QUESTION:
        return (
            False,
            past_answer_record,
            f"Maximum retry limit reached for this question (limit: {MAX_RETRIES_PER_QUESTION} retries).",
        )

    new_attempt_number = len(existing_attempts) + 1
    new_retry_count = current_retry_count + 1
    retries_left = MAX_RETRIES_PER_QUESTION - new_retry_count

    # Compare new evaluation against the most recent preceding attempt
    prev_attempt = existing_attempts[-1]
    comparison = compare_answer_attempts(
        prev_eval=prev_attempt.get("evaluation", {}),
        current_eval=evaluation_results,
        prev_answer=prev_attempt.get("answer", ""),
        current_answer=candidate_response,
    )

    new_attempt_entry = {
        "attempt_number": new_attempt_number,
        "answer": candidate_response,
        "evaluation": evaluation_results,
        "comparison": comparison,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    if additional_metadata:
        for k, v in additional_metadata.items():
            if k not in new_attempt_entry:
                new_attempt_entry[k] = v

    existing_attempts.append(new_attempt_entry)

    # Build updated response record (latest attempt as top-level fields)
    updated_record = dict(past_answer_record)
    updated_record["answer"] = candidate_response
    updated_record["evaluation"] = evaluation_results
    updated_record["attempt_number"] = new_attempt_number
    updated_record["retry_count"] = new_retry_count
    updated_record["retries_left"] = retries_left
    updated_record["can_retry"] = retries_left > 0
    updated_record["comparison"] = comparison
    updated_record["attempts"] = existing_attempts

    if additional_metadata:
        for k, v in additional_metadata.items():
            updated_record[k] = v

    return True, updated_record, None


def initialize_initial_attempt_record(
    question_index: int,
    target_question: Dict[str, Any],
    candidate_response: str,
    evaluation_results: Dict[str, Any],
    additional_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Constructs the initial answer record (attempt #1) with full attempts container.
    """
    initial_attempt = {
        "attempt_number": 1,
        "answer": candidate_response,
        "evaluation": evaluation_results,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    if additional_metadata:
        for k, v in additional_metadata.items():
            if k not in initial_attempt:
                initial_attempt[k] = v

    q_type = target_question.get("type", "Technical")
    is_behav = target_question.get("is_behavioral", False)

    record = {
        "question_index": question_index,
        "type": q_type,
        "question": target_question.get("question", ""),
        "is_behavioral": is_behav,
        "answer": candidate_response,
        "evaluation": evaluation_results,
        "attempt_number": 1,
        "retry_count": 0,
        "retries_left": MAX_RETRIES_PER_QUESTION,
        "can_retry": True,
        "comparison": None,
        "attempts": [initial_attempt],
    }
    if additional_metadata:
        for k, v in additional_metadata.items():
            record[k] = v

    return record
