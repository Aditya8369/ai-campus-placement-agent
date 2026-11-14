"""Best-effort checks for external learning-resource links."""

import re
import socket
import ipaddress
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse


URL_PATTERN = re.compile(r"https?://[^\s<>\"]*", re.IGNORECASE)
CHECK_TIMEOUT_SECONDS = 2.0
MAX_LINKS = 30


def extract_http_links(value: Any) -> List[str]:
    """Extract unique HTTP(S) links from a resource description."""
    if not isinstance(value, str):
        return []
    links = []
    seen = set()
    for raw_url in URL_PATTERN.findall(value):
        url = raw_url.rstrip(".,;:)]}")
        if url.lower() not in seen:
            links.append(url)
            seen.add(url.lower())
    return links


def _is_public_host(hostname: str) -> bool:
    """Avoid making server-side requests to local or private network targets."""
    try:
        addresses = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    for address in addresses:
        ip = address[4][0]
        if not ipaddress.ip_address(ip).is_global:
            return False
    return True


def check_link(url: str, timeout: float = CHECK_TIMEOUT_SECONDS) -> Dict[str, str]:
    """Check one link without raising network errors to the caller."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or not parsed.hostname:
        return {"url": url, "status": "broken", "label": "Broken", "detail": "Malformed URL"}
    if not _is_public_host(parsed.hostname):
        return {
            "url": url,
            "status": "unchecked",
            "label": "Unchecked",
            "detail": "Link could not be checked from this server",
        }

    try:
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "CampusPlacementLinkChecker/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status_code = response.getcode()
        except urllib.error.HTTPError as error:
            if error.code == 405:
                request = urllib.request.Request(
                    url,
                    method="GET",
                    headers={"Range": "bytes=0-0", "User-Agent": "CampusPlacementLinkChecker/1.0"},
                )
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    status_code = response.getcode()
            else:
                status_code = error.code
        if 200 <= status_code < 400:
            return {"url": url, "status": "working", "label": "Working", "detail": f"HTTP {status_code}"}
        return {"url": url, "status": "broken", "label": "Broken", "detail": f"HTTP {status_code}"}
    except (TimeoutError, socket.timeout):
        return {"url": url, "status": "unchecked", "label": "Unchecked", "detail": "Check timed out"}
    except (urllib.error.URLError, OSError):
        return {
            "url": url,
            "status": "unchecked",
            "label": "Unchecked",
            "detail": "Temporary connection failure",
        }


def check_learning_resources(skill_gaps: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Copy skill-gap records and attach best-effort status for their URLs."""
    records = [dict(item) for item in skill_gaps if isinstance(item, dict)]
    urls = []
    for record in records:
        for url in extract_http_links(record.get("learning_resource", "")):
            if url not in urls and len(urls) < MAX_LINKS:
                urls.append(url)

    results: Dict[str, Dict[str, str]] = {}
    if urls:
        executor = ThreadPoolExecutor(max_workers=min(6, len(urls)))
        futures = {executor.submit(check_link, url): url for url in urls}
        try:
            for future in as_completed(futures, timeout=CHECK_TIMEOUT_SECONDS + 0.5):
                url = futures[future]
                try:
                    results[url] = future.result()
                except Exception:
                    results[url] = {
                        "url": url,
                        "status": "unchecked",
                        "label": "Unchecked",
                        "detail": "Link could not be checked",
                    }
        except TimeoutError:
            for url in urls:
                results.setdefault(
                    url,
                    {
                        "url": url,
                        "status": "unchecked",
                        "label": "Unchecked",
                        "detail": "Check timed out",
                    },
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    for record in records:
        record["resource_links"] = [
            results.get(url, {
                "url": url,
                "status": "unchecked",
                "label": "Unchecked",
                "detail": "Link could not be checked",
            })
            for url in extract_http_links(record.get("learning_resource", ""))
        ]
    return records
