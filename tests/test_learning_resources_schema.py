"""
tests/test_learning_resources_schema.py
Unit & Integration Tests for Curated Learning Resources Catalog & Progress Tracking (#885).

Acceptance Criteria:
1. Resources appear for skills present in the catalog and not for others.
2. Progress is saved per user and shown in the roadmap.
3. The JSON file is validated in CI against its JSON schema.
4. Links are https and reviewed in pull requests.
"""

import json

from utils.learning_resource_service import (
    load_learning_resources,
    validate_learning_resources_data,
    get_resources_for_skill,
    get_user_resource_progress,
    set_user_resource_progress,
    enrich_items_with_resources,
    RESOURCES_FILE,
    SCHEMA_FILE,
    ALLOWED_TYPES,
)


def test_schema_file_exists_and_is_valid():
    """Verify that learning_resources.schema.json exists and is valid JSON."""
    assert SCHEMA_FILE.exists(), f"Schema file not found at {SCHEMA_FILE}"
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        schema = json.load(f)
    assert schema.get("$schema") is not None
    assert "properties" in schema
    assert "resources" in schema["properties"]
    assert "definitions" in schema
    assert "LearningResource" in schema["definitions"]


def test_learning_resources_json_passes_schema_validation():
    """Verify data/learning_resources.json validates without errors."""
    assert RESOURCES_FILE.exists(), f"Resources file not found at {RESOURCES_FILE}"
    with open(RESOURCES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    errors = validate_learning_resources_data(data)
    assert len(errors) == 0, f"Validation errors found: {errors}"
    assert len(data.get("resources", {})) >= 10, "Expected at least 10 skills in catalog"


def test_all_links_use_https():
    """Acceptance Criterion: Links are https."""
    catalog = load_learning_resources()
    assert len(catalog) > 0

    for skill, items in catalog.items():
        assert len(items) > 0, f"Skill '{skill}' must have at least one resource"
        for item in items:
            link = item.get("link", "")
            assert link.startswith("https://"), f"Resource '{item.get('title')}' in skill '{skill}' must be https: {link}"
            assert item.get("type") in ALLOWED_TYPES, f"Invalid type in '{item.get('title')}': {item.get('type')}"
            assert item.get("estimated_hours") > 0, f"Invalid hours in '{item.get('title')}'"
            assert len(item.get("review_note", "").strip()) >= 10, f"Review note too short in '{item.get('title')}'"


def test_resources_appear_for_present_skills_and_not_for_others():
    """Acceptance Criterion: Resources appear for skills present in the catalog and not for others."""
    # Present skills
    py_res = get_resources_for_skill("Python")
    assert len(py_res) > 0
    assert any("py" in r["id"].lower() for r in py_res)

    docker_res = get_resources_for_skill("Docker")
    assert len(docker_res) > 0

    sql_res = get_resources_for_skill("SQL")
    assert len(sql_res) > 0

    # Skill with alias resolution (e.g., 'k8s' -> Kubernetes, 'js' -> JavaScript)
    k8s_res = get_resources_for_skill("k8s")
    assert len(k8s_res) > 0

    js_res = get_resources_for_skill("js")
    assert len(js_res) > 0

    # Non-existent / obscure skills should return empty list
    unknown_res = get_resources_for_skill("NonExistentSkillXYZ12345")
    assert unknown_res == []

    empty_res = get_resources_for_skill("")
    assert empty_res == []


def test_validation_fails_on_missing_required_fields_or_non_https():
    """Verify validator flags non-https links and missing fields."""
    invalid_data = {
        "version": "1.0",
        "resources": {
            "Rust": [
                {
                    "id": "rust-bad",
                    "title": "Rust Book",
                    "link": "http://insecure.example.com/rust",  # HTTP not HTTPS
                    "type": "book",
                    "estimated_hours": 10.0,
                    "review_note": "A comprehensive book on Rust programming."
                }
            ]
        }
    }
    errors = validate_learning_resources_data(invalid_data)
    assert len(errors) > 0
    assert any("must start with https://" in e for e in errors)

    missing_fields = {
        "version": "1.0",
        "resources": {
            "Go": [
                {
                    "id": "go-incomplete",
                    "title": "Go",
                    # missing link, type, hours, review_note
                }
            ]
        }
    }
    errors2 = validate_learning_resources_data(missing_fields)
    assert len(errors2) > 0


def test_user_resource_progress_persistence(tmp_path, monkeypatch):
    """Acceptance Criterion: Progress is saved per user and shown in the roadmap."""
    test_db = tmp_path / "test_progress.db"
    monkeypatch.setenv("DATABASE_PATH", str(test_db))

    import config
    from db.migrations import init_db
    config.DATABASE_PATH = test_db
    init_db(test_db)

    user_a = "user_student_123"
    user_b = "user_student_456"
    resource_id = "py-official-tutorial"

    # Initially empty
    prog_a = get_user_resource_progress(user_a)
    assert prog_a == {}

    # User A starts resource
    set_user_resource_progress(user_a, resource_id, "started", skill_name="Python")
    prog_a_updated = get_user_resource_progress(user_a)
    assert prog_a_updated.get(resource_id) == "started"

    # User B is unaffected
    prog_b = get_user_resource_progress(user_b)
    assert prog_b.get(resource_id) is None

    # User A completes resource
    set_user_resource_progress(user_a, resource_id, "done", skill_name="Python")
    prog_a_done = get_user_resource_progress(user_a)
    assert prog_a_done.get(resource_id) == "done"

    # Reset back to not_started
    set_user_resource_progress(user_a, resource_id, "not_started", skill_name="Python")
    prog_a_reset = get_user_resource_progress(user_a)
    assert prog_a_reset.get(resource_id) == "not_started"


def test_enrich_items_with_resources(tmp_path, monkeypatch):
    """Verify enrichment adds curated resources and per-user status."""
    test_db = tmp_path / "test_enrich.db"
    monkeypatch.setenv("DATABASE_PATH", str(test_db))

    import config
    from db.migrations import init_db
    config.DATABASE_PATH = test_db
    init_db(test_db)

    user_id = "test_user_enrich"
    set_user_resource_progress(user_id, "py-official-tutorial", "started", skill_name="Python")

    items = [
        {"skill": "Python", "importance": "High"},
        {"skill": "UnknownFictionalSkill", "importance": "Low"}
    ]

    enriched = enrich_items_with_resources(items, user_id=user_id)
    assert len(enriched) == 2

    # Item 1: Python
    assert enriched[0]["has_curated_resources"] is True
    res_list = enriched[0]["curated_learning_resources"]
    assert len(res_list) > 0
    py_tut = next(r for r in res_list if r["id"] == "py-official-tutorial")
    assert py_tut["status"] == "started"

    # Item 2: Unknown skill
    assert enriched[1]["has_curated_resources"] is False
    assert enriched[1]["curated_learning_resources"] == []


def test_learning_resources_api_endpoints(tmp_path, monkeypatch):
    """Verify API routes for GET and POST learning-resources progress."""
    test_db = tmp_path / "test_api.db"
    monkeypatch.setenv("DATABASE_PATH", str(test_db))

    import config
    from db.migrations import init_db
    from routes import create_app
    config.DATABASE_PATH = test_db
    init_db(test_db)

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["ENFORCE_LOGIN_IN_TESTS"] = True

    with app.test_client() as client:
        # Unauthenticated request fails with 401
        res = client.get("/api/learning-resources/progress")
        assert res.status_code == 401

        # Simulate authenticated session
        with client.session_transaction() as sess:
            sess["user_id"] = "session_user_789"

        # Update progress to 'started'
        post_res = client.post(
            "/api/learning-resources/progress",
            json={
                "resource_id": "py-official-tutorial",
                "status": "started",
                "skill_name": "Python"
            }
        )
        assert post_res.status_code == 200
        post_data = post_res.get_json()
        assert post_data["success"] is True
        assert post_data["status"] == "started"

        # Read back progress
        get_res = client.get("/api/learning-resources/progress")
        assert get_res.status_code == 200
        get_data = get_res.get_json()
        assert get_data["success"] is True
        assert get_data["progress"].get("py-official-tutorial") == "started"
