"""
Unit tests for company interview cheat sheet PDF generation and route (#433).
"""

import json
import os
import tempfile
import pytest
from PyPDF2 import PdfReader

from app import app
from utils.database import (
    init_db,
    save_analysis,
    get_student_top_skill_gaps_for_company,
)
from utils.report_generator import generate_company_cheat_sheet_pdf


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as test_client:
        yield test_client


def test_cheat_sheet_pdf_generation_every_company_fits_on_one_page():
    """
    Acceptance Criteria:
    - The PDF downloads for every company in data/companies.json and fits on one page.
    - Generates a PDF for each company and verifies it has exactly one page.
    """
    companies_path = os.path.join(os.path.dirname(__file__), "..", "data", "companies.json")
    with open(companies_path, "r", encoding="utf-8") as f:
        companies_data = json.load(f)

    assert len(companies_data) > 0, "No companies found in data/companies.json"

    with tempfile.TemporaryDirectory() as tmp_dir:
        for company_name, c_data in companies_data.items():
            out_pdf = os.path.join(tmp_dir, f"{company_name}_cheat_sheet.pdf")
            
            # Test without skill gaps
            result_path = generate_company_cheat_sheet_pdf(
                company_name=company_name,
                company_data=c_data,
                output_path=out_pdf,
                skill_gaps=None
            )
            assert os.path.exists(result_path), f"PDF file not created for {company_name}"
            reader = PdfReader(result_path)
            num_pages = len(reader.pages)
            assert num_pages == 1, f"Expected exactly 1 page for {company_name} (no gaps), got {num_pages}"

            # Test with top 3 skill gaps
            out_pdf_gaps = os.path.join(tmp_dir, f"{company_name}_cheat_sheet_gaps.pdf")
            result_path_gaps = generate_company_cheat_sheet_pdf(
                company_name=company_name,
                company_data=c_data,
                output_path=out_pdf_gaps,
                skill_gaps=["Distributed Systems & C++", "Microservices Architecture & GraphQL", "Kafka & Event Streams"]
            )
            assert os.path.exists(result_path_gaps), f"PDF file not created for {company_name} with gaps"
            reader_gaps = PdfReader(result_path_gaps)
            num_pages_gaps = len(reader_gaps.pages)
            assert num_pages_gaps == 1, f"Expected exactly 1 page for {company_name} (with gaps), got {num_pages_gaps}"


def test_cheat_sheet_special_characters_render_correctly():
    """
    Acceptance Criteria:
    - Special characters such as &, < and C++ render correctly without XML syntax errors.
    """
    special_company_data = {
        "overview": "Pioneering systems with C++ & Modern Frameworks <Enterprise & Cloud>.",
        "hiring_process": "Stage 1 <Aptitude & Coding in C++>, Stage 2 <System Design & Architecture>.",
        "technical_rounds": "Deep dive into C++ & STL, Multithreading <Memory Leaks & Pointers>.",
        "hr_rounds": "Questions on ethics & leadership: 'Tell me about a time <conflict> arose & was resolved'.",
        "frequent_topics": [
            "C++ & Memory Management",
            "Algorithms <Trees & Graphs>",
            "Concurrency & Locks",
            "Design Patterns <SOLID & Gang of 4>",
        ],
        "required_skills": [
            "C++ & Low-Level Programming",
            "SQL & ACID Properties <Transactions>",
            "REST APIs & WebSockets",
            "Git & CI/CD Pipelines",
        ],
        "prep_tips": "Review C++ templates, smart pointers & avoid raw malloc/free calls <Modern C++17/20>.",
    }

    special_gaps = [
        "Modern C++ & Standard Template Library (STL)",
        "Database Indexing <B-Trees & Hash Indexes>",
        "Operating Systems <Deadlocks & Semaphores>",
    ]

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_pdf = os.path.join(tmp_dir, "special_chars_cheat_sheet.pdf")
        result_path = generate_company_cheat_sheet_pdf(
            company_name="Tech & Innovation <Lab> C++ Corp",
            company_data=special_company_data,
            output_path=out_pdf,
            skill_gaps=special_gaps,
        )
        assert os.path.exists(result_path)
        reader = PdfReader(result_path)
        assert len(reader.pages) == 1
        
        # Verify text extracted contains escaped characters rendered readable
        extracted_text = reader.pages[0].extract_text()
        assert "C++" in extracted_text
        assert "Tech & Innovation" in extracted_text


def test_cheat_sheet_skill_gap_section_skipped_gracefully_when_no_analysis(client):
    """
    Acceptance Criteria:
    - The skill-gap section is skipped gracefully when the student has no analysis.
    """
    student_id = "student_without_any_analysis_xyz_123"
    
    # Database helper check
    gaps = get_student_top_skill_gaps_for_company(student_id, "Google")
    assert gaps == []

    # Route check
    resp = client.get(f"/company/Google/cheat-sheet?student_id={student_id}")
    assert resp.status_code == 200
    assert resp.content_type == "application/pdf"
    assert "attachment;" in resp.headers.get("Content-Disposition", "")
    assert "Google_Interview_Cheat_Sheet.pdf" in resp.headers.get("Content-Disposition", "")

    # Write out response and check page count & absence of skill gap header
    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = os.path.join(tmp_dir, "google_no_gaps.pdf")
        with open(pdf_path, "wb") as f:
            f.write(resp.data)
        reader = PdfReader(pdf_path)
        assert len(reader.pages) == 1
        extracted = reader.pages[0].extract_text()
        assert "Identified Skill Gaps" not in extracted


def test_cheat_sheet_includes_student_skill_gaps_when_analysis_exists(client):
    """
    Verifies that when a student has an analysis for a target company,
    their top 3 skill gaps are retrieved and included in the cheat sheet.
    """
    init_db()
    student_id = "student_with_analysis_433"
    company = "Adobe"

    mock_results = {
        "resume_analysis": {"ats_score": 75},
        "job_match": {
            "match_percentage": 70,
            "missing_skills": ["C++", "System Architecture", "GraphQL", "Kubernetes"],
        },
        "skill_gap": [
            {"skill": "C++", "priority": "High"},
            {"skill": "System Architecture", "priority": "High"},
            {"skill": "GraphQL", "priority": "Medium"},
            {"skill": "Kubernetes", "priority": "Low"},
        ]
    }

    save_analysis(
        analysis_id="test_analysis_433_id",
        resume_filename="resume_test.pdf",
        company_name=company,
        job_description="Software Engineer at Adobe working with C++ and Cloud",
        results_dict=mock_results,
        student_id=student_id,
    )

    gaps = get_student_top_skill_gaps_for_company(student_id, company, limit=3)
    assert len(gaps) == 3
    assert gaps[0] == "C++"
    assert gaps[1] == "System Architecture"
    assert gaps[2] == "GraphQL"

    # Request cheat sheet through route with session
    with client.session_transaction() as sess:
        sess["user_id"] = student_id

    resp = client.get(f"/company/{company}/cheat-sheet")
    assert resp.status_code == 200
    assert resp.content_type == "application/pdf"

    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = os.path.join(tmp_dir, "adobe_with_gaps.pdf")
        with open(pdf_path, "wb") as f:
            f.write(resp.data)
        reader = PdfReader(pdf_path)
        assert len(reader.pages) == 1
        extracted = reader.pages[0].extract_text()
        assert "Identified Skill Gaps" in extracted
        assert "C++" in extracted


def test_cheat_sheet_company_not_found(client):
    """
    Verifies 302 redirect when an unknown company profile is requested.
    """
    resp = client.get("/company/UnknownCompanyNonExistentXYZ/cheat-sheet")
    assert resp.status_code == 302
    assert "/companies" in resp.headers.get("Location", "")
