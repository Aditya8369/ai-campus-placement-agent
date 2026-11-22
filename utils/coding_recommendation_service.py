"""
Coding problem recommendation reasons service (#618).
Recommends targeted problems with deterministic, plain-English justifications
based on weak topics, past incorrect attempts, and respects 'not relevant' exclusions.
"""

from typing import Dict, Any, List

CODING_PROBLEM_CATALOG = [
    {
        "id": "two-sum",
        "title": "Two Sum",
        "topic": "Arrays & Hash Maps",
        "difficulty": "Easy",
        "focus_areas": ["hash maps", "arrays", "lookup optimization"]
    },
    {
        "id": "valid-parentheses",
        "title": "Valid Parentheses",
        "topic": "Stacks",
        "difficulty": "Easy",
        "focus_areas": ["stacks", "strings", "nesting validation"]
    },
    {
        "id": "merge-intervals",
        "title": "Merge Intervals",
        "topic": "Intervals & Sorting",
        "difficulty": "Medium",
        "focus_areas": ["intervals", "sorting", "sweep-line"]
    },
    {
        "id": "lru-cache",
        "title": "LRU Cache",
        "topic": "Design & Linked Lists",
        "difficulty": "Medium",
        "focus_areas": ["doubly linked lists", "hash maps", "system design"]
    }
]

def recommend_problems_with_reasons(
    weak_topics: List[str] = None,
    recent_failed_attempts: List[str] = None,
    dismissed_problem_ids: List[str] = None
) -> List[Dict[str, Any]]:
    weak_topics = [t.lower() for t in (weak_topics or [])]
    recent_failed_attempts = recent_failed_attempts or []
    dismissed_problem_ids = set(dismissed_problem_ids or [])

    recommendations = []

    for prob in CODING_PROBLEM_CATALOG:
        if prob["id"] in dismissed_problem_ids:
            continue

        reasons = []

        # Check if user had past failed attempt on this problem
        if prob["id"] in recent_failed_attempts:
            reasons.append("Follow-up: You had previous incorrect or unsubmitted attempts on this problem.")

        # Check if problem relates to identified weak topics
        matched_weak = [t for t in weak_topics if any(t in focus for focus in prob["focus_areas"]) or t in prob["topic"].lower()]
        if matched_weak:
            reasons.append(f"Targeted practice: Strengthens your growth areas in {', '.join(matched_weak)}.")

        # Fallback default reason
        if not reasons:
            reasons.append(f"Foundational problem: Frequently asked in campus placement interviews for {prob['topic']}.")

        recommendations.append({
            "problem": prob,
            "reasons": reasons,
            "primary_reason": reasons[0]
        })

    return recommendations
