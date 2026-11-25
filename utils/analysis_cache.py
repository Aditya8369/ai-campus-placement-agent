"""
Analysis Result Caching Service (#296)
=====================================
Computes a cryptographic SHA-256 hash across normalized inputs
(resume text, job description, target company) and caches coordinator analysis
findings in SQLite to prevent wasteful re-invocation of third-party AI APIs (Gemini).

Key capabilities:
1. Normalization & Hashing: Deterministic SHA-256 hash generation over normalized inputs.
2. Cache Lookup (Hit / Miss): Validates expiration timestamp (default: 24h TTL) before return.
3. Cache Storage: Persists only (input_hash, student_id, analysis_id, timestamps) without extra PII.
4. Invalidation & Re-run: Bypasses cache when force_rerun flag is provided or on demand.
5. Automatic Expiry Cleanup: Purges expired cache entries.
"""

import hashlib
import time
import re
import logging
from typing import Dict, Any, Optional

import config
from utils.database import get_db_connection, get_analysis

logger = logging.getLogger(__name__)


def normalize_text(text: Optional[str]) -> str:
    """
    Normalizes text for consistent hashing:
    - Trims whitespace
    - Normalizes line endings (CRLF -> LF)
    - Normalizes internal multiple horizontal whitespace characters to single spaces
    - Strips empty lines and trims each line
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def compute_analysis_hash(
    resume_text: str,
    job_description: Optional[str] = "",
    company_name: Optional[str] = "General"
) -> str:
    """
    Computes a deterministic SHA-256 hash of the normalized input combination:
    normalized resume text, job description, and selected company.
    """
    norm_resume = normalize_text(resume_text)
    norm_jd = normalize_text(job_description)
    norm_company = (company_name or "General").strip().lower()

    preimage = (
        f"company:{norm_company}\n"
        f"jd:{norm_jd}\n"
        f"resume:{norm_resume}"
    )
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def get_cached_analysis_id(
    input_hash: str,
    student_id: Optional[str] = None,
    current_time: Optional[float] = None
) -> Optional[str]:
    """
    Looks up an unexpired analysis ID for the given input hash.
    Returns analysis_id if found and valid, otherwise None.
    """
    if not getattr(config, "ANALYSIS_CACHE_ENABLED", True):
        return None

    if not input_hash:
        return None

    now = current_time if current_time is not None else time.time()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "").strip()

        if effective_student_id and effective_student_id != "default_student":
            cursor.execute(
                """
                SELECT analysis_id, expires_at FROM analysis_cache
                WHERE input_hash = ? AND (student_id = ? OR student_id = 'default_student')
                ORDER BY created_at DESC LIMIT 1
                """,
                (input_hash, effective_student_id)
            )
        else:
            cursor.execute(
                """
                SELECT analysis_id, expires_at FROM analysis_cache
                WHERE input_hash = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (input_hash,)
            )

        row = cursor.fetchone()
        if not row:
            return None

        analysis_id = row[0]
        expires_at = float(row[1])

        if expires_at <= now:
            logger.info(f"Analysis cache entry for hash {input_hash[:12]}... expired at {expires_at} (now {now}).")
            cursor.execute("DELETE FROM analysis_cache WHERE input_hash = ?", (input_hash,))
            conn.commit()
            return None

        return analysis_id
    except Exception as e:
        logger.error(f"Error querying analysis_cache: {e}")
        return None
    finally:
        conn.close()


def get_cached_analysis(
    input_hash: str,
    student_id: Optional[str] = None,
    current_time: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """
    Retrieves full analysis record from cache if present and unexpired.
    Returns deserialized analysis record with 'from_cache'=True, or None if miss/expired.
    """
    analysis_id = get_cached_analysis_id(input_hash, student_id=student_id, current_time=current_time)
    if not analysis_id:
        return None

    record = get_analysis(analysis_id)
    if not record:
        invalidate_cache_entry(input_hash=input_hash)
        return None

    # Never serve basic fallback analysis as a cached full result (#849)
    results = record.get("results")
    if isinstance(results, dict) and (results.get("is_basic_analysis") or results.get("ai_unavailable")):
        logger.info(f"Analysis {analysis_id} is a basic fallback; excluding from cache hits.")
        invalidate_cache_entry(input_hash=input_hash, analysis_id=analysis_id)
        return None

    record["from_cache"] = True
    record["is_cached"] = True
    return record


def set_cached_analysis(
    input_hash: str,
    analysis_id: str,
    student_id: Optional[str] = "default_student",
    ttl_seconds: Optional[int] = None,
    created_at: Optional[float] = None
) -> None:
    """
    Stores or updates a cache entry for an input hash pointing to an existing analysis record.
    Default TTL is 24 hours (86400 seconds).
    """
    if not getattr(config, "ANALYSIS_CACHE_ENABLED", True):
        return

    if not input_hash or not analysis_id:
        return

    # Never cache a basic fallback analysis as a full result (#849)
    try:
        record = get_analysis(analysis_id)
        if record:
            results = record.get("results")
            if isinstance(results, dict) and (results.get("is_basic_analysis") or results.get("ai_unavailable")):
                logger.info(f"Skipping caching for basic fallback analysis {analysis_id}")
                return
    except Exception as check_err:
        logger.debug(f"Could not check basic analysis flag on {analysis_id}: {check_err}")

    now = created_at if created_at is not None else time.time()
    ttl = ttl_seconds if ttl_seconds is not None else getattr(config, "ANALYSIS_CACHE_EXPIRY_SECONDS", 86400)
    expires_at = now + ttl
    effective_student_id = (student_id or "default_student").strip()

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO analysis_cache (input_hash, student_id, analysis_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (input_hash, effective_student_id, analysis_id, now, expires_at)
        )
        conn.commit()
        logger.info(
            f"Cached analysis {analysis_id} for hash {input_hash[:12]}... (expires in {ttl}s at {expires_at})"
        )
    except Exception as e:
        logger.error(f"Failed to set analysis cache entry: {e}")
    finally:
        conn.close()


def invalidate_cache_entry(
    input_hash: Optional[str] = None,
    analysis_id: Optional[str] = None,
    student_id: Optional[str] = None
) -> int:
    """
    Invalidates (deletes) a cache entry by input_hash or analysis_id.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if input_hash and student_id:
            cursor.execute(
                "DELETE FROM analysis_cache WHERE input_hash = ? AND student_id = ?",
                (input_hash, student_id)
            )
        elif input_hash:
            cursor.execute("DELETE FROM analysis_cache WHERE input_hash = ?", (input_hash,))
        elif analysis_id:
            cursor.execute("DELETE FROM analysis_cache WHERE analysis_id = ?", (analysis_id,))
        else:
            return 0
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        logger.error(f"Failed to invalidate cache entry: {e}")
        return 0
    finally:
        conn.close()


def clear_expired_cache(current_time: Optional[float] = None) -> int:
    """
    Deletes all expired cache entries from SQLite.
    Returns count of removed entries.
    """
    now = current_time if current_time is not None else time.time()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM analysis_cache WHERE expires_at <= ?", (now,))
        conn.commit()
        deleted = cursor.rowcount
        if deleted > 0:
            logger.info(f"Purged {deleted} expired analysis cache entries.")
        return deleted
    except Exception as e:
        logger.error(f"Error purging expired analysis cache: {e}")
        return 0
    finally:
        conn.close()
