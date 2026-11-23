"""
Mock Interview Answer Outline Mode Service (#608)
=================================================
Provides structured answer outline templates (Introduction, Main Point, Example, Conclusion),
dynamic checklists based on question types (STAR for Behavioral, Architecture/Tradeoffs for Technical),
draft conversion from outline into final answer prose, and keeps outline practice scores separate
from final answer evaluation.
"""

from typing import Dict, Any, List, Optional


OUTLINE_TEMPLATES = {
    "Behavioral": {
        "headings": [
            {"key": "intro", "title": "Introduction / Situation", "placeholder": "Describe the context, project, or challenge you faced..."},
            {"key": "main", "title": "Task & Approach", "placeholder": "What was your direct responsibility or goal?"},
            {"key": "example", "title": "Action & Execution", "placeholder": "What specific actions and skills did you apply to resolve it?"},
            {"key": "conclusion", "title": "Conclusion / Result", "placeholder": "What was the outcome, business impact, or lesson learned?"}
        ],
        "checklist": [
            {"key": "clear_context", "label": "Contextual Situation", "desc": "Explicitly mention company, project name, or situation context."},
            {"key": "personal_ownership", "label": "Personal Ownership", "desc": "Focus on what YOU did rather than general team efforts ('I implemented...')."},
            {"key": "quantifiable_impact", "label": "Measurable Result", "desc": "Include numbers, percentages, or concrete outcomes (e.g. 'reduced latency by 30%')."},
            {"key": "key_takeaway", "label": "Key Lesson / Takeaway", "desc": "Summarize how this experience prepared you for future challenges."}
        ]
    },
    "Technical": {
        "headings": [
            {"key": "intro", "title": "High-Level Concept / Definition", "placeholder": "Define the concept concisely in plain language..."},
            {"key": "main", "title": "Core Mechanism & How It Works", "placeholder": "Explain the internal architecture, algorithm, or data flow..."},
            {"key": "example", "title": "Real-World Practical Example", "placeholder": "Describe where and how you implemented or used this in a project..."},
            {"key": "conclusion", "title": "Trade-offs & Alternatives", "placeholder": "What are the time/space trade-offs or alternative approaches?"}
        ],
        "checklist": [
            {"key": "definition", "label": "Precise Definition", "desc": "Accurate technical terminology without vague buzzwords."},
            {"key": "complexity", "label": "Time & Space Complexity", "desc": "Mention Big-O bounds and memory consumption if relevant."},
            {"key": "edge_cases", "label": "Edge Cases & Failure Modes", "desc": "Highlight null inputs, overflow, concurrency, or scale limits."},
            {"key": "tradeoffs", "label": "Trade-off Evaluation", "desc": "Explain why this solution was chosen over competing approaches."}
        ]
    },
    "General": {
        "headings": [
            {"key": "intro", "title": "Direct Thesis / Introduction", "placeholder": "Direct, confident summary answer to the interviewer's prompt..."},
            {"key": "main", "title": "Supporting Arguments & Evidence", "placeholder": "Elaborate with 2-3 logical supporting points..."},
            {"key": "example", "title": "Specific Concrete Example", "placeholder": "Provide an illustration from your academic or project history..."},
            {"key": "conclusion", "title": "Forward-Looking Conclusion", "placeholder": "Connect your answer back to the company or target role."}
        ],
        "checklist": [
            {"key": "direct_answer", "label": "Direct Answer First", "desc": "Don't ramble; state your main point within the opening sentence."},
            {"key": "clarity", "label": "Structured Flow", "desc": "Smooth logical transitions between introduction, example, and conclusion."},
            {"key": "role_alignment", "label": "Relevance to Role", "desc": "Tie the conclusion back to the role you are interviewing for."}
        ]
    }
}


def get_outline_template(question_type: str = "General") -> Dict[str, Any]:
    """Returns outline headings and checklist for a specific question type."""
    q_norm = (question_type or "").capitalize()
    if "behav" in q_norm.lower():
        template = OUTLINE_TEMPLATES["Behavioral"]
    elif "tech" in q_norm.lower():
        template = OUTLINE_TEMPLATES["Technical"]
    else:
        template = OUTLINE_TEMPLATES["General"]

    return {
        "question_type": question_type,
        "headings": template["headings"],
        "checklist": template["checklist"]
    }


def convert_outline_to_draft(sections: Dict[str, str]) -> str:
    """
    Converts outline headings into a continuous cohesive answer draft prose.
    """
    if not sections or not any(v.strip() for v in sections.values() if isinstance(v, str)):
        return ""

    parts = []
    intro = (sections.get("intro") or "").strip()
    main = (sections.get("main") or "").strip()
    example = (sections.get("example") or "").strip()
    conclusion = (sections.get("conclusion") or "").strip()

    if intro:
        parts.append(intro)
    if main:
        parts.append(main)
    if example:
        parts.append(f"For instance, {example}" if not example.lower().startswith("for") else example)
    if conclusion:
        parts.append(f"In summary, {conclusion}" if not conclusion.lower().startswith("in") else conclusion)

    return "\n\n".join(parts).strip()


def score_outline_completeness(sections: Dict[str, str], checked_items: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Evaluates outline completeness without modifying or confusing final interview scores.
    """
    non_empty_count = sum(1 for v in sections.values() if isinstance(v, str) and len(v.strip()) >= 5)
    total_headings = len(sections) or 4
    heading_ratio = non_empty_count / total_headings

    checked_count = len(checked_items or [])
    checklist_score = min(40, checked_count * 10)
    structure_score = min(60, int(heading_ratio * 60))

    total_outline_score = checklist_score + structure_score

    return {
        "outline_score": total_outline_score,
        "is_ready_for_draft": non_empty_count >= 3,
        "filled_headings_count": non_empty_count,
        "checked_items_count": checked_count,
        "feedback": "Outline has strong structure." if total_outline_score >= 70 else "Fill more sections to convert into a complete answer draft."
    }
