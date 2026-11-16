import pytest
from app import app
from utils.analysis_reproducibility_service import (
    AnalysisReproducibilityService,
    analysis_reproducibility_service
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_fingerprints_stability():
    service = AnalysisReproducibilityService()
    fp1 = service.generate_input_fingerprint(
        resume_text="Candidate with 4 years Python and Flask experience.",
        job_description="Looking for Python backend developer.",
        target_role="Backend Engineer"
    )
    fp2 = service.generate_input_fingerprint(
        resume_text="Candidate with 4 years Python and Flask experience.",
        job_description="Looking for Python backend developer.",
        target_role="Backend Engineer"
    )
    # Must be deterministic
    assert fp1 == fp2

    # Different inputs yield different fingerprint
    fp3 = service.generate_input_fingerprint(
        resume_text="Candidate with Java and Spring skills.",
        job_description="Looking for Python backend developer.",
        target_role="Backend Engineer"
    )
    assert fp1 != fp3


def test_build_and_record_summary():
    service = AnalysisReproducibilityService()
    analysis_id = "test_run_repro_101"
    student_id = "student_repro_user"

    summary = service.record_reproducibility_summary(
        analysis_id=analysis_id,
        student_id=student_id,
        resume_text="Resume with Python, AWS, Docker.",
        job_description="Senior Software Engineer position.",
        target_role="Software Engineer",
        model_name="gemini-1.5-pro",
        prompt_version="rubric-v3.0",
        temperature=0.1,
        seed=1234,
        scores={"overall": 88, "ats_score": 92}
    )

    assert summary["analysis_id"] == analysis_id
    assert summary["reproducibility_certificate"]["deterministic_seed"] == 1234
    assert summary["reproducibility_certificate"]["temperature"] == 0.1
    assert summary["parameters_audited"]["evaluated_scores"]["overall"] == 88

    # Fetch back
    fetched = service.get_reproducibility_summary(analysis_id)
    assert fetched is not None
    assert fetched["reproducibility_certificate"]["verification_hash"] == summary["reproducibility_certificate"]["verification_hash"]


def test_compare_runs():
    service = AnalysisReproducibilityService()
    resume_text = "Standard resume text content."
    jd = "Junior developer role."

    # Run 1
    service.record_reproducibility_summary(
        analysis_id="run_comp_1",
        student_id="student_1",
        resume_text=resume_text,
        job_description=jd,
        model_name="gemini-1.5-flash",
        prompt_version="v2.0"
    )

    # Run 2 with identical inputs & config
    service.record_reproducibility_summary(
        analysis_id="run_comp_2",
        student_id="student_1",
        resume_text=resume_text,
        job_description=jd,
        model_name="gemini-1.5-flash",
        prompt_version="v2.0"
    )

    comp = service.compare_runs_reproducibility("run_comp_1", "run_comp_2")
    assert comp["is_fully_identical_environment"] is True
    assert comp["same_inputs"] is True
    assert comp["same_configurations"] is True

    # Run 3 with different model
    service.record_reproducibility_summary(
        analysis_id="run_comp_3",
        student_id="student_1",
        resume_text=resume_text,
        job_description=jd,
        model_name="gpt-4o",
        prompt_version="v2.0"
    )
    comp_diff = service.compare_runs_reproducibility("run_comp_1", "run_comp_3")
    assert comp_diff["is_fully_identical_environment"] is False
    assert comp_diff["same_inputs"] is True
    assert comp_diff["same_configurations"] is False


def test_api_reproducibility_endpoints(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "student_repro_api"

    # POST create
    res = client.post("/api/analysis/reproducibility-summary", json={
        "analysis_id": "api_repro_1",
        "resume_text": "Candidate details for API test",
        "target_role": "Full Stack Dev"
    })
    assert res.status_code == 201
    assert res.get_json()["success"] is True

    # GET fetch
    get_res = client.get("/api/analysis/reproducibility-summary?analysis_id=api_repro_1")
    assert get_res.status_code == 200
    assert get_res.get_json()["reproducibility"]["parameters_audited"]["target_role"] == "Full Stack Dev"

    # POST compare
    cmp_res = client.post("/api/analysis/compare-reproducibility", json={
        "analysis_id_a": "api_repro_1",
        "analysis_id_b": "api_repro_1"
    })
    assert cmp_res.status_code == 200
    assert cmp_res.get_json()["comparison"]["is_fully_identical_environment"] is True
