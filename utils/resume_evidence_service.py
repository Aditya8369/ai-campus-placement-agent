"""
Resume Evidence Service (#599).
==============================
Connects AI resume feedback and improvement suggestions to the exact resume text
that triggered them. Distinguishes confirmed content weaknesses from missing evidence
(e.g., missing metrics, missing keywords, undetected sections) rather than treating
unmentioned details as factual flaws.
"""

import re
from typing import Any, Dict, List, Optional


def extract_evidence_snippets(resume_text: str) -> List[str]:
    """Splits raw resume text into cleaned, identifiable sentence/bullet snippets."""
    if not resume_text:
        return []
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    snippets: List[str] = []
    for line in lines:
        cleaned = re.sub(r"^[•\-\*\d\.\)\s]+", "", line).strip()
        if len(cleaned) >= 15:
            snippets.append(cleaned)
    return snippets


def find_matching_evidence(
    suggestion_text: str,
    resume_text: str,
    snippets: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Finds the exact matching sentence/bullet from the resume text for a suggestion,
    or flags it as 'missing_evidence' if the suggestion is about something absent.
    """
    clean_suggestion = (suggestion_text or "").strip()
    if not clean_suggestion:
        return {
            "has_evidence": False,
            "evidence_type": "none",
            "matched_snippet": "",
            "relevant_section": "General",
            "explanation": "No suggestion text provided.",
            "status_badge": "No Evidence",
            "badge_class": "bg-secondary-subtle text-secondary border"
        }

    lowered_suggestion = clean_suggestion.lower()
    lowered_resume = (resume_text or "").lower()

    # Detect if the suggestion fundamentally concerns missing information
    missing_indicators = [
        "missing", "add ", "include", "not found", "does not contain", "lack",
        "no mention", "omit", "unclear", "specify", "quantify", "no metrics",
        "absent", "without", "incorporate", "provide"
    ]
    is_missing_aspect = any(term in lowered_suggestion for term in missing_indicators)

    # Keywords extraction from suggestion
    tokens = re.findall(r"\b[A-Za-z0-9_\-\+]{3,}\b", clean_suggestion)
    filtered_tokens = [
        t for t in tokens if t.lower() not in {
            "the", "and", "for", "with", "that", "this", "from", "your", "resume",
            "should", "could", "would", "must", "more", "into", "their", "such",
            "about", "which", "using", "have", "been", "each", "were", "when"
        }
    ]

    all_snippets = snippets if snippets is not None else extract_evidence_snippets(resume_text)

    best_snippet = ""
    best_score = 0
    matched_token_list: List[str] = []

    for snip in all_snippets:
        snip_low = snip.lower()
        matched = [t for t in filtered_tokens if t.lower() in snip_low]
        score = len(matched)
        if score > best_score:
            best_score = score
            best_snippet = snip
            matched_token_list = matched

    # Identify relevant resume section
    section = "Experience / Projects"
    if any(k in lowered_suggestion for k in ["degree", "cgpa", "gpa", "university", "college", "education"]):
        section = "Education"
    elif any(k in lowered_suggestion for k in ["skill", "python", "java", "sql", "framework", "library", "tool"]):
        section = "Technical Skills"
    elif any(k in lowered_suggestion for k in ["format", "layout", "font", "length", "spacing", "bullet", "margin"]):
        section = "Formatting & Structure"
    elif any(k in lowered_suggestion for k in ["grammar", "tense", "passive", "spelling", "typo"]):
        section = "Grammar & Phrasing"

    if best_score >= 1 and len(best_snippet) > 0:
        return {
            "has_evidence": True,
            "evidence_type": "matched_text",
            "matched_snippet": best_snippet,
            "matched_terms": matched_token_list,
            "relevant_section": section,
            "explanation": f"Found direct reference in your resume under '{section}'.",
            "status_badge": "Direct Resume Evidence",
            "badge_class": "bg-info-subtle text-info-emphasis border border-info-subtle",
            "is_missing": False
        }

    if is_missing_aspect:
        return {
            "has_evidence": True,
            "evidence_type": "missing_information",
            "matched_snippet": "Information not detected in provided resume text.",
            "matched_terms": [],
            "relevant_section": section,
            "explanation": f"Notice: This is unverified / missing information in your {section} section, not an affirmative flaw.",
            "status_badge": "Missing Information (Not a Flaw)",
            "badge_class": "bg-warning-subtle text-warning-emphasis border border-warning-subtle",
            "is_missing": True
        }

    return {
        "has_evidence": False,
        "evidence_type": "general_guideline",
        "matched_snippet": "General industry recruitment standard.",
        "matched_terms": [],
        "relevant_section": section,
        "explanation": "Derived from placement benchmark best practices rather than specific resume excerpt.",
        "status_badge": "Industry Standard",
        "badge_class": "bg-secondary-subtle text-secondary border",
        "is_missing": False
    }


def build_resume_evidence_cards(
    analysis_record: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Constructs structured evidence cards for major suggestions:
    - top_5_resume_changes
    - weaknesses
    - formatting_suggestions
    - grammar_suggestions
    """
    results = analysis_record.get("results") or {}
    resume_analysis = results.get("resume_analysis") or {}
    job_match = results.get("job_match") or {}

    raw_resume = (
        analysis_record.get("resume_text")
        or results.get("extracted_resume_text")
        or results.get("resume_text")
        or ""
    )

    snippets = extract_evidence_snippets(raw_resume)

    categories = [
        ("top_5_changes", "Priority Action Items", job_match.get("top_5_resume_changes") or []),
        ("weaknesses", "Areas of Improvement", resume_analysis.get("weaknesses") or []),
        ("formatting", "Formatting Suggestions", resume_analysis.get("formatting_suggestions") or []),
        ("grammar", "Grammar & Structure", resume_analysis.get("grammar_suggestions") or [])
    ]

    grouped_cards: List[Dict[str, Any]] = []
    total_cards = 0
    direct_evidence_count = 0
    missing_info_count = 0

    for cat_id, cat_title, items in categories:
        card_items = []
        for idx, item in enumerate(items):
            item_text = str(item).strip()
            if not item_text:
                continue
            ev = find_matching_evidence(item_text, raw_resume, snippets=snippets)
            total_cards += 1
            if ev.get("evidence_type") == "matched_text":
                direct_evidence_count += 1
            elif ev.get("is_missing"):
                missing_info_count += 1

            card_items.append({
                "id": f"{cat_id}_{idx+1}",
                "suggestion": item_text,
                "evidence": ev
            })

        if card_items:
            grouped_cards.append({
                "category_id": cat_id,
                "category_title": cat_title,
                "count": len(card_items),
                "items": card_items
            })

    return {
        "has_evidence_cards": total_cards > 0,
        "total_cards": total_cards,
        "direct_evidence_count": direct_evidence_count,
        "missing_info_count": missing_info_count,
        "grouped_cards": grouped_cards,
        "summary": (
            f"Evaluated {total_cards} suggestions across {len(grouped_cards)} categories. "
            f"{direct_evidence_count} backed by direct resume text, {missing_info_count} labeled as missing information."
        )
    }
