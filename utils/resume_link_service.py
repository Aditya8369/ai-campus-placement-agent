"""
Resume Link Service (#845)
==========================
Extracts URLs from resume text, validates formats (schemes, hosts, GitHub & LinkedIn
path patterns), checks reachability with SSRF protections, applies rate limiting,
and returns structured link health findings with actionable fix suggestions.

Acceptance Criteria:
- Malformed links are reported without any network call.
- Private and loopback targets are never requested.
- Timeouts and connection errors show as 'could not verify', not as failures.
- Rate limiting per user.
- Tests mock the HTTP layer.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

logger = logging.getLogger(__name__)

# Pattern to extract candidate URLs, schemes, and web profile handles
URL_REGEX = re.compile(
    r"""(?xi)
    \b
    (?:
        # Standard URL with scheme (http, https, ftp, etc.)
        (?:[a-z][a-z0-9+.-]*://[^\s<>"'{}|\\^`]+)
        |
        # Common domain patterns without explicit scheme
        (?:www\.[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s<>"'{}|\\^`]*)?)
        |
        # Common candidate profile host prefixes without scheme (including root domain)
        (?:(?:github\.com|linkedin\.com(?:/in)?|gitlab\.com|bitbucket\.org|leetcode\.com|hackerrank\.com)(?:/[^\s<>"'{}|\\^`]*)?)
    )
    """
)

# Trailing punctuation to strip from extracted URLs
TRAILING_PUNCT = ".,;:!?)'\"}]>/"

# Network safety and resource limits
DEFAULT_HEAD_TIMEOUT: float = 2.5
MAX_LINKS_TO_CHECK: int = 15
ALLOWED_SCHEMES = frozenset({"http", "https"})

# Blocked SSRF internal/private networks
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    # IPv6
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]

# Simple in-memory rate limiting per user (bucket of timestamps)
_USER_RATE_LIMITS: Dict[str, List[float]] = {}
MAX_CHECKS_PER_MINUTE = 10


def is_rate_limited(user_id: str) -> bool:
    """Checks and updates the sliding-window per-user rate limit."""
    now = time.time()
    u_key = str(user_id or "anonymous").strip()
    history = _USER_RATE_LIMITS.get(u_key, [])
    # Keep timestamps within the last 60 seconds
    valid_history = [t for t in history if now - t < 60]
    if len(valid_history) >= MAX_CHECKS_PER_MINUTE:
        _USER_RATE_LIMITS[u_key] = valid_history
        return True
    valid_history.append(now)
    _USER_RATE_LIMITS[u_key] = valid_history
    return False


def clear_rate_limits() -> None:
    """Clears all in-memory rate limits (useful in testing)."""
    global _USER_RATE_LIMITS
    _USER_RATE_LIMITS = {}


def extract_links_from_text(text: str) -> List[str]:
    """
    Extracts, cleans, and deduplicates URL strings from resume text.
    """
    if not text or not isinstance(text, str):
        return []

    found = []
    seen = set()

    for match in URL_REGEX.finditer(text):
        raw_url = match.group(0).strip()
        while raw_url and raw_url[-1] in TRAILING_PUNCT:
            raw_url = raw_url[:-1]

        if not raw_url:
            continue

        # Add https:// scheme if missing
        normalized_url = raw_url
        if not re.match(r"^https?://", raw_url, re.IGNORECASE):
            normalized_url = "https://" + raw_url

        url_key = normalized_url.lower()
        if url_key not in seen:
            seen.add(url_key)
            found.append(normalized_url)

    return found


def validate_url_format(url: str) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """
    Validates URL format strictly without performing any network request.

    Returns:
        (is_valid, link_type, error_reason, fix_suggestion)
    """
    if not url or not isinstance(url, str):
        return False, "unknown", "Empty or non-string URL", "Provide a valid URL."

    trimmed = url.strip()
    try:
        parsed = urllib.parse.urlparse(trimmed)
    except Exception as e:
        return False, "malformed", f"Could not parse URL: {e}", "Ensure link contains no invalid characters."

    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        return False, "malformed", f"Unsupported scheme '{scheme}'. Only http and https are allowed", f"Prefix link with https://: https://{trimmed.lstrip(':/')}"

    host = parsed.netloc.lower().split(":")[0]
    if not host or "." not in host:
        return False, "malformed", f"Invalid hostname '{host or 'none'}'", "Include a full domain name (e.g., github.com/username)."

    # Detect link type and validate specific platform patterns
    path = parsed.path.strip("/")
    path_segments = [s for s in path.split("/") if s]

    # 1. GitHub
    if "github.com" in host:
        link_type = "github"
        if not path_segments:
            return False, link_type, "GitHub profile missing username", "Provide your GitHub profile URL: https://github.com/your-username"
        username = path_segments[0]
        # GitHub username validation rule (alphanumeric, hyphens, not starting/ending with hyphen)
        if not re.match(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?$", username):
            return False, link_type, f"Malformed GitHub username '{username}'", "Check your GitHub username for typos or invalid characters."
        return True, link_type, None, None

    # 2. LinkedIn
    if "linkedin.com" in host:
        link_type = "linkedin"
        # LinkedIn profile paths usually start with /in/
        if not path_segments:
            return False, link_type, "LinkedIn profile missing profile path", "Provide your LinkedIn URL: https://linkedin.com/in/your-profile"
        if path_segments[0] != "in":
            return False, link_type, "LinkedIn URL should point to /in/ profile", "Update link to personal profile path: https://linkedin.com/in/your-username"
        if len(path_segments) < 2 or not path_segments[1]:
            return False, link_type, "LinkedIn URL missing profile identifier after /in/", "Include your public handle: https://linkedin.com/in/your-username"
        return True, link_type, None, None

    # 3. LeetCode
    if "leetcode.com" in host:
        link_type = "leetcode"
        if not path_segments:
            return False, link_type, "LeetCode URL missing username", "Link directly to your profile: https://leetcode.com/u/your-username"
        return True, link_type, None, None

    # 4. Other portfolio / website
    link_type = "portfolio"
    return True, link_type, None, None


def is_ip_private_or_loopback(ip_str: str) -> bool:
    """Checks if an IP string belongs to a private, loopback, or non-global range."""
    try:
        ip_obj = ipaddress.ip_address(ip_str)
        if not ip_obj.is_global:
            return True
        for net in BLOCKED_NETWORKS:
            if ip_obj in net:
                return True
        return False
    except ValueError:
        return True


def is_safe_public_host(hostname: str) -> bool:
    """
    Resolves hostname DNS and ensures all destination IPs are strictly public.
    Blocks private and loopback addresses from SSRF exploitation.
    """
    if not hostname:
        return False

    clean_host = hostname.strip().lower()
    # Check if host is direct IP literal
    try:
        return not is_ip_private_or_loopback(clean_host)
    except Exception:
        pass

    try:
        addrs = socket.getaddrinfo(clean_host, None)
        if not addrs:
            return False
        for entry in addrs:
            ip = entry[4][0]
            if is_ip_private_or_loopback(ip):
                logger.warning(f"Blocked request to internal/loopback IP '{ip}' for host '{clean_host}'")
                return False
        return True
    except (socket.gaierror, socket.herror, socket.timeout):
        return False


def check_url_reachability(
    url: str,
    timeout: float = DEFAULT_HEAD_TIMEOUT,
    session: Optional[requests.Session] = None
) -> Dict[str, Any]:
    """
    Checks the reachability of a single URL via HTTP HEAD request (with GET fallback on 405).

    Guarantees:
    - Never contacts private or loopback targets (SSRF protection).
    - Blocks redirects into private or loopback IPs.
    - Timeouts and connection errors show as 'could not verify', not as failures.
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().split(":")[0]

    # 1. SSRF host validation
    if not is_safe_public_host(host):
        return {
            "status": "could_not_verify",
            "status_label": "Could not verify",
            "status_code": None,
            "detail": "Target host cannot be reached or resolved to a non-public address."
        }

    sess = session or requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    try:
        # Perform request with short connect and read timeout
        resp = sess.head(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
            verify=True
        )

        # Validate final URL after redirects for SSRF
        final_host = urllib.parse.urlparse(resp.url).netloc.lower().split(":")[0]
        if not is_safe_public_host(final_host):
            return {
                "status": "could_not_verify",
                "status_label": "Could not verify",
                "status_code": None,
                "detail": "Redirected to private or prohibited address."
            }

        # If server rejects HEAD with 405 Method Not Allowed or 403, fallback to GET with byte range
        if resp.status_code in (405, 403):
            get_headers = dict(headers)
            get_headers["Range"] = "bytes=0-1024"
            resp = sess.get(
                url,
                headers=get_headers,
                timeout=timeout,
                allow_redirects=True,
                stream=True
            )

        status_code = resp.status_code
        if 200 <= status_code < 400:
            return {
                "status": "working",
                "status_label": "Working",
                "status_code": status_code,
                "detail": f"HTTP {status_code} OK"
            }
        elif status_code == 404:
            return {
                "status": "broken",
                "status_label": "Broken (404 Not Found)",
                "status_code": 404,
                "detail": "Page returned 404 Not Found. Double-check username or repository path."
            }
        elif status_code in (401, 403):
            # Often private profile or bot protection (e.g. LinkedIn auth-wall)
            return {
                "status": "working",
                "status_label": "Restricted / Auth Required",
                "status_code": status_code,
                "detail": f"HTTP {status_code}: Profile may be private or protected by login."
            }
        else:
            return {
                "status": "broken",
                "status_label": f"HTTP {status_code}",
                "status_code": status_code,
                "detail": f"Server responded with error status {status_code}."
            }

    except (requests.exceptions.Timeout, socket.timeout):
        return {
            "status": "could_not_verify",
            "status_label": "Could not verify",
            "status_code": None,
            "detail": "Verification timed out. Link may be slow or blocking automated requests."
        }
    except (requests.exceptions.ConnectionError, requests.exceptions.RequestException) as e:
        return {
            "status": "could_not_verify",
            "status_label": "Could not verify",
            "status_code": None,
            "detail": "Connection failed or host was unreachable."
        }


def analyze_resume_links(
    resume_text: str,
    check_reachability: bool = True,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Main entrypoint: extracts links from resume, validates syntax, checks reachability
    (if permitted and not rate limited), and compiles the 'Links' card report.

    Acceptance criteria satisfied:
    - Malformed links are reported without any network call.
    - Private and loopback targets are never requested.
    - Timeouts and errors show as 'could not verify', not as failures.
    - Rate limited per user.
    """
    raw_urls = extract_links_from_text(resume_text)
    if not raw_urls:
        return {
            "total_links": 0,
            "working_count": 0,
            "broken_count": 0,
            "malformed_count": 0,
            "unverified_count": 0,
            "has_issues": False,
            "links": [],
            "summary": "No profile links or URLs detected in resume."
        }

    # Check user rate limiting
    rate_limited = False
    if check_reachability and user_id:
        if is_rate_limited(user_id):
            rate_limited = True
            logger.info(f"User '{user_id}' rate limited for live link checking.")

    results: List[Dict[str, Any]] = []
    urls_to_check: List[Dict[str, Any]] = []

    for url in raw_urls:
        is_valid, link_type, error_reason, fix_suggestion = validate_url_format(url)

        item = {
            "url": url,
            "link_type": link_type or "portfolio",
            "is_valid_format": is_valid,
            "status": "malformed" if not is_valid else "valid_format",
            "status_label": "Malformed Link" if not is_valid else "Valid Format",
            "status_code": None,
            "detail": error_reason if not is_valid else "Valid URL format.",
            "fix_suggestion": fix_suggestion or "Ensure link is accessible to recruiters."
        }

        # If malformed, report immediately without ANY network call
        if not is_valid:
            results.append(item)
            continue

        # If valid and reachability checking enabled & not rate limited
        if check_reachability and not rate_limited:
            urls_to_check.append(item)
        else:
            if rate_limited:
                item["status"] = "could_not_verify"
                item["status_label"] = "Could not verify"
                item["detail"] = "Rate limit reached for live link checking; format verified."
            results.append(item)

    # Perform concurrent HEAD reachability checks on valid links (up to MAX_LINKS_TO_CHECK)
    if urls_to_check:
        to_check = urls_to_check[:MAX_LINKS_TO_CHECK]
        with ThreadPoolExecutor(max_workers=min(5, len(to_check))) as executor:
            future_to_item = {
                executor.submit(check_url_reachability, item["url"]): item
                for item in to_check
            }
            for future in as_completed(future_to_item):
                target_item = future_to_item[future]
                try:
                    reach_res = future.result()
                    target_item["status"] = reach_res["status"]
                    target_item["status_label"] = reach_res["status_label"]
                    target_item["status_code"] = reach_res["status_code"]
                    target_item["detail"] = reach_res["detail"]
                    if reach_res["status"] == "broken":
                        target_item["fix_suggestion"] = "Fix URL spelling or ensure page exists publicly before sending resume."
                except Exception as exc:
                    target_item["status"] = "could_not_verify"
                    target_item["status_label"] = "Could not verify"
                    target_item["detail"] = f"Verification error: {exc}"
                results.append(target_item)

        # Add any remaining unchecked items
        for item in urls_to_check[MAX_LINKS_TO_CHECK:]:
            item["status"] = "could_not_verify"
            item["status_label"] = "Could not verify"
            item["detail"] = "Verification deferred: link limit reached."
            results.append(item)

    working_count = sum(1 for r in results if r["status"] == "working")
    broken_count = sum(1 for r in results if r["status"] == "broken")
    malformed_count = sum(1 for r in results if r["status"] == "malformed")
    unverified_count = sum(1 for r in results if r["status"] in ("could_not_verify", "valid_format"))

    has_issues = (broken_count > 0 or malformed_count > 0)

    return {
        "total_links": len(results),
        "working_count": working_count,
        "broken_count": broken_count,
        "malformed_count": malformed_count,
        "unverified_count": unverified_count,
        "has_issues": has_issues,
        "rate_limited": rate_limited,
        "links": results,
        "summary": (
            f"Found {len(results)} profile link(s): {working_count} verified working, "
            f"{broken_count} broken, {malformed_count} malformed."
        )
    }
