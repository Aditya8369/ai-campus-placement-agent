"""
Subresource Integrity (SRI) Validator (#648)
============================================
Audits templates for external <script> and <link rel="stylesheet"> tags.
Enforces:
1. Every external resource is pinned to an exact version (no unpinned / latest).
2. Every external resource defines a valid SRI integrity hash (sha256/sha384/sha512).
3. Every external resource defines crossorigin="anonymous".
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


SRI_HASH_PATTERN = re.compile(r'integrity=["\'](sha(?:256|384|512)-[A-Za-z0-9+/=]+)["\']', re.IGNORECASE)
CROSSORIGIN_PATTERN = re.compile(r'crossorigin=["\']anonymous["\']', re.IGNORECASE)
UNPINNED_PATTERNS = [
    re.compile(r'/latest/', re.IGNORECASE),
    re.compile(r'@latest\b', re.IGNORECASE),
    re.compile(r'@\d+/(?![\d.])', re.IGNORECASE),  # e.g. @5/ instead of @5.35.1/
    re.compile(r'/chart\.js(?![@\d])', re.IGNORECASE),  # unversioned chart.js
]


def is_external_url(url: str) -> bool:
    """Returns True if the URL targets an external origin."""
    return url.startswith(("http://", "https://", "//"))


def is_version_pinned(url: str) -> Tuple[bool, str]:
    """
    Validates whether an external resource URL has an exact pinned version.
    Returns (pinned, reason_if_unpinned).
    """
    for pat in UNPINNED_PATTERNS:
        if pat.search(url):
            return False, f"URL uses floating/unpinned tag matching pattern '{pat.pattern}'."

    # Look for version numbers like @1.2.3, /1.2.3/, /v1.2.3/
    has_version = bool(
        re.search(r'[@/v]\d+\.\d+(?:\.\d+)?', url, re.IGNORECASE) or
        re.search(r'/\d+\.\d+\.\d+/', url)
    )

    if not has_version:
        return False, "URL lacks an explicit semantic version (e.g. @x.y.z or /x.y.z/)."

    return True, ""


def check_tag_sri(tag: str, url: str) -> List[str]:
    """
    Checks an external HTML tag for SRI integrity, crossorigin, and version pinning.
    Returns a list of error messages (empty if compliant).
    """
    errors: List[str] = []

    # 1. Integrity attribute
    integrity_match = SRI_HASH_PATTERN.search(tag)
    if not integrity_match:
        errors.append("Missing or malformed 'integrity' attribute (expected sha256-, sha384-, or sha512-).")

    # 2. Crossorigin attribute
    crossorigin_match = CROSSORIGIN_PATTERN.search(tag)
    if not crossorigin_match:
        errors.append("Missing required 'crossorigin=\"anonymous\"' attribute.")

    # 3. Pinned version
    pinned, reason = is_version_pinned(url)
    if not pinned:
        errors.append(f"Unpinned resource version: {reason}")

    return errors


def scan_template_content(content: str, filename: str = "template.html") -> List[Dict[str, Any]]:
    """
    Scans HTML template content for external scripts and stylesheets.
    Returns list of violation dictionaries.
    """
    violations: List[Dict[str, Any]] = []

    # 1. Scan <script> tags
    for match in re.finditer(r'<script\b([^>]*)>', content, re.IGNORECASE):
        tag = match.group(0)
        src_match = re.search(r'src=["\']([^"\']+)["\']', tag, re.IGNORECASE)
        if src_match:
            src = src_match.group(1).strip()
            if is_external_url(src):
                errors = check_tag_sri(tag, src)
                if errors:
                    violations.append({
                        "file": filename,
                        "type": "script",
                        "url": src,
                        "tag": tag,
                        "errors": errors,
                    })

    # 2. Scan <link> tags
    for match in re.finditer(r'<link\b([^>]*)>', content, re.IGNORECASE):
        tag = match.group(0)
        href_match = re.search(r'href=["\']([^"\']+)["\']', tag, re.IGNORECASE)
        rel_match = re.search(r'rel=["\']([^"\']+)["\']', tag, re.IGNORECASE)
        rel = rel_match.group(1).lower() if rel_match else ""

        if href_match:
            href = href_match.group(1).strip()
            # Only stylesheet links require SRI; preconnect/dns-prefetch/icon do not execute CSS/code
            if is_external_url(href) and ("stylesheet" in rel or not rel):
                errors = check_tag_sri(tag, href)
                if errors:
                    violations.append({
                        "file": filename,
                        "type": "stylesheet",
                        "url": href,
                        "tag": tag,
                        "errors": errors,
                    })

    return violations


def scan_templates_directory(
    directory: str | Path = "templates"
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Recursively scans all .html files in directory.
    Returns (violations, stats).
    """
    dir_path = Path(directory)
    if not dir_path.exists():
        return [], {"scanned_files": 0, "external_tags": 0, "violations": 0}

    all_violations: List[Dict[str, Any]] = []
    scanned_files = 0
    external_tags = 0

    for html_file in dir_path.rglob("*.html"):
        scanned_files += 1
        content = html_file.read_text(encoding="utf-8", errors="ignore")

        # Count total external tags
        for m in re.finditer(r'<(?:script|link)\b[^>]*(?:src|href)=["\'](https?://[^"\']+|//[^"\']+)["\'][^>]*>', content, re.IGNORECASE):
            external_tags += 1

        rel_path = str(html_file.relative_to(dir_path))
        violations = scan_template_content(content, filename=rel_path)
        all_violations.extend(violations)

    stats = {
        "scanned_files": scanned_files,
        "external_tags": external_tags,
        "violations": len(all_violations),
    }
    return all_violations, stats


def main() -> int:
    """CLI runner for CI checks."""
    parser = argparse.ArgumentParser(description="Validate Subresource Integrity (SRI) on template tags.")
    parser.add_argument("--templates", default="templates", help="Path to templates directory")
    args = parser.parse_args()

    print("======================================================================")
    print("  AI Campus Placement Agent - Subresource Integrity (SRI) Audit")
    print("======================================================================")

    violations, stats = scan_templates_directory(args.templates)
    print(f"Scanned {stats['scanned_files']} templates containing {stats['external_tags']} external tags.")

    if violations:
        print(f"\n[FAIL] Found {len(violations)} subresource integrity violation(s):")
        for v in violations:
            print(f"\n  File: {v['file']} ({v['type']})")
            print(f"  URL : {v['url']}")
            for err in v["errors"]:
                print(f"    - {err}")
            print(f"  Tag : {v['tag']}")
        print("\nAll external resources must be pinned to exact versions with integrity and crossorigin attributes.")
        print("See CONTRIBUTING.md for instructions on generating SRI hashes.")
        return 1

    print(f"[PASS] All {stats['external_tags']} external scripts and stylesheets are protected with valid SRI hashes and exact version pins.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
