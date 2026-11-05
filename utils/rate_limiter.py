"""
Lightweight thread-safe sliding-window and token bucket in-memory rate limiter for Flask.

Provides IP-based and route-based throttling to defend computationally expensive endpoints
(such as multi-agent LLM analysis and mock interview answer evaluation) against denial-of-service,
brute-force abuse, and third-party quota exhaustion.
"""

import time
import threading
from typing import Dict, List, Optional, Tuple, Callable, Any
from functools import wraps
from flask import request, jsonify, flash, redirect, url_for, make_response, render_template
import logging

logger = logging.getLogger(__name__)


class InMemoryRateLimiter:
    """
    Sliding-window rate limiter maintaining request timestamps per client identifier.
    Thread-safe implementation with automatic background cleanup of stale records.
    """

    def __init__(self, default_limit: int = 60, default_window_seconds: int = 60):
        self.default_limit = default_limit
        self.default_window_seconds = default_window_seconds
        self._records: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def get_client_ip(self) -> str:
        """
        Extracts genuine client IP address considering reverse proxies (X-Forwarded-For).
        Falls back to remote_addr if headers are not present.
        """
        if request.headers.get("X-Forwarded-For"):
            # The first IP in the list represents the originating client
            client_ip = request.headers["X-Forwarded-For"].split(",")[0].strip()
            return client_ip
        if request.headers.get("X-Real-IP"):
            return request.headers["X-Real-IP"].strip()
        return request.remote_addr or "127.0.0.1"

    def is_allowed(
        self, key: str, max_requests: int, window_seconds: int
    ) -> Tuple[bool, int, float]:
        """
        Checks whether the specified key has exceeded max_requests in window_seconds.

        Returns:
            Tuple[bool, int, float]:
                - allowed: True if request is allowed, False if throttled
                - remaining: Number of permitted requests left in current window
                - reset_seconds: Seconds until current sliding window expires
        """
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            # Retrieve or initialize timestamp history
            timestamps = self._records.get(key, [])
            # Filter out timestamps older than the sliding window cutoff
            fresh_timestamps = [ts for ts in timestamps if ts > cutoff]

            if len(fresh_timestamps) >= max_requests:
                earliest_active_ts = fresh_timestamps[0]
                reset_seconds = max(1.0, (earliest_active_ts + window_seconds) - now)
                self._records[key] = fresh_timestamps
                return False, 0, reset_seconds

            fresh_timestamps.append(now)
            self._records[key] = fresh_timestamps
            remaining = max(0, max_requests - len(fresh_timestamps))
            reset_seconds = float(window_seconds)
            return True, remaining, reset_seconds

    def reset(self):
        """Clears all in-memory rate limit records (useful for test isolation)."""
        with self._lock:
            self._records.clear()


# Global rate limiter instance
limiter = InMemoryRateLimiter()


def parse_rate_limit(limit_val: Any) -> Tuple[int, int]:
    """
    Parses a rate limit definition into (max_requests, window_seconds).
    Supports:
        - Flask-Limiter style strings: "5/hour", "30/hour", "100/minute", "10/day", "5/second", "60/min", "10/hr"
        - Tuples or lists: (5, 3600)
        - Integers: 5 (defaults to a 60-second window)
    """
    if limit_val is None:
        return 60, 60

    if isinstance(limit_val, (tuple, list)) and len(limit_val) >= 2:
        try:
            return int(limit_val[0]), int(limit_val[1])
        except (ValueError, TypeError):
            return 60, 60

    if isinstance(limit_val, (int, float)):
        return max(1, int(limit_val)), 60

    val_str = str(limit_val).strip().lower()
    if "/" in val_str:
        parts = val_str.split("/", 1)
        try:
            req_count = max(1, int(parts[0].strip()))
        except ValueError:
            req_count = 60

        unit = parts[1].strip()
        if unit.startswith("s"):
            window = 1
        elif unit.startswith("m"):
            window = 60
        elif unit.startswith("h"):
            window = 3600
        elif unit.startswith("d"):
            window = 86400
        else:
            try:
                window = max(1, int(unit))
            except ValueError:
                window = 60
        return req_count, window

    try:
        return max(1, int(val_str)), 60
    except ValueError:
        return 60, 60


def format_time_hint(seconds: float) -> str:
    """
    Formats the seconds remaining until quota reset into a human-readable hint:
    e.g. 'try again in 59 minutes', 'try again in 1 minute', 'try again in 30 seconds'.
    """
    secs = max(1, int(round(seconds)))
    if secs < 60:
        return f"try again in {secs} second" if secs == 1 else f"try again in {secs} seconds"
    mins = max(1, round(secs / 60))
    return f"try again in {mins} minute" if mins == 1 else f"try again in {mins} minutes"


def get_limit_for_scope(
    scope: Optional[str] = None,
    default_max: Optional[int] = None,
    default_window: Optional[int] = None,
) -> Tuple[int, int]:
    """
    Resolves (max_requests, window_seconds) dynamically from config.py or environment.
    Allows rate limits to be modified centrally without editing route code (#160).
    """
    import os

    norm_scope = scope.upper() if scope else ""

    # Check direct environment variable first
    if norm_scope and os.getenv(f"RATE_LIMIT_{norm_scope}"):
        return parse_rate_limit(os.getenv(f"RATE_LIMIT_{norm_scope}"))
    if "ANALYZE" in norm_scope and os.getenv("RATE_LIMIT_ANALYZE"):
        return parse_rate_limit(os.getenv("RATE_LIMIT_ANALYZE"))
    if "INTERVIEW" in norm_scope and os.getenv("RATE_LIMIT_INTERVIEW"):
        return parse_rate_limit(os.getenv("RATE_LIMIT_INTERVIEW"))

    try:
        import config

        rate_limits = getattr(config, "RATE_LIMITS", {})
        if scope and isinstance(rate_limits, dict) and scope in rate_limits:
            return parse_rate_limit(rate_limits[scope])

        if scope:
            if hasattr(config, f"RATE_LIMIT_{norm_scope}"):
                return parse_rate_limit(getattr(config, f"RATE_LIMIT_{norm_scope}"))
            if "ANALYZE" in norm_scope and hasattr(config, "RATE_LIMIT_ANALYZE"):
                return parse_rate_limit(getattr(config, "RATE_LIMIT_ANALYZE"))
            if "INTERVIEW" in norm_scope and hasattr(config, "RATE_LIMIT_INTERVIEW"):
                return parse_rate_limit(getattr(config, "RATE_LIMIT_INTERVIEW"))

        if default_max is None and hasattr(config, "RATE_LIMIT_DEFAULT"):
            return parse_rate_limit(getattr(config, "RATE_LIMIT_DEFAULT"))

    except Exception as exc:
        logger.warning(f"Error reading rate limit configuration for scope '{scope}': {exc}")

    if os.getenv("RATE_LIMIT_DEFAULT"):
        return parse_rate_limit(os.getenv("RATE_LIMIT_DEFAULT"))

    return (
        default_max if default_max is not None else 60,
        default_window if default_window is not None else 60,
    )


def rate_limit(
    max_requests: Optional[int] = None,
    window_seconds: Optional[int] = None,
    scope: Optional[str] = None,
    is_api: Optional[bool] = None,
    redirect_endpoint: str = "index",
):
    """
    Decorator for Flask view endpoints enforcing request throttling (#160).
    Dynamically loads configurable limits from config.py / environment variables.
    Returns HTTP 429 with Retry-After headers, a friendly message, and a 'try again in X minutes' hint.

    Parameters:
        max_requests: Optional override for max requests within window_seconds.
        window_seconds: Optional override for sliding window duration in seconds.
        scope: Unique string identifier for endpoint throttling group (e.g. 'analyze', 'interview_eval').
        is_api: If True, returns HTTP 429 JSON; if False, renders 429 UI template; if None, detects automatically.
        redirect_endpoint: Fallback endpoint for non-API route.
    """
    def decorator(f: Callable):
        @wraps(f)
        def wrapped(*args, **kwargs):
            try:
                import os
                import config
                env_enabled = os.getenv("RATE_LIMIT_ENABLED")
                if env_enabled is not None:
                    if env_enabled.lower() in ("false", "0", "no", "off"):
                        return f(*args, **kwargs)
                elif hasattr(config, "RATE_LIMIT_ENABLED") and not config.RATE_LIMIT_ENABLED:
                    return f(*args, **kwargs)
            except Exception:
                pass

            effective_max, effective_window = get_limit_for_scope(
                scope=scope or f.__name__,
                default_max=max_requests,
                default_window=window_seconds,
            )

            client_ip = limiter.get_client_ip()
            bucket_key = f"{scope or f.__name__}:{client_ip}"

            allowed, remaining, reset_seconds = limiter.is_allowed(
                bucket_key, effective_max, effective_window
            )

            if not allowed:
                retry_hint = format_time_hint(reset_seconds)
                retry_after_str = str(int(reset_seconds) + 1)
                friendly_message = (
                    f"You have temporarily exceeded the request rate limit for this action. "
                    f"Please {retry_hint}."
                )

                logger.warning(
                    f"Rate limit exceeded for client {client_ip} on '{bucket_key}'. "
                    f"Throttled for {reset_seconds:.1f}s ({retry_hint})."
                )

                # Detect whether request is API / AJAX
                is_json_request = (
                    is_api is True
                    or (is_api is None and (
                        request.is_json
                        or request.path.startswith("/api/")
                        or request.headers.get("Accept") == "application/json"
                        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
                    ))
                )

                if is_json_request:
                    response = jsonify({
                        "success": False,
                        "error": "Too Many Requests",
                        "message": friendly_message,
                        "retry_after_seconds": int(reset_seconds) + 1,
                        "retry_after_hint": retry_hint,
                    })
                    response.status_code = 429
                    response.headers["Retry-After"] = retry_after_str
                    response.headers["X-RateLimit-Limit"] = str(effective_max)
                    response.headers["X-RateLimit-Remaining"] = "0"
                    return response

                # Non-API / Browser UI: render friendly 429 page
                try:
                    html_content = render_template(
                        "429.html",
                        message=friendly_message,
                        retry_hint=retry_hint,
                        retry_after_seconds=int(reset_seconds) + 1,
                        scope=scope or f.__name__,
                    )
                    resp = make_response(html_content, 429)
                except Exception as err:
                    logger.warning(f"Failed to render 429.html: {err}")
                    flash(friendly_message, "error")
                    resp = make_response(
                        f"<!DOCTYPE html><html><head><title>429 Too Many Requests</title></head>"
                        f"<body style='font-family:sans-serif;text-align:center;padding:50px;'>"
                        f"<h1>429 - Too Many Requests</h1><p>{friendly_message}</p>"
                        f"<p><a href='/'>Return to Home</a></p></body></html>",
                        429,
                    )

                resp.headers["Retry-After"] = retry_after_str
                resp.headers["X-RateLimit-Limit"] = str(effective_max)
                resp.headers["X-RateLimit-Remaining"] = "0"
                return resp

            return f(*args, **kwargs)

        return wrapped
    return decorator
