"""
Text Sanitizer and Safe Rendering Utility.
=========================================
Provides safe rendering and URL validation for user-generated content across
the platform (notes, comments, feedback, bookmarks, links, etc.):

1. HTML-Like Text Escaping:
   - Ensures all raw HTML tags, scripts, and brackets (e.g. `<script>`, `<div>`, `<email>`)
     are escaped to entity references (`&lt;...&gt;`) before any rendering.

2. Long String & Word Breaking:
   - Prevents layout overflows or hidden content from unbroken character sequences
     (long hashes, continuous tokens, long URLs) while preserving full readability.

3. URL Scheme Validation & Sanitization:
   - Restricts hyperlinks strictly to safe schemes (`http`, `https`, `mailto`).
   - Rejects dangerous schemes (`javascript:`, `data:`, `vbscript:`, `file:`, `blob:`).
   - Sanitizes and escapes URLs for safe attribute interpolation.

4. Safe Notes & Comments Auto-Linking:
   - Scans user notes and comments for safe URLs, wraps them in secure `<a>` tags
     with `target="_blank" rel="noopener noreferrer" class="safe-link"`, and converts
     newlines to `<br>` without ever exposing unescaped user HTML.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from typing import Optional, Set, Tuple, Union
from markupsafe import Markup, escape

# Allowed URL schemes for safe hyperlinking
ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({"http", "https", "mailto"})

# Dangerous schemes explicitly blacklisted for clarity and immediate rejection
DANGEROUS_URL_SCHEMES: frozenset[str] = frozenset(
    {"javascript", "data", "vbscript", "file", "blob", "about"}
)

# Regex matching candidate URLs inside user text
# Matches http://, https://, or mailto:
# Handles non-whitespace, stopping before trailing sentence punctuation
_URL_CANDIDATE_REGEX = re.compile(
    r"""
    \b(https?://[^\s<>"'()]+|mailto:[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Trailing punctuation characters that are typically part of surrounding prose, not the URL
_TRAILING_PUNCTUATION = ".,!?:;)]}\"'"


def is_safe_url(
    url: Optional[str],
    allowed_schemes: Union[Set[str], frozenset[str]] = ALLOWED_URL_SCHEMES,
    allow_relative: bool = True,
) -> bool:
    """
    Validates whether a URL uses an allowed, safe scheme and lacks dangerous payloads.

    Args:
        url: The candidate URL string.
        allowed_schemes: Set of allowed lowercase URL schemes (default: http, https, mailto).
        allow_relative: Whether internal relative paths (e.g. '/dashboard') are accepted.

    Returns:
        True if the URL is safe, False otherwise.
    """
    if not url or not isinstance(url, str):
        return False

    cleaned = url.strip()
    if not cleaned:
        return False

    # Check for disallowed control characters or zero-byte bypasses
    if any(ord(c) < 32 or ord(c) == 127 for c in cleaned):
        return False

    # Allow relative URLs if explicitly requested (must start with single '/')
    if allow_relative:
        if cleaned.startswith("/") and not cleaned.startswith("//") and not cleaned.startswith("/\\"):
            return True

    # Reject protocol-relative URLs (e.g. '//evil.com') unless scheme is explicit
    if cleaned.startswith("//") or cleaned.startswith("\\\\"):
        return False

    try:
        parsed = urllib.parse.urlsplit(cleaned)
    except Exception:
        return False

    scheme = parsed.scheme.lower()
    if not scheme:
        # No scheme present: if relative allowed and valid path
        if allow_relative and cleaned.startswith("/"):
            return True
        return False

    if scheme in DANGEROUS_URL_SCHEMES:
        return False

    if scheme not in allowed_schemes:
        return False

    # For web URLs (http/https), require a valid non-empty network location (host)
    if scheme in {"http", "https"}:
        if not parsed.netloc or not parsed.netloc.strip():
            return False

    # For mailto:, require a valid email format
    if scheme == "mailto":
        recipient = parsed.path.strip()
        if not recipient or "@" not in recipient:
            return False

    return True


def sanitize_url(
    url: Optional[str],
    default: str = "#",
    allowed_schemes: Union[Set[str], frozenset[str]] = ALLOWED_URL_SCHEMES,
    allow_relative: bool = True,
) -> str:
    """
    Returns the sanitized URL if valid; otherwise returns the safe default fallback.
    The returned URL is properly HTML-attribute escaped.

    Args:
        url: The candidate URL string.
        default: Safe fallback string if invalid (default: '#').
        allowed_schemes: Allowed schemes set.
        allow_relative: Whether to allow relative paths.

    Returns:
        Safe HTML-escaped URL string.
    """
    if is_safe_url(url, allowed_schemes=allowed_schemes, allow_relative=allow_relative):
        assert url is not None
        return html.escape(url.strip(), quote=True)
    return default


def break_long_words(text: Optional[str], max_chunk: int = 60, break_char: str = "\u200B") -> str:
    """
    Inserts a zero-width space into words that exceed `max_chunk` characters without spaces,
    ensuring long continuous character strings can break gracefully without layout overflow.

    Args:
        text: The input text string.
        max_chunk: Maximum characters allowed before a break opportunity.
        break_char: Character to insert (defaults to zero-width space \\u200B).

    Returns:
        String with long unbroken tokens divided.
    """
    if not text:
        return ""

    tokens = text.split(" ")
    broken_tokens = []
    for token in tokens:
        if len(token) > max_chunk and not token.startswith("http://") and not token.startswith("https://"):
            # Chunk the long token
            chunks = [token[i : i + max_chunk] for i in range(0, len(token), max_chunk)]
            broken_tokens.append(break_char.join(chunks))
        else:
            broken_tokens.append(token)

    return " ".join(broken_tokens)


def render_safe_notes(
    text: Optional[str],
    autolink: bool = True,
    max_length: Optional[int] = None,
) -> Markup:
    """
    Renders user notes and comments safely for HTML template insertion:
    1. Escapes all HTML entities so HTML-like text cannot be interpreted as markup.
    2. Autolinks valid HTTP/HTTPS and mailto URLs with `target="_blank" rel="noopener noreferrer"`.
    3. Blocks dangerous schemes (e.g. `javascript:`) from becoming active links.
    4. Converts line breaks (\\r\\n, \\n) into `<br>` tags.
    5. Returns a MarkupSafe `Markup` instance that can be safely embedded in Jinja templates.

    Args:
        text: Raw user notes or comment text.
        autolink: Whether to convert safe URLs to clickable links (default: True).
        max_length: Optional truncation length before rendering.

    Returns:
        MarkupSafe Markup instance containing escaped, safe HTML.
    """
    if text is None:
        return Markup("")

    str_text = str(text)
    if not str_text.strip():
        return Markup("")

    if max_length and len(str_text) > max_length:
        str_text = str_text[:max_length] + "..."

    # Normalize line endings to \n
    normalized = str_text.replace("\r\n", "\n").replace("\r", "\n")

    if not autolink:
        # Just escape HTML and replace newlines with <br>
        escaped = html.escape(normalized, quote=True)
        html_with_br = escaped.replace("\n", "<br>\n")
        return Markup(html_with_br)

    # Process text by segments: find URLs, escape non-URLs, validate and link URLs
    result_pieces = []
    last_idx = 0

    for match in _URL_CANDIDATE_REGEX.finditer(normalized):
        start, end = match.span()

        # Non-URL segment before this match
        if start > last_idx:
            non_url_segment = normalized[last_idx:start]
            result_pieces.append(html.escape(non_url_segment, quote=True))

        raw_url = match.group(1)

        # Strip any trailing sentence punctuation that was captured
        trailing = ""
        while raw_url and raw_url[-1] in _TRAILING_PUNCTUATION:
            trailing = raw_url[-1] + trailing
            raw_url = raw_url[:-1]

        if raw_url and is_safe_url(raw_url):
            escaped_url = html.escape(raw_url, quote=True)
            link_html = (
                f'<a href="{escaped_url}" target="_blank" rel="noopener noreferrer" '
                f'class="safe-link safe-text-break">{escaped_url}</a>'
            )
            result_pieces.append(link_html)
        else:
            # If not a safe URL, render as escaped plain text
            result_pieces.append(html.escape(raw_url, quote=True))

        if trailing:
            result_pieces.append(html.escape(trailing, quote=True))

        last_idx = end

    # Remaining text after the last match
    if last_idx < len(normalized):
        remaining = normalized[last_idx:]
        result_pieces.append(html.escape(remaining, quote=True))

    full_escaped = "".join(result_pieces)
    html_with_br = full_escaped.replace("\n", "<br>\n")
    return Markup(html_with_br)
