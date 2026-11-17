"""
Resume Bullet Point Rewriter & Action-Oriented Impact Optimizer (#429).

Identifies the weakest bullet points in candidate experience and project sections
based on three core criteria:
1. Short length / lack of detail (< 45 chars) or excessive run-on length
2. Missing strong action verbs / passive or weak openings ("Worked on", "Responsible for")
3. Missing quantifiable metrics, scale, and results (no numbers, percentages, or impact metrics)

Rewrites the top 5 weakest bullets using the XYZ formula:
Accomplished [X] (Action Verb + Task) as measured by [Y] (Measurable Result) by doing [Z] (Methodology / Tech Stack).

Enforces strict placeholder integrity:
NO invented facts, statistics, or metrics. Standard placeholders such as [X%], [number]+,
[X ms], and [$amount] are utilized so students fill in their own verified results.
Provides side-by-side comparison with instant copy functionality and a helpful empty state.
"""

import os
import re
import html
import json
import logging
from typing import Dict, List, Tuple, Any, Optional

import config
import prompts
from utils.pdf_reader import standardize_resume_sections
from utils.gemini import generate_json_response
from utils.prompt_security import (
    sanitize_untrusted_text,
    encapsulate_untrusted_input,
    build_secure_system_instruction,
    redact_sensitive_information,
)

logger = logging.getLogger(__name__)

# Weak / Passive phrasing patterns at the start of bullet points
WEAK_VERB_PATTERNS: List[Tuple[str, str]] = [
    (r"^(?:worked on|worked with|worked in|was responsible for|responsible for|helped with|helped to|helped in|assisted with|assisted in|assisted|tasked with|handled|managed|involved in|part of a team that|contributed to|did|made)\s+", ""),
    (r"^(?:my role was to|i was tasked with|i was responsible for|i worked on|i helped with|i built|i created|i developed)\s+", ""),
    (r"^(?:support for|supported|helped|aided|participated in)\s+", ""),
]

# Recognized power action verbs (lowercased for matching)
STRONG_ACTION_VERBS = {
    "accelerated", "accomplished", "achieved", "acquired", "administered", "advanced",
    "analyzed", "architected", "authored", "automated", "boosted", "built", "calculated",
    "centralized", "championed", "collaborated", "compiled", "composed", "computed",
    "configured", "consolidated", "constructed", "containerized", "converted", "coordinated",
    "created", "customized", "debugged", "decreased", "delivered", "deployed", "designed",
    "detected", "determined", "developed", "devised", "diagnosed", "directed", "discovered",
    "dispatched", "documented", "drafted", "drove", "eliminated", "enabled", "enforced",
    "engineered", "enhanced", "established", "estimated", "evaluated", "executed", "expanded",
    "expedited", "fabricated", "facilitated", "formulated", "founded", "generated", "guided",
    "halted", "headed", "identified", "implemented", "improved", "increased", "initiated",
    "inspected", "installed", "instituted", "integrated", "interfaced", "introduced",
    "invented", "investigated", "launched", "lead", "led", "leveraged", "maintained",
    "managed", "mapped", "marshaled", "maximized", "mentored", "migrated", "minimized",
    "modeled", "moderated", "modernized", "modified", "monitored", "motivated", "navigated",
    "negotiated", "operated", "orchestrated", "organized", "originated", "overhauled",
    "oversaw", "packaged", "partnered", "performed", "pioneered", "planned", "prepared",
    "presented", "prevented", "prioritized", "processed", "produced", "programmed",
    "promoted", "proposed", "provided", "published", "re-engineered", "rebuilt", "received",
    "recommended", "reconciled", "recorded", "recruited", "redesigned", "reduced",
    "refactored", "refined", "reformed", "regulated", "reinforced", "rejuvenated",
    "remodeled", "reorganized", "repaired", "replaced", "resolved", "restructured",
    "retrieved", "revamped", "reviewed", "revised", "revitalized", "routed", "scaled",
    "scheduled", "screened", "scrutinized", "secured", "selected", "separated", "served",
    "simplified", "simulated", "solved", "spearheaded", "standardized", "started",
    "stimulated", "streamlined", "strengthened", "structured", "supervised", "supplied",
    "supported", "surpassed", "synthesized", "systematized", "tabled", "targeted",
    "tested", "tracked", "trained", "transcribed", "transformed", "translated",
    "troubleshot", "unified", "unraveled", "updated", "upgraded", "utilized", "validated",
    "verified", "visualized", "won", "wrote", "yielded"
}

# Regex to detect existing quantifiable metrics, percentages, currency, counts, or latency.
# Explicitly ignores 4-digit calendar years between 1980 and 2039.
METRIC_REGEX = re.compile(
    r"(?:"
    r"\b\d+(?:\.\d+)?%\b|"  # percentages: 25%, 3.5%
    r"\b\d+(?:\.\d+)?x\b|"  # multipliers: 2x, 10x
    r"[\$€£₹]\s*\d+(?:,\d{3})*(?:\.\d+)?\b|"  # currency: $500, €1000
    r"\b\d+\+\b|"  # plus counts: 500+, 1000+
    r"\b\d+\s*(?:ms|sec|seconds?|mins?|minutes?|hours?|days?|weeks?|months?)\b|"  # time/latency
    r"\b\d+\s*(?:k|m|million|billion|thousand|users|clients|customers|requests|queries|tps|qps|endpoints|records|rows|tests|features|services|servers)\b|"  # scale
    r"\b(?!(?:19[89]\d|20[0-3]\d)\b)\d{2,}\b"  # 2+ digit numbers that are NOT years 1980-2039
    r")",
    re.IGNORECASE
)

# Common bullet line starters to strip
BULLET_PREFIX_REGEX = re.compile(
    r"^[\s\-\*\•\–\▪\▫\◦\+\u2022\u2023\u25e6\u2043\u2219]+|^\s*\d+[\.\)]\s*",
    re.UNICODE
)

# Date check regex to avoid classifying pure date lines as bullets
DATE_LINE_REGEX = re.compile(
    r"^(?:(?:\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|present|\d{4})\b[\s\-\–\|,]*)+)$",
    re.IGNORECASE
)


def extract_bullet_candidates(resume_text: str) -> List[Dict[str, Any]]:
    """
    Extracts candidate bullet points strictly from the Experience and Projects
    sections of the resume text.

    Returns a list of candidate dictionaries:
    [{"original_bullet": str, "section": "experience"|"projects", "raw_line": str}]
    """
    if not resume_text or not isinstance(resume_text, str) or not resume_text.strip():
        return []

    sections = standardize_resume_sections(resume_text)
    candidates: List[Dict[str, Any]] = []
    seen_bullets = set()

    target_sections = [
        ("experience", sections.get("experience", "")),
        ("projects", sections.get("projects", ""))
    ]

    for section_name, section_text in target_sections:
        if not section_text or not section_text.strip():
            continue

        lines = section_text.splitlines()
        for line in lines:
            raw_line = line.strip()
            if not raw_line:
                continue

            # Strip leading bullet indicators
            cleaned_line = BULLET_PREFIX_REGEX.sub("", raw_line).strip()

            # Filter out non-bullet headers, dates, tech stacks, or very short fragments
            if len(cleaned_line) < 18:
                continue

            # Avoid pure date lines (e.g. "May 2023 - Present")
            if DATE_LINE_REGEX.match(cleaned_line):
                continue

            # Avoid pure technology stack listings (e.g. "Tech: React, Node.js, MongoDB")
            if re.match(r"^(?:tech|technologies|tools|stack|skills used):\s*", cleaned_line, re.IGNORECASE):
                continue

            # Must contain at least 3 whitespace-separated words
            words = cleaned_line.split()
            if len(words) < 3:
                continue

            # Check if this line looks like a project/company title header with no verb
            # (e.g. "E-Commerce Web Application | React, Django")
            if "|" in cleaned_line and len(words) <= 6:
                continue
            if re.match(r"^[A-Z0-9\s\-]+(?:\s*-\s*[A-Z0-9\s\-]+)?$", cleaned_line) and len(cleaned_line) < 50:
                # Header in ALL CAPS
                continue

            norm_key = cleaned_line.lower()
            if norm_key in seen_bullets:
                continue

            seen_bullets.add(norm_key)
            candidates.append({
                "original_bullet": cleaned_line,
                "section": section_name,
                "raw_line": raw_line
            })

    return candidates


def evaluate_bullet_weakness(bullet: str) -> Dict[str, Any]:
    """
    Evaluates the weakness of a resume bullet point across the 3 core criteria:
    1. Length: Bullets that are too short (< 45 chars) or excessively run-on (> 260 chars)
    2. Missing Action Verb: Starts with weak/passive phrasing or lacks a recognized power verb
    3. Missing Numbers: Devoid of quantifiable metrics, percentages, counts, or scale

    Returns an evaluation dictionary with weakness score (higher = weaker)
    and specific explanatory weakness reasons.
    """
    clean_bullet = (bullet or "").strip()
    if not clean_bullet:
        return {
            "bullet": "",
            "weakness_score": 100,
            "weakness_reasons": ["Empty bullet point"],
            "has_weak_verb": True,
            "has_no_action_verb": True,
            "has_no_metrics": True,
            "length_issue": True,
            "length": 0
        }

    weakness_score = 0
    reasons: List[str] = []

    # 1. Length Criterion
    b_len = len(clean_bullet)
    length_issue = False
    if b_len < 40:
        weakness_score += 35
        length_issue = True
        reasons.append("Too brief (< 40 chars) to convey technical depth or impact")
    elif 40 <= b_len < 60:
        weakness_score += 15
        length_issue = True
        reasons.append("Short statement lacking technical context or scope")
    elif b_len > 260:
        weakness_score += 10
        length_issue = True
        reasons.append("Run-on bullet (> 260 chars) lacking concise impact")

    # 2. Missing Action Verb / Weak Phrasing Criterion
    has_weak_verb = False
    has_no_action_verb = False

    is_weak_starter = any(re.search(pat[0], clean_bullet, re.IGNORECASE) for pat in WEAK_VERB_PATTERNS)
    if is_weak_starter:
        weakness_score += 35
        has_weak_verb = True
        has_no_action_verb = True
        reasons.append("Starts with passive/weak phrasing ('Worked on' / 'Responsible for')")
    else:
        # Check first word against strong action verb taxonomy
        first_word = clean_bullet.split()[0].lower().strip(".,:;()-")
        if first_word not in STRONG_ACTION_VERBS:
            weakness_score += 20
            has_no_action_verb = True
            reasons.append("Lacks a strong opening action verb")

    # 3. Missing Numbers / Metrics Criterion
    has_no_metrics = False
    if not METRIC_REGEX.search(clean_bullet):
        weakness_score += 30
        has_no_metrics = True
        reasons.append("Missing quantifiable metrics, percentages, or measurable results")

    if not reasons:
        reasons.append("Good baseline bullet that can be optimized with sharper metrics")

    return {
        "bullet": clean_bullet,
        "weakness_score": weakness_score,
        "weakness_reasons": reasons,
        "has_weak_verb": has_weak_verb,
        "has_no_action_verb": has_no_action_verb,
        "has_no_metrics": has_no_metrics,
        "length_issue": length_issue,
        "length": b_len
    }


def select_weakest_bullets(
    candidate_bullets: List[Dict[str, Any]],
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Ranks candidate bullet points by weakness score (weakest first) and
    selects up to `limit` (default 5) bullets for optimization.
    """
    if not candidate_bullets:
        return []

    evaluated: List[Dict[str, Any]] = []
    seen = set()

    for item in candidate_bullets:
        txt = item.get("original_bullet", "").strip()
        if not txt or txt.lower() in seen:
            continue
        seen.add(txt.lower())

        eval_res = evaluate_bullet_weakness(txt)
        evaluated.append({
            "original_bullet": txt,
            "section": item.get("section", "experience"),
            "weakness_score": eval_res["weakness_score"],
            "weakness_reasons": eval_res["weakness_reasons"],
            "has_weak_verb": eval_res["has_weak_verb"],
            "has_no_action_verb": eval_res["has_no_action_verb"],
            "has_no_metrics": eval_res["has_no_metrics"],
            "length": eval_res["length"]
        })

    # Sort descending by weakness score (weakest first); tie break by shorter length
    evaluated.sort(key=lambda x: (-x["weakness_score"], x["length"]))

    return evaluated[:limit]


def sanitize_metrics_with_placeholders(
    suggested_rewrite: str,
    original_bullet: str
) -> str:
    """
    Enforces strict acceptance criterion:
    'Suggestions never contain invented metrics (placeholders are used instead).'

    Scans the suggested rewrite. If any metric, number, or percentage was introduced
    that was NOT present in the candidate's original bullet (and not already inside brackets [ ]),
    it replaces the invented metric with standard bracketed placeholders ([X%], [number], [X ms]).
    """
    if not suggested_rewrite:
        return ""

    original_text = original_bullet or ""

    # Helper to check if a token was in the original text
    def was_in_original(token: str) -> bool:
        clean_tok = re.sub(r"[^\w\.]", "", token).lower()
        clean_orig = re.sub(r"[^\w\.]", " ", original_text).lower().split()
        return clean_tok in clean_orig

    res = suggested_rewrite

    # 1. Replace unbracketed percentages not in original with [X%]
    def replace_percent(match):
        full = match.group(0)
        # Check if already enclosed in brackets e.g. [X%] or [25%]
        start = match.start()
        end = match.end()
        if start > 0 and res[start - 1] == "[" and end < len(res) and res[end] == "]":
            return full
        if was_in_original(full):
            return full
        return "[X%]"

    res = re.sub(r"\b\d+(?:\.\d+)?%", replace_percent, res)

    # 2. Replace unbracketed latencies (e.g. 50ms) not in original with [X ms]
    def replace_latency(match):
        full = match.group(0)
        start = match.start()
        end = match.end()
        if start > 0 and res[start - 1] == "[" and end < len(res) and res[end] == "]":
            return full
        if was_in_original(full):
            return full
        return "[X ms]"

    res = re.sub(r"\b\d+\s*ms\b", replace_latency, res, flags=re.IGNORECASE)

    # 3. Replace unbracketed currency not in original with [$amount]
    def replace_currency(match):
        full = match.group(0)
        start = match.start()
        end = match.end()
        if start > 0 and res[start - 1] == "[" and end < len(res) and res[end] == "]":
            return full
        if was_in_original(full):
            return full
        return "[$amount]"

    res = re.sub(r"[\$€£₹]\s*\d+(?:,\d{3})*(?:\.\d+)?", replace_currency, res)

    # 4. Replace unbracketed numbers (>= 2 digits, excluding calendar years 1980-2039) not in original with [number]
    def replace_numbers(match):
        full = match.group(0)
        start = match.start()
        end = match.end()
        if start > 0 and res[start - 1] == "[" and end < len(res) and res[end] == "]":
            return full
        # Skip years
        if full.isdigit() and 1980 <= int(full) <= 2039:
            return full
        if was_in_original(full):
            return full
        return "[number]"

    res = re.sub(r"\b\d{2,}\b", replace_numbers, res)

    # Clean any accidental double brackets like [[X%]]
    res = re.sub(r"\[\[(.*?)\]\]", r"[\1]", res)

    return res.strip()


def format_placeholders_for_display(text: str) -> str:
    """
    Escapes HTML for safe rendering and wraps bracketed placeholders (e.g., [X%], [number]+)
    in visual badge tags for clear student guidance in the UI.
    """
    if not text:
        return ""

    escaped = html.escape(text)

    # Wrap placeholders in styling badge
    formatted = re.sub(
        r"\[([A-Za-z0-9%_+\-\$#\s]+)\]",
        r'<span class="badge bg-primary-subtle text-primary border border-primary-subtle px-1 py-0 rounded font-monospace small">[\1]</span>',
        escaped
    )

    return formatted


def _generate_rule_based_rewrite(
    original_bullet: str,
    section: str = "experience",
    target_role: str = "Software Engineer",
    index: int = 0
) -> Dict[str, Any]:
    """
    High-fidelity deterministic algorithmic fallback for rewriting bullet points
    when Gemini API is offline or unconfigured.

    Strictly complies with the requirement:
    Never invent facts or metrics; strictly use placeholders [X%], [number]+, [X ms], etc.
    """
    clean_text = original_bullet.strip().rstrip(".")
    clean_text = BULLET_PREFIX_REGEX.sub("", clean_text).strip()

    # Strip weak verbs / passive starters
    core_task = clean_text
    for pat, rep in WEAK_VERB_PATTERNS:
        core_task = re.sub(pat, rep, core_task, flags=re.IGNORECASE).strip()

    if not core_task:
        core_task = "core features and scalable system components"

    # Identify domain keywords to select the most appropriate power action verb
    text_lower = original_bullet.lower()

    if any(k in text_lower for k in ["api", "backend", "database", "sql", "server", "microservice", "fastapi", "django"]):
        action_verb = ["Architected", "Engineered", "Optimized", "Scaled"][index % 4]
        result_templates = [
            "reducing response latency by [X%] and supporting [number]+ concurrent users",
            "optimizing query execution time by [X%] and streamlining data pipelines across [number]+ endpoints",
            "improving system throughput by [X%] and cutting operational overhead by [Y hours]",
            "achieving [X%] test coverage and eliminating [number] production defects"
        ]
    elif any(k in text_lower for k in ["ui", "frontend", "react", "css", "html", "javascript", "user interface"]):
        action_verb = ["Engineered", "Implemented", "Revamped", "Designed"][index % 4]
        result_templates = [
            "improving client-side page load speed by [X%] across [number]+ monthly active users",
            "enhancing responsive user experience by [X%] and decreasing bounce rate by [Y%]",
            "streamlining workflow navigation for [number]+ users and boosting task completion rate by [X%]",
            "delivering accessible, cross-browser interfaces achieving [X%] compliance"
        ]
    elif any(k in text_lower for k in ["test", "testing", "qa", "bug", "automated", "pytest", "selenium"]):
        action_verb = ["Automated", "Engineered", "Streamlined", "Standardized"][index % 4]
        result_templates = [
            "increasing automated test coverage to [X%] and reducing regression bug escape rate by [Y%]",
            "cutting test cycle duration by [X%] and preventing [number] critical release regressions",
            "accelerating continuous integration pipelines by [X%] across [number]+ test suites",
            "achieving [X%] coverage across core workflows and eliminating [number] bottlenecks"
        ]
    elif any(k in text_lower for k in ["data", "model", "ml", "machine learning", "analysis", "pipeline", "etl"]):
        action_verb = ["Formulated", "Engineered", "Optimized", "Constructed"][index % 4]
        result_templates = [
            "improving model prediction accuracy to [X%] and processing [number]+ records daily",
            "reducing data ingestion pipeline latency by [X%] across [number]+ daily datasets",
            "increasing pipeline throughput by [X%] and cutting manual processing time by [Y hours]",
            "achieving [X%] precision while scaling data operations to [number]+ concurrent requests"
        ]
    else:
        action_verb = ["Engineered", "Spearheaded", "Optimized", "Implemented", "Streamlined"][index % 5]
        result_templates = [
            "improving overall execution efficiency by [X%] and reducing turnaround time by [Y hours]",
            "enhancing system reliability by [X%] and supporting [number]+ active users",
            "streamlining operational workflows to reduce manual interventions by [X%]",
            "achieving [X%] performance improvement and accelerating release cycle by [Z weeks]"
        ]

    chosen_result = result_templates[index % len(result_templates)]

    # Smooth casing transition
    first_word = core_task.split()[0] if core_task.split() else "task"
    if first_word.isupper():
        task_str = core_task
    else:
        # Lowercase first char for smooth sentence concatenation unless proper noun
        proper_nouns = ["Python", "Java", "Docker", "React", "AWS", "SQL", "Git", "FastAPI", "Django", "Kubernetes", "Linux"]
        if any(p.lower() == first_word.lower() for p in proper_nouns):
            task_str = core_task
        else:
            task_str = core_task[0].lower() + core_task[1:] if len(core_task) > 1 else core_task.lower()

    suggested_rewrite = f"{action_verb} {task_str}, {chosen_result}."

    return {
        "original_bullet": original_bullet,
        "action_verb": action_verb,
        "task": task_str,
        "measurable_result": chosen_result,
        "suggested_rewrite": suggested_rewrite
    }


def rewrite_weak_bullets(
    weak_bullets: List[Dict[str, Any]],
    company_name: str = "General",
    target_role: str = "Software Engineer"
) -> List[Dict[str, Any]]:
    """
    Rewrites the selected weak bullets using Action Verb + Task + Measurable Result
    formula with strict placeholders.

    Tries Gemini API first (if configured), falling back gracefully to the
    high-fidelity rule-based generator.
    """
    if not weak_bullets:
        return []

    rewritten_results: List[Dict[str, Any]] = []

    # Attempt Gemini API call
    try:
        bullets_payload = [
            {
                "index": idx + 1,
                "section": b.get("section", "experience"),
                "original_bullet": sanitize_untrusted_text(b.get("original_bullet", ""), max_length=500),
                "weakness_reasons": b.get("weakness_reasons", [])
            }
            for idx, b in enumerate(weak_bullets)
        ]

        encapsulated_json = encapsulate_untrusted_input(
            json.dumps(bullets_payload, indent=2),
            document_type="weak_resume_bullets"
        )

        user_prompt = prompts.BULLET_REWRITE_USER_PROMPT_TEMPLATE.format(
            company_name=company_name or "Target Company",
            target_role=target_role or "Software Engineer",
            bullets_json=encapsulated_json
        )

        system_instruction = build_secure_system_instruction(
            prompts.BULLET_REWRITE_SYSTEM_INSTRUCTION
        )

        response_json = generate_json_response(
            system_instruction=system_instruction,
            prompt=user_prompt,
            feature="analysis"
        )

        response_json = redact_sensitive_information(response_json)

        if isinstance(response_json, dict) and "rewrites" in response_json and isinstance(response_json["rewrites"], list):
            ai_rewrites = response_json["rewrites"]
            # Match AI rewrites to weak bullets
            for idx, b in enumerate(weak_bullets):
                orig = b.get("original_bullet", "")
                ai_match = None
                if idx < len(ai_rewrites):
                    ai_match = ai_rewrites[idx]
                else:
                    for item in ai_rewrites:
                        if item.get("original_bullet", "").strip().lower() == orig.strip().lower():
                            ai_match = item
                            break

                if ai_match and isinstance(ai_match, dict) and ai_match.get("suggested_rewrite"):
                    raw_rewrite = ai_match.get("suggested_rewrite", "").strip()
                    # Strictly sanitize: never allow invented metrics, enforce placeholders
                    sanitized_rewrite = sanitize_metrics_with_placeholders(raw_rewrite, orig)
                    action_v = ai_match.get("action_verb") or sanitized_rewrite.split()[0]

                    rewritten_results.append({
                        **b,
                        "action_verb": action_v,
                        "task": ai_match.get("task", ""),
                        "measurable_result": ai_match.get("measurable_result", ""),
                        "suggested_rewrite": sanitized_rewrite,
                        "suggested_rewrite_formatted": format_placeholders_for_display(sanitized_rewrite)
                    })
                else:
                    # Fallback for this individual item
                    fallback = _generate_rule_based_rewrite(
                        orig,
                        section=b.get("section", "experience"),
                        target_role=target_role,
                        index=idx
                    )
                    rewritten_results.append({
                        **b,
                        **fallback,
                        "suggested_rewrite_formatted": format_placeholders_for_display(fallback["suggested_rewrite"])
                    })

            if len(rewritten_results) == len(weak_bullets):
                return rewritten_results
    except Exception as e:
        logger.warning(f"Gemini bullet rewrites failed ({e}). Utilizing rule-based optimizer fallback.")

    # Rule-based fallback generator
    rewritten_results = []
    for idx, b in enumerate(weak_bullets):
        orig = b.get("original_bullet", "")
        fallback = _generate_rule_based_rewrite(
            orig,
            section=b.get("section", "experience"),
            target_role=target_role,
            index=idx
        )
        sanitized_rewrite = sanitize_metrics_with_placeholders(fallback["suggested_rewrite"], orig)
        rewritten_results.append({
            **b,
            **fallback,
            "suggested_rewrite": sanitized_rewrite,
            "suggested_rewrite_formatted": format_placeholders_for_display(sanitized_rewrite)
        })

    return rewritten_results


def get_bullet_rewrites_for_analysis(analysis_record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main orchestration function.
    Given a placement analysis record, extracts candidate bullets from experience
    and projects sections, identifies the top 5 weakest, and generates
    action-oriented before/after rewrites with placeholders.

    Returns:
    {
        "has_bullets": bool,
        "bullets": List[Dict[str, Any]],
        "total_detected": int,
        "empty_message": str
    }
    """
    empty_fallback = {
        "has_bullets": False,
        "bullets": [],
        "total_detected": 0,
        "empty_message": (
            "No bullet points detected in Experience or Projects sections. "
            "Use bullet points starting with strong action verbs (e.g., Engineered, Spearheaded, Optimized) "
            "and quantifiable metrics ([X%], [number]+) to highlight your impact."
        )
    }

    if not analysis_record or not isinstance(analysis_record, dict):
        return empty_fallback

    # Extract resume text
    try:
        from utils.resume_keyword_highlighter import get_analysis_resume_text
        resume_text = get_analysis_resume_text(analysis_record)
    except Exception as e:
        logger.warning(f"Could not retrieve resume text via get_analysis_resume_text: {e}")
        resume_text = analysis_record.get("resume_text") or ""

    if not resume_text or not isinstance(resume_text, str) or not resume_text.strip():
        return empty_fallback

    # Extract candidates from experience and projects
    candidate_bullets = extract_bullet_candidates(resume_text)
    if not candidate_bullets:
        return empty_fallback

    # Select top 5 weakest bullets
    weakest_5 = select_weakest_bullets(candidate_bullets, limit=5)
    if not weakest_5:
        return empty_fallback

    company_name = analysis_record.get("company_name", "Target Company")
    target_role = "Software Engineer"
    # Try to extract role from job description or results
    results = analysis_record.get("results") or {}
    if isinstance(results, dict):
        role_pref = results.get("role_preparation") or results.get("role_prep")
        if isinstance(role_pref, dict) and role_pref.get("role_title"):
            target_role = role_pref["role_title"]

    # Generate rewrites
    rewritten_bullets = rewrite_weak_bullets(
        weak_bullets=weakest_5,
        company_name=company_name,
        target_role=target_role
    )

    return {
        "has_bullets": bool(rewritten_bullets),
        "bullets": rewritten_bullets,
        "total_detected": len(candidate_bullets),
        "empty_message": ""
    }
