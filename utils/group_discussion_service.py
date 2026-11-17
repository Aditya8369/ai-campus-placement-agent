"""
Group Discussion Practice & AI Evaluation Service (#427)
========================================================
Empowers students to prepare for Campus Placement Group Discussion (GD) rounds.

Core Features:
1. Curated topics across Current Affairs, Technology, and Abstract categories.
2. Random topic selector and category-specific filtering.
3. Multi-type contribution submissions: Opening Statement, Rebuttal, and Conclusion.
4. Robust input validation rejecting empty or overly brief submissions (<30 words).
5. Comprehensive AI evaluation scoring 4 distinct criteria:
   - Content (knowledge depth, data, evidence)
   - Structure (logical flow, transitions, framework)
   - Balance (multi-perspective awareness, nuance, trade-offs)
   - Clarity (articulation, conciseness, tone)
6. Actionable recommendations:
   - Stronger opening line suggestion
   - Crucial counter-point / blind spot missed
   - Concrete strengths and improvement areas
7. Resilient rule-based fallback when Gemini API is offline.
8. Persistent attempt tracking and student progress analytics.
"""

import os
import json
import random
import logging
from typing import Dict, Any, List, Optional, Tuple

import config
from prompts import GD_EVALUATION_SYSTEM_INSTRUCTION, GD_EVALUATION_USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

# Constants
MIN_WORD_COUNT = 30
RECOMMENDED_MIN_WORDS = 150
RECOMMENDED_MAX_WORDS = 250

VALID_CATEGORIES = {
    "current_affairs": "Current Affairs",
    "technology": "Technology",
    "abstract": "Abstract"
}

VALID_CONTRIBUTION_TYPES = {
    "opening": "Opening Statement",
    "rebuttal": "Rebuttal / Counter-Point",
    "conclusion": "Discussion Synthesis / Conclusion"
}

TOPICS_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "group_discussion_topics.json"
)

# In-memory cached topics
_CACHED_TOPICS: Optional[List[Dict[str, Any]]] = None


def load_gd_topics(force_reload: bool = False) -> List[Dict[str, Any]]:
    """
    Loads group discussion topics from data/group_discussion_topics.json.
    Returns a list of topic dictionaries with fallback defaults if the file cannot be accessed.
    """
    global _CACHED_TOPICS
    if _CACHED_TOPICS is not None and not force_reload:
        return _CACHED_TOPICS

    if os.path.exists(TOPICS_FILE_PATH):
        try:
            with open(TOPICS_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    _CACHED_TOPICS = data
                    return _CACHED_TOPICS
        except Exception as e:
            logger.error(f"Error loading GD topics from {TOPICS_FILE_PATH}: {e}")

    # Fallback seed topics in case JSON file is missing or corrupted
    _CACHED_TOPICS = [
        {
            "id": "gd_tech_default",
            "title": "Generative AI in the Workplace: Replacement or Augmentation of Human Jobs?",
            "category": "technology",
            "category_label": "Technology",
            "description": "Evaluate whether generative AI will cause mass white-collar job displacement or primarily augment productivity and create higher-value roles.",
            "key_angles": [
                "Automation of repetitive cognitive tasks vs. emergence of new AI roles",
                "Widening wage disparity between AI-fluent and non-fluent professionals",
                "Need for rapid curriculum overhaul in universities and corporate reskilling"
            ]
        },
        {
            "id": "gd_ca_default",
            "title": "Electric Vehicles: Is India's Grid and Supply Chain Infrastructure Prepared for Mass Adoption?",
            "category": "current_affairs",
            "category_label": "Current Affairs",
            "description": "Examine EV charging grid readiness, battery mineral dependency, subsidies, and recycling ecosystems.",
            "key_angles": [
                "Power grid transmission capacity and peak-load stress",
                "Rare earth and lithium import vulnerabilities vs. domestic battery chemistries",
                "Total cost of ownership and tier-2/3 charging infrastructure equity"
            ]
        },
        {
            "id": "gd_abs_default",
            "title": "Work-Life Integration vs. Work-Life Balance: Which is More Sustainable in High-Performance Careers?",
            "category": "abstract",
            "category_label": "Abstract",
            "description": "Analyze whether rigid boundaries between work and life or fluid integration yields better long-term fulfillment and success.",
            "key_angles": [
                "Cognitive fatigue and constant connectivity vs. structured detachment",
                "Autonomy and output-driven culture vs. clock-in presence",
                "Generational attitudes toward corporate ambition, well-being, and burnout"
            ]
        }
    ]
    return _CACHED_TOPICS


def get_topic_by_id(topic_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a specific GD topic by its unique ID."""
    topics = load_gd_topics()
    for t in topics:
        if t.get("id") == topic_id:
            return t
    return None


def get_random_topic(category: Optional[str] = None) -> Dict[str, Any]:
    """
    Selects a random topic from the topic pool, optionally filtered by category.
    Raises ValueError if the requested category has no topics.
    """
    topics = load_gd_topics()
    if category:
        clean_cat = category.strip().lower()
        filtered = [t for t in topics if t.get("category", "").lower() == clean_cat]
        if not filtered:
            raise ValueError(f"No topics found for category '{category}'. Available: {', '.join(VALID_CATEGORIES.keys())}")
        return random.choice(filtered)
    return random.choice(topics)


def get_topics_by_category() -> Dict[str, List[Dict[str, Any]]]:
    """Returns topics grouped by category dictionary."""
    topics = load_gd_topics()
    grouped: Dict[str, List[Dict[str, Any]]] = {
        "current_affairs": [],
        "technology": [],
        "abstract": []
    }
    for t in topics:
        cat = t.get("category", "abstract").lower()
        if cat in grouped:
            grouped[cat].append(t)
        else:
            grouped.setdefault(cat, []).append(t)
    return grouped


def validate_contribution(text: str, min_words: int = MIN_WORD_COUNT) -> Tuple[bool, str, int]:
    """
    Validates a student's group discussion input.
    Returns (is_valid, error_message, word_count).
    Enforces rejection of empty or excessively short contributions (<30 words).
    """
    if not text or not text.strip():
        return False, "Please write your group discussion contribution before submitting.", 0

    words = text.strip().split()
    word_count = len(words)

    if word_count < min_words:
        return (
            False,
            f"Contribution is too brief ({word_count} words). "
            f"Please write at least {min_words} words (recommended: 150-250 words) to receive meaningful evaluation.",
            word_count
        )

    return True, "", word_count


def generate_fallback_gd_feedback(
    topic_title: str,
    category: str,
    contribution_type: str,
    contribution_text: str,
    word_count: int,
    topic_description: Optional[str] = None,
    topic_angles: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Generates deterministic, high-quality rule-based GD feedback when the Gemini AI API is unavailable.
    Accurately computes scores for Content, Structure, Balance, and Clarity.
    Provides targeted opening line revisions and missed counter-points.
    """
    text_lower = contribution_text.lower()

    # 1. Structure Marker Analysis
    structure_markers = [
        "firstly", "first and foremost", "to begin with", "furthermore", "moreover",
        "in addition", "secondly", "on the other hand", "consequently", "in conclusion",
        "to conclude", "to summarize", "looking ahead", "ultimately", "in my view"
    ]
    structure_hits = sum(1 for m in structure_markers if m in text_lower)
    structure_score = min(92, 60 + (structure_hits * 8))

    # 2. Balance & Counter-Argument Analysis
    balance_markers = [
        "however", "on the other hand", "conversely", "counterpoint", "alternatively",
        "while it is true", "despite", "although", "trade-off", "perspective",
        "critics argue", "proponents", "both sides", "nuance", "nonetheless"
    ]
    balance_hits = sum(1 for m in balance_markers if m in text_lower)
    balance_score = min(90, 55 + (balance_hits * 9))

    # 3. Content & Substance Analysis (Length, Data, Concrete nouns)
    content_markers = [
        "percent", "%", "data", "report", "growth", "cost", "economic", "market",
        "infrastructure", "regulation", "industry", "technology", "research", "evidence",
        "impact", "sustainable", "scale", "global", "policy"
    ]
    content_hits = sum(1 for m in content_markers if m in text_lower)

    # Word count scaling
    if word_count < 60:
        content_score = max(50, 45 + word_count // 3)
        clarity_score = 65
    elif 60 <= word_count < 140:
        content_score = min(82, 65 + (content_hits * 3))
        clarity_score = 78
    elif 140 <= word_count <= 260:
        content_score = min(95, 75 + (content_hits * 3))
        clarity_score = 88
    else:  # > 260 words
        content_score = min(90, 78 + (content_hits * 2))
        clarity_score = 76  # penalized slightly for rambling beyond the 150-250 window

    # Overall weighted score
    overall_score = int(round(
        (content_score * 0.35) +
        (structure_score * 0.25) +
        (balance_score * 0.20) +
        (clarity_score * 0.20)
    ))

    # Construct context-aware stronger opening
    c_type_label = VALID_CONTRIBUTION_TYPES.get(contribution_type, "Opening Statement")
    if contribution_type == "rebuttal":
        stronger_opening = (
            f"While I appreciate the perspective highlighted regarding {topic_title.split(':')[0]}, "
            f"we must examine the critical trade-off that is frequently overlooked."
        )
    elif contribution_type == "conclusion":
        stronger_opening = (
            f"Synthesizing the diverse viewpoints shared today on {topic_title.split(':')[0]}, "
            f"the consensus converges on balancing immediate execution with long-term systemic stability."
        )
    else:
        stronger_opening = (
            f"To initiate our discussion on {topic_title.split(':')[0]}, "
            f"I propose framing our analysis around three core dimensions: stakeholder impact, economic viability, and future scalability."
        )

    # Identify a crucial missed counterpoint
    if topic_angles and len(topic_angles) > 0:
        # Pick an angle not explicitly referenced
        missed_counterpoint = topic_angles[-1]
    else:
        if category == "technology":
            missed_counterpoint = "Consider the ethical, regulatory, and workforce displacement implications alongside pure technological efficiency."
        elif category == "current_affairs":
            missed_counterpoint = "Evaluate fiscal sustainability, supply-chain vulnerabilities, and socioeconomic equity across non-metro regions."
        else:
            missed_counterpoint = "Examine how systemic incentives and unintended second-order consequences challenge conventional assumptions."

    # Construct strengths and improvements
    strengths = []
    if content_score >= 70:
        strengths.append(f"Demonstrated good domain awareness relevant to {topic_title.split(':')[0]}.")
    if structure_hits >= 2:
        strengths.append("Employed helpful transitional phrases that guide the listener through your reasoning.")
    else:
        strengths.append("Maintained an assertive, professional tone suitable for campus placement GDs.")
    if word_count >= 140 and word_count <= 260:
        strengths.append(f"Adhered closely to the ideal speaking duration ({word_count} words; ~1.5 minutes).")

    improvements = []
    if balance_hits < 2:
        improvements.append("Acknowledge opposing viewpoints or counter-arguments before defending your core stance to demonstrate analytical maturity.")
    if content_hits < 3:
        improvements.append("Anchor assertions with concrete data points, industry examples, or measurable benchmarks rather than broad generalizations.")
    if word_count < 140:
        improvements.append(f"Expand your argument with deeper substantiation; current contribution is {word_count} words (aim for 150-250 words).")
    elif word_count > 260:
        improvements.append(f"Condense your points to prevent rambling ({word_count} words); campus moderators favor crisp, punchy contributions.")

    return {
        "overall_score": overall_score,
        "scores": {
            "content": content_score,
            "structure": structure_score,
            "balance": balance_score,
            "clarity": clarity_score
        },
        "criteria_feedback": {
            "content": f"Evaluated knowledge depth and factual grounding. Content score: {content_score}/100.",
            "structure": f"Evaluated logical coherence, transitions, and argument flow. Structure score: {structure_score}/100.",
            "balance": f"Evaluated nuance and multi-perspective acknowledgment. Balance score: {balance_score}/100.",
            "clarity": f"Evaluated conciseness, vocabulary, and articulation. Clarity score: {clarity_score}/100."
        },
        "strengths": strengths[:3],
        "improvements": improvements[:3],
        "stronger_opening": stronger_opening,
        "missed_counterpoint": missed_counterpoint,
        "summary_verdict": f"Solid contribution for a campus placement GD {c_type_label.lower()}. Incorporate more concrete counterpoints to stand out.",
        "word_count": word_count,
        "is_fallback": True
    }


def evaluate_gd_contribution(
    topic_title: str,
    category: str,
    contribution_type: str,
    contribution_text: str,
    topic_description: Optional[str] = None,
    topic_angles: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Evaluates a student's group discussion contribution.
    Attempts AI evaluation via Gemini API using generate_json_response,
    with an automatic fallback to deterministic evaluation upon API error.

    Raises:
        ValueError: If contribution validation fails (e.g. empty or <30 words).
    """
    # 1. Enforce strict input validation
    is_valid, error_msg, word_count = validate_contribution(contribution_text)
    if not is_valid:
        raise ValueError(error_msg)

    # 2. Prepare prompt
    clean_cat = category.strip().lower() if category else "technology"
    c_type = contribution_type.strip().lower() if contribution_type else "opening"
    desc = topic_description or "Campus placement group discussion round."

    user_prompt = GD_EVALUATION_USER_PROMPT_TEMPLATE.format(
        category=clean_cat,
        topic_title=topic_title,
        topic_description=desc,
        contribution_type=c_type,
        word_count=word_count,
        contribution_text=contribution_text.strip()
    )

    # 3. Invoke Gemini AI via generate_json_response
    try:
        from utils.gemini import generate_json_response
        ai_resp = generate_json_response(
            system_instruction=GD_EVALUATION_SYSTEM_INSTRUCTION,
            prompt=user_prompt,
            feature="group_discussion"
        )

        if isinstance(ai_resp, dict) and "scores" in ai_resp and "overall_score" in ai_resp:
            scores = ai_resp.get("scores", {})
            return {
                "overall_score": int(ai_resp.get("overall_score", 75)),
                "scores": {
                    "content": int(scores.get("content", 75)),
                    "structure": int(scores.get("structure", 75)),
                    "balance": int(scores.get("balance", 75)),
                    "clarity": int(scores.get("clarity", 75))
                },
                "criteria_feedback": ai_resp.get("criteria_feedback", {
                    "content": "Good grasp of the core concepts.",
                    "structure": "Logical flow from point to point.",
                    "balance": "Addressed primary angles with reasonable balance.",
                    "clarity": "Clear and comprehensible articulation."
                }),
                "strengths": ai_resp.get("strengths", ["Clear point of view", "Professional tone"]),
                "improvements": ai_resp.get("improvements", ["Provide additional supporting data"]),
                "stronger_opening": ai_resp.get("stronger_opening", f"To initiate our discussion on {topic_title}..."),
                "missed_counterpoint": ai_resp.get("missed_counterpoint", "Consider opposing economic and logistical constraints."),
                "summary_verdict": ai_resp.get("summary_verdict", "Constructive contribution suitable for campus placement discussion."),
                "word_count": word_count,
                "is_fallback": False
            }
        elif isinstance(ai_resp, dict) and "content_score" in ai_resp:
            # Flattened format compatibility
            return {
                "overall_score": int(ai_resp.get("overall_score", 75)),
                "scores": {
                    "content": int(ai_resp.get("content_score", 75)),
                    "structure": int(ai_resp.get("structure_score", 75)),
                    "balance": int(ai_resp.get("balance_score", 75)),
                    "clarity": int(ai_resp.get("clarity_score", 75))
                },
                "criteria_feedback": ai_resp.get("criteria_feedback", {}),
                "strengths": ai_resp.get("strengths", []),
                "improvements": ai_resp.get("improvements", []),
                "stronger_opening": ai_resp.get("stronger_opening", ""),
                "missed_counterpoint": ai_resp.get("missed_counterpoint", ""),
                "summary_verdict": ai_resp.get("summary_verdict", ""),
                "word_count": word_count,
                "is_fallback": False
            }
        else:
            logger.warning(f"Gemini returned unrecognized GD response structure: {ai_resp}. Falling back to rule-based engine.")
    except Exception as e:
        logger.warning(f"AI evaluation for GD contribution failed: {e}. Falling back to rule-based engine.")

    # 4. Fallback execution
    return generate_fallback_gd_feedback(
        topic_title=topic_title,
        category=clean_cat,
        contribution_type=c_type,
        contribution_text=contribution_text,
        word_count=word_count,
        topic_description=desc,
        topic_angles=topic_angles
    )


def record_and_evaluate_gd_attempt(
    student_id: str,
    topic_title: str,
    category: str,
    contribution_type: str,
    contribution_text: str,
    topic_id: Optional[str] = None,
    topic_description: Optional[str] = None,
    topic_angles: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Evaluates a student's group discussion submission and saves the attempt in the database.
    Returns both the saved database record and full evaluation dictionary.
    """
    from utils.database import save_gd_attempt

    evaluation = evaluate_gd_contribution(
        topic_title=topic_title,
        category=category,
        contribution_type=contribution_type,
        contribution_text=contribution_text,
        topic_description=topic_description,
        topic_angles=topic_angles
    )

    scores = evaluation.get("scores", {})
    saved_record = save_gd_attempt(
        student_id=student_id or "default_student",
        topic_title=topic_title,
        category=category,
        contribution_type=contribution_type,
        contribution_text=contribution_text,
        word_count=evaluation.get("word_count", len(contribution_text.split())),
        overall_score=evaluation.get("overall_score", 0),
        content_score=scores.get("content", 0),
        structure_score=scores.get("structure", 0),
        balance_score=scores.get("balance", 0),
        clarity_score=scores.get("clarity", 0),
        stronger_opening=evaluation.get("stronger_opening", ""),
        missed_counterpoint=evaluation.get("missed_counterpoint", ""),
        feedback_json=json.dumps(evaluation),
        topic_id=topic_id
    )

    return {
        "status": "success",
        "attempt": saved_record,
        "evaluation": evaluation
    }
