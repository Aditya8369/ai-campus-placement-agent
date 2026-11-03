"""
Document reader utilities for PDF and DOCX resume parsing and validation.

Supports extracting clean, structured textual representations from uploaded .pdf
and .docx documents, checking page/paragraph constraints, handling corrupt or
encrypted files gracefully, and validating word/character thresholds.
"""

import io
import logging
import os
import re
from typing import List, Optional, Tuple, Union, Dict, Any
from typing import Dict, List, Optional, Tuple, Union
from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError

try:
    import docx
    from docx.opc.exceptions import PackageNotFoundError
except ImportError:  # pragma: no cover
    docx = None
    PackageNotFoundError = Exception

logger = logging.getLogger(__name__)

# Constants for document processing limits
MAX_PDF_PAGES = 10
MAX_DOCX_PARAGRAPHS = 1000
MAX_RESUME_TEXT_CHARS = 25000
MIN_RESUME_TEXT_CHARS = 50
MIN_RESUME_WORD_COUNT = 10
ALLOWED_RESUME_EXTENSIONS = {".pdf", ".docx"}


def validate_resume_text(text: str) -> Tuple[bool, str]:
    """
    Validates whether resume text satisfies length, word count, and content criteria.
    Returns (is_valid, error_message).
    """
    if not text or not text.strip():
        return False, "Resume content cannot be empty. Please provide your resume details."

    cleaned = text.strip()
    if len(cleaned) < MIN_RESUME_TEXT_CHARS:
        return False, f"Resume content is too short (minimum {MIN_RESUME_TEXT_CHARS} characters required for analysis)."

    words = [w for w in cleaned.split() if w.strip()]
    if len(words) < MIN_RESUME_WORD_COUNT:
        return False, f"Resume content must contain at least {MIN_RESUME_WORD_COUNT} words (education, skills, or experience)."

    return True, ""


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extracts and returns text content from a PDF file using PyPDF2.
    Enforces maximum page limits, verifies encryption status, and validates extracted text.
    """
    text_content = ""
    try:
        logger.info(f"Initiating text extraction from PDF: {pdf_path}")
        reader = PdfReader(pdf_path)

        if getattr(reader, "is_encrypted", False):
            raise ValueError(
                "The uploaded PDF is password-protected or encrypted. Please upload an unprotected PDF."
            )

        num_pages = len(reader.pages)
        if num_pages == 0:
            raise ValueError("The PDF file contains no readable pages.")

        if num_pages > MAX_PDF_PAGES:
            raise ValueError(
                f"The uploaded PDF contains {num_pages} pages, exceeding the {MAX_PDF_PAGES}-page limit for resumes. "
                "Please upload a standard concise campus placement resume."
            )

        for page_idx, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text_content += page_text + "\n"

        cleaned_text = text_content.strip()
        is_valid, validation_msg = validate_resume_text(cleaned_text)
        if not is_valid:
            logger.warning(
                f"Extracted PDF text validation failed ({validation_msg}). "
                "Attempting multimodal OCR fallback via Gemini Vision / OCR engine..."
            )
            try:
                ocr_candidate = extract_text_with_ocr_fallback(pdf_path)
                ocr_valid, ocr_msg = validate_resume_text(ocr_candidate)
                if ocr_valid:
                    logger.info(
                        f"Multimodal OCR fallback succeeded ({len(ocr_candidate)} characters extracted)."
                    )
                    cleaned_text = ocr_candidate
                    is_valid = True
                else:
                    logger.warning(f"OCR fallback yielded insufficient text: {ocr_msg}")
            except Exception as ocr_err:
                logger.warning(f"Multimodal OCR fallback encountered error: {ocr_err}")

        if not is_valid:
            logger.warning(f"Extracted PDF text validation failed: {validation_msg}")
            raise ValueError(
                f"Could not extract sufficient text from PDF: {validation_msg} "
                "Ensure your document is a readable text-based or scanned PDF resume."
            )

        # Enforce maximum character boundary to avoid excessive token consumption
        if len(cleaned_text) > MAX_RESUME_TEXT_CHARS:
            logger.warning(
                f"PDF text length ({len(cleaned_text)} chars) exceeded limit. Truncating to {MAX_RESUME_TEXT_CHARS} chars."
            )
            cleaned_text = cleaned_text[:MAX_RESUME_TEXT_CHARS]

        logger.info(f"PDF text extraction completed successfully ({len(cleaned_text)} characters).")
        return cleaned_text

    except FileNotFoundError:
        logger.error(f"File not found: {pdf_path}")
        raise FileNotFoundError(f"Resume file was not found at path: {pdf_path}")
    except ValueError as ve:
        logger.error(f"Validation error reading PDF: {str(ve)}")
        raise ve
    except PdfReadError as pre:
        logger.error(f"PyPDF2 ReadError encountered: {str(pre)}")
        raise ValueError(f"Could not read PDF file (corrupted or malformed): {str(pre)}")
    except Exception as e:
        logger.error(f"Unexpected error reading PDF: {str(e)}")
        raise RuntimeError(f"Failed to parse PDF file: {str(e)}")


def extract_text_with_ocr_fallback(pdf_path: str) -> str:
    """
    Multimodal OCR fallback mechanism using Gemini Vision or pytesseract.
    Activated when embedded PDF text density is below threshold (e.g. scanned, image-based,
    or graphical Canva resumes).
    """
    logger.info(f"Triggering multimodal OCR fallback for PDF: {pdf_path}")

    # 1. Attempt Gemini Vision multimodal extraction
    try:
        from utils.gemini import get_gemini_client
        import config
        from google.genai import types

        client = get_gemini_client()
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        logger.info(f"Submitting {len(pdf_bytes)} bytes to Gemini Vision for OCR transcription.")
        response = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                (
                    "You are an expert optical character recognition (OCR) and resume parsing engine. "
                    "Extract and transcribe all readable text from this scanned or graphical resume document. "
                    "Preserve all headings, sections (Education, Skills, Experience, Projects, Certifications), "
                    "bullet points, and dates verbatim. Output clean plain text without any introductory commentary."
                ),
            ],
        )
        ocr_result = getattr(response, "text", "") or ""
        if ocr_result and ocr_result.strip():
            logger.info(f"Gemini Vision OCR extraction succeeded ({len(ocr_result.strip())} chars).")
            return ocr_result.strip()
    except Exception as gemini_ocr_err:
        logger.warning(f"Gemini Vision OCR attempt failed: {gemini_ocr_err}")

    # 2. Attempt pytesseract if installed and available
    try:
        import pytesseract
        from pdf2image import convert_from_path

        logger.info(f"Attempting pytesseract OCR extraction for {pdf_path}")
        images = convert_from_path(pdf_path, first_page=1, last_page=MAX_PDF_PAGES)
        tesseract_lines = []
        for img in images:
            page_str = pytesseract.image_to_string(img)
            if page_str.strip():
                tesseract_lines.append(page_str.strip())

        combined_tess = "\n".join(tesseract_lines).strip()
        if combined_tess:
            logger.info(f"pytesseract OCR extraction succeeded ({len(combined_tess)} chars).")
            return combined_tess
    except Exception as tess_err:
        logger.debug(f"pytesseract OCR attempt skipped or failed: {tess_err}")

    return ""


def extract_text_from_docx(docx_source: Union[str, io.BytesIO]) -> str:
    """
    Extracts structured text content from a Microsoft Word (.docx) document.

    Iterates through body paragraphs, tables (rows and cells), and section headers/footers
    where applicable to assemble a complete textual resume profile.

    Parameters:
        docx_source: File path (str) or binary stream (io.BytesIO) pointing to the .docx file.

    Returns:
        Cleaned, extracted text string from the DOCX document.

    Raises:
        ImportError: If python-docx library is not installed in the environment.
        FileNotFoundError: If the specified file path does not exist on disk.
        ValueError: If file is malformed, password-locked, empty, or fails validation checks.
        RuntimeError: For other unexpected document processing errors.
    """
    if docx is None:
        logger.error("python-docx package is not available for DOCX parsing.")
        raise ImportError(
            "DOCX parsing support requires the 'python-docx' library. Please install python-docx."
        )

    logger.info(f"Initiating text extraction from DOCX source: {docx_source}")
    if isinstance(docx_source, str) and not os.path.exists(docx_source):
        logger.error(f"DOCX file not found: {docx_source}")
        raise FileNotFoundError(f"Resume file was not found at path: {docx_source}")

    try:
        doc = docx.Document(docx_source)
    except FileNotFoundError:
        logger.error(f"DOCX file not found: {docx_source}")
        raise FileNotFoundError(f"Resume file was not found at path: {docx_source}")
    except PackageNotFoundError as pnfe:
        logger.error(f"DOCX package corrupted or not a valid zip archive: {pnfe}")
        raise ValueError(
            "The uploaded file is not a valid or readable Word document (.docx). "
            "Please ensure it is not corrupt or saved in legacy binary .doc format."
        )
    except Exception as exc:
        logger.error(f"Unexpected error opening DOCX document: {exc}")
        raise ValueError(f"Unable to read Word document (.docx): {str(exc)}")

    extracted_lines: List[str] = []

    try:
        # Extract paragraph text
        paragraph_count = len(doc.paragraphs)
        if paragraph_count > MAX_DOCX_PARAGRAPHS:
            logger.warning(
                f"DOCX contains {paragraph_count} paragraphs, which is unusually long for a resume."
            )

        for paragraph in doc.paragraphs:
            text = paragraph.text.strip()
            if text:
                extracted_lines.append(text)

        # Extract text from tables (common in resume templates for education/skills)
        for table in doc.tables:
            for row in table.rows:
                row_cells_text = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_cells_text:
                    # Deduplicate adjacent merged cells having identical text
                    deduped_cells = []
                    for c_text in row_cells_text:
                        if not deduped_cells or deduped_cells[-1] != c_text:
                            deduped_cells.append(c_text)
                    if deduped_cells:
                        extracted_lines.append(" | ".join(deduped_cells))

        # Extract header and footer text if present
        for section in doc.sections:
            try:
                for header_para in section.header.paragraphs:
                    h_text = header_para.text.strip()
                    if h_text and h_text not in extracted_lines:
                        extracted_lines.insert(0, h_text)
            except Exception as hdr_err:
                logger.debug(f"Could not read section header: {hdr_err}")

        combined_text = "\n".join(extracted_lines).strip()

        # Validate extracted text content
        is_valid, validation_msg = validate_resume_text(combined_text)
        if not is_valid:
            logger.warning(f"Extracted DOCX text validation failed: {validation_msg}")
            raise ValueError(
                f"Could not extract sufficient text from DOCX document: {validation_msg} "
                "Ensure your Word document contains actual text rather than embedded images or empty sections."
            )

        # Enforce maximum character boundary
        if len(combined_text) > MAX_RESUME_TEXT_CHARS:
            logger.warning(
                f"DOCX text length ({len(combined_text)} chars) exceeded limit. Truncating to {MAX_RESUME_TEXT_CHARS} chars."
            )
            combined_text = combined_text[:MAX_RESUME_TEXT_CHARS]

        logger.info(
            f"DOCX text extraction completed successfully ({len(combined_text)} characters, "
            f"{len(extracted_lines)} content blocks)."
        )
        return combined_text

    except ValueError as ve:
        raise ve
    except Exception as e:
        logger.error(f"Error parsing DOCX content: {str(e)}")
        raise RuntimeError(f"Failed to parse Word document: {str(e)}")


def standardize_resume_sections(text: str) -> Dict[str, str]:
    """
    Parses unstructured or semi-structured resume text into standardized canonical sections:
    - Education
    - Technical Skills
    - Work Experience / Internships
    - Projects
    - Certifications & Achievements
    - Summary & Profile

    Returns a dictionary of {section_name: section_content}.
    """
    if not text or not text.strip():
        return {}

    raw_text = text.strip()

    section_patterns = [
        ("summary", re.compile(r"(?:^|\n)\s*(?:[#*_\-~=]+\s*)?(?:professional summary|executive summary|career objective|about me|summary|objective|profile)(?:\s*[:\n]|\s*$)", re.IGNORECASE)),
        ("education", re.compile(r"(?:^|\n)\s*(?:[#*_\-~=]+\s*)?(?:education|academic background|academics|qualifications|academic credentials|degrees?)(?:\s*[:\n]|\s*$)", re.IGNORECASE)),
        ("skills", re.compile(r"(?:^|\n)\s*(?:[#*_\-~=]+\s*)?(?:technical skills|skills & tools|core competencies|skills|technologies|tech stack|key skills|competencies)(?:\s*[:\n]|\s*$)", re.IGNORECASE)),
        ("experience", re.compile(r"(?:^|\n)\s*(?:[#*_\-~=]+\s*)?(?:work experience|professional experience|experience|employment history|internships|work history|career history)(?:\s*[:\n]|\s*$)", re.IGNORECASE)),
        ("projects", re.compile(r"(?:^|\n)\s*(?:[#*_\-~=]+\s*)?(?:academic projects|key projects|personal projects|portfolio projects|projects)(?:\s*[:\n]|\s*$)", re.IGNORECASE)),
        ("certifications", re.compile(r"(?:^|\n)\s*(?:[#*_\-~=]+\s*)?(?:certifications|certificates|licenses|achievements|awards|honors|publications|extracurricular activities|activities)(?:\s*[:\n]|\s*$)", re.IGNORECASE)),
    ]

    found_matches = []
    for sec_key, pattern in section_patterns:
        for match in pattern.finditer(raw_text):
            found_matches.append({
                "key": sec_key,
                "start": match.start(),
                "end": match.end(),
                "matched_text": match.group().strip()
            })

    found_matches.sort(key=lambda m: m["start"])

    filtered_matches = []
    last_end = 0
    for m in found_matches:
        if m["start"] >= last_end:
            filtered_matches.append(m)
            last_end = m["end"]

    sections: Dict[str, str] = {
        "summary": "",
        "education": "",
        "skills": "",
        "experience": "",
        "projects": "",
        "certifications": "",
    }

    if not filtered_matches:
        sections["summary"] = raw_text
        return {k: v for k, v in sections.items() if v}

    first_start = filtered_matches[0]["start"]
    if first_start > 0:
        intro_content = raw_text[:first_start].strip()
        if intro_content:
            sections["summary"] = intro_content

    for idx, match_info in enumerate(filtered_matches):
        sec_key = match_info["key"]
        content_start = match_info["end"]
        content_end = filtered_matches[idx + 1]["start"] if idx + 1 < len(filtered_matches) else len(raw_text)
        chunk = raw_text[content_start:content_end].strip()

        if chunk:
            if sections.get(sec_key):
                sections[sec_key] += "\n" + chunk
            else:
                sections[sec_key] = chunk

    return {k: v.strip() for k, v in sections.items() if v.strip()}


def format_standardized_resume(sections: Dict[str, str]) -> str:
    """
    Assembles a standardized, cleanly formatted Markdown representation of the resume
    from structured section blocks for downstream agent consumption.
    """
    if not sections:
        return ""

    label_map = [
        ("summary", "Contact & Professional Summary"),
        ("education", "Education & Qualifications"),
        ("skills", "Technical Skills & Competencies"),
        ("experience", "Work Experience & Internships"),
        ("projects", "Key Projects & Portfolio"),
        ("certifications", "Certifications, Awards & Achievements"),
    ]

    parts: List[str] = []
    for key, title in label_map:
        content = sections.get(key, "").strip()
        if content:
            parts.append(f"### {title}\n{content}")

    for key, content in sections.items():
        if key not in dict(label_map) and content.strip():
            clean_title = key.replace("_", " ").title()
            parts.append(f"### {clean_title}\n{content.strip()}")

    return "\n\n".join(parts).strip()


def extract_text_from_file(file_path: str, standardize: bool = True) -> str:
    """
    Unified resume text extractor that routes automatically based on file extension (.pdf or .docx).
    When standardize=True, structures sections into canonical blocks for clean downstream agent consumption.

    Parameters:
        file_path: Filesystem path to the resume file.
        standardize: Whether to standardize and format canonical sections (default True).

    Returns:
        Validated text extracted from the document.

    Raises:
        ValueError: If file extension is unsupported or content fails validation.
        FileNotFoundError: If the file does not exist.
        RuntimeError: For parsing failures.
    """
    lower_path = file_path.lower()
    if lower_path.endswith(".pdf"):
        raw_text = extract_text_from_pdf(file_path)
    elif lower_path.endswith(".docx"):
        raw_text = extract_text_from_docx(file_path)
    else:
        raise ValueError(
            "Unsupported file format. Only PDF (.pdf) and Word documents (.docx) are supported."
        )

    if standardize:
        sections = standardize_resume_sections(raw_text)
        standardized_text = format_standardized_resume(sections)
        if standardized_text:
            return standardized_text
    return raw_text
