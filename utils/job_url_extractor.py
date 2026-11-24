"""
Job Description URL Extractor with Server-Side Request Forgery (SSRF) Protection (#689).
========================================================================================
Enables students to import job posting text directly from a URL instead of copying
and pasting manual page clutter (navigation menus, cookie banners, similar jobs, etc.).

Security & Reliability Controls:
1. SSRF Prevention:
   - Restricts schemes strictly to http and https.
   - Resolves DNS and blocks private (RFC 1918), loopback (127.0.0.0/8, ::1),
     link-local (169.254.0.0/16, fe80::/10), carrier-grade NAT (100.64.0.0/10),
     multicast, reserved, and unspecified addresses.
   - Validates IP addresses across all redirects before each request is initiated.
   - Blocks dangerous non-web destination ports.
2. Resource Limits:
   - Enforces a short connect/read timeout (default 8 seconds total).
   - Enforces a strict maximum download size (default 2 MB) via Content-Length and stream chunks.
   - Enforces a maximum redirect limit (default 5 hops).
3. Lightweight Content Extraction:
   - Strips non-content tags (script, style, noscript, iframe, svg, nav, footer, header, form, modal).
   - Identifies primary job content containers using semantic heuristics and standard job board selectors.
   - Normalizes text formatting (headings, bullet points, paragraph breaks) while discarding clutter.
   - Provides clear, actionable user messages when anti-bot protections or extraction issues occur.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import urllib.parse
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Security and Resource Limits
MAX_DOWNLOAD_SIZE: int = 2 * 1024 * 1024  # 2 MB maximum HTML download size
MAX_REDIRECTS: int = 5
DEFAULT_CONNECT_TIMEOUT: float = 3.0
DEFAULT_READ_TIMEOUT: float = 5.0
DEFAULT_TIMEOUT: Tuple[float, float] = (DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT)
MAX_EXTRACTED_CHARS: int = 15000  # Matches platform analysis text length limit
MIN_EXTRACTED_CHARS: int = 50

ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Block well-known internal and non-HTTP service ports from SSRF probing
DANGEROUS_PORTS: frozenset[int] = frozenset({
    21,    # FTP
    22,    # SSH
    23,    # Telnet
    25,    # SMTP
    53,    # DNS
    69,    # TFTP
    110,   # POP3
    111,   # RPC
    135,   # RPC
    137,   # NetBIOS
    138,   # NetBIOS
    139,   # NetBIOS
    143,   # IMAP
    445,   # SMB
    1433,  # MSSQL
    1521,  # Oracle DB
    2049,  # NFS
    2375,  # Docker
    2376,  # Docker TLS
    3306,  # MySQL
    3389,  # RDP
    5000,  # Development / Internal services
    5432,  # PostgreSQL
    5900,  # VNC
    6379,  # Redis
    8500,  # Consul
    11211, # Memcached
    27017, # MongoDB
})


class JobURLExtractionError(Exception):
    """Base error raised when fetching or extracting a job posting fails."""
    pass


class SSRFSecurityError(JobURLExtractionError):
    """Raised when a request is blocked due to SSRF safety policies."""
    pass


def is_ip_blocked(ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]) -> Tuple[bool, str]:
    """
    Evaluates whether an IP address belongs to a restricted, private, loopback,
    or link-local address range.

    Returns:
        (is_blocked: bool, reason: str)
    """
    if ip.is_loopback:
        return True, "Loopback addresses (e.g. 127.0.0.1, ::1) are not allowed."
    if ip.is_private:
        return True, "Private internal network addresses are not allowed."
    if ip.is_link_local:
        return True, "Link-local addresses (e.g. 169.254.x.x, fe80::) are not allowed."
    if ip.is_multicast:
        return True, "Multicast addresses are not allowed."
    if ip.is_reserved:
        return True, "Reserved network addresses are not allowed."
    if ip.is_unspecified:
        return True, "Unspecified network addresses (0.0.0.0, ::) are not allowed."

    # In IPv6, unwrap IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return is_ip_blocked(ip.ipv4_mapped)

    # Global reachability check
    if hasattr(ip, "is_global") and not ip.is_global:
        return True, "Non-global internet addresses are not allowed."

    return False, ""


def validate_url_safety(url: str) -> None:
    """
    Validates that a URL uses a safe scheme (http/https), does not point to a
    blocked port, and that its target hostname and resolved IP addresses do not
    point to private, loopback, or link-local destinations.

    Raises:
        SSRFSecurityError: If the URL or its resolved target is blocked.
        JobURLExtractionError: If URL format or DNS resolution is invalid.
    """
    if not url or not isinstance(url, str):
        raise JobURLExtractionError("Please provide a valid URL string.")

    cleaned_url = url.strip()
    if not cleaned_url:
        raise JobURLExtractionError("URL cannot be empty.")

    try:
        parsed = urllib.parse.urlsplit(cleaned_url)
    except Exception as e:
        raise JobURLExtractionError(f"Malformed URL: {e}")

    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SSRFSecurityError(
            f"Only HTTP and HTTPS links are allowed (received '{scheme}://'). "
            "Please provide a public web URL."
        )

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise JobURLExtractionError("Invalid URL: missing host address.")

    # Remove IPv6 bracket wrapper if present
    clean_host = hostname.strip("[]")

    # Explicit hostname blocklist
    if clean_host in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "metadata.google.internal", "instance-data"):
        raise SSRFSecurityError(f"Access to '{hostname}' is blocked for security reasons.")

    # Check for port restrictions
    if parsed.port and parsed.port in DANGEROUS_PORTS:
        raise SSRFSecurityError(
            f"Access to port {parsed.port} is blocked for security reasons. "
            "Only standard web ports are permitted."
        )

    # Check if host is an integer or hex notation of an IPv4 address (e.g. 2130706433 or 0x7f000001)
    try:
        int_ip = int(clean_host, 0)
        parsed_from_int = ipaddress.IPv4Address(int_ip)
        blocked, reason = is_ip_blocked(parsed_from_int)
        if blocked:
            raise SSRFSecurityError(f"Access to '{hostname}' ({parsed_from_int}) is blocked: {reason}")
    except (ValueError, OverflowError):
        pass

    # Check if host is already a direct IP address literal
    try:
        direct_ip = ipaddress.ip_address(clean_host)
        blocked, reason = is_ip_blocked(direct_ip)
        if blocked:
            raise SSRFSecurityError(f"Access to IP address '{hostname}' is blocked: {reason}")
        return
    except ValueError:
        pass

    # Hostname is a domain name: resolve DNS records to verify all candidate IPs
    try:
        addr_info = socket.getaddrinfo(clean_host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise JobURLExtractionError(
            f"Could not resolve host '{hostname}'. Please verify the URL or copy and paste the job description text manually."
        )
    except Exception as e:
        raise JobURLExtractionError(f"DNS lookup error for '{hostname}': {e}")

    if not addr_info:
        raise JobURLExtractionError(f"No IP address found for host '{hostname}'.")

    for entry in addr_info:
        sockaddr = entry[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
            blocked, reason = is_ip_blocked(ip)
            if blocked:
                raise SSRFSecurityError(
                    f"Host '{hostname}' resolves to a restricted address ({ip_str}): {reason}"
                )
        except ValueError:
            raise SSRFSecurityError(f"Invalid resolved IP address: {ip_str}")


def fetch_job_page_html(
    url: str,
    timeout: Union[float, Tuple[float, float]] = DEFAULT_TIMEOUT,
    max_download_size: int = MAX_DOWNLOAD_SIZE,
    max_redirects: int = MAX_REDIRECTS,
    session: Optional[requests.Session] = None,
) -> str:
    """
    Fetches the HTML of a job posting URL while strictly enforcing SSRF defenses,
    short timeouts, download byte ceilings, and redirect IP verification.

    Returns:
        Decoded HTML string of the webpage.
    """
    if session is None:
        session = requests.Session()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }

    current_url = url.strip()
    redirect_count = 0
    resp = None

    while True:
        # Strictly validate target URL before initiating network request
        validate_url_safety(current_url)

        try:
            resp = session.get(
                current_url,
                headers=headers,
                timeout=timeout,
                stream=True,
                allow_redirects=False,
            )
        except requests.exceptions.Timeout:
            raise JobURLExtractionError(
                "Connection timed out while fetching the job page. The website might be slow or blocking automated access. "
                "Please copy and paste the job description text manually."
            )
        except requests.exceptions.SSLError as e:
            raise JobURLExtractionError(
                f"Secure connection (SSL/TLS) failed: {e}. Please copy and paste the job description text manually."
            )
        except requests.exceptions.RequestException as e:
            raise JobURLExtractionError(
                f"Failed to connect to the job site: {e}. Please copy and paste the job description text manually."
            )

        # Handle manual redirect resolution to inspect target safety
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            redirect_count += 1
            if redirect_count > max_redirects:
                resp.close()
                raise JobURLExtractionError(
                    f"Too many redirects encountered (maximum allowed is {max_redirects}). "
                    "Please copy and paste the job description text manually."
                )

            location = resp.headers.get("Location")
            if not location:
                resp.close()
                raise JobURLExtractionError(
                    "Redirect encountered without a Location header. "
                    "Please copy and paste the job description text manually."
                )

            # Join relative redirects against current URL
            next_url = urllib.parse.urljoin(current_url, location)
            resp.close()
            current_url = next_url
            continue

        # Terminal non-redirect response reached
        break

    try:
        # Check HTTP status codes
        if resp.status_code in (401, 403, 429):
            raise JobURLExtractionError(
                f"The job posting site restricted automated access (HTTP {resp.status_code}). "
                "Please copy and paste the job description text manually."
            )
        elif resp.status_code != 200:
            raise JobURLExtractionError(
                f"Failed to fetch job page (HTTP {resp.status_code}). "
                "Please check the URL or copy and paste the job description text manually."
            )

        # Validate Content-Type
        content_type = (resp.headers.get("Content-Type") or "").lower()
        if not ("text/html" in content_type or "application/xhtml+xml" in content_type):
            raise JobURLExtractionError(
                f"The URL did not return an HTML web page (received '{content_type or 'unknown format'}'). "
                "Please copy and paste the job description text manually."
            )

        # Check declared Content-Length
        content_length = resp.headers.get("Content-Length")
        if content_length:
            try:
                length_int = int(content_length)
                if length_int > max_download_size:
                    raise JobURLExtractionError(
                        f"The webpage is too large ({length_int // 1024} KB exceeds limit of {max_download_size // 1024} KB). "
                        "Please copy and paste the job description text manually."
                    )
            except ValueError:
                pass

        # Read response body stream with strict size limit
        chunks: List[bytes] = []
        total_downloaded = 0
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                total_downloaded += len(chunk)
                if total_downloaded > max_download_size:
                    raise JobURLExtractionError(
                        f"The webpage exceeded the maximum download size ({max_download_size // 1024} KB). "
                        "Please copy and paste the job description text manually."
                    )
                chunks.append(chunk)

        raw_bytes = b"".join(chunks)
        encoding = resp.encoding or "utf-8"
        try:
            return raw_bytes.decode(encoding, errors="replace")
        except Exception:
            return raw_bytes.decode("utf-8", errors="replace")
    finally:
        resp.close()


def extract_job_text_from_html(html_content: str, max_length: int = MAX_EXTRACTED_CHARS) -> Dict[str, Any]:
    """
    Extracts and normalizes the core job description from an HTML document using
    a lightweight readability approach:
    - Strips scripts, styles, forms, navigation bars, headers, footers, and cookie banners.
    - Locates the main job content container using semantic tags and common job selectors.
    - Preserves headings, bulleted lists, and paragraph formatting.
    - Returns structured output with text and extracted title/company hints.
    """
    if not html_content or not isinstance(html_content, str):
        raise JobURLExtractionError(
            "Received empty HTML content. Please copy and paste the job description text manually."
        )

    soup = BeautifulSoup(html_content, "html.parser")

    # Extract preliminary metadata hints before stripping tags
    page_title = (soup.title.string or "").strip() if soup.title else ""
    first_h1 = soup.find("h1")
    role_hint = first_h1.get_text(strip=True) if first_h1 else ""

    company_hint = ""
    if page_title:
        # Heuristic: titles often formatted like "Software Engineer - Google | Careers"
        parts = re.split(r"[-–|•:]", page_title)
        if len(parts) >= 2:
            p0 = parts[0].strip()
            p1 = parts[1].strip()
            if not role_hint:
                role_hint = p0
            # Common company position in title
            if "job" not in p1.lower() and "career" not in p1.lower() and len(p1) < 40:
                company_hint = p1

    # Remove non-content and clutter tags
    clutter_tags = [
        "script", "style", "noscript", "iframe", "svg", "canvas", "header",
        "footer", "nav", "form", "aside", "menu", "template", "dialog",
        "button", "input", "textarea", "select", "meta", "link"
    ]
    for tag_name in clutter_tags:
        for element in list(soup.find_all(tag_name)):
            element.decompose()

    # Remove banner and cookie notice clutter elements
    clutter_pattern = re.compile(
        r"(cookie|consent|banner|sidebar|navbar|site-header|site-footer|modal|popup|social|share|advertisement|promo)",
        re.I,
    )
    job_safelist = re.compile(
        r"(job|posting|description|detail|requirement|qualification|responsibilit)",
        re.I,
    )
    for element in list(soup.find_all(True)):
        if not hasattr(element, "attrs") or element.attrs is None:
            continue
        if element.name in ("body", "html", "main"):
            continue
        classes_raw = element.attrs.get("class", "")
        classes = " ".join(classes_raw) if isinstance(classes_raw, list) else str(classes_raw)
        element_id = str(element.attrs.get("id", ""))
        combined = f"{classes} {element_id}"
        if clutter_pattern.search(combined) and not job_safelist.search(combined):
            element.decompose()

    # Search for job description container
    job_container = (
        soup.find(attrs={"id": re.compile(r"job[-_]?(description|details|post|overview|content)", re.I)})
        or soup.find(class_=re.compile(r"job[-_]?(description|details|post|overview|content)|description__text|jobsearch-JobComponent-description", re.I))
        or soup.find("main")
        or soup.find("article")
        or soup.find(attrs={"role": "main"})
        or soup.body
        or soup
    )

    # Format semantic blocks inside container for readable text representation
    for h in list(job_container.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])):
        h.insert_before("\n\n")
        h.insert_after("\n")

    for li in list(job_container.find_all("li")):
        li.insert_before("\n• ")
        li.insert_after("\n")

    for p in list(job_container.find_all(["p", "div", "section", "article", "blockquote"])):
        p.insert_before("\n")
        p.insert_after("\n")

    for br in list(job_container.find_all("br")):
        br.replace_with("\n")

    # Extract text and normalize line breaks and spacing
    raw_text = job_container.get_text()
    raw_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")

    cleaned_lines: List[str] = []
    consecutive_empty = 0
    for line in raw_text.splitlines():
        trimmed = line.strip()
        if trimmed:
            consecutive_empty = 0
            cleaned_lines.append(trimmed)
        else:
            consecutive_empty += 1
            if consecutive_empty <= 1 and cleaned_lines:
                cleaned_lines.append("")

    extracted_text = "\n".join(cleaned_lines).strip()

    # Verify extracted text meets minimum threshold
    if len(extracted_text) < MIN_EXTRACTED_CHARS:
        raise JobURLExtractionError(
            "Could not extract sufficient job description text from this page (the site may load content dynamically with JavaScript). "
            "Please copy and paste the job description text manually."
        )

    # Enforce maximum text length
    if len(extracted_text) > max_length:
        extracted_text = extracted_text[:max_length].rstrip() + "\n\n[... truncated to maximum length ...]"

    return {
        "status": "success",
        "job_description": extracted_text,
        "character_count": len(extracted_text),
        "title": role_hint,
        "company": company_hint,
    }


def extract_job_description_from_url(
    url: str,
    timeout: Union[float, Tuple[float, float]] = DEFAULT_TIMEOUT,
    max_download_size: int = MAX_DOWNLOAD_SIZE,
    max_redirects: int = MAX_REDIRECTS,
    session: Optional[requests.Session] = None,
) -> Dict[str, Any]:
    """
    High-level entry point:
    1. Validates URL safety and SSRF restrictions.
    2. Fetches public HTML content safely.
    3. Extracts and cleans main job description text.

    Returns dict containing status, job_description, character_count, and metadata hints.
    """
    html = fetch_job_page_html(
        url=url,
        timeout=timeout,
        max_download_size=max_download_size,
        max_redirects=max_redirects,
        session=session,
    )
    result = extract_job_text_from_html(html)
    result["url"] = url.strip()
    return result
