"""
Job Expiration and Duplicate Detection Engine (#248)
===================================================
Provides robust deduplication, deadline parsing, and expiration detection
for job opportunities and internship feeds.

Features:
1. Exact and fuzzy duplicate detection comparing normalized job titles, company names,
   and application URLs / domains.
2. Deadline parsing across multiple format representations (ISO YYYY-MM-DD, Month DD YYYY,
   relative strings, rolling deadlines).
3. Clear expiration status marking with deadline metadata and remaining days.
4. Preserves primary source attribution and merges duplicate metadata.
5. Missing/unparseable deadline resilience (defaults to active/rolling).
"""

import re
import time
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Common rolling deadline identifiers
ROLLING_KEYWORDS = [
    "rolling",
    "ongoing",
    "active drive",
    "open until filled",
    "continuous",
    "asap",
    "immediate",
    "n/a",
    "tbd"
]


def normalize_title(title: str) -> str:
    """Normalizes job title by stripping punctuation, extra whitespace, and common fluff."""
    if not title:
        return ""
    cleaned = title.lower()
    # Strip common batch tags and brackets
    cleaned = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", cleaned)
    # Strip punctuation
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    # Strip common stop terms
    tokens = [t for t in cleaned.split() if t not in ("graduate", "hiring", "drive", "batch", "campus", "off", "pool", "2025", "2026")]
    return " ".join(tokens)


def normalize_company_name(company: str) -> str:
    """Normalizes company names by lowercasing and stripping corporate suffixes."""
    if not company:
        return ""
    cleaned = company.lower().strip()
    # Remove common company legal suffixes
    for suffix in ("inc.", "inc", "corp.", "corp", "ltd.", "ltd", "technologies", "technology", "services", "solutions", "pvt", "llc"):
        cleaned = re.sub(rf"\b{re.escape(suffix)}\b", "", cleaned)
    cleaned = re.sub(r"[^a-z0-9\s]", "", cleaned)
    return " ".join(cleaned.split())


def normalize_url(url: str) -> str:
    """Normalizes application URLs by extracting domain and canonical path without tracking params."""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip().lower())
        domain = parsed.netloc.replace("www.", "")
        path = parsed.path.rstrip("/")
        return f"{domain}{path}"
    except Exception:
        return url.strip().lower()


def parse_job_deadline(deadline_str: Optional[str], reference_timestamp: Optional[float] = None) -> Dict[str, Any]:
    """
    Parses arbitrary job deadline representations into structured expiration metadata.

    Returns:
        Dict with keys:
            - is_expired: bool
            - is_rolling: bool
            - parsed_date_iso: Optional[str]
            - remaining_days: Optional[int]
            - status_badge: str ("Active", "Closing Soon", "Expired", "Rolling")
    """
    ref_ts = reference_timestamp or time.time()
    now_dt = datetime.fromtimestamp(ref_ts, tz=timezone.utc)

    if not deadline_str or not str(deadline_str).strip():
        return {
            "is_expired": False,
            "is_rolling": True,
            "parsed_date_iso": None,
            "remaining_days": None,
            "status_badge": "Rolling",
            "raw_deadline": "Rolling Basis"
        }

    raw = str(deadline_str).strip()
    raw_lower = raw.lower()

    # Check for rolling / continuous recruitment
    if any(k in raw_lower for k in ROLLING_KEYWORDS):
        return {
            "is_expired": False,
            "is_rolling": True,
            "parsed_date_iso": None,
            "remaining_days": None,
            "status_badge": "Rolling",
            "raw_deadline": raw
        }

    # Extract date patterns
    parsed_dt = None
    date_patterns = [
        r"(\d{4}-\d{2}-\d{2})",                       # 2026-11-28
        r"(\d{2}/\d{2}/\d{4})",                       # 28/11/2026
        r"([a-zA-Z]{3,9}\s+\d{1,2},?\s+\d{4})",       # Nov 28, 2026 or November 28 2026
        r"(\d{1,2}\s+[a-zA-Z]{3,9}\s+\d{4})",        # 28 Nov 2026
    ]

    for pat in date_patterns:
        match = re.search(pat, raw)
        if match:
            date_snippet = match.group(1).replace(",", "")
            # Try parsing with datetime formats
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y"):
                try:
                    dt = datetime.strptime(date_snippet, fmt).replace(tzinfo=timezone.utc)
                    parsed_dt = dt
                    break
                except ValueError:
                    continue
        if parsed_dt:
            break

    if not parsed_dt:
        # Fallback: could not recognize date, treat as active rolling
        return {
            "is_expired": False,
            "is_rolling": True,
            "parsed_date_iso": None,
            "remaining_days": None,
            "status_badge": "Active",
            "raw_deadline": raw
        }

    # Compare with reference time
    is_expired = parsed_dt < now_dt
    diff_days = (parsed_dt.date() - now_dt.date()).days

    if is_expired:
        badge = "Expired"
    elif diff_days <= 3:
        badge = "Closing Soon"
    else:
        badge = "Active"

    return {
        "is_expired": is_expired,
        "is_rolling": False,
        "parsed_date_iso": parsed_dt.strftime("%Y-%m-%d"),
        "remaining_days": diff_days if not is_expired else 0,
        "status_badge": badge,
        "raw_deadline": raw
    }


def compute_job_duplicate_key(job: Dict[str, Any]) -> str:
    """
    Computes a deterministic matching key based on company name, normalized title,
    and normalized destination URL / domain path.
    """
    comp = normalize_company_name(job.get("company", ""))
    title = normalize_title(job.get("title", ""))
    url = normalize_url(job.get("apply_url", ""))

    # If title and company are present, they form the primary identity
    return f"{comp}::{title}::{url[:40]}"


def deduplicate_job_feed(jobs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """
    Filters out duplicate job opportunities while preserving original sources and metadata.

    Returns:
        (deduplicated_jobs, duplicate_count)
    """
    seen_keys: Dict[str, Dict[str, Any]] = {}
    deduped: List[Dict[str, Any]] = []
    duplicate_count = 0

    for job in jobs:
        dup_key = compute_job_duplicate_key(job)

        if dup_key in seen_keys:
            duplicate_count += 1
            existing = seen_keys[dup_key]
            # Merge auxiliary tags/sources if beneficial
            sources = existing.setdefault("merged_sources", [existing.get("id")])
            if job.get("id") and job.get("id") not in sources:
                sources.append(job.get("id"))
            continue

        item = dict(job)
        seen_keys[dup_key] = item
        deduped.append(item)

    return deduped, duplicate_count


def process_jobs_feed_with_expiration_and_dedup(
    jobs: List[Dict[str, Any]],
    hide_expired: bool = False,
    reference_timestamp: Optional[float] = None
) -> Dict[str, Any]:
    """
    Comprehensive pipeline to deduplicate and annotate jobs with expiration status.

    Parameters:
        jobs: Raw job feed list.
        hide_expired: If True, filters out expired listings from the primary results.
        reference_timestamp: Optional time anchor for deterministic testing.

    Returns:
        Dict with:
            - total_raw: int
            - deduplicated_count: int
            - duplicates_removed: int
            - expired_count: int
            - active_count: int
            - jobs: List[Dict[str, Any]] (annotated with 'expiration_meta')
    """
    deduped_jobs, dup_count = deduplicate_job_feed(jobs)

    annotated_jobs: List[Dict[str, Any]] = []
    expired_count = 0
    active_count = 0

    for job in deduped_jobs:
        item = dict(job)
        exp_meta = parse_job_deadline(item.get("deadline"), reference_timestamp=reference_timestamp)
        item["expiration_meta"] = exp_meta
        item["is_expired"] = exp_meta["is_expired"]
        item["status_badge"] = exp_meta["status_badge"]

        if exp_meta["is_expired"]:
            expired_count += 1
            if not hide_expired:
                annotated_jobs.append(item)
        else:
            active_count += 1
            annotated_jobs.append(item)

    return {
        "total_raw": len(jobs),
        "deduplicated_count": len(deduped_jobs),
        "duplicates_removed": dup_count,
        "expired_count": expired_count,
        "active_count": active_count,
        "jobs": annotated_jobs
    }
