"""
Delta Analysis & Longitudinal Progress Tracking Engine

Calculates incremental improvements between resume versions including:
- ATS score differentials
- Job match percentage improvements
- Newly matched keywords and resolved skill gaps
- Longitudinal trend data serialization for Chart.js visualizations
"""

import logging
from typing import Dict, Any, List, Optional, Set

logger = logging.getLogger(__name__)


def calculate_version_delta(
    current_record: Dict[str, Any],
    previous_record: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Computes delta metrics between the current analysis version and a previous iteration.
    """
    curr_results = current_record.get("results", {}) if isinstance(current_record, dict) else {}
    curr_resume = curr_results.get("resume_analysis", {})
    curr_job = curr_results.get("job_match", {})

    curr_ats = curr_resume.get("ats_score", 0)
    curr_match = curr_job.get("match_percentage", 0)
    curr_version = current_record.get("version_number", 1) if isinstance(current_record, dict) else 1

    curr_found = _sanitize_list(curr_resume.get("keywords_found"))
    curr_missing = _sanitize_list(curr_resume.get("keywords_missing"))
    curr_gaps = _extract_skill_names(curr_results.get("skill_gap"))
    curr_matched_skills = _sanitize_list(curr_job.get("matched_skills"))

    if not previous_record:
        return {
            "has_previous": False,
            "current_version": curr_version,
            "previous_version": None,
            "current_analysis_id": current_record.get("id", ""),
            "previous_analysis_id": None,
            "ats_current": curr_ats,
            "ats_previous": None,
            "ats_delta": 0,
            "match_current": curr_match,
            "match_previous": None,
            "match_delta": 0,
            "newly_matched_keywords": [],
            "persistent_missing_keywords": curr_missing,
            "resolved_skill_gaps": [],
            "remaining_skill_gaps": curr_gaps,
            "current_keywords_found": curr_found,
            "previous_keywords_found": [],
            "badge_text": f"Baseline v{curr_version}",
            "badge_class": "primary",
            "status_message": (
                f"Initial baseline analysis established (Version {curr_version}). "
                "Upload updated resumes or revisions to track longitudinal growth."
            ),
            "summary_bullets": [
                f"Baseline ATS Score: {curr_ats}/100",
                f"Initial Job Match: {curr_match}%",
                f"Identified {len(curr_gaps)} initial skill gaps for targeted preparation."
            ]
        }

    prev_results = previous_record.get("results", {}) if isinstance(previous_record, dict) else {}
    prev_resume = prev_results.get("resume_analysis", {})
    prev_job = prev_results.get("job_match", {})

    prev_ats = prev_resume.get("ats_score", 0)
    prev_match = prev_job.get("match_percentage", 0)
    prev_version = previous_record.get("version_number", 1) if isinstance(previous_record, dict) else 1

    prev_found = _sanitize_list(prev_resume.get("keywords_found"))
    prev_missing = _sanitize_list(prev_resume.get("keywords_missing"))
    prev_gaps = _extract_skill_names(prev_results.get("skill_gap"))

    ats_delta = curr_ats - prev_ats
    match_delta = curr_match - prev_match

    # Compare keywords (case-insensitive sets)
    prev_found_set = {k.lower() for k in prev_found}
    prev_missing_set = {k.lower() for k in prev_missing}
    curr_found_set = {k.lower() for k in curr_found}

    newly_matched = [
        k for k in curr_found
        if k.lower() in prev_missing_set or k.lower() not in prev_found_set
    ]

    persistent_missing = [
        k for k in curr_missing
        if k.lower() in prev_missing_set or k.lower() not in curr_found_set
    ]

    # Compare skill gaps
    curr_matched_lower = {s.lower() for s in curr_matched_skills}
    curr_gaps_lower = {g.lower() for g in curr_gaps}

    resolved_gaps = [
        g for g in prev_gaps
        if g.lower() in curr_matched_lower or g.lower() not in curr_gaps_lower
    ]

    # Badge classification and summary messages
    if ats_delta >= 10:
        badge_text = f"+{ats_delta}% Significant Improvement"
        badge_class = "success"
    elif ats_delta > 0:
        badge_text = f"+{ats_delta}% Steady Growth"
        badge_class = "success"
    elif ats_delta == 0:
        badge_text = "Maintained Score (0%)"
        badge_class = "secondary"
    else:
        badge_text = f"{ats_delta}% Score Dip"
        badge_class = "warning"

    summary_bullets = []
    if ats_delta > 0:
        summary_bullets.append(f"ATS compatibility increased by +{ats_delta} points (from {prev_ats} to {curr_ats}).")
    elif ats_delta < 0:
        summary_bullets.append(f"ATS compatibility decreased by {abs(ats_delta)} points. Review removed sections.")
    else:
        summary_bullets.append(f"ATS compatibility held steady at {curr_ats}/100.")

    if match_delta > 0:
        summary_bullets.append(f"Target company job match increased by +{match_delta}% (from {prev_match}% to {curr_match}%).")

    if newly_matched:
        summary_bullets.append(f"Successfully incorporated {len(newly_matched)} newly matched keywords ({', '.join(newly_matched[:3])}).")

    if resolved_gaps:
        summary_bullets.append(f"Resolved {len(resolved_gaps)} previously identified skill gaps: {', '.join(resolved_gaps[:2])}.")

    return {
        "has_previous": True,
        "current_version": curr_version,
        "previous_version": prev_version,
        "current_analysis_id": current_record.get("id", ""),
        "previous_analysis_id": previous_record.get("id", ""),
        "ats_current": curr_ats,
        "ats_previous": prev_ats,
        "ats_delta": ats_delta,
        "match_current": curr_match,
        "match_previous": prev_match,
        "match_delta": match_delta,
        "newly_matched_keywords": newly_matched,
        "persistent_missing_keywords": persistent_missing,
        "resolved_skill_gaps": resolved_gaps,
        "remaining_skill_gaps": curr_gaps,
        "current_keywords_found": curr_found,
        "previous_keywords_found": prev_found,
        "badge_text": badge_text,
        "badge_class": badge_class,
        "status_message": (
            f"Comparing Version {curr_version} with Version {prev_version}: "
            f"ATS score changed by {ats_delta:+d} points, match changed by {match_delta:+d}%."
        ),
        "summary_bullets": summary_bullets
    }


def build_longitudinal_series(versions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Constructs serialized longitudinal data sets ready for Chart.js trend visualization.
    """
    labels = []
    dates = []
    ats_scores = []
    match_scores = []
    gap_counts = []
    version_ids = []
    filenames = []

    for idx, v in enumerate(versions, start=1):
        v_num = v.get("version_number", idx)
        labels.append(f"v{v_num}")
        
        # Clean date string
        created_at = str(v.get("created_at", ""))
        dates.append(created_at[:10] if len(created_at) >= 10 else f"Iter #{idx}")
        
        results = v.get("results", {}) if isinstance(v.get("results"), dict) else {}
        resume = results.get("resume_analysis", {})
        job = results.get("job_match", {})
        gaps = results.get("skill_gap", [])

        ats_scores.append(int(resume.get("ats_score", v.get("ats_score", 0))))
        match_scores.append(int(job.get("match_percentage", v.get("match_percentage", 0))))
        gap_counts.append(len(gaps) if isinstance(gaps, list) else 0)
        version_ids.append(v.get("id", ""))
        filenames.append(v.get("resume_filename", f"resume_v{v_num}"))

    return {
        "labels": labels,
        "dates": dates,
        "ats_scores": ats_scores,
        "match_scores": match_scores,
        "gap_counts": gap_counts,
        "version_ids": version_ids,
        "filenames": filenames,
        "total_versions": len(versions)
    }


def generate_side_by_side_diff(
    record_a: Dict[str, Any],
    record_b: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Produces a detailed side-by-side comparison structure between two specific versions
    suitable for the interactive modal diff view.
    """
    delta = calculate_version_delta(record_b, record_a)
    
    results_a = record_a.get("results", {})
    results_b = record_b.get("results", {})

    return {
        "version_a": {
            "id": record_a.get("id", ""),
            "version_number": record_a.get("version_number", 1),
            "filename": record_a.get("resume_filename", ""),
            "created_at": record_a.get("created_at", ""),
            "ats_score": results_a.get("resume_analysis", {}).get("ats_score", 0),
            "match_percentage": results_a.get("job_match", {}).get("match_percentage", 0),
            "strengths": _sanitize_list(results_a.get("resume_analysis", {}).get("strengths")),
            "areas_of_improvement": _sanitize_list(results_a.get("resume_analysis", {}).get("areas_of_improvement")),
            "keywords_found": _sanitize_list(results_a.get("resume_analysis", {}).get("keywords_found")),
            "keywords_missing": _sanitize_list(results_a.get("resume_analysis", {}).get("keywords_missing")),
            "skill_gaps": _extract_skill_names(results_a.get("skill_gap")),
        },
        "version_b": {
            "id": record_b.get("id", ""),
            "version_number": record_b.get("version_number", 2),
            "filename": record_b.get("resume_filename", ""),
            "created_at": record_b.get("created_at", ""),
            "ats_score": results_b.get("resume_analysis", {}).get("ats_score", 0),
            "match_percentage": results_b.get("job_match", {}).get("match_percentage", 0),
            "strengths": _sanitize_list(results_b.get("resume_analysis", {}).get("strengths")),
            "areas_of_improvement": _sanitize_list(results_b.get("resume_analysis", {}).get("areas_of_improvement")),
            "keywords_found": _sanitize_list(results_b.get("resume_analysis", {}).get("keywords_found")),
            "keywords_missing": _sanitize_list(results_b.get("resume_analysis", {}).get("keywords_missing")),
            "skill_gaps": _extract_skill_names(results_b.get("skill_gap")),
        },
        "delta": delta
    }


def compare_two_resume_texts(
    text_v1: str,
    text_v2: str,
    filename_v1: str = "Resume_v1.pdf",
    filename_v2: str = "Resume_v2.pdf",
) -> Dict[str, Any]:
    """
    Compares two raw resume text versions directly without requiring pre-existing database records (#140).
    Identifies newly added keywords, removed items, section changes (education, skills, projects, experience),
    and builds an automated summary delta.
    """
    import re
    from collections import Counter

    def _extract_tokens(txt: str) -> Set[str]:
        words = re.findall(r"\b[A-Za-z0-9#\+\.\-]{2,25}\b", txt.lower())
        stopwords = {
            "the", "and", "for", "with", "from", "this", "that", "have", "were", "been",
            "will", "about", "into", "then", "them", "some", "what", "when", "where",
            "your", "which", "there", "their", "more", "such", "than", "other"
        }
        return {w for w in words if w not in stopwords and not w.isdigit()}

    tokens_v1 = _extract_tokens(text_v1)
    tokens_v2 = _extract_tokens(text_v2)

    added_tokens = sorted(list(tokens_v2 - tokens_v1))
    removed_tokens = sorted(list(tokens_v1 - tokens_v2))
    retained_tokens = sorted(list(tokens_v1 & tokens_v2))

    # Detect common resume section presence
    sections = ["skills", "education", "experience", "projects", "certifications", "achievements"]
    section_comparison = {}
    for sec in sections:
        in_v1 = bool(re.search(rf"\b{sec}\b", text_v1, re.IGNORECASE))
        in_v2 = bool(re.search(rf"\b{sec}\b", text_v2, re.IGNORECASE))
        section_comparison[sec] = {
            "in_v1": in_v1,
            "in_v2": in_v2,
            "status": "added" if (in_v2 and not in_v1) else ("removed" if (in_v1 and not in_v2) else "retained")
        }

    # Word and length counts
    len_v1 = len(text_v1.split())
    len_v2 = len(text_v2.split())
    len_diff = len_v2 - len_v1

    # Heuristic scoring improvements
    est_ats_v1 = min(95, max(40, int(len(set(retained_tokens) | (tokens_v1 - tokens_v2)) * 0.45 + (15 if len_v1 > 150 else 5))))
    est_ats_v2 = min(98, max(45, int(len(set(retained_tokens) | (tokens_v2 - tokens_v1)) * 0.48 + (20 if len_v2 > 180 else 8))))
    ats_delta = est_ats_v2 - est_ats_v1

    # Summary analysis message
    if ats_delta > 0:
        summary_msg = f"Version 2 shows strong positive iteration (+{ats_delta} estimated ATS points) with {len(added_tokens)} newly introduced keywords."
    elif ats_delta == 0:
        summary_msg = "Both resume versions demonstrate comparable keyword density and structural depth."
    else:
        summary_msg = f"Version 2 removed key terms (-{abs(ats_delta)} estimated ATS points). Review whether vital technical proficiencies were omitted."

    return {
        "filename_v1": filename_v1,
        "filename_v2": filename_v2,
        "word_count_v1": len_v1,
        "word_count_v2": len_v2,
        "word_count_delta": len_diff,
        "estimated_ats_v1": est_ats_v1,
        "estimated_ats_v2": est_ats_v2,
        "ats_delta": ats_delta,
        "added_keywords": added_tokens[:30],
        "removed_keywords": removed_tokens[:30],
        "retained_keywords_count": len(retained_tokens),
        "sections": section_comparison,
        "summary": summary_msg
    }


def _sanitize_list(val: Any) -> List[str]:
    if isinstance(val, list):
        return [str(x).strip() for x in val if x and str(x).strip()]
    return []


def _extract_skill_names(val: Any) -> List[str]:
    if not isinstance(val, list):
        return []
    res = []
    for item in val:
        if isinstance(item, dict):
            name = item.get("skill", "")
            if name:
                res.append(str(name).strip())
        elif item:
            res.append(str(item).strip())
    return res

