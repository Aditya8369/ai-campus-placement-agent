"""
Tests for Progressive Web App (PWA) Manifest, Service Worker, and Offline Fallback (#471).

Covers:
1. Web App Manifest endpoint (/manifest.json) returning valid PWA spec JSON.
2. PWA icon assets presence, valid format, and dimensions (192x192, 512x512, maskable).
3. Service Worker endpoint (/sw.js) with root scope permissions (Service-Worker-Allowed: /).
4. Service Worker caching logic:
   - Precaches static assets (CSS, JS, manifest, icons, /offline).
   - Serves offline fallback on navigation failures.
   - Strictly EXCLUDES personal data routes (/dashboard, /interview, /profile, /reports, etc.) and /api/ from caching.
5. Offline fallback page (/offline) rendering friendly guidance, retry button, and placement tips.
6. Template integration: manifest link, theme-color meta, apple-touch-icon, and SW registration.
7. README documentation of PWA installability and offline resilience.
"""

import os
import json
import pytest
from PIL import Image
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_manifest_endpoint_and_pwa_spec(client):
    """GET /manifest.json must return HTTP 200 with valid PWA manifest JSON."""
    res = client.get("/manifest.json")
    assert res.status_code == 200
    assert "application/manifest+json" in res.content_type or "application/json" in res.content_type

    data = res.get_json()
    assert data is not None

    # Required PWA manifest properties
    assert data.get("name") == "AI Campus Placement Agent"
    assert data.get("short_name") == "AI Campus"
    assert data.get("start_url") == "/"
    assert data.get("display") == "standalone"
    assert data.get("theme_color") == "#1a73e8"
    assert data.get("background_color") == "#ffffff"

    # Icon requirements for Lighthouse installability
    icons = data.get("icons", [])
    assert len(icons) >= 2, "Manifest must specify multiple icon sizes"

    sizes = [icon.get("sizes") for icon in icons]
    assert "192x192" in sizes, "Must include 192x192 icon"
    assert "512x512" in sizes, "Must include 512x512 icon"

    purposes = [icon.get("purpose") for icon in icons if "purpose" in icon]
    assert any("maskable" in p for p in purposes), "Must include at least one maskable icon for Android adaptive icons"


def test_pwa_icon_files_exist_and_are_valid():
    """Verify that all referenced icons exist on disk with correct image dimensions."""
    manifest_path = os.path.join("static", "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    icons = manifest.get("icons", [])
    assert len(icons) > 0

    for icon in icons:
        src = icon["src"]
        # Strip leading slash for relative path
        rel_path = src.lstrip("/")
        assert os.path.isfile(rel_path), f"Icon file '{rel_path}' does not exist on disk"

        if rel_path.endswith(".png"):
            with Image.open(rel_path) as img:
                expected_size = icon["sizes"].split("x")
                w, h = int(expected_size[0]), int(expected_size[1])
                assert img.size == (w, h), f"Icon {rel_path} expected {w}x{h}, got {img.size}"


def test_service_worker_endpoint_and_headers(client):
    """
    GET /sw.js must return HTTP 200 with javascript content-type,
    root scope permissions (Service-Worker-Allowed: /), and no-cache headers.
    """
    res = client.get("/sw.js")
    assert res.status_code == 200
    assert "javascript" in res.content_type
    assert res.headers.get("Service-Worker-Allowed") == "/"
    assert "no-cache" in res.headers.get("Cache-Control", "")


def test_service_worker_script_logic():
    """
    Service worker script must:
    1. Precache static assets and /offline.
    2. Exclude personal routes and /api/ from caching.
    3. Serve /offline fallback on failed navigation requests.
    """
    sw_path = os.path.join("static", "sw.js")
    with open(sw_path, "r", encoding="utf-8") as f:
        sw_code = f.read()

    # Pre-caching checks
    assert "/offline" in sw_code
    assert "/manifest.json" in sw_code
    assert "CACHE_NAME_STATIC" in sw_code or "cache" in sw_code.lower()

    # Privacy guarantee: personal data routes must NOT be cached
    for private_route in ["/dashboard", "/interview", "/profile", "/download", "/notes", "/history", "/api/"]:
        assert private_route in sw_code, f"SW must explicitly reference and safeguard private route '{private_route}'"

    # Ensure API requests are never cached
    assert "pathname.startsWith('/api/')" in sw_code or "startsWith('/api/')" in sw_code

    # Navigation fallback to /offline
    assert "navigate" in sw_code
    assert "OFFLINE_URL" in sw_code


def test_offline_page_endpoint(client):
    """GET /offline must return HTTP 200 with friendly messaging, retry action, and tips."""
    res = client.get("/offline")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Friendly offline text
    assert "No Internet Connection" in html or "Offline Mode" in html
    assert "Wi-Fi" in html or "connection" in html.lower()

    # Actionable retry button
    assert "btnRetryConnection" in html or "handleRetry" in html
    assert "Try Reconnecting" in html

    # Placement preparation tips
    assert "STAR Technique" in html or "Placement Preparation" in html


def test_templates_contain_pwa_meta_and_registration():
    """HTML templates must link the manifest, define theme-color, and register the service worker."""
    templates = ["templates/base.html", "templates/index.html", "templates/dashboard.html"]

    for tmpl in templates:
        with open(tmpl, "r", encoding="utf-8") as f:
            html = f.read()

        assert 'rel="manifest"' in html or "rel='manifest'" in html, f"{tmpl} missing manifest link"
        assert 'name="theme-color"' in html, f"{tmpl} missing theme-color meta tag"
        assert "serviceWorker" in html, f"{tmpl} missing ServiceWorker registration"
        assert "/sw.js" in html, f"{tmpl} missing /sw.js registration path"


def test_readme_documents_pwa_feature():
    """README.md must document the PWA installability, offline fallback, and Lighthouse checks."""
    with open("README.md", "r", encoding="utf-8") as f:
        readme = f.read()

    assert "Progressive Web App" in readme or "PWA" in readme
    assert "manifest.json" in readme
    assert "sw.js" in readme
    assert "Lighthouse" in readme
    assert "offline" in readme.lower()
