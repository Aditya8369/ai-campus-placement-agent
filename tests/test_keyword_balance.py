"""
Unit and integration tests for Keyword Balance & Stuffing Detection (#685).
Verifies:
- A normal resume shows no warning and zero penalty.
- A resume with a skill repeated many times shows a warning naming the skill and the count.
- A resume with a long comma-separated skill dump (> 40 items) triggers a dump warning.
- The score impact is strictly capped at MAX_KEYWORD_BALANCE_PENALTY and documented.
- Dashboard integration:
  * Renders Keyword balance warning card when stuffing or dumps are detected.
  * Shows no warning card for normal resumes.
"""

import pytest
from app import app
import config
from utils.database import init_db, save_analysis
from utils.keyword_balance_service import (
    check_keyword_balance,
    count_keyword_occurrences,
    detect_skill_dumps,
    MAX_KEYWORD_REPETITION_THRESHOLD,
    MAX_SKILL_LIST_ITEMS_THRESHOLD,
    MAX_KEYWORD_BALANCE_PENALTY,
    DEFAULT_REPETITION_SUGGESTION,
)
from utils.ats_score_service import evaluate_resume_ats_score


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_kw_balance.db")
    monkeypatch.setattr(config, "DATABASE_PATH", test_db)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()
    return test_db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["ENFORCE_LOGIN_IN_TESTS"] = False
    with app.test_client() as c:
        yield c


NORMAL_RESUME_TEXT = """
Jane Doe
Email: jane.doe@example.com | Phone: +1-555-0199 | LinkedIn: linkedin.com/in/janedoe | GitHub: github.com/janedoe

Professional Summary:
Motivated Software Engineer with experience developing scalable web applications and REST APIs.

Education:
Bachelor of Technology in Computer Science, State University, GPA: 3.8/4.0, 2021 - 2025

Technical Skills:
Languages & Frameworks: Python, Java, JavaScript, React, Django, SQL
Tools & Platforms: Docker, Git, Linux, PostgreSQL, AWS

Projects:
Campus Placement Tracker (2024):
- Developed a full-stack portal using Python, Django, and PostgreSQL.
- Implemented real-time dashboard analytics reducing placement coordinator workload by 35%.
- Integrated Docker containers and automated CI/CD deployment pipelines on AWS.

Experience:
Software Engineering Intern, CloudTech Labs (May 2024 - Aug 2024):
- Engineered microservices using Java and Spring Boot handling 5,000 daily requests.
- Optimized slow SQL queries with indexing, cutting average API latency by 40%.
- Authored automated test suites with 85% code coverage.
"""

REPEATED_SKILL_RESUME_TEXT = """
Alex Kumar
Email: alex.kumar@example.com | Phone: +1-555-0144 | LinkedIn: linkedin.com/in/alexkumar | GitHub: github.com/alexkumar

Professional Summary:
Python specialist and Python engineer dedicated to high-performance Python backends and Python applications.

Education:
B.Tech in Computer Science, Tech University, 2021 - 2025

Technical Skills:
Skills: Python, Python Scripting, Python OOP, SQL, Git, Linux

Projects:
Python Web Engine:
- Built a Python system for high-throughput batch analysis using Python.
- Leveraged Python asyncio to orchestrate background worker tasks.

Experience:
Python Developer Intern:
- Wrote clean Python code and Python data scrapers.
- Maintained Python services across production environments.
"""

LONG_SKILL_DUMP_RESUME_TEXT = """
Sam Lee
Email: sam.lee@example.com | Phone: +1-555-0177 | LinkedIn: linkedin.com/in/samlee | GitHub: github.com/samlee

Professional Summary:
Full stack developer with vast technology experience across modern stacks.

Education:
B.Tech Computer Science, Metro College, 2020 - 2024

Technical Skills:
Skills: Python, Java, C, C++, C#, JavaScript, TypeScript, Go, Rust, Ruby, PHP, Swift, Kotlin, HTML, CSS, Sass, React, Angular, Vue, Next.js, Node.js, Express, Django, Flask, FastAPI, Spring Boot, Docker, Kubernetes, AWS, GCP, Azure, Git, GitHub, GitLab, Linux, PostgreSQL, MySQL, MongoDB, Redis, SQLite, GraphQL, REST APIs, Tailwind CSS, Bootstrap, Pandas, NumPy, Scikit-Learn, TensorFlow, PyTorch

Projects:
Portfolio Project:
- Created web app using React and Node.js.

Experience:
Developer Intern:
- Built API endpoints and tested web services.
"""


def test_count_keyword_occurrences():
    """Verify exact word boundary keyword counting."""
    sample = "Python developer building Python APIs with Python. Python scripts in Python."
    assert count_keyword_occurrences(sample, "Python") == 5

    # C++ punctuation test
    cpp_sample = "Proficient in C++, writing C++ modules. Tested C++17."
    assert count_keyword_occurrences(cpp_sample, "C++") == 2


def test_normal_resume_shows_no_warning():
    """Verify that a balanced, natural resume triggers no keyword balance warning."""
    res = check_keyword_balance(NORMAL_RESUME_TEXT)
    assert res["has_warnings"] is False
    assert res["status"] == "Balanced"
    assert len(res["flagged_terms"]) == 0
    assert res["skill_dump_detected"] is False
    assert res["score_penalty"] == 0


def test_repeated_skill_shows_warning_with_name_and_count():
    """
    Acceptance criterion:
    A resume with a skill repeated many times shows a warning naming the skill and the count.
    """
    res = check_keyword_balance(REPEATED_SKILL_RESUME_TEXT)
    assert res["has_warnings"] is True
    assert res["status"] == "Warning"

    # Python appears 10+ times in this text
    flagged_python = next((item for item in res["flagged_terms"] if item["term"].lower() == "python"), None)
    assert flagged_python is not None
    assert flagged_python["count"] > MAX_KEYWORD_REPETITION_THRESHOLD
    assert flagged_python["threshold"] == MAX_KEYWORD_REPETITION_THRESHOLD
    assert flagged_python["suggestion"] == DEFAULT_REPETITION_SUGGESTION
    assert res["score_penalty"] > 0


def test_long_skill_list_dump_detection():
    """
    Acceptance criterion:
    Flags very long comma-separated skill dumps (> 40 items).
    """
    is_dump, count = detect_skill_dumps(LONG_SKILL_DUMP_RESUME_TEXT)
    assert is_dump is True
    assert count > MAX_SKILL_LIST_ITEMS_THRESHOLD

    res = check_keyword_balance(LONG_SKILL_DUMP_RESUME_TEXT)
    assert res["has_warnings"] is True
    assert res["skill_dump_detected"] is True
    assert res["skill_dump_count"] == count


def test_score_impact_is_capped_and_documented():
    """
    Acceptance criterion:
    The score impact is capped and documented.
    """
    # Create extreme stuffing with multiple terms repeated 10+ times and a huge skill dump
    extreme_text = REPEATED_SKILL_RESUME_TEXT + "\n" + LONG_SKILL_DUMP_RESUME_TEXT + "\n" + (
        "Java Java Java Java Java Java Java Java Java Java\n"
        "SQL SQL SQL SQL SQL SQL SQL SQL SQL SQL\n"
        "Docker Docker Docker Docker Docker Docker Docker Docker\n"
        "React React React React React React React React\n"
    )

    res = check_keyword_balance(extreme_text)
    assert res["has_warnings"] is True
    # Verify penalty does not exceed the maximum penalty cap
    assert res["score_penalty"] <= MAX_KEYWORD_BALANCE_PENALTY
    assert res["score_penalty"] == MAX_KEYWORD_BALANCE_PENALTY
    assert res["max_penalty_cap"] == MAX_KEYWORD_BALANCE_PENALTY
    assert "capped at a maximum of" in res["documentation"]

    # Test through evaluate_resume_ats_score
    ats_res = evaluate_resume_ats_score(extreme_text)
    assert "keyword_balance" in ats_res
    assert ats_res["keyword_balance"]["has_warnings"] is True
    assert ats_res["keyword_balance"]["score_penalty"] == MAX_KEYWORD_BALANCE_PENALTY
    assert ats_res["total_score"] == ats_res["base_score"] - MAX_KEYWORD_BALANCE_PENALTY


def test_ats_breakdown_integration_normal_vs_stuffed():
    """Verify that evaluate_resume_ats_score cleanly embeds keyword balance metadata."""
    normal_eval = evaluate_resume_ats_score(NORMAL_RESUME_TEXT)
    assert normal_eval["keyword_balance"]["has_warnings"] is False
    assert normal_eval["keyword_balance"]["score_penalty"] == 0

    stuffed_eval = evaluate_resume_ats_score(REPEATED_SKILL_RESUME_TEXT)
    assert stuffed_eval["keyword_balance"]["has_warnings"] is True
    assert len(stuffed_eval["keyword_balance"]["flagged_terms"]) >= 1


def test_dashboard_renders_keyword_balance_warning_on_stuffed_resume(client):
    """Verify dashboard UI renders the Keyword Balance Warning card with skill name and count."""
    import uuid
    analysis_id = f"test_stuffed_analysis_{uuid.uuid4().hex[:8]}"
    stuffed_breakdown = evaluate_resume_ats_score(REPEATED_SKILL_RESUME_TEXT)

    save_analysis(
        analysis_id=analysis_id,
        resume_filename="resume_stuffed.pdf",
        company_name="Google",
        job_description="Software Engineer",
        results_dict={
            "match_score": 80,
            "resume_analysis": {
                "ats_score": stuffed_breakdown["total_score"],
                "ats_breakdown": stuffed_breakdown,
                "skills": ["Python", "SQL"],
            },
            "extracted_resume_text": REPEATED_SKILL_RESUME_TEXT
        },
        student_id="default_student",
        ats_breakdown=stuffed_breakdown
    )

    res = client.get(f"/dashboard/{analysis_id}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "atsKeywordBalanceCard" in html
    assert "Keyword Balance Warning" in html
    assert "Python" in html
    assert "Mention it once in skills and once with evidence in a project" in html


def test_dashboard_shows_no_warning_on_normal_resume(client):
    """Verify dashboard UI shows NO warning card on a normal, balanced resume."""
    import uuid
    analysis_id = f"test_normal_analysis_{uuid.uuid4().hex[:8]}"
    normal_breakdown = evaluate_resume_ats_score(NORMAL_RESUME_TEXT)

    save_analysis(
        analysis_id=analysis_id,
        resume_filename="resume_normal.pdf",
        company_name="Google",
        job_description="Software Engineer",
        results_dict={
            "match_score": 85,
            "resume_analysis": {
                "ats_score": normal_breakdown["total_score"],
                "ats_breakdown": normal_breakdown,
                "skills": ["Python", "Java", "SQL"],
            },
            "extracted_resume_text": NORMAL_RESUME_TEXT
        },
        student_id="default_student",
        ats_breakdown=normal_breakdown
    )

    res = client.get(f"/dashboard/{analysis_id}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "atsKeywordBalanceCard" not in html
    assert "Keyword Balance Warning" not in html
    assert "Flagged Repeated Terms" not in html
