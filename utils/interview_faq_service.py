"""
Frequently Asked Interview Questions Aggregator (utils/interview_faq_service.py)
================================================================================
Aggregates, normalizes, and groups frequently asked questions from approved,
unreported company interview experiences without AI calls (#694).

Key Capabilities:
1. Deterministic Normalization:
   - Lowercases, trims surrounding punctuation, removes list bullets/numbering,
     and collapses multiple whitespaces into a single space.
2. Lightweight Token Overlap Similarity:
   - Extracts stemmed lexical tokens (ignoring conversational stopwords).
   - Computes Jaccard token similarity & overlap coefficient to group near-identical questions.
   - Counts occurrences ONCE per distinct interview experience.
3. Strict Content Moderation & Exclusion:
   - Excludes reported experiences (`reported_flag == 1`).
   - Excludes rejected or non-approved experiences (`moderation_status != 'approved'`).
   - Excludes hidden experiences (`is_hidden == 1` or `hidden == 1`).
   - Enforces a minimum experience count threshold (default >= 3) before showing results.
4. Practice Mode Link Generation:
   - Formats a direct deep-link to the interview practice mode for each top question.
"""

from __future__ import annotations

import html
import json
import logging
import math
import re
import string
import urllib.parse
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

# Common English conversational/question stopwords that add noise to question similarity
COMMON_QUESTION_STOPWORDS: Set[str] = {
    "a", "an", "the", "in", "on", "at", "of", "to", "for", "with", "by", "from",
    "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had",
    "what", "how", "why", "when", "where", "which", "who", "whom",
    "can", "could", "would", "should", "will", "shall", "may", "might",
    "you", "your", "me", "my", "we", "our", "us",
    "tell", "explain", "describe", "discuss", "give", "please", "briefly",
    "and", "or", "but", "if", "then", "about",
}

# Regex to strip leading list prefixes like "1.", "1)", "a)", "-", "*", "•", "Q1:"
LEADING_PREFIX_RE = re.compile(
    r"^\s*(?:(?:q(?:uestion)?\s*\d+[:\.\)]?)|(?:\d+[\.\)]?)|(?:[a-zA-Z][\.\)])|[-*•–—])\s*",
    re.IGNORECASE,
)

PUNCTUATION_CHARS = string.punctuation + " \t\r\n’'\"“”¿¡`´"


def normalize_question(text: str) -> str:
    """
    Normalizes a question line for deterministic clustering:
    - Unescapes HTML entities.
    - Strips leading numbers, question prefixes (e.g. '1.', 'Q:').
    - Converts to lowercase.
    - Collapses multiple whitespace characters into single space.
    - Trims leading and trailing punctuation (including '?', '.', '!', quotes).
    """
    if not text:
        return ""

    raw = html.unescape(str(text)).strip()
    if not raw:
        return ""

    # Remove leading numbering, e.g. "1. What is..." or "Q1: " or "- "
    cleaned = LEADING_PREFIX_RE.sub("", raw).strip()

    # Lowercase
    cleaned = cleaned.lower()

    # Collapse multiple whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Trim leading and trailing punctuation & quotes
    cleaned = re.sub(r"^[^\w\s#+]+|[^\w\s#+]+$", "", cleaned).strip()

    return cleaned


def clean_display_question(text: str) -> str:
    """
    Cleans a question string for user-facing display:
    - Removes numbering and leading bullet prefixes.
    - Preserves internal casing where appropriate.
    - Ensures proper sentence capitalization and a trailing question mark.
    """
    if not text:
        return ""

    cleaned = html.unescape(str(text)).strip()
    cleaned = LEADING_PREFIX_RE.sub("", cleaned).strip()
    # Trim leading quote or bullet punctuation
    cleaned = re.sub(r"^[^\w\s#+]+", "", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned:
        return ""

    # Capitalize the very first character if alphabetic
    first_char = cleaned[0].upper()
    cleaned = first_char + cleaned[1:] if len(cleaned) > 1 else first_char

    # Ensure trailing question mark if not ending in question punctuation
    if not cleaned.endswith(("?", "!", ".")):
        cleaned += "?"

    return cleaned


def _light_stem(word: str) -> str:
    """Lightweight rule-based suffix normalization without external dependencies."""
    w = word.lower()
    if len(w) > 4 and w.endswith("ing"):
        w = w[:-3]
    elif len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith("es"):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("ed"):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    return w


def tokenize_question(normalized_text: str, filter_stopwords: bool = True) -> Set[str]:
    """
    Extracts stemmed word tokens from normalized question text.
    Preserves programming symbols like C++, C#, .NET.
    """
    if not normalized_text:
        return set()

    # Match alphanumeric words or special tech tokens
    words = re.findall(r"[a-z0-9+#.]+", normalized_text.lower())
    tokens = set()

    for word in words:
        # Strip trailing dots from abbreviations
        clean_word = word.rstrip(".")
        if not clean_word:
            continue

        if filter_stopwords and clean_word in COMMON_QUESTION_STOPWORDS:
            continue

        tokens.add(_light_stem(clean_word))

    # If all tokens were filtered out as stopwords, fallback to keeping raw tokens
    if not tokens and words:
        tokens = {_light_stem(w.rstrip(".")) for w in words if w.rstrip(".")}

    return tokens


def calculate_token_similarity(tokens1: Set[str], tokens2: Set[str]) -> Tuple[float, float]:
    """
    Calculates Jaccard similarity and Overlap coefficient between two token sets.
    Returns: (jaccard_similarity, overlap_coefficient)
    """
    if not tokens1 or not tokens2:
        return 0.0, 0.0

    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)

    jaccard = len(intersection) / len(union) if union else 0.0
    overlap = len(intersection) / min(len(tokens1), len(tokens2)) if tokens1 and tokens2 else 0.0

    return jaccard, overlap


def is_near_identical_question(
    norm_q1: str,
    norm_q2: str,
    tokens1: Optional[Set[str]] = None,
    tokens2: Optional[Set[str]] = None,
    jaccard_threshold: float = 0.60,
    overlap_threshold: float = 0.80,
) -> bool:
    """
    Evaluates whether two questions are identical or near-identical:
    - True if normalized strings match exactly.
    - True if Jaccard token similarity >= jaccard_threshold.
    - True if token overlap coefficient >= overlap_threshold and Jaccard >= 0.45.
    """
    if norm_q1 == norm_q2:
        return True

    t1 = tokens1 if tokens1 is not None else tokenize_question(norm_q1)
    t2 = tokens2 if tokens2 is not None else tokenize_question(norm_q2)

    if not t1 or not t2:
        return False

    jaccard, overlap = calculate_token_similarity(t1, t2)

    if jaccard >= jaccard_threshold:
        return True

    if overlap >= overlap_threshold and jaccard >= 0.45:
        return True

    return False


def is_experience_eligible(exp: Dict[str, Any]) -> bool:
    """
    Validates that an interview experience is eligible for public FAQ aggregation:
    - Must NOT be reported (`reported_flag == 1`).
    - Must NOT be rejected or unapproved (`moderation_status` must be 'approved' if present).
    - Must NOT be hidden (`is_hidden` or `hidden` must not be truthy).
    """
    if not isinstance(exp, dict):
        return False

    # Check reported flag
    if bool(exp.get("reported_flag")):
        return False

    # Check moderation status (if column exists)
    mod_status = exp.get("moderation_status")
    if mod_status is not None:
        status_clean = str(mod_status).strip().lower()
        if status_clean != "approved":
            return False

    # Check hidden flags
    if bool(exp.get("is_hidden")) or bool(exp.get("hidden")):
        return False

    return True


def extract_questions_from_experience(exp: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Extracts individual question lines from an interview experience record.
    Supports structured 'rounds' list, 'rounds_json', and top-level 'questions_asked'.
    Returns list of dicts: [{"question": str, "round": str}]
    """
    extracted: List[Dict[str, str]] = []

    # 1. Inspect rounds
    rounds_data = exp.get("rounds")
    if not rounds_data and exp.get("rounds_json"):
        try:
            rounds_data = json.loads(exp["rounds_json"])
        except Exception:
            rounds_data = []

    if isinstance(rounds_data, list):
        for round_idx, r in enumerate(rounds_data):
            if not isinstance(r, dict):
                continue

            category = (r.get("category") or r.get("round_type") or f"Round {round_idx + 1}").strip()
            # Standardize category labels
            cat_lower = category.lower()
            if "code" in cat_lower or "oa" in cat_lower or "online assessment" in cat_lower:
                canonical_round = "Coding"
            elif "hr" in cat_lower or "behavioral" in cat_lower or "fit" in cat_lower:
                canonical_round = "HR"
            else:
                canonical_round = "Technical"

            # Check both 'questions' and structured 'questions_asked'
            q_source = r.get("questions") or r.get("questions_asked") or []
            if isinstance(q_source, str):
                lines = q_source.splitlines()
            elif isinstance(q_source, list):
                lines = []
                for item in q_source:
                    if isinstance(item, str):
                        lines.extend(item.splitlines())
                    elif isinstance(item, dict) and "question" in item:
                        lines.append(str(item["question"]))
            else:
                lines = []

            for line in lines:
                q_text = line.strip()
                if len(q_text) >= 4:
                    extracted.append({
                        "question": q_text,
                        "round": canonical_round,
                    })

    # 2. Check top-level questions_asked if present and no rounds found
    if not extracted and exp.get("questions_asked"):
        raw_qa = exp["questions_asked"]
        lines = raw_qa.splitlines() if isinstance(raw_qa, str) else (raw_qa if isinstance(raw_qa, list) else [])
        for line in lines:
            q_text = str(line).strip()
            if len(q_text) >= 4:
                extracted.append({
                    "question": q_text,
                    "round": "Technical",
                })

    return extracted


def build_practice_url(question_text: str, company_name: str = "", category: str = "Technical") -> str:
    """Builds a direct deep-link to the interview practice mode for a specific question."""
    params = {
        "question_text": question_text,
        "company": company_name or "General",
        "category": category or "Technical",
    }
    return f"/interview/bookmarks/practice?{urllib.parse.urlencode(params)}"


def group_frequently_asked_questions(
    experiences: List[Dict[str, Any]],
    min_experiences: int = 3,
    limit: int = 10,
    company_name: str = "",
) -> List[Dict[str, Any]]:
    """
    Groups questions from eligible experiences by token similarity and returns the top questions.
    Requirements:
    - Excludes hidden, rejected, or reported experiences.
    - If eligible experiences < min_experiences, returns an empty list (too little data).
    - Counts questions once per distinct experience.
    - Limits result to top 10 questions.
    """
    # Filter eligible experiences
    eligible_exps = [e for e in experiences if is_experience_eligible(e)]

    # Section is NOT shown when there is too little data (< min_experiences)
    if len(eligible_exps) < min_experiences:
        return []

    # Clusters list
    clusters: List[Dict[str, Any]] = []

    for exp_idx, exp in enumerate(eligible_exps):
        exp_id = str(exp.get("id") or f"exp_idx_{exp_idx}")
        questions_list = extract_questions_from_experience(exp)

        # Track questions seen in THIS experience to guarantee 1 count per experience
        matched_cluster_indices_in_this_exp: Set[int] = set()

        for item in questions_list:
            raw_q = item["question"]
            round_cat = item["round"]

            norm_q = normalize_question(raw_q)
            if not norm_q or len(norm_q) < 4:
                continue

            tokens = tokenize_question(norm_q)

            # Find matching cluster
            matched_idx: Optional[int] = None
            best_sim = 0.0

            for c_idx, cluster in enumerate(clusters):
                if is_near_identical_question(
                    norm_q,
                    cluster["normalized_question"],
                    tokens,
                    cluster["tokens"],
                ):
                    jaccard, _ = calculate_token_similarity(tokens, cluster["tokens"])
                    if jaccard > best_sim:
                        best_sim = jaccard
                        matched_idx = c_idx

            if matched_idx is not None:
                cluster = clusters[matched_idx]
                # Increment round counts
                cluster["round_counts"][round_cat] += 1

                # Count distinct experience once
                cluster["experience_ids"].add(exp_id)
                matched_cluster_indices_in_this_exp.add(matched_idx)

                # Keep cleaner or more descriptive canonical question
                if len(raw_q) > len(cluster["canonical_question"]) and raw_q.istitle():
                    cluster["canonical_question"] = clean_display_question(raw_q)
            else:
                new_idx = len(clusters)
                clean_display = clean_display_question(raw_q)
                clusters.append({
                    "canonical_question": clean_display,
                    "normalized_question": norm_q,
                    "tokens": tokens,
                    "experience_ids": {exp_id},
                    "round_counts": Counter({round_cat: 1}),
                })
                matched_cluster_indices_in_this_exp.add(new_idx)

    if not clusters:
        return []

    # Sort clusters primarily by distinct experience count descending, then alphabetically
    clusters.sort(
        key=lambda c: (-len(c["experience_ids"]), c["canonical_question"].lower())
    )

    total_eligible = len(eligible_exps)
    results: List[Dict[str, Any]] = []

    for c in clusters[:limit]:
        count = len(c["experience_ids"])
        most_common_round = c["round_counts"].most_common(1)[0][0] if c["round_counts"] else "Technical"
        canonical_q = c["canonical_question"]
        practice_url = build_practice_url(
            question_text=canonical_q,
            company_name=company_name,
            category=most_common_round,
        )

        results.append({
            "question": canonical_q,
            "normalized_question": c["normalized_question"],
            "count": count,
            "round": most_common_round,
            "practice_url": practice_url,
            "percentage": round((count / total_eligible) * 100, 1) if total_eligible > 0 else 0.0,
            "total_experiences": total_eligible,
        })

    return results


def get_frequently_asked_questions(
    company_name: str,
    min_experiences: int = 3,
    limit: int = 10,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Queries the database for interview experiences of the given company and computes
    frequently asked questions. Excludes reported, rejected, or hidden content.
    Returns empty list if fewer than min_experiences exist.
    """
    clean_company = (company_name or "").strip()
    if not clean_company or clean_company.lower() in ("all", "any"):
        return []

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Query experiences for this company
            # We filter reported_flag = 0 at the DB level, and apply eligibility check
            query = """
                SELECT * FROM interview_experiences
                WHERE LOWER(company_name) = LOWER(?)
                  AND reported_flag = 0
                ORDER BY interview_date DESC, created_at DESC
            """
            cursor.execute(query, (clean_company,))
            rows = cursor.fetchall()

            experiences = []
            for r in rows:
                rec = dict(r)
                if rec.get("rounds_json"):
                    try:
                        rec["rounds"] = json.loads(rec["rounds_json"])
                    except Exception:
                        rec["rounds"] = []
                experiences.append(rec)

            return group_frequently_asked_questions(
                experiences=experiences,
                min_experiences=min_experiences,
                limit=limit,
                company_name=clean_company,
            )
    except Exception as e:
        logger.error(f"Error computing frequently asked questions for {clean_company}: {e}")
        return []
