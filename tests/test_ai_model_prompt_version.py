import pytest
from app import app
from utils.ai_versioning_service import AIModelPromptVersioningService, ai_versioning_service


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_build_version_metadata():
    service = AIModelPromptVersioningService()
    meta = service.build_version_metadata(
        model_name="Gemini 1.5 Pro",
        model_version="gemini-1.5-pro-002",
        prompt_version="resume-scorer-v2",
        raw_prompt_template="System preamble: evaluate candidates strictly based on ATS metrics."
    )

    assert meta["model_name"] == "Gemini 1.5 Pro"
    assert meta["model_version"] == "gemini-1.5-pro-002"
    assert meta["prompt_version"] == "resume-scorer-v2"
    assert "quantifiable outcomes" in meta["prompt_description"]
    assert len(meta["prompt_fingerprint"]) == 16
    assert "System preamble" not in meta["prompt_fingerprint"]  # Raw prompt must not leak


def test_sanitize_metadata_inputs():
    service = AIModelPromptVersioningService()
    unsafe = {
        "model_version": "v1.0",
        "api_key": "AIzaSyD-secret-google-api-key-here",
        "raw_token": "bearer 123456",
        "notes": "Testing with AIzaSyD123456789012345678901234567890123 key inline"
    }
    sanitized = service.sanitize_metadata_inputs(unsafe)
    assert "api_key" not in sanitized
    assert "raw_token" not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized["notes"]


def test_record_and_retrieve_analysis_version():
    service = AIModelPromptVersioningService()
    analysis_id = "test_analysis_run_999"
    student_id = "student_ver_42"

    row_id = service.record_analysis_version(
        analysis_id=analysis_id,
        student_id=student_id,
        model_name="Campus Placement Evaluator",
        model_version="v2.5.1",
        prompt_version="resume-scorer-2026-q1",
        raw_prompt_template="Detailed instructions here",
        execution_mode="staging"
    )
    assert row_id > 0

    info = service.get_analysis_version_info(analysis_id)
    assert info is not None
    assert info["analysis_id"] == analysis_id
    assert info["student_id"] == student_id
    assert info["model_name"] == "Campus Placement Evaluator"
    assert info["model_version"] == "v2.5.1"
    assert info["prompt_version"] == "resume-scorer-2026-q1"
    assert info["execution_mode"] == "staging"
    assert len(info["prompt_fingerprint"]) == 16

    history = service.list_student_version_history(student_id)
    assert len(history) >= 1
    assert history[0]["analysis_id"] == analysis_id


def test_api_version_metadata_flow(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "student_api_ver_test"

    post_res = client.post("/api/analysis/version-metadata", json={
        "analysis_id": "api_run_888",
        "model_name": "DeepSeek / Gemini Hybrid",
        "model_version": "v1.2",
        "prompt_version": "interview-evaluator-v1",
        "execution_mode": "production"
    })
    assert post_res.status_code == 201
    post_data = post_res.get_json()
    assert post_data["success"] is True
    assert post_data["metadata"]["model_name"] == "DeepSeek / Gemini Hybrid"

    # GET
    get_res = client.get("/api/analysis/version-metadata?analysis_id=api_run_888")
    assert get_res.status_code == 200
    get_data = get_res.get_json()
    assert get_data["success"] is True
    assert get_data["metadata"]["prompt_version"] == "interview-evaluator-v1"


def test_api_version_metadata_missing_id(client):
    res = client.post("/api/analysis/version-metadata", json={
        "model_version": "v1.0"
    })
    assert res.status_code == 400
    assert res.get_json()["success"] is False

    get_res = client.get("/api/analysis/version-metadata")
    assert get_res.status_code == 400
