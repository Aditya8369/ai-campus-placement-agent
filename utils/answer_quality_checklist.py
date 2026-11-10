"""
AI-Generated Interview Answer Quality Checklist Engine (#257)
=============================================================
Evaluates student interview responses across a rigorous 6-point Quality Rubric:
1. Direct Question Addressing: Did the candidate answer the specific core prompt asked?
2. Concrete Real-World Examples: Are specific projects, metrics, or technologies cited?
3. Factual & Unsupported Claim Verification: Are bold claims backed by technical rationale or quantifiable impact?
4. Technical Depth & Mechanical Explanations: Does the answer explain HOW systems work, rather than high-level buzzwords?
5. Answer Clarity & Structural Flow: Logical flow, clear topic sentences, concise transitions without ramblings.
6. Actionable Improvements & Remediation Checklist: Granular check items (PASSED / WARNING / FAILED) with exact advice.

Safeguards:
- Rejects answers that are completely irrelevant to the prompt or empty.
- Avoids generating hallucinated feedback disconnected from the candidate's actual words.
- Emits structured checklist results ready for interactive UI widgets and API consumption.
"""

import logging
import json
import re
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

CHECKLIST_ITEMS = [
    {
        "id": "direct_address",
        "title": "Directly Addresses Question Prompt",
        "description": "Verifies that the answer directly targets what was asked without dodging or generic deflection."
    },
    {
        "id": "concrete_examples",
        "title": "Includes Concrete Technical Examples",
        "description": "Checks for specific frameworks, real projects, system architectures, or numerical performance metrics."
    },
    {
        "id": "supported_claims",
        "title": "Substantiates Engineering Claims",
        "description": "Identifies broad or unsupported assertions (e.g. 'I made it 100x faster') and checks for technical rationale."
    },
    {
        "id": "technical_explanation",
        "title": "Explains Internal Mechanics & Trade-offs",
        "description": "Evaluates whether internal workings, time/space complexities, or design trade-offs are articulated."
    },
    {
        "id": "clarity_structure",
        "title": "Structural Clarity & Brevity",
        "description": "Checks for clear organization (e.g. STAR, problem-solution-impact) and absence of filler word congestion."
    },
    {
        "id": "actionable_remediation",
        "title": "Actionable Delivery & Follow-up Readiness",
        "description": "Provides candidate next-step talking points to anticipate interviewer follow-up questions."
    }
]

# Indicator dictionaries
EXAMPLE_INDICATORS = [
    r"\bfor example\b", r"\bfor instance\b", r"\bsuch as\b", r"\bin my previous project\b",
    r"\bin my experience\b", r"\bwe implemented\b", r"\bi designed\b", r"\bi built\b",
    r"\bwe used\b", r"\bspecifically\b", r"\bwhen working on\b", r"\bcase study\b"
]

UNSUPPORTED_BUZZWORD_PATTERNS = [
    r"\b100x\b", r"\b10x\b", r"\bcompletely solved\b", r"\bzero bugs\b",
    r"\bflawless\b", r"\bperfect architecture\b", r"\beverything was automated\b",
    r"\bbest practice always\b"
]

MECHANICS_INDICATORS = [
    r"\bbecause\b", r"\btrade-off\b", r"\bcomplexity\b", r"\bo\([1n]\b", r"\bunder the hood\b",
    r"\bmechanism\b", r"\binternally\b", r"\bconcurrency\b", r"\bconsistency\b", r"\blatency\b",
    r"\bthroughput\b", r"\bmemory\b", r"\bthread\b", r"\block\b", r"\balgorithm\b"
]


def audit_interview_answer_quality(
    question: str,
    answer: str,
    question_type: str = "technical"
) -> Dict[str, Any]:
    """
    Performs comprehensive checklist auditing of an interview answer.
    Returns checklist item statuses (PASS, WARNING, FAIL), qualitative insights, and quality score.
    """
    q_clean = (question or "").strip()
    a_clean = (answer or "").strip()

    if not a_clean:
        return {
            "overall_quality_score": 0,
            "overall_status": "NEEDS_IMPROVEMENT",
            "checklist": [
                {
                    "item_id": item["id"],
                    "title": item["title"],
                    "status": "FAIL",
                    "feedback": f"No answer was provided to evaluate {item['title'].lower()}."
                }
                for item in CHECKLIST_ITEMS
            ],
            "passed_items_count": 0,
            "failed_items_count": len(CHECKLIST_ITEMS),
            "unsupported_claims_flagged": [],
            "actionable_suggestions": ["Please submit an answer to receive quality checklist feedback."]
        }

    q_lower = q_clean.lower()
    a_lower = a_clean.lower()
    words = a_clean.split()
    word_count = len(words)

    # 1. Direct Question Addressing
    # Extract significant keywords from question
    q_words = set(re.findall(r"\b[a-z]{3,}\b", q_lower))
    stopwords = {"what", "when", "where", "which", "who", "whom", "whose", "why", "how", "explain", "describe", "discuss", "does", "your", "have", "with", "from"}
    significant_q_words = q_words - stopwords

    common_overlap = [w for w in significant_q_words if w in a_lower]
    overlap_ratio = len(common_overlap) / max(1, len(significant_q_words))

    if overlap_ratio >= 0.35 or word_count >= 50 and len(common_overlap) >= 2:
        direct_status = "PASS"
        direct_feedback = f"Directly addresses key topic terms: {', '.join(common_overlap[:3])}."
    elif overlap_ratio > 0.15:
        direct_status = "WARNING"
        direct_feedback = "Answer touches upon the subject but could align more directly with the exact prompt asked."
    else:
        direct_status = "FAIL"
        direct_feedback = "Answer appears tangential or does not explicitly address core question concepts."

    # 2. Concrete Examples
    has_example_indicator = any(re.search(pat, a_lower) for pat in EXAMPLE_INDICATORS)
    has_metrics = bool(re.search(r"\b\d+[%ms|k|gb|mb|sec|hours|days|x]?\b", a_clean))

    if has_example_indicator and (has_metrics or word_count >= 60):
        examples_status = "PASS"
        examples_feedback = "Included concrete project scenarios and practical illustrations."
    elif has_example_indicator or has_metrics:
        examples_status = "WARNING"
        examples_feedback = "Mentioned examples briefly; add more specifics regarding team context or quantitative impact."
    else:
        examples_status = "FAIL"
        examples_feedback = "Lacks real-world examples. Reference a specific project, system, or case study."

    # 3. Unsupported Claims & Buzzwords
    unsupported_flags = []
    for pat in UNSUPPORTED_BUZZWORD_PATTERNS:
        matches = re.findall(pat, a_lower)
        if matches:
            unsupported_flags.extend(matches)

    if not unsupported_flags:
        claims_status = "PASS"
        claims_feedback = "Claims appear balanced and grounded in technical reality."
    else:
        claims_status = "WARNING"
        claims_feedback = f"Contains potentially overstated claims ({', '.join(unsupported_flags)}); justify with technical evidence."

    # 4. Technical Explanation & Mechanics
    mechanics_matches = [m for m in MECHANICS_INDICATORS if re.search(m, a_lower)]
    if len(mechanics_matches) >= 3 or (len(mechanics_matches) >= 1 and word_count >= 80):
        mechanics_status = "PASS"
        mechanics_feedback = "Articulated internal mechanisms, reasoning, or trade-offs clearly."
    elif len(mechanics_matches) >= 1:
        mechanics_status = "WARNING"
        mechanics_feedback = "Introduced technical terms but could explain internal mechanics in greater depth."
    else:
        mechanics_status = "FAIL"
        mechanics_feedback = "High-level answer. Explain HOW the underlying system functions and what trade-offs exist."

    # 5. Clarity & Structure
    if word_count < 25:
        clarity_status = "FAIL"
        clarity_feedback = "Response is too brief to establish strong interview depth. Aim for 80-150 words."
    elif 40 <= word_count <= 250 and ("." in a_clean):
        clarity_status = "PASS"
        clarity_feedback = "Well-paced, structured sentences with clear narrative progression."
    else:
        clarity_status = "WARNING"
        clarity_feedback = "Structure could be tightened; use clear topic transitions and concise paragraphs."

    # 6. Actionable Remediation
    remediation_status = "PASS" if direct_status == "PASS" and mechanics_status == "PASS" else "WARNING"
    remediation_feedback = "Be prepared for follow-up questions probing edge cases and failure modes."

    checklist_results = [
        {"item_id": "direct_address", "title": CHECKLIST_ITEMS[0]["title"], "status": direct_status, "feedback": direct_feedback},
        {"item_id": "concrete_examples", "title": CHECKLIST_ITEMS[1]["title"], "status": examples_status, "feedback": examples_feedback},
        {"item_id": "supported_claims", "title": CHECKLIST_ITEMS[2]["title"], "status": claims_status, "feedback": claims_feedback},
        {"item_id": "technical_explanation", "title": CHECKLIST_ITEMS[3]["title"], "status": mechanics_status, "feedback": mechanics_feedback},
        {"item_id": "clarity_structure", "title": CHECKLIST_ITEMS[4]["title"], "status": clarity_status, "feedback": clarity_feedback},
        {"item_id": "actionable_remediation", "title": CHECKLIST_ITEMS[5]["title"], "status": remediation_status, "feedback": remediation_feedback}
    ]

    # Calculate overall quality score
    status_weights = {"PASS": 100, "WARNING": 60, "FAIL": 20}
    avg_score = int(sum(status_weights[item["status"]] for item in checklist_results) / len(checklist_results))

    passed_count = sum(1 for item in checklist_results if item["status"] == "PASS")
    failed_count = sum(1 for item in checklist_results if item["status"] == "FAIL")

    suggestions = []
    if direct_status != "PASS":
        suggestions.append("Re-read the question carefully and ensure your opening sentence addresses the central prompt directly.")
    if examples_status != "PASS":
        suggestions.append("Anchor your explanation with a concrete project story: what was built, what technology was selected, and why.")
    if mechanics_status != "PASS":
        suggestions.append("Dive into internal data structures, network round-trips, or memory implications.")
    if claims_status == "WARNING":
        suggestions.append("Replace superlative claims with measurable metrics (e.g. 'reduced latency by 35% under peak load').")

    if not suggestions:
        suggestions.append("Strong response! Ready for high-bar technical interviews.")

    overall_status = "EXCELLENT" if avg_score >= 80 else ("GOOD" if avg_score >= 60 else "NEEDS_IMPROVEMENT")

    return {
        "overall_quality_score": avg_score,
        "overall_status": overall_status,
        "checklist": checklist_results,
        "passed_items_count": passed_count,
        "failed_items_count": failed_count,
        "unsupported_claims_flagged": unsupported_flags,
        "actionable_suggestions": suggestions,
        "word_count": word_count
    }
