"""
CSRF Protection & Session Security Module (#300).
Integrates Flask-WTF CSRFProtect with automated fallback, request header validation,
and custom error handling.
"""

import os
import hmac
import time
import secrets
import hashlib
import logging
from typing import Optional, Callable, Any, Set
from flask import Flask, request, session, g, current_app

logger = logging.getLogger(__name__)

try:
    from flask_wtf.csrf import (
        CSRFProtect as _FlaskWTFCSRFProtect,
        CSRFError as _FlaskWTFCSRFError,
        generate_csrf as _wtf_generate_csrf,
        validate_csrf as _wtf_validate_csrf,
    )
    HAS_FLASK_WTF = True
except ImportError:
    HAS_FLASK_WTF = False
    _FlaskWTFCSRFProtect = object
    _FlaskWTFCSRFError = None
    _wtf_generate_csrf = None
    _wtf_validate_csrf = None


class FallbackCSRFError(Exception):
    """Exception raised when CSRF token validation fails (#300)."""
    code = 400

    def __init__(self, description: str = "The CSRF token is missing or invalid."):
        super().__init__(description)
        self.description = description


CSRFError = _FlaskWTFCSRFError if HAS_FLASK_WTF else FallbackCSRFError


def _fallback_generate_csrf(secret_key: Optional[str] = None, token_key: Optional[str] = None) -> str:
    """Fallback generator for HMAC-signed per-session CSRF tokens."""
    token_key = token_key or "csrf_token"
    if token_key not in session:
        session[token_key] = secrets.token_hex(32)

    session_token = session[token_key]
    if not secret_key:
        secret_key = current_app.secret_key or current_app.config.get("SECRET_KEY", "fallback-dev-secret")

    timestamp = int(time.time())
    data = f"{session_token}##{timestamp}".encode("utf-8")
    key = str(secret_key).encode("utf-8")
    signature = hmac.new(key, data, hashlib.sha256).hexdigest()
    return f"{signature}##{timestamp}"


def _fallback_validate_csrf(
    data: Any,
    secret_key: Optional[str] = None,
    time_limit: Optional[int] = None,
    token_key: Optional[str] = None
) -> None:
    """Fallback validator for HMAC-signed per-session CSRF tokens."""
    token_key = token_key or "csrf_token"
    if not data or not isinstance(data, str):
        raise CSRFError("The CSRF token is missing.")

    session_token = session.get(token_key)
    if not session_token:
        raise CSRFError("The CSRF session token is missing.")

    parts = data.split("##")
    if len(parts) != 2:
        raise CSRFError("The CSRF token is malformed.")

    signature, ts_str = parts
    try:
        timestamp = int(ts_str)
    except ValueError:
        raise CSRFError("The CSRF token timestamp is invalid.")

    if time_limit is None:
        time_limit = current_app.config.get("WTF_CSRF_TIME_LIMIT", 3600)

    if time_limit is not None and (time.time() - timestamp) > time_limit:
        raise CSRFError("The CSRF token has expired.")

    if not secret_key:
        secret_key = current_app.secret_key or current_app.config.get("SECRET_KEY", "fallback-dev-secret")

    expected_data = f"{session_token}##{timestamp}".encode("utf-8")
    expected_key = str(secret_key).encode("utf-8")
    expected_sig = hmac.new(expected_key, expected_data, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        raise CSRFError("The CSRF token is invalid.")


def generate_csrf(secret_key: Optional[str] = None, token_key: Optional[str] = None) -> str:
    """Generate a per-session CSRF token using Flask-WTF or internal HMAC fallback."""
    if HAS_FLASK_WTF and _wtf_generate_csrf is not None:
        return _wtf_generate_csrf(secret_key=secret_key, token_key=token_key)
    return _fallback_generate_csrf(secret_key=secret_key, token_key=token_key)


def validate_csrf(
    data: Any,
    secret_key: Optional[str] = None,
    time_limit: Optional[int] = None,
    token_key: Optional[str] = None
) -> None:
    """Validate a CSRF token using Flask-WTF or internal HMAC fallback."""
    if HAS_FLASK_WTF and _wtf_validate_csrf is not None:
        try:
            return _wtf_validate_csrf(data, secret_key=secret_key, time_limit=time_limit, token_key=token_key)
        except Exception as exc:
            # Flask-WTF raises wtforms.validators.ValidationError; normalize to CSRFError
            desc = str(exc) or "The CSRF token is missing or invalid."
            raise CSRFError(desc) from exc
    return _fallback_validate_csrf(data, secret_key=secret_key, time_limit=time_limit, token_key=token_key)


class CSRFProtect:
    """
    CSRF Protection extension for Flask applications (#300).
    Wraps Flask-WTF CSRFProtect when installed or operates a standalone fallback.
    """

    def __init__(self, app: Optional[Flask] = None):
        self._exempt_views: Set[Callable] = set()
        self._app: Optional[Flask] = None
        if HAS_FLASK_WTF:
            self._impl = _FlaskWTFCSRFProtect()
        else:
            self._impl = None

        if app is not None:
            self.init_app(app)

    def init_app(self, app: Flask) -> None:
        self._app = app
        app.config.setdefault("WTF_CSRF_ENABLED", True)
        app.config.setdefault("WTF_CSRF_CHECK_DEFAULT", True)
        app.config.setdefault("WTF_CSRF_TIME_LIMIT", 3600)
        app.config.setdefault("WTF_CSRF_HEADERS", ["X-CSRFToken", "X-CSRF-Token"])

        # Inject csrf_token into all Jinja2 template contexts
        app.jinja_env.globals["csrf_token"] = generate_csrf

        if HAS_FLASK_WTF and self._impl is not None:
            self._impl.init_app(app)
            for view in self._exempt_views:
                self._impl.exempt(view)
        else:
            self._init_fallback(app)

    def _init_fallback(self, app: Flask) -> None:
        @app.before_request
        def _check_csrf():
            if not app.config.get("WTF_CSRF_ENABLED", True):
                return

            if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
                return

            view_func = app.view_functions.get(request.endpoint) if request.endpoint else None
            if view_func and (getattr(view_func, "_csrf_exempt", False) or view_func in self._exempt_views):
                return

            # Extract token from headers or form data
            token = (
                request.headers.get("X-CSRFToken") or
                request.headers.get("X-CSRF-Token") or
                (request.form.get("csrf_token") if request.form else None)
            )

            try:
                validate_csrf(token)
            except CSRFError as err:
                raise err
            except Exception as exc:
                raise CSRFError(str(exc))

    def exempt(self, view: Callable) -> Callable:
        """Exempt a specific route view function from CSRF protection."""
        self._exempt_views.add(view)
        setattr(view, "_csrf_exempt", True)
        if HAS_FLASK_WTF and self._impl is not None:
            return self._impl.exempt(view)
        return view


csrf = CSRFProtect()
