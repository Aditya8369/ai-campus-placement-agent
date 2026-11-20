"""
Timed Aptitude Practice & Diagnostic Service (#426)
===================================================
Provides timed aptitude assessments across Quantitative, Logical Reasoning,
and Verbal Ability categories for campus placement drives.

Features:
1. Curated original question bank loaded from data/aptitude_questions.json.
2. Timed test generator with client sanitization (answers/explanations stripped).
3. Accurate scoring, topic-wise diagnostic breakdowns, and explanation generation.
4. Detection of weak aptitude topics (<60% accuracy) for dashboard display.
5. Integration with SQLite persistence and per-student attempt tracking.
"""

import os
import json
import uuid
import random
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Constants
DEFAULT_TIME_LIMIT_SECONDS = 600  # 10 minutes default
DEFAULT_TEST_QUESTIONS = 10
WEAK_TOPIC_THRESHOLD_PCT = 60.0

VALID_CATEGORIES = {
    "all": "Comprehensive Drive Test (All Categories)",
    "quantitative": "Quantitative Aptitude",
    "logical_reasoning": "Logical Reasoning",
    "verbal_ability": "Verbal Ability"
}

QUESTIONS_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "aptitude_questions.json"
)

# In-memory cached questions
_CACHED_QUESTIONS: Optional[List[Dict[str, Any]]] = None


def load_aptitude_questions(force_reload: bool = False) -> List[Dict[str, Any]]:
    """
    Loads curated original aptitude questions from data/aptitude_questions.json.
    Returns list of question dictionaries with fallback defaults if the file cannot be accessed.
    """
    global _CACHED_QUESTIONS
    if _CACHED_QUESTIONS is not None and not force_reload:
        return _CACHED_QUESTIONS

    if os.path.exists(QUESTIONS_FILE_PATH):
        try:
            with open(QUESTIONS_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    _CACHED_QUESTIONS = data
                    return _CACHED_QUESTIONS
        except Exception as e:
            logger.error(f"Error loading aptitude questions from {QUESTIONS_FILE_PATH}: {e}")

    # Minimal fallback in case file is temporarily missing
    _CACHED_QUESTIONS = [
        {
            "id": "quant_fallback_01",
            "category": "quantitative",
            "category_label": "Quantitative Aptitude",
            "topic": "Time and Work",
            "difficulty": "medium",
            "question": "A can complete a task in 10 days and B in 15 days. How many days will they take working together?",
            "options": ["5 days", "6 days", "7 days", "8 days"],
            "answer": "6 days",
            "explanation": "Combined 1-day work = 1/10 + 1/15 = 5/30 = 1/6. Therefore, together they take 6 days."
        },
        {
            "id": "logical_fallback_01",
            "category": "logical_reasoning",
            "category_label": "Logical Reasoning",
            "topic": "Blood Relations",
            "difficulty": "easy",
            "question": "A is B's brother. C is B's mother. How is C related to A?",
            "options": ["Mother", "Aunt", "Sister", "Grandmother"],
            "answer": "Mother",
            "explanation": "Since A and B are siblings and C is B's mother, C is also A's mother."
        },
        {
            "id": "verbal_fallback_01",
            "category": "verbal_ability",
            "category_label": "Verbal Ability",
            "topic": "Synonyms",
            "difficulty": "easy",
            "question": "Choose the word most nearly synonymous with 'TRANSIENT':",
            "options": ["Permanent", "Ephemeral", "Enduring", "Perpetual"],
            "answer": "Ephemeral",
            "explanation": "'Transient' and 'Ephemeral' both mean lasting for a very short time."
        }
    ]
    return _CACHED_QUESTIONS


def get_question_by_id(question_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a single aptitude question by its ID."""
    all_q = load_aptitude_questions()
    for q in all_q:
        if q.get("id") == question_id:
            return q
    return None


def get_questions_by_category(category: str) -> List[Dict[str, Any]]:
    """Filters questions by category ('quantitative', 'logical_reasoning', 'verbal_ability')."""
    clean_cat = (category or "").strip().lower()
    all_q = load_aptitude_questions()
    if clean_cat == "all" or not clean_cat:
        return all_q
    return [q for q in all_q if q.get("category", "").lower() == clean_cat]


def generate_aptitude_test_set(
    category: str = "all",
    num_questions: int = DEFAULT_TEST_QUESTIONS,
    time_limit_seconds: Optional[int] = None
) -> Dict[str, Any]:
    """
    Generates a timed test question set.
    Sanitizes question payloads by removing correct answers and explanations.

    Returns:
        Dict containing test_id, category, time_limit_seconds, total_questions, and questions list.
    """
    clean_cat = (category or "all").strip().lower()
    if clean_cat not in VALID_CATEGORIES:
        clean_cat = "all"

    all_questions = load_aptitude_questions()

    if clean_cat == "all":
        # Balanced sampling across all 3 categories
        quant_pool = [q for q in all_questions if q.get("category") == "quantitative"]
        logical_pool = [q for q in all_questions if q.get("category") == "logical_reasoning"]
        verbal_pool = [q for q in all_questions if q.get("category") == "verbal_ability"]

        # Determine counts per section
        target_each = max(1, num_questions // 3)
        selected_quant = random.sample(quant_pool, min(len(quant_pool), target_each))
        selected_logical = random.sample(logical_pool, min(len(logical_pool), target_each))
        selected_verbal = random.sample(verbal_pool, min(len(verbal_pool), target_each))

        chosen = selected_quant + selected_logical + selected_verbal
        # Fill remaining if needed
        remaining_needed = num_questions - len(chosen)
        if remaining_needed > 0:
            already_chosen_ids = {q["id"] for q in chosen}
            pool_remaining = [q for q in all_questions if q["id"] not in already_chosen_ids]
            if pool_remaining:
                chosen.extend(random.sample(pool_remaining, min(len(pool_remaining), remaining_needed)))
    else:
        pool = [q for q in all_questions if q.get("category", "").lower() == clean_cat]
        if not pool:
            pool = all_questions
        k = min(len(pool), num_questions)
        chosen = random.sample(pool, k)

    # Calculate reasonable time limit if not specified (approx 60s per question)
    calc_time_limit = time_limit_seconds if time_limit_seconds is not None else (len(chosen) * 60)

    # Sanitize questions: omit answer and explanation from student payload
    sanitized_questions = []
    for idx, q in enumerate(chosen):
        sanitized_questions.append({
            "index": idx + 1,
            "id": q["id"],
            "category": q["category"],
            "category_label": q.get("category_label", q["category"].replace("_", " ").title()),
            "topic": q.get("topic", "General"),
            "difficulty": q.get("difficulty", "medium"),
            "question": q["question"],
            "options": q["options"]
        })

    test_id = f"test_{uuid.uuid4().hex[:10]}"

    return {
        "test_id": test_id,
        "category": clean_cat,
        "category_label": VALID_CATEGORIES.get(clean_cat, "Aptitude Assessment"),
        "time_limit_seconds": calc_time_limit,
        "total_questions": len(sanitized_questions),
        "questions": sanitized_questions,
        "question_ids": [q["id"] for q in sanitized_questions]
    }


def evaluate_aptitude_submission(
    question_ids: List[str],
    answers: Dict[str, str],
    time_taken_seconds: int,
    time_limit_seconds: int,
    timed_out: bool = False,
    test_category: str = "all"
) -> Dict[str, Any]:
    """
    Evaluates a candidate's aptitude test submission against the master question bank.

    Calculates:
    1. Overall score and percentage.
    2. Per-topic accuracy and weak topic identification (<60% accuracy).
    3. Per-category accuracy summary.
    4. Comprehensive question review with user choice, correct answer, correctness flag, and explanation.
    """
    all_questions_map = {q["id"]: q for q in load_aptitude_questions()}

    total_questions = len(question_ids)
    correct_count = 0
    incorrect_count = 0
    unattempted_count = 0

    question_reviews = []
    topic_aggregates: Dict[str, Dict[str, Any]] = {}
    category_aggregates: Dict[str, Dict[str, Any]] = {}

    for idx, q_id in enumerate(question_ids):
        master_q = all_questions_map.get(q_id)
        if not master_q:
            continue

        topic = master_q.get("topic", "General")
        category = master_q.get("category", "quantitative")
        correct_answer = master_q.get("answer", "")
        explanation = master_q.get("explanation", "")

        user_answer = answers.get(q_id)
        if user_answer is not None and str(user_answer).strip():
            user_choice = str(user_answer).strip()
            is_correct = (user_choice.lower() == correct_answer.lower())
            if is_correct:
                correct_count += 1
            else:
                incorrect_count += 1
        else:
            user_choice = None
            is_correct = False
            unattempted_count += 1

        # Track topic aggregates
        if topic not in topic_aggregates:
            topic_aggregates[topic] = {
                "topic": topic,
                "category": category,
                "total": 0,
                "correct": 0
            }
        topic_aggregates[topic]["total"] += 1
        if is_correct:
            topic_aggregates[topic]["correct"] += 1

        # Track category aggregates
        if category not in category_aggregates:
            category_aggregates[category] = {
                "category": category,
                "category_label": master_q.get("category_label", category.replace("_", " ").title()),
                "total": 0,
                "correct": 0
            }
        category_aggregates[category]["total"] += 1
        if is_correct:
            category_aggregates[category]["correct"] += 1

        question_reviews.append({
            "index": idx + 1,
            "id": q_id,
            "category": category,
            "topic": topic,
            "question": master_q.get("question", ""),
            "options": master_q.get("options", []),
            "user_answer": user_choice,
            "correct_answer": correct_answer,
            "is_correct": is_correct,
            "is_unattempted": (user_choice is None),
            "explanation": explanation
        })

    # Compute overall score percentage
    score_percentage = round((correct_count / total_questions) * 100.0, 1) if total_questions > 0 else 0.0

    # Format topic accuracy and detect weak topics (<60% accuracy)
    topic_accuracy = {}
    weak_topics = []
    for topic_name, data in topic_aggregates.items():
        tot = data["total"]
        corr = data["correct"]
        acc = round((corr / tot) * 100.0, 1) if tot > 0 else 0.0
        is_weak = (acc < WEAK_TOPIC_THRESHOLD_PCT)
        topic_accuracy[topic_name] = {
            "topic": topic_name,
            "category": data["category"],
            "total": tot,
            "correct": corr,
            "accuracy_percentage": acc,
            "is_weak": is_weak
        }
        if is_weak:
            weak_topics.append({
                "topic": topic_name,
                "category": data["category"],
                "total": tot,
                "correct": corr,
                "accuracy_percentage": acc,
                "recommendation": f"Accuracy in {topic_name} is {acc}%. Strengthen foundational concepts and practice speed drills."
            })

    # Sort weak topics by lowest accuracy first
    weak_topics.sort(key=lambda x: (x["accuracy_percentage"], -x["total"]))

    # Format category accuracy
    category_accuracy = {}
    for cat_name, data in category_aggregates.items():
        tot = data["total"]
        corr = data["correct"]
        acc = round((corr / tot) * 100.0, 1) if tot > 0 else 0.0
        category_accuracy[cat_name] = {
            "category": cat_name,
            "category_label": data["category_label"],
            "total": tot,
            "correct": corr,
            "accuracy_percentage": acc
        }

    # Performance Verdict
    if score_percentage >= 80:
        verdict = "Excellent! You are campus drive ready in this aptitude segment."
        verdict_badge = "success"
    elif score_percentage >= 60:
        verdict = "Good attempt! Target your weak topics below to achieve high placement percentiles."
        verdict_badge = "primary"
    else:
        verdict = "Needs improvement. Prioritize focused topic drills and practice time management."
        verdict_badge = "warning"

    return {
        "test_category": test_category,
        "total_questions": total_questions,
        "correct_count": correct_count,
        "incorrect_count": incorrect_count,
        "unattempted_count": unattempted_count,
        "score_percentage": score_percentage,
        "time_taken_seconds": time_taken_seconds,
        "time_limit_seconds": time_limit_seconds,
        "timed_out": bool(timed_out),
        "verdict": verdict,
        "verdict_badge": verdict_badge,
        "topic_accuracy": topic_accuracy,
        "weak_topics": weak_topics,
        "category_accuracy": category_accuracy,
        "reviews": question_reviews
    }


def record_and_evaluate_aptitude_test(
    student_id: str,
    question_ids: List[str],
    answers: Dict[str, str],
    time_taken_seconds: int,
    time_limit_seconds: int,
    timed_out: bool = False,
    test_category: str = "all",
    attempt_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evaluates a student's aptitude test submission and persists the record into SQLite.
    Returns both the saved database record and full evaluation report.
    """
    from utils.database import save_aptitude_attempt

    evaluation = evaluate_aptitude_submission(
        question_ids=question_ids,
        answers=answers,
        time_taken_seconds=time_taken_seconds,
        time_limit_seconds=time_limit_seconds,
        timed_out=timed_out,
        test_category=test_category
    )

    saved_attempt = save_aptitude_attempt(
        student_id=student_id or "default_student",
        test_category=test_category,
        total_questions=evaluation["total_questions"],
        correct_count=evaluation["correct_count"],
        score_percentage=evaluation["score_percentage"],
        time_taken_seconds=evaluation["time_taken_seconds"],
        time_limit_seconds=evaluation["time_limit_seconds"],
        timed_out=evaluation["timed_out"],
        topic_accuracy_json=json.dumps(evaluation["topic_accuracy"]),
        weak_topics_json=json.dumps(evaluation["weak_topics"]),
        results_json=json.dumps(evaluation),
        attempt_id=attempt_id
    )

    return {
        "status": "success",
        "attempt": saved_attempt,
        "evaluation": evaluation
    }


def get_student_aptitude_summary(student_id: str) -> Dict[str, Any]:
    """
    Computes aggregated aptitude performance summary for the student's dashboard.
    Returns test count, average score, and top weak topics.
    """
    from utils.database import get_student_aptitude_attempts, get_student_weak_aptitude_topics

    attempts = get_student_aptitude_attempts(student_id, limit=20)
    weak_topics = get_student_weak_aptitude_topics(student_id, threshold=WEAK_TOPIC_THRESHOLD_PCT)

    if not attempts:
        return {
            "has_attempts": False,
            "total_attempts": 0,
            "average_score": 0.0,
            "weak_topics": [],
            "recent_score": None
        }

    total_pct = sum(float(a.get("score_percentage", 0.0)) for a in attempts)
    avg_score = round(total_pct / len(attempts), 1)
    recent_score = attempts[0].get("score_percentage", 0.0)

    return {
        "has_attempts": True,
        "total_attempts": len(attempts),
        "average_score": avg_score,
        "recent_score": recent_score,
        "weak_topics": weak_topics[:5],
        "latest_attempt": attempts[0]
    }
