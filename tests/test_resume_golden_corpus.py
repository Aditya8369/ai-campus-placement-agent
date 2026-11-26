"""Score regression fixtures through the public upload extraction path."""

import json
import re
import unicodedata
from pathlib import Path

import pytest

import config
from utils.pdf_reader import (
    ScannedPDFError,
    extract_text_from_file,
    standardize_resume_sections,
)
from utils.resume_info_extractor import extract_resume_information

CORPUS = Path(__file__).parent / "fixtures" / "resumes" / "golden"
CASES = json.loads((CORPUS / "expected.json").read_text(encoding="utf-8"))
MIN_COVERAGE = 0.90


def normalized(value):
    folded = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", folded).strip()


@pytest.mark.parametrize("filename", sorted(CASES))
def test_resume_golden_corpus(filename, monkeypatch):
    case = CASES[filename]
    path = str(CORPUS / filename)
    monkeypatch.setattr(config, "ENABLE_OCR_FALLBACK", False)

    if case.get("image_only"):
        error = ScannedPDFError if filename.endswith(".pdf") else ValueError
        with pytest.raises(error, match=r"(?i)(scanned|no extractable text)"):
            extract_text_from_file(path)
        print(f"{filename}: image-only rejection PASS")
        return

    raw_text = extract_text_from_file(path, standardize=False)
    sections = standardize_resume_sections(raw_text)
    skills = {
        normalized(skill) for skill in extract_resume_information(raw_text, filename)["skills"]
    }
    section_results = {
        f"{section}: {phrase}": normalized(phrase) in normalized(sections.get(section, ""))
        for section, phrases in case["sections"].items()
        for phrase in phrases
    }
    skill_results = {f"skill: {skill}": normalized(skill) in skills for skill in case["skills"]}
    results = {**section_results, **skill_results}
    score = sum(results.values()) / len(results)
    missing = [label for label, found in results.items() if not found]
    print(f"{filename}: {score:.0%} ({sum(results.values())}/{len(results)})")
    assert score >= MIN_COVERAGE, f"{filename} scored {score:.0%}, missing: {missing}"
