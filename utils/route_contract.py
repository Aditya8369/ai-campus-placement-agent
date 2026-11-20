"""
Route Contract & Frontend URL Verification Engine (#554)
=========================================================
Ensures that all URLs and endpoints referenced across frontend templates
(templates/**/*.html) and client-side scripts (static/js/**/*.js) resolve
against Flask's registered URL map (`app.url_map`), preventing silent 404
regressions and dropped routes.

Also audits test coverage for all registered Flask routes, reporting any
untested endpoints as a warning (with support for strict failure
enforcement in future milestones).

Acceptance Criteria:
1. Removing a route used by the frontend causes immediate failure displaying
   the route name.
2. The allow-list is minimal, strictly documented, and subject to PR review.
3. Runs in CI in under a few seconds with zero external network or AI key.
4. Dynamic URL segments (e.g. /api/jobs/<id>) are matched correctly.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from werkzeug.routing import RequestRedirect  # noqa: E402
from werkzeug.exceptions import MethodNotAllowed, NotFound  # noqa: E402


# ==============================================================================
# Documented Allow-List
# ==============================================================================
# The allow-list is strictly reserved for:
# 1. External protocols (https, http, mailto, tel)
# 2. In-page anchors and empty placeholders (#, javascript:void(0))
# 3. Static asset prefixes (/static/) served by Flask static handler or CDN
# 4. Third-party or dynamically injected client-side paths
# Every entry MUST have a documented justification.
# ==============================================================================

ALLOWLIST_PATTERNS = {
    # In-page anchor hash targets (e.g. #main-content, #step1)
    r"^#.*$": "In-page DOM anchor target navigation",

    # Protocol-relative and external links
    r"^https?://.*$": "External third-party link or CDN URL",
    r"^//.*$": "Protocol-relative external URL",
    r"^mailto:.*$": "Email client mailto link",
    r"^tel:.*$": "Telephone dialer tel link",
    r"^javascript:.*$": "Inline JavaScript pseudo-protocol (void links)",

    # Static assets directory (managed by Flask static handler / CDN)
    r"^/static/.*$": (
        "Static asset file served via Flask static handler or CDN"
    ),

    # Dynamic client-side dummy paths or preview mock URLs
    r"^blob:.*$": "Client-side Blob object URL created in memory",
    r"^data:.*$": "Data URI scheme for client-side previews/downloads",
}


def is_allowlisted(url: str) -> Tuple[bool, Optional[str]]:
    """
    Checks if a URL pattern is covered by the documented allow-list.
    Returns (True, reason) if allowed, otherwise (False, None).
    """
    if not url or url.strip() == "":
        return True, "Empty URL"

    clean_url = url.strip()

    # Direct prefixes
    prefixes = ("#", "javascript:", "mailto:", "tel:", "data:", "blob:")
    if clean_url.startswith(prefixes):
        return True, "Standard non-HTTP link scheme or anchor"

    if clean_url.startswith(("http://", "https://", "//")):
        return True, "External third-party URL"

    for pattern, rationale in ALLOWLIST_PATTERNS.items():
        if re.match(pattern, clean_url, re.IGNORECASE):
            return True, rationale

    return False, None


# ==============================================================================
# Dynamic URL Normalizer
# ==============================================================================

def normalize_frontend_url(raw_url: str) -> str:
    """
    Normalizes template and JavaScript URL expressions into concrete path
    strings suitable for matching against Werkzeug's URL adapter.

    Handles:
    - Jinja control tags: {% if ... %}...{% endif %}
    - Jinja variables: {{ id }}, {{ analysis.id }}, {{ sugg.id }}
    - JS template literals: ${id}, ${analysisId}, ${appId}
    - JS string concatenation: '/api/session/' + sessionId
    - Query parameters and hash fragments: ?foo=bar#section
    """
    if not raw_url:
        return ""

    url = raw_url.strip()

    # 1. Strip Jinja block tags e.g. {% if ... %}...{% endif %}
    url = re.sub(r"\{%.*?%\}", "", url)

    # 2. Strip Jinja query string variables e.g. {{ export_qs }}
    url = re.sub(r"\{\{[^}]*(?:qs|query|params)[^}]*\}\}", "", url)

    # 3. Strip URL query string and fragment
    url = url.split("?")[0].split("#")[0]

    # 4. Replace remaining Jinja expressions like {{ analysis_id }} with '1'
    url = re.sub(r"\{\{[^}]+\}\}", "1", url)

    # 5. Replace JS template literals like ${analysisId} with '1'
    url = re.sub(r"\$\{[^}]+\}", "1", url)

    # 6. Replace JS string concatenation like ' + id or " + id with '1'
    url = re.sub(r"['\"]\s*\+\s*[a-zA-Z0-9_.]+", "1", url)

    # 7. Collapse redundant slashes
    url = re.sub(r"/+", "/", url)

    # 8. Ensure leading slash for root paths
    if not url.startswith("/") and not url.startswith(
        ("http", "#", "mailto", "tel")
    ):
        url = "/" + url

    return url.strip()


# ==============================================================================
# Frontend Scanner
# ==============================================================================

class RouteContractScanner:
    """
    Scans templates and JavaScript files for endpoint names and URL paths,
    verifying each against Flask's registered URL map.
    """

    def __init__(self, app=None, root_dir: Optional[Path] = None):
        if app is None:
            from app import app as flask_app
            self.app = flask_app
        else:
            self.app = app

        self.root_dir = root_dir or PROJECT_ROOT
        self.url_adapter = self.app.url_map.bind("localhost")

        # Compile search regexes
        self.url_for_pattern = re.compile(
            r"""url_for\(\s*['"]([a-zA-Z0-9_\.]+)['"]""",
            re.MULTILINE
        )

        self.fetch_pattern = re.compile(
            r"""\b(?:fetch|apiFetch|\$\.ajax|\$\.get|\$\.post)\("""
            r"""\s*['"`](/[^'"`\s?#)]*)['"`]""",
            re.MULTILINE
        )

        self.action_pattern = re.compile(
            r"""action\s*=\s*['"](/[^'"]*)['"]""",
            re.MULTILINE
        )

        self.href_pattern = re.compile(
            r"""href\s*=\s*['"](/[^'"]*)['"]""",
            re.MULTILINE
        )

        self.location_pattern = re.compile(
            r"""window\.location(?:\.href)?\s*=\s*['"`](/[^'"`]*)['"`]""",
            re.MULTILINE
        )

    def scan_url_for_endpoints(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Scans all HTML templates and JS files for url_for calls.
        Returns a dict mapping endpoint_name -> list of occurrence locations.
        """
        results: Dict[str, List[Dict[str, Any]]] = {}
        target_files = self._get_frontend_files()

        for file_path in target_files:
            try:
                content = file_path.read_text(
                    encoding="utf-8", errors="ignore"
                )
            except Exception:
                continue

            for match in self.url_for_pattern.finditer(content):
                endpoint = match.group(1)
                line_no = content[:match.start()].count("\n") + 1
                rel_path = str(file_path.relative_to(self.root_dir))

                results.setdefault(endpoint, []).append({
                    "file": rel_path,
                    "line": line_no,
                    "raw": match.group(0)
                })

        return results

    def scan_url_paths(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Scans all HTML templates and JS files for path literals.
        Returns a dict mapping raw_path -> list of occurrence locations.
        """
        results: Dict[str, List[Dict[str, Any]]] = {}
        target_files = self._get_frontend_files()

        patterns = [
            ("fetch", self.fetch_pattern),
            ("action", self.action_pattern),
            ("href", self.href_pattern),
            ("location", self.location_pattern),
        ]

        for file_path in target_files:
            try:
                content = file_path.read_text(
                    encoding="utf-8", errors="ignore"
                )
            except Exception:
                continue

            rel_path = str(file_path.relative_to(self.root_dir))

            for source_kind, pattern in patterns:
                for match in pattern.finditer(content):
                    raw_url = match.group(1)
                    line_no = content[:match.start()].count("\n") + 1

                    results.setdefault(raw_url, []).append({
                        "file": rel_path,
                        "line": line_no,
                        "kind": source_kind,
                        "raw": match.group(0)
                    })

        return results

    def verify_frontend_routes(self) -> Dict[str, Any]:
        """
        Verifies that all url_for endpoints and URL paths resolve against
        Flask's url_map.
        """
        registered_endpoints = set(self.app.view_functions.keys())
        url_for_map = self.scan_url_for_endpoints()
        path_map = self.scan_url_paths()

        missing_endpoints = []
        for ep, locations in url_for_map.items():
            if ep not in registered_endpoints:
                if ep == "static":
                    continue
                missing_endpoints.append({
                    "endpoint": ep,
                    "occurrences": locations
                })

        missing_paths = []
        allowlisted_paths = []

        for raw_path, locations in path_map.items():
            allowed, reason = is_allowlisted(raw_path)
            if allowed:
                allowlisted_paths.append({
                    "path": raw_path,
                    "reason": reason,
                    "occurrences": locations
                })
                continue

            clean_path = normalize_frontend_url(raw_path)
            allowed_norm, norm_reason = is_allowlisted(clean_path)
            if allowed_norm:
                allowlisted_paths.append({
                    "path": raw_path,
                    "normalized": clean_path,
                    "reason": norm_reason,
                    "occurrences": locations
                })
                continue

            matched = False
            for method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                try:
                    self.url_adapter.match(clean_path, method=method)
                    matched = True
                    break
                except (MethodNotAllowed, RequestRedirect):
                    matched = True
                    break
                except NotFound:
                    continue
                except Exception:
                    pass

            if not matched:
                missing_paths.append({
                    "raw_path": raw_path,
                    "normalized_path": clean_path,
                    "occurrences": locations
                })

        is_valid = (len(missing_endpoints) == 0 and len(missing_paths) == 0)

        return {
            "valid": is_valid,
            "total_url_for_endpoints": len(url_for_map),
            "total_url_paths": len(path_map),
            "missing_endpoints": missing_endpoints,
            "missing_paths": missing_paths,
            "allowlisted_paths": allowlisted_paths,
        }

    def audit_tested_routes(self) -> Dict[str, Any]:
        """
        Inspects all registered routes in app.url_map and reports which routes
        are referenced by automated test files (tests/test_*.py).
        """
        test_files = list((self.root_dir / "tests").glob("test_*.py"))
        combined_tests = []
        for tf in test_files:
            try:
                combined_tests.append(
                    tf.read_text(encoding="utf-8", errors="ignore")
                )
            except Exception:
                continue

        all_tests_text = "\n".join(combined_tests)

        registered_rules = list(self.app.url_map.iter_rules())
        tested_rules = []
        untested_rules = []

        for rule in registered_rules:
            rule_str = rule.rule
            endpoint = rule.endpoint

            if endpoint == "static":
                tested_rules.append(rule)
                continue

            base_prefix = re.sub(r"<[^>]+>", "", rule_str).rstrip("/")
            if not base_prefix:
                base_prefix = "/"

            is_referenced = (
                rule_str in all_tests_text
                or endpoint in all_tests_text
                or (base_prefix != "/" and base_prefix in all_tests_text)
            )

            if is_referenced:
                tested_rules.append(rule)
            else:
                untested_rules.append(rule)

        return {
            "total_registered_routes": len(registered_rules),
            "tested_routes_count": len(tested_rules),
            "untested_routes_count": len(untested_rules),
            "untested_routes": [
                {
                    "rule": r.rule,
                    "endpoint": r.endpoint,
                    "methods": sorted(
                        [m for m in r.methods if m not in ("HEAD", "OPTIONS")]
                    )
                }
                for r in sorted(untested_rules, key=lambda x: x.rule)
            ]
        }

    def _get_frontend_files(self) -> List[Path]:
        """Collects all template HTML files and static JavaScript files."""
        templates = list((self.root_dir / "templates").glob("**/*.html"))
        scripts = list((self.root_dir / "static" / "js").glob("**/*.js"))
        return templates + scripts


# ==============================================================================
# Human-Readable Diff & CLI Formatter
# ==============================================================================

def format_readable_diff(verification_result: Dict[str, Any]) -> str:
    """Formats missing routes into a clear, actionable diff report."""
    lines = []
    missing_eps = verification_result.get("missing_endpoints", [])
    missing_paths = verification_result.get("missing_paths", [])

    if not missing_eps and not missing_paths:
        return (
            "All frontend URLs and endpoints resolved successfully "
            "against app.url_map!"
        )

    lines.append("=" * 72)
    lines.append("ROUTE CONTRACT VIOLATIONS (UNREGISTERED FRONTEND ROUTES)")
    lines.append("=" * 72)

    if missing_eps:
        lines.append(
            f"\n[-] {len(missing_eps)} Missing Endpoint(s) via url_for():"
        )
        for ep_info in missing_eps:
            lines.append(f"    * Endpoint: '{ep_info['endpoint']}'")
            for occ in ep_info["occurrences"][:3]:
                lines.append(
                    f"        -> {occ['file']}:{occ['line']} ({occ['raw']})"
                )
            if len(ep_info["occurrences"]) > 3:
                remainder = len(ep_info["occurrences"]) - 3
                lines.append(f"        ... and {remainder} more occurrences")

    if missing_paths:
        lines.append(
            f"\n[-] {len(missing_paths)} Missing URL Route(s) "
            "via fetch/href/action:"
        )
        for path_info in missing_paths:
            lines.append(
                f"    * Route: '{path_info['raw_path']}' "
                f"(Normalized: '{path_info['normalized_path']}')"
            )
            for occ in path_info["occurrences"][:3]:
                lines.append(
                    f"        -> {occ['file']}:{occ['line']} "
                    f"[{occ['kind']}] ({occ['raw']})"
                )
            if len(path_info["occurrences"]) > 3:
                remainder = len(path_info["occurrences"]) - 3
                lines.append(f"        ... and {remainder} more occurrences")

    lines.append("\n" + "=" * 80)
    lines.append(
        "Remediation: Register missing routes in app.py or update the call."
    )
    lines.append("=" * 80)
    return "\n".join(lines)


def format_untested_routes_warning(
    audit_result: Dict[str, Any], max_display: int = 15
) -> str:
    """
    Formats an audit report of registered routes not yet covered in tests.
    """
    lines = []
    total = audit_result["total_registered_routes"]
    tested = audit_result["tested_routes_count"]
    untested = audit_result["untested_routes_count"]
    untested_list = audit_result["untested_routes"]

    coverage_pct = round((tested / total) * 100, 1) if total else 0.0

    lines.append("-" * 72)
    lines.append(
        f"ROUTE TEST COVERAGE AUDIT: {tested}/{total} tested "
        f"({coverage_pct}% coverage)"
    )
    lines.append(
        f"[WARNING] {untested} registered route(s) not referenced by tests."
    )
    lines.append("-" * 72)

    for r in untested_list[:max_display]:
        methods_str = ", ".join(r["methods"])
        lines.append(f"  ? {r['rule']} [{methods_str}] -> {r['endpoint']}")

    if len(untested_list) > max_display:
        remainder = len(untested_list) - max_display
        lines.append(f"  ... and {remainder} additional untested route(s).")

    lines.append("-" * 80)
    return "\n".join(lines)


# ==============================================================================
# CLI Entrypoint
# ==============================================================================

def main() -> int:
    """CLI runner executing route contract validation and test audit."""
    print("=" * 72)
    print("AI Campus Placement Agent - Route Contract Verification Runner")
    print("=" * 72)

    scanner = RouteContractScanner()

    # 1. Verify frontend URLs against app.url_map
    verification = scanner.verify_frontend_routes()
    if not verification["valid"]:
        diff_output = format_readable_diff(verification)
        print(diff_output, file=sys.stderr)
    else:
        print(
            f"[PASS] Verified {verification['total_url_for_endpoints']} "
            f"url_for endpoints and {verification['total_url_paths']} "
            "URL paths across templates and JavaScript."
        )

    # 2. Audit test coverage for registered routes
    audit = scanner.audit_tested_routes()
    warning_output = format_untested_routes_warning(audit)
    print(warning_output)

    if not verification["valid"]:
        print(
            "[FAIL] Route contract check failed. Missing routes in frontend.",
            file=sys.stderr,
        )
        return 1

    print("[SUCCESS] All frontend routes exist and contract is satisfied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
