"""
Unit tests for resume version comparison and diff analyzer (#140).
"""

from app import app
from utils.progress_tracker import compare_two_resume_texts


def test_compare_two_resume_texts_delta():
    """Verify keyword extraction and differential scoring between two text versions."""
    text_v1 = (
        "John Doe. Education: B.Tech Computer Science. Skills: Python, Django, HTML, CSS. "
        "Projects: Built basic web application with database integration."
    )
    text_v2 = (
        "John Doe. Education: B.Tech Computer Science. Skills: Python, Django, FastAPI, Docker, Kubernetes, AWS, SQL. "
        "Projects: Architected microservices with distributed caching and CI/CD pipelines. Experience: Software Engineer Intern."
    )

    diff = compare_two_resume_texts(text_v1, text_v2, "v1.pdf", "v2.pdf")
    assert diff["word_count_v2"] > diff["word_count_v1"]
    assert "docker" in diff["added_keywords"] or "kubernetes" in diff["added_keywords"]
    assert diff["sections"]["experience"]["status"] == "added"
    assert "Version 2 shows strong positive iteration" in diff["summary"]


def test_compare_resumes_get_route():
    """Verify GET /compare-resumes returns the comparison template."""
    with app.test_client() as client:
        res = client.get("/compare-resumes")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "Resume Version Comparison" in html
        assert "btnCompareResumes" in html


def test_compare_resumes_post_ajax():
    """Verify POST /compare-resumes with text inputs returns JSON diff."""
    with app.test_client() as client:
        res = client.post(
            "/compare-resumes",
            data={
                "text_v1": "Skills: Python, Java. Education: B.Tech.",
                "text_v2": "Skills: Python, Java, Docker, AWS. Experience: 2 years. Education: B.Tech.",
            },
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert "comparison" in data
        assert data["comparison"]["ats_delta"] >= 0
