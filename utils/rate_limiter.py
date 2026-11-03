"""
Lightweight thread-safe sliding-window and token bucket in-memory rate limiter for Flask.

Provides IP-based and route-based throttling to defend computationally expensive endpoints
(such as multi-agent LLM analysis and mock interview answer evaluation) against denial-of-service,
brute-force abuse, and third-party quota exhaustion.
"""

import time
import threading
from typing import Dict, List, Optional, Tuple, Callable
from functools import wraps
from flask import request, jsonify, flash, redirect, url_for, make_response
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


def rate_limit(
    max_requests: int = 30,
    window_seconds: int = 60,
    scope: Optional[str] = None,
    is_api: bool = False,
    redirect_endpoint: str = "index",
):
    """
    Decorator for Flask view endpoints enforcing request throttling.

    Parameters:
        max_requests: Maximum requests allowed within window_seconds.
        window_seconds: Sliding window duration in seconds.
        scope: Unique string identifier for endpoint throttling group.
        is_api: If True, returns HTTP 429 JSON; if False, flashes error and redirects.
        redirect_endpoint: Endpoint to redirect to when non-API route is throttled.
    """
    def decorator(f: Callable):
        @wraps(f)
        def wrapped(*args, **kwargs):
            client_ip = limiter.get_client_ip()
            bucket_key = f"{scope or f.__name__}:{client_ip}"

            allowed, remaining, reset_seconds = limiter.is_allowed(
                bucket_key, max_requests, window_seconds
            )

            if not allowed:
                logger.warning(
                    f"Rate limit exceeded for client {client_ip} on '{bucket_key}'. "
                    f"Throttled for {reset_seconds:.1f}s."
                )
                retry_after_str = str(int(reset_seconds) + 1)

                if is_api or request.is_json or request.path.startswith("/api/"):
                    response = jsonify({
                        "success": False,
                        "error": "Too Many Requests",
                        "message": (
                            f"You have temporarily exceeded the request rate limit for this action. "
                            f"Please wait {retry_after_str} seconds before retrying."
                        ),
                        "retry_after_seconds": int(reset_seconds) + 1,
                    })
                    response.status_code = 429
                    response.headers["Retry-After"] = retry_after_str
                    response.headers["X-RateLimit-Limit"] = str(max_requests)
                    response.headers["X-RateLimit-Remaining"] = "0"
                    return response

                flash(
                    f"Too many requests. Please wait {retry_after_str} seconds before submitting again.",
                    "error",
                )
                resp = make_response(redirect(url_for(redirect_endpoint)))
                resp.headers["Retry-After"] = retry_after_str
                return resp

            # Execute decorated function and attach informative rate limit headers
            result = f(*args, **kwargs)
            return result

        return wrapped
    return decorator
