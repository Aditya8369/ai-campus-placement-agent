"""
Interview Performance Breakdown Service (#267).

Provides detailed multidimensional performance analytics for completed mock interviews:
- Competency Breakdown:
  1. Technical Knowledge (accuracy, foundational depth, algorithmic logic)
  2. Communication & Articulation (structure, clarity, conciseness)
  3. Problem-Solving & Critical Thinking (trade-off analysis, edge-case handling)
  4. Answer Relevance & Directness (staying on topic, addressing core question)
- Automatic derivation of top candidate Strengths and targeted Areas for Improvement.
- Visual scoring bands (Exemplary, Proficient, Developing, Critical Need).
- Overall performance summary card generation and comparison analytics.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

COMPETENCY_TECHNICAL = "Technical Knowledge"
COMPETENCY_COMMUNICATION = "Communication"
COMPETENCY_PROBLEM_SOLVING = "Problem-Solving"
COMPETENCY_RELEVANCE = "Answer Relevance"

COMPETENCY_KEYS = [
    COMPETENCY_TECHNICAL,
    COMPETENCY_COMMUNICATION,
    COMPETENCY_PROBLEM_SOLVING,
    COMPETENCY_RELEVANCE,
]


def calculate_competency_breakdown(answers_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes a granular 4-pillar competency breakdown from interview responses:
    - Technical Knowledge
    - Communication
    - Problem-Solving
    - Answer Relevance
    Also synthesizes specific strengths and areas for improvement.
    """
    if not answers_list:
        return {
            "overall_score": 0,
            "competencies": {
                COMPETENCY_TECHNICAL: {"score": 0, "rating": "Not Assessed", "color": "secondary"},
                COMPETENCY_COMMUNICATION: {"score": 0, "rating": "Not Assessed", "color": "secondary"},
                COMPETENCY_PROBLEM_SOLVING: {"score": 0, "rating": "Not Assessed", "color": "secondary"},
                COMPETENCY_RELEVANCE: {"score": 0, "rating": "Not Assessed", "color": "secondary"},
            },
            "strengths": [],
            "improvements": ["No answers submitted yet for evaluation."],
            "readiness_band": "Not Evaluated"
        }

    tech_scores = []
    comm_scores = []
    prob_scores = []
    relevance_scores = []

    for item in answers_list:
        eval_data = item.get("evaluation") or {}
        q_type = str(item.get("type", "Technical")).lower()
        ans_text = str(item.get("answer", "")).strip()
        word_count = len(ans_text.split())

        # 1. Technical Score
        raw_tech = eval_data.get("technical_accuracy") or eval_data.get("score") or 60
        try:
            tech_val = max(0, min(100, int(raw_tech)))
        except (ValueError, TypeError):
            tech_val = 60
        tech_scores.append(tech_val)

        # 2. Communication Score
        raw_comm = eval_data.get("communication_score") or eval_data.get("verbal_clarity_score") or 65
        try:
            comm_val = max(0, min(100, int(raw_comm)))
        except (ValueError, TypeError):
            comm_val = 65
        comm_scores.append(comm_val)

        # 3. Problem-Solving Score
        # Derived from confidence, STAR execution, or algorithm discussion
        raw_conf = eval_data.get("confidence_score") or 60
        try:
            conf_val = max(0, min(100, int(raw_conf)))
        except (ValueError, TypeError):
            conf_val = 60

        star_meta = eval_data.get("star_method_analysis") or eval_data.get("star_evaluation") or {}
        star_boost = 10 if (isinstance(star_meta, dict) and star_meta.get("used_star")) else 0
        prob_val = max(0, min(100, int((tech_val * 0.5) + (conf_val * 0.5) + star_boost)))
        prob_scores.append(prob_val)

        # 4. Answer Relevance
        # Assessed based on word length sweet spot (30 to 250 words) and specific keywords
        relevance = 80
        if word_count < 15:
            relevance = max(20, tech_val - 25)
        elif word_count > 300:
            relevance = max(50, tech_val - 10)
        else:
            relevance = max(40, min(95, int((tech_val * 0.6) + (comm_val * 0.4))))
        relevance_scores.append(relevance)

    avg_tech = int(round(sum(tech_scores) / len(tech_scores)))
    avg_comm = int(round(sum(comm_scores) / len(comm_scores)))
    avg_prob = int(round(sum(prob_scores) / len(prob_scores)))
    avg_rel = int(round(sum(relevance_scores) / len(relevance_scores)))

    overall = int(round((avg_tech + avg_comm + avg_prob + avg_rel) / 4))

    def _get_rating(score: int) -> Dict[str, str]:
        if score >= 85:
            return {"rating": "Exemplary", "color": "success", "progress_class": "bg-success"}
        elif score >= 70:
            return {"rating": "Proficient", "color": "primary", "progress_class": "bg-primary"}
        elif score >= 55:
            return {"rating": "Developing", "color": "warning", "progress_class": "bg-warning text-dark"}
        else:
            return {"rating": "Needs Focus", "color": "danger", "progress_class": "bg-danger"}

    tech_meta = _get_rating(avg_tech)
    comm_meta = _get_rating(avg_comm)
    prob_meta = _get_rating(avg_prob)
    rel_meta = _get_rating(avg_rel)

    # Synthesize strengths and improvements
    strengths = []
    improvements = []

    if avg_tech >= 75:
        strengths.append("Demonstrated solid foundational technical command and accurate domain terminology.")
    else:
        improvements.append("Deepen core technical knowledge: focus on exact algorithmic complexities and architectural tradeoffs.")

    if avg_comm >= 75:
        strengths.append("Articulate, well-paced communication with structured delivery.")
    else:
        improvements.append("Refine response structure: use concise bullet-style signposts (e.g. 'First, Second, Finally').")

    if avg_prob >= 75:
        strengths.append("High problem-solving proficiency, effectively dissecting tradeoffs and practical edge-cases.")
    else:
        improvements.append("Strengthen problem-solving articulation by explicitly explaining assumptions before proposing solutions.")

    if avg_rel >= 75:
        strengths.append("Responses remained tightly aligned with the specific prompt without off-topic drift.")
    else:
        improvements.append("Ensure answers directly address the primary question before expanding into peripheral details.")

    # Readiness tier
    if overall >= 80:
        band = "Placement Ready (Tier 1)"
    elif overall >= 65:
        band = "Interview Ready (Standard Roles)"
    else:
        band = "Targeted Practice Required"

    return {
        "overall_score": overall,
        "readiness_band": band,
        "competencies": {
            COMPETENCY_TECHNICAL: {
                "score": avg_tech,
                "rating": tech_meta["rating"],
                "color": tech_meta["color"],
                "progress_class": tech_meta["progress_class"],
                "icon": "fa-code"
            },
            COMPETENCY_COMMUNICATION: {
                "score": avg_comm,
                "rating": comm_meta["rating"],
                "color": comm_meta["color"],
                "progress_class": comm_meta["progress_class"],
                "icon": "fa-comments"
            },
            COMPETENCY_PROBLEM_SOLVING: {
                "score": avg_prob,
                "rating": prob_meta["rating"],
                "color": prob_meta["color"],
                "progress_class": prob_meta["progress_class"],
                "icon": "fa-brain"
            },
            COMPETENCY_RELEVANCE: {
                "score": avg_rel,
                "rating": rel_meta["rating"],
                "color": rel_meta["color"],
                "progress_class": rel_meta["progress_class"],
                "icon": "fa-bullseye"
            },
        },
        "strengths": strengths or ["Attempted all designated interview questions."],
        "improvements": improvements or ["Continue daily practice to maintain peak placement performance."],
        "total_evaluated_questions": len(answers_list)
    }
