"""
Unit and Integration Tests for Resume Text Extraction and Section Parsing.

Tests resume parsing accuracy across multiple layout styles:
1. Single Column Layout (traditional top-to-bottom)
2. Two Column Layout (modern sidebar / parallel columns)
3. Table Layout (academic grid / pipe-separated tables)
4. No Section Headings Layout (unstructured narrative / conversational format)

Verifies extraction of:
- Contact details (Candidate Name, Email, Phone Number)
- Technical Skills
- Education (Degree, Institution, Graduation Year, Score/GPA)
- Work Experience & Internships (Role, Company, Duration, Responsibilities)
- Section Validation and Completeness Scoring

Also verifies:
- PDF document extraction for each layout
- Strict privacy enforcement (zero real personal data in fixtures)

Runnable with one documented command:
    pytest tests/test_resume_parser.py -o addopts=""
"""

import os
import io
import re
import tempfile
import pytest
from typing import Dict, Any

from utils.pdf_reader import (
    extract_text_from_pdf,
    extract_text_from_file,
    standardize_resume_sections,
    validate_pdf_content,
    deinterleave_two_column_text
)
from utils.resume_info_extractor import (
    extract_resume_information,
    extract_candidate_name,
    extract_emails,
    extract_phone,
    extract_education_entries,
    extract_skills_list,
    extract_experience_entries,
    extract_projects_entries
)
from utils.resume_section_validator import ResumeSectionValidator

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "resumes")


def load_fixture(filename: str) -> str:
    """Helper to load resume fixture text from file."""
    path = os.path.join(FIXTURES_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ============================================================================
# 1. FIXTURE DATA INTEGRITY & PRIVACY AUDIT TESTS
# ============================================================================

def test_fixtures_exist():
    """Verify all four layout fixture files are present in tests/fixtures/resumes."""
    expected_files = [
        "single_column_resume.txt",
        "two_column_resume.txt",
        "table_resume.txt",
        "no_headings_resume.txt"
    ]
    for filename in expected_files:
        filepath = os.path.join(FIXTURES_DIR, filename)
        assert os.path.exists(filepath), f"Missing required resume fixture: {filename}"
        assert os.path.getsize(filepath) > 50, f"Fixture file is empty or too short: {filename}"


def test_fixtures_contain_no_real_personal_data():
    """
    Acceptance criterion: Fixtures contain no real personal data.
    Ensures all emails use RFC 2606 example domains and phone numbers use 555 fictitious exchanges.
    """
    for filename in os.listdir(FIXTURES_DIR):
        if not filename.endswith(".txt"):
            continue
        content = load_fixture(filename)

        # Check emails: must use @example.com, @example.org, @example.net, or @test
        emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", content)
        assert len(emails) >= 1, f"Fixture {filename} should contain at least one fictional email."
        for email in emails:
            domain = email.split("@")[1].lower()
            assert any(domain.startswith(allowed) for allowed in ["example.", "test."]), (
                f"Found non-fictional email domain '{domain}' in {filename}"
            )

        # Check phones: must contain 555 exchange
        phones = re.findall(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", content)
        for phone in phones:
            assert "555" in phone, f"Found phone number without fictional 555 exchange: {phone} in {filename}"


# ============================================================================
# 2. SINGLE COLUMN RESUME LAYOUT TESTS
# ============================================================================

class TestSingleColumnResumeLayout:
    """Test suite for single-column linear layout resumes."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.text = load_fixture("single_column_resume.txt")
        self.info = extract_resume_information(self.text, filename="single_column_resume.txt")

    def test_contact_details_extraction(self):
        """Verify candidate name, email, and phone extraction from single-column layout."""
        assert self.info["candidate_name"] == "Maya Lin"
        assert self.info["email"] == "maya.lin@example.com"
        assert "(555) 234-5678" in self.info["phone"]

    def test_education_extraction(self):
        """Verify degree, institution, graduation year, and score from single-column layout."""
        edu = self.info["education"]
        assert len(edu) >= 1
        entry = edu[0]
        assert "Computer Science" in entry["degree"]
        assert "University of Washington" in entry["institution"]
        assert "2020 - 2024" in entry["graduation_year"]
        assert entry["score"] == "3.85"
        assert entry["is_incomplete"] is False

    def test_skills_extraction(self):
        """Verify technical skills detection from single-column layout."""
        skills = self.info["skills"]
        assert len(skills) >= 6
        expected = ["Python", "Java", "Go", "PostgreSQL", "Docker", "Kubernetes", "AWS", "Git", "Redis"]
        for s in expected:
            assert s in skills, f"Expected skill '{s}' not detected in single-column resume"

    def test_experience_extraction(self):
        """Verify job role, company, duration, and responsibilities from single-column layout."""
        exp = self.info["experience"]
        assert len(exp) == 1
        entry = exp[0]
        assert "Software Engineer Intern" in entry["role"]
        assert "ByteWave Labs" in entry["company"]
        assert "Jun 2023 - Sep 2023" in entry["duration"]
        assert "RESTful API endpoints" in entry["responsibilities"]
        assert entry["is_incomplete"] is False

    def test_section_validation_completeness(self):
        """Verify completeness score and presence of sections in single-column layout."""
        validator = ResumeSectionValidator()
        res = validator.validate_sections(self.text)
        assert res["completeness_score"] >= 80
        assert res["sections"]["contact"]["present"] is True
        assert res["sections"]["education"]["present"] is True
        assert res["sections"]["skills"]["present"] is True
        assert res["sections"]["experience"]["present"] is True


# ============================================================================
# 3. TWO COLUMN RESUME LAYOUT TESTS
# ============================================================================

class TestTwoColumnResumeLayout:
    """Test suite for two-column parallel / sidebar layout resumes."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.text = load_fixture("two_column_resume.txt")
        self.info = extract_resume_information(self.text, filename="two_column_resume.txt")

    def test_contact_details_extraction(self):
        """Verify contact details extraction when placed in headers or columns."""
        assert self.info["candidate_name"] == "Devon Vance"
        assert self.info["email"] == "devon.vance@example.com"
        assert "555-890-1234" in self.info["phone"]

    def test_education_extraction(self):
        """Verify education credentials extracted from left column."""
        edu = self.info["education"]
        assert len(edu) >= 1
        entry = edu[0]
        assert "Computer Science" in entry["degree"]
        assert "University of Texas at Austin" in entry["institution"]
        assert "2020 - 2024" in entry["graduation_year"]
        assert entry["score"] == "3.75"
        assert entry["is_incomplete"] is False

    def test_skills_extraction(self):
        """Verify technical skills extracted from two-column sidebar."""
        skills = self.info["skills"]
        assert len(skills) >= 6
        expected = ["Python", "TypeScript", "React", "Node.js", "Docker", "MongoDB", "Git", "PostgreSQL"]
        for s in expected:
            assert s in skills, f"Expected skill '{s}' not detected in two-column resume"

    def test_experience_extraction(self):
        """Verify work experience extracted from right column."""
        exp = self.info["experience"]
        assert len(exp) >= 1
        entry = exp[0]
        assert "Full Stack Intern" in entry["role"]
        assert "Horizon Cloud" in entry["company"]
        assert "Jun 2023 - Aug 2023" in entry["duration"]
        assert "Node.js" in entry["responsibilities"]
        assert entry["is_incomplete"] is False

    def test_deinterleave_two_column_text(self):
        """Verify the column deinterleaver cleanly unstacks parallel columns into sequential text."""
        unstacked = deinterleave_two_column_text(self.text)
        assert "EDUCATION" in unstacked
        assert "WORK EXPERIENCE" in unstacked
        # After unstacking, left column precedes right column in sequential order
        edu_pos = unstacked.find("EDUCATION")
        exp_pos = unstacked.find("WORK EXPERIENCE")
        assert edu_pos < exp_pos


# ============================================================================
# 4. TABLE RESUME LAYOUT TESTS
# ============================================================================

class TestTableResumeLayout:
    """Test suite for academic / institutional table-formatted resumes."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.text = load_fixture("table_resume.txt")
        self.info = extract_resume_information(self.text, filename="table_resume.txt")

    def test_contact_details_extraction(self):
        """Verify contact details extraction from table-formatted resume."""
        assert self.info["candidate_name"] == "Elena Rostova"
        assert self.info["email"] == "elena.rostova@example.com"
        assert "555-432-8765" in self.info["phone"]

    def test_education_table_row_extraction(self):
        """Verify table rows are parsed into structured education entries and headers are ignored."""
        edu = self.info["education"]
        assert len(edu) >= 1
        entry = edu[0]
        # Ensure table header row ("Degree | Institution | Year | Score") is NOT extracted as an entry
        assert entry["degree"] != "Degree"
        assert entry["institution"] != "Institution"
        assert "Computer Engineering" in entry["degree"]
        assert "Midwest State University" in entry["institution"]
        assert "2020 - 2024" in entry["graduation_year"]
        assert entry["score"] == "3.9"
        assert entry["is_incomplete"] is False

    def test_skills_table_extraction(self):
        """Verify skills are extracted from table cells while ignoring table category headers."""
        skills = self.info["skills"]
        assert len(skills) >= 6
        expected = ["Python", "Java", "C++", "TypeScript", "React", "Node.js", "Docker", "Kubernetes", "AWS", "SQL"]
        for s in expected:
            assert s in skills, f"Expected skill '{s}' not detected in table resume"

        # Verify table header keywords are strictly filtered out
        for non_skill in ["Category", "Technologies", "Programming", "Web & Cloud"]:
            assert non_skill not in skills, f"Table header '{non_skill}' was mistakenly captured as a skill"

    def test_experience_table_extraction(self):
        """Verify experience table rows are parsed and table headers are ignored."""
        exp = self.info["experience"]
        assert len(exp) == 2

        # First table row: Backend Intern | DataFlow Tech | May 2023 - Aug 2023
        exp1 = exp[0]
        assert exp1["role"] == "Backend Intern"
        assert exp1["company"] == "DataFlow Tech"
        assert "May 2023 - Aug 2023" in exp1["duration"]
        assert "ETL pipelines" in exp1["responsibilities"]
        assert exp1["is_incomplete"] is False

        # Second table row: Full Stack Trainee | Apex Software | Jan 2023 - Apr 2023
        exp2 = exp[1]
        assert exp2["role"] == "Full Stack Trainee"
        assert exp2["company"] == "Apex Software"
        assert "Jan 2023 - Apr 2023" in exp2["duration"]
        assert "GraphQL" in exp2["responsibilities"]
        assert exp2["is_incomplete"] is False

        # Ensure table header row is NOT in experience entries
        for e in exp:
            assert e["role"] != "Role"
            assert e["company"] != "Company"


# ============================================================================
# 5. NO SECTION HEADINGS RESUME LAYOUT TESTS
# ============================================================================

class TestNoHeadingsResumeLayout:
    """Test suite for unstructured narrative resumes without standard section headers."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.text = load_fixture("no_headings_resume.txt")
        self.info = extract_resume_information(self.text, filename="no_headings_resume.txt")

    def test_contact_details_extraction(self):
        """Verify contact details extraction from unstructured conversational text."""
        assert self.info["candidate_name"] == "Marcus Brody"
        assert self.info["email"] == "marcus.brody@example.com"
        assert "555" in self.info["phone"]

    def test_narrative_education_extraction(self):
        """Verify education credentials extracted from narrative sentences without headers."""
        edu = self.info["education"]
        assert len(edu) >= 1
        entry = edu[0]
        assert "Computer Science" in entry["degree"]
        assert "Colorado State University" in entry["institution"]
        assert "2024" in entry["graduation_year"]
        assert "3.8" in entry["score"]

    def test_narrative_skills_extraction(self):
        """Verify skills identified across unstructured text blocks."""
        skills = self.info["skills"]
        assert len(skills) >= 6
        expected = ["Python", "C++", "Java", "Docker", "Git", "Linux", "PostgreSQL", "SQL"]
        for s in expected:
            assert s in skills, f"Expected skill '{s}' not detected in no-headings resume"

    def test_narrative_experience_extraction(self):
        """Verify work experience extracted from conversational sentences."""
        exp = self.info["experience"]
        assert len(exp) >= 1
        # Find the entry matching Rocky Mountain Cloud
        entry = next((e for e in exp if "Rocky Mountain Cloud" in e.get("company", "")), None)
        assert entry is not None, "Did not extract experience at Rocky Mountain Cloud"
        assert "Software Engineer Intern" in entry["role"]
        assert "June 2023 to August 2023" in entry["duration"]
        assert "microservices" in entry["responsibilities"]

    def test_section_validator_keyword_detection(self):
        """Verify section validator recognizes keywords even without explicit section headers."""
        validator = ResumeSectionValidator()
        res = validator.validate_sections(self.text)
        assert res["completeness_score"] >= 70
        assert res["sections"]["education"]["present"] is True
        assert res["sections"]["skills"]["present"] is True


# ============================================================================
# 6. PDF EXTRACTION PIPELINE TESTS FOR ALL FOUR LAYOUTS
# ============================================================================

class TestPDFResumeExtraction:
    """End-to-end integration tests compiling layout fixtures to PDF and reading via pdf_reader."""

    def _create_simple_pdf_bytes(self, text: str) -> bytes:
        """Compiles plain text into a valid PDF in memory using ReportLab."""
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []

        for line in text.splitlines():
            line_str = line.strip()
            if line_str:
                # Escape XML entities for ReportLab Paragraph
                escaped = line_str.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                story.append(Paragraph(escaped, styles["Normal"]))
            else:
                story.append(Spacer(1, 6))

        doc.build(story)
        buf.seek(0)
        return buf.getvalue()

    @pytest.mark.parametrize("fixture_name", [
        "single_column_resume.txt",
        "two_column_resume.txt",
        "table_resume.txt",
        "no_headings_resume.txt"
    ])
    def test_pdf_extraction_for_all_fixtures(self, fixture_name: str):
        """Compile each fixture to PDF and verify text extraction and validation."""
        text = load_fixture(fixture_name)
        pdf_bytes = self._create_simple_pdf_bytes(text)

        # 1. Validate PDF signature magic bytes
        is_valid_pdf, err = validate_pdf_content(pdf_bytes)
        assert is_valid_pdf is True
        assert err == ""

        # 2. Extract text from PDF file on disk
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        try:
            extracted_text = extract_text_from_pdf(tmp_path)
            assert len(extracted_text) >= 100

            # Also verify unified extract_text_from_file works on this PDF
            unified_text = extract_text_from_file(tmp_path)
            assert len(unified_text) >= 100

            # 3. Verify core entities are present in extracted text
            # Email should always survive PDF serialization and extraction
            email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", extracted_text)
            assert email_match is not None

            # Python skill should survive PDF round-trip
            assert "Python" in extracted_text
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
