"""
Privacy-Friendly CAPTCHA Provider and Verification Utility (#653).

Supports Cloudflare Turnstile and hCaptcha.
Disabled when CAPTCHA_PROVIDER, CAPTCHA_SITE_KEY, or CAPTCHA_SECRET_KEY are not configured.
Provides configurable fail-closed (default) and fail-open modes, timeout handling,
and optional tracking of repeated failed attempts before enforcement.
"""

import os
import json
import time
import socket
import logging
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional, Tuple, Dict, List
from flask import current_app, Request
import config

logger = logging.getLogger(__name__)

# Verification API endpoints
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
HCAPTCHA_VERIFY_URL = "https://api.hcaptcha.com/siteverify"

# In-memory tracking for failed attempts per IP or account identifier
_failed_attempts: Dict[str, List[float]] = {}


def get_captcha_provider() -> str:
    """Returns normalized lowercase provider name ('turnstile' or 'hcaptcha'), or empty string."""
    val = ""
    try:
        val = current_app.config.get("CAPTCHA_PROVIDER", "")
    except (RuntimeError, AttributeError):
        pass
    if not val:
        val = getattr(config, "CAPTCHA_PROVIDER", "") or os.getenv("CAPTCHA_PROVIDER", "")
    val = str(val).strip().lower()
    if val in ("turnstile", "cloudflare", "cloudflare_turnstile"):
        return "turnstile"
    if val in ("hcaptcha",):
        return "hcaptcha"
    return ""


def get_captcha_site_key() -> str:
    """Returns the configured public site key."""
    try:
        val = current_app.config.get("CAPTCHA_SITE_KEY")
        if val is not None:
            return str(val).strip()
    except (RuntimeError, AttributeError):
        pass
    return (getattr(config, "CAPTCHA_SITE_KEY", "") or os.getenv("CAPTCHA_SITE_KEY", "")).strip()


def get_captcha_secret_key() -> str:
    """Returns the configured secret server key."""
    try:
        val = current_app.config.get("CAPTCHA_SECRET_KEY")
        if val is not None:
            return str(val).strip()
    except (RuntimeError, AttributeError):
        pass
    return (getattr(config, "CAPTCHA_SECRET_KEY", "") or os.getenv("CAPTCHA_SECRET_KEY", "")).strip()


def is_captcha_fail_open() -> bool:
    """Returns True if verification should fail open when the provider is unreachable."""
    try:
        val = current_app.config.get("CAPTCHA_FAIL_OPEN")
        if val is not None:
            if isinstance(val, bool):
                return val
            return str(val).strip().lower() in ("true", "1", "yes")
    except (RuntimeError, AttributeError):
        pass
    val = getattr(config, "CAPTCHA_FAIL_OPEN", None)
    if val is not None:
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("true", "1", "yes")
    return os.getenv("CAPTCHA_FAIL_OPEN", "false").lower() in ("true", "1", "yes")


def get_captcha_verify_timeout() -> float:
    """Returns the verification network timeout in seconds."""
    try:
        val = current_app.config.get("CAPTCHA_VERIFY_TIMEOUT")
        if val is not None:
            return float(val)
    except (RuntimeError, AttributeError, ValueError, TypeError):
        pass
    try:
        return float(getattr(config, "CAPTCHA_VERIFY_TIMEOUT", 5.0) or os.getenv("CAPTCHA_VERIFY_TIMEOUT", "5.0"))
    except (ValueError, TypeError):
        return 5.0


def is_captcha_always_enforced() -> bool:
    """Returns True if CAPTCHA is enforced on every request when keys are configured."""
    try:
        val = current_app.config.get("CAPTCHA_ALWAYS_ENFORCE")
        if val is not None:
            if isinstance(val, bool):
                return val
            return str(val).strip().lower() in ("true", "1", "yes")
    except (RuntimeError, AttributeError):
        pass
    val = getattr(config, "CAPTCHA_ALWAYS_ENFORCE", None)
    if val is not None:
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("true", "1", "yes")
    return os.getenv("CAPTCHA_ALWAYS_ENFORCE", "true").lower() in ("true", "1", "yes")


def get_captcha_failure_threshold() -> int:
    """Returns the number of failed attempts required before enforcing CAPTCHA (0 = always)."""
    try:
        val = current_app.config.get("CAPTCHA_REQUIRE_AFTER_FAILURES")
        if val is not None:
            return int(val)
    except (RuntimeError, AttributeError, ValueError, TypeError):
        pass
    try:
        return int(getattr(config, "CAPTCHA_REQUIRE_AFTER_FAILURES", 0) or os.getenv("CAPTCHA_REQUIRE_AFTER_FAILURES", "0"))
    except (ValueError, TypeError):
        return 0


def is_captcha_enabled() -> bool:
    """Returns True if a valid provider, site key, and secret key are configured."""
    provider = get_captcha_provider()
    site_key = get_captcha_site_key()
    secret_key = get_captcha_secret_key()
    return bool(provider in ("turnstile", "hcaptcha") and site_key and secret_key)


def record_failed_attempt(ip: Optional[str] = None, identifier: Optional[str] = None, window_seconds: int = 900) -> None:
    """Records a failed attempt timestamp for the given IP address and/or account identifier."""
    now = time.time()
    cutoff = now - window_seconds
    keys = []
    if ip and ip.strip():
        keys.append(f"ip:{ip.strip()}")
    if identifier and identifier.strip():
        keys.append(f"id:{identifier.strip().lower()}")

    for k in keys:
        attempts = _failed_attempts.get(k, [])
        attempts = [t for t in attempts if t > cutoff]
        attempts.append(now)
        _failed_attempts[k] = attempts


def get_failed_attempts(ip: Optional[str] = None, identifier: Optional[str] = None, window_seconds: int = 900) -> int:
    """Returns the maximum number of recent failed attempts for the given IP or identifier."""
    now = time.time()
    cutoff = now - window_seconds
    counts = []
    if ip and ip.strip():
        k = f"ip:{ip.strip()}"
        counts.append(len([t for t in _failed_attempts.get(k, []) if t > cutoff]))
    if identifier and identifier.strip():
        k = f"id:{identifier.strip().lower()}"
        counts.append(len([t for t in _failed_attempts.get(k, []) if t > cutoff]))
    return max(counts) if counts else 0


def reset_failed_attempts(ip: Optional[str] = None, identifier: Optional[str] = None) -> None:
    """Resets failed attempt counters upon successful authentication."""
    if ip and ip.strip():
        _failed_attempts.pop(f"ip:{ip.strip()}", None)
    if identifier and identifier.strip():
        _failed_attempts.pop(f"id:{identifier.strip().lower()}", None)


def should_require_captcha(ip: Optional[str] = None, identifier: Optional[str] = None, form_type: str = "login") -> bool:
    """Determines whether CAPTCHA verification should be required for a request."""
    if not is_captcha_enabled():
        return False
    if is_captcha_always_enforced():
        return True
    threshold = get_captcha_failure_threshold()
    if threshold <= 0:
        return True
    recent_failures = get_failed_attempts(ip=ip, identifier=identifier)
    return recent_failures >= threshold


def extract_captcha_token(request_obj: Request) -> Optional[str]:
    """Extracts the submitted CAPTCHA response token from form or JSON data."""
    if not request_obj:
        return None

    if request_obj.is_json:
        data = request_obj.get_json(silent=True) or {}
        token = (
            data.get("cf-turnstile-response")
            or data.get("h-captcha-response")
            or data.get("g-recaptcha-response")
            or data.get("captcha_token")
        )
    else:
        token = (
            request_obj.form.get("cf-turnstile-response")
            or request_obj.form.get("h-captcha-response")
            or request_obj.form.get("g-recaptcha-response")
            or request_obj.form.get("captcha_token")
        )

    if token and isinstance(token, str):
        cleaned = token.strip()
        return cleaned if cleaned else None
    return None


def verify_captcha_token(token: str, remote_ip: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    Validates a CAPTCHA response token against the configured provider's verification API.
    Returns (True, None) on success or (False, error_message) on failure.
    """
    provider = get_captcha_provider()
    secret_key = get_captcha_secret_key()
    timeout = get_captcha_verify_timeout()
    fail_open = is_captcha_fail_open()

    if provider == "turnstile":
        verify_url = TURNSTILE_VERIFY_URL
    elif provider == "hcaptcha":
        verify_url = HCAPTCHA_VERIFY_URL
    else:
        return (True, None)

    payload = {
        "secret": secret_key,
        "response": token,
    }
    if remote_ip and remote_ip.strip():
        payload["remoteip"] = remote_ip.strip()

    data_encoded = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        verify_url,
        data=data_encoded,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "AI-Campus-Placement-Agent",
        },
        method="POST",
    )

    try:
        response = urllib.request.urlopen(req, timeout=timeout)
        try:
            status_code = response.getcode() if hasattr(response, "getcode") else 200
            raw_body = response.read()
            if hasattr(raw_body, "decode"):
                body_str = raw_body.decode("utf-8")
            else:
                body_str = str(raw_body)

            if status_code != 200:
                logger.warning(
                    f"CAPTCHA provider {provider} returned HTTP {status_code}."
                )
                if fail_open:
                    return (True, None)
                return (False, "Security verification service is temporarily unavailable. Please try again shortly.")

            result = json.loads(body_str)
            if bool(result.get("success", False)):
                return (True, None)

            error_codes = result.get("error-codes", [])
            logger.info(f"CAPTCHA verification failed ({provider}): {error_codes}")
            return (False, "CAPTCHA verification failed. Please try again.")
        finally:
            if hasattr(response, "close"):
                response.close()

    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout, OSError) as err:
        if fail_open:
            logger.warning(
                f"CAPTCHA provider {provider} unreachable: {err}. Failing open as configured."
            )
            return (True, None)
        logger.warning(
            f"CAPTCHA provider {provider} unreachable: {err}. Failing closed."
        )
        return (False, "Security verification service is temporarily unavailable. Please try again shortly.")
    except Exception as err:
        logger.exception(f"Unexpected error during CAPTCHA verification ({provider}): {err}")
        if fail_open:
            return (True, None)
        return (False, "Security verification service is temporarily unavailable. Please try again shortly.")


def verify_captcha(request_obj: Request, form_type: str = "login", identifier: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    High-level entrypoint verifying the CAPTCHA requirement for an incoming request.
    Returns (True, None) if valid or not required.
    Returns (False, message) if required and missing or invalid.
    """
    if not is_captcha_enabled():
        return (True, None)

    ip = request_obj.remote_addr if request_obj else None
    token = extract_captcha_token(request_obj)

    required = should_require_captcha(ip=ip, identifier=identifier, form_type=form_type)
    if not required and not token:
        return (True, None)

    if not token:
        return (False, "Please complete the CAPTCHA verification to proceed.")

    return verify_captcha_token(token, remote_ip=ip)
