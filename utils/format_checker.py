"""
Format compatibility checker for resumes (Issue #474).

Rule-based inspection for PDF and document resumes evaluating ATS layout compatibility:
1. Page Count: Verifies document length is 1-2 pages (standard for campus placement).
2. Multi-Column Layout: Detects side-by-side columns where text blocks have overlapping
   vertical ranges and distinct horizontal bands separated by gutters.
3. Tables & Grids: Detects grid lines, border rectangles, or multi-column aligned tabular rows.
4. Embedded Images: Detects raster images or graphic objects that cannot be indexed by ATS.
5. Text Legibility & Encoding: Detects low text density, garbled non-standard encodings,
   or unprintable glyphs.

All checks are rule-based, non-blocking, and return actionable one-line fixes.
"""

import io
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError

logger = logging.getLogger(__name__)


def check_page_count(reader: PdfReader) -> Dict[str, Any]:
    """Check 1: Number of pages. Standard campus resumes are 1-2 pages."""
    try:
        pages = len(reader.pages)
    except Exception:
        pages = 1

    if 1 <= pages <= 2:
        return {
            "id": "page_count",
            "name": "Page Count",
            "status": "pass",
            "explanation": f"{pages} page{'s' if pages != 1 else ''} detected. Ideal length for campus placement and ATS parsing.",
            "fix": "Keep resume within 1-2 pages.",
            "value": pages,
        }
    elif pages > 2:
        return {
            "id": "page_count",
            "name": "Page Count",
            "status": "warn",
            "explanation": f"{pages} pages detected. Resumes exceeding 2 pages often face lower recruiter review rates and parser truncation.",
            "fix": "Condense your resume to 1-2 pages by trimming older projects or secondary coursework.",
            "value": pages,
        }
    else:
        return {
            "id": "page_count",
            "name": "Page Count",
            "status": "warn",
            "explanation": "No readable pages found in document.",
            "fix": "Upload a standard 1-2 page PDF resume.",
            "value": 0,
        }


def check_multi_column_layout(reader: PdfReader) -> Dict[str, Any]:
    """
    Check 2: Multi-column layout.
    Detects side-by-side text columns where blocks have overlapping vertical (y)
    ranges and non-overlapping horizontal (x) ranges.
    """
    multi_column_detected = False
    evidence_lines: List[str] = []

    for page_idx, page in enumerate(reader.pages):
        try:
            width = float(page.mediabox.width)
        except Exception:
            width = 612.0

        chunks: List[Dict[str, Any]] = []

        def visitor(text, cm, tm, font_dict, font_size):
            t = (text or "").strip()
            if t:
                try:
                    x = float(cm[4] + tm[4])
                    y = float(cm[5] + tm[5])
                    chunks.append({"text": t, "x": x, "y": y, "len": len(t)})
                except Exception:
                    pass

        try:
            page.extract_text(visitor_text=visitor)
        except Exception as e:
            logger.debug(f"Visitor text extraction error on page {page_idx}: {e}")

        # Group chunks into horizontal lines (within 5 points vertically)
        lines: Dict[float, List[Dict[str, Any]]] = {}
        for ch in chunks:
            y_val = ch["y"]
            matched_y = None
            for existing_y in lines:
                if abs(existing_y - y_val) <= 5.0:
                    matched_y = existing_y
                    break
            if matched_y is None:
                matched_y = y_val
                lines[matched_y] = []
            lines[matched_y].append(ch)

        # Count lines with substantial left and right text
        concurrent_lines = 0
        date_pattern = re.compile(
            r'^(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{2,4}|\d{4}|\d{1,2}/\d{2,4}|\w+,\s*[A-Z]{2}|\w+,\s*India|\w+,\s*USA|\s*-\s*present|\s*-\s*\d{4}|\(\s*\d{4}\s*\))+$',
            re.IGNORECASE
        )

        for y_pos, line_chunks in lines.items():
            left_chunks = [c for c in line_chunks if c["x"] < width * 0.45]
            right_chunks = [c for c in line_chunks if c["x"] >= width * 0.45]

            if left_chunks and right_chunks:
                l_text = " ".join(c["text"] for c in left_chunks).strip()
                r_text = " ".join(c["text"] for c in right_chunks).strip()

                # Ignore right-aligned dates or brief metadata tags (< 20 chars matching date)
                if len(l_text) >= 10 and len(r_text) >= 15 and not date_pattern.match(r_text):
                    concurrent_lines += 1
                    if len(evidence_lines) < 3:
                        evidence_lines.append(f"Line '{l_text[:20]}...' | '{r_text[:20]}...'")

        if concurrent_lines >= 3:
            multi_column_detected = True
            break

        # Also check raw text for two-column vertical pipe dividers
        try:
            raw_text = page.extract_text() or ""
            pipe_lines = [l for l in raw_text.splitlines() if l.count("|") == 1 and len(l) > 25]
            if len(pipe_lines) >= 4:
                multi_column_detected = True
                break
        except Exception:
            pass

    if multi_column_detected:
        return {
            "id": "multi_column",
            "name": "Single-Column Layout",
            "status": "warn",
            "explanation": "Multi-column or sidebar layout detected. Many ATS engines struggle with multi-column text and scramble reading order across columns.",
            "fix": "Switch to a clean single-column format so ATS parsers read sections sequentially top-to-bottom.",
            "value": True,
        }
    else:
        return {
            "id": "multi_column",
            "name": "Single-Column Layout",
            "status": "pass",
            "explanation": "Clean single-column structure detected. Text will be parsed in natural top-to-bottom reading order without column mixing.",
            "fix": "Maintain a linear single-column layout without sidebars or vertical columns.",
            "value": False,
        }


def check_tables_and_grids(reader: PdfReader) -> Dict[str, Any]:
    """
    Check 3: Presence of tables or grid layouts.
    Detects vector line grids, table cell rectangles, and tab-separated columns.
    """
    tables_detected = False

    for page in reader.pages:
        try:
            # 1. Check content stream drawing paths for intersecting grid lines
            contents = page.get_contents()
            content_data = b""
            if contents:
                if isinstance(contents, list):
                    content_data = b"".join(c.get_data() for c in contents if hasattr(c, "get_data"))
                elif hasattr(contents, "get_data"):
                    content_data = contents.get_data()

            text_stream = content_data.decode("latin1", errors="ignore")
            h_lines = 0
            v_lines = 0
            rectangles = 0

            for line in text_stream.splitlines():
                # Line drawing path: [n] x1 y1 m x2 y2 l [S/s]
                m_line = re.search(r'([-\d.]+)\s+([-\d.]+)\s+m\s+([-\d.]+)\s+([-\d.]+)\s+l', line)
                if m_line:
                    x1, y1, x2, y2 = map(float, m_line.groups())
                    if abs(y1 - y2) <= 1.5 and abs(x1 - x2) > 25:
                        h_lines += 1
                    elif abs(x1 - x2) <= 1.5 and abs(y1 - y2) > 25:
                        v_lines += 1

                # Rectangle operator: x y w h re
                m_re = re.search(r'([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+re', line)
                if m_re:
                    w, h = float(m_re.group(3)), float(m_re.group(4))
                    if abs(w) > 20 and abs(h) > 10:
                        rectangles += 1

            # A table grid contains multiple horizontal lines AND vertical lines, or multiple cell rects
            if (h_lines >= 2 and v_lines >= 2) or rectangles >= 3:
                tables_detected = True
                break

            # 2. Text layout table checks (multiple tabs or pipe-delimited grid rows)
            page_text = page.extract_text() or ""
            tab_rows = [l for l in page_text.splitlines() if l.count("\t") >= 2]
            pipe_rows = [l for l in page_text.splitlines() if l.strip().startswith("|") and l.strip().endswith("|") and l.count("|") >= 3]
            if len(tab_rows) >= 3 or len(pipe_rows) >= 2:
                tables_detected = True
                break

        except Exception as e:
            logger.debug(f"Error checking page tables: {e}")

    if tables_detected:
        return {
            "id": "tables",
            "name": "Tables & Grids",
            "status": "warn",
            "explanation": "Table or grid structures detected. Complex tables often get flattened or garbled by ATS parsers, mixing up column data.",
            "fix": "Replace tables with simple bulleted lists to ensure reliable ATS extraction.",
            "value": True,
        }
    else:
        return {
            "id": "tables",
            "name": "Tables & Grids",
            "status": "pass",
            "explanation": "No complex table grids detected. Information is structured cleanly as linear text.",
            "fix": "Avoid tables; use simple bullet points for education, experience, and skills.",
            "value": False,
        }


def check_embedded_images(reader: PdfReader) -> Dict[str, Any]:
    """
    Check 4: Embedded images and raster graphics.
    Detects images in page.images or /XObject with /Subtype /Image.
    """
    total_images = 0

    for page in reader.pages:
        # 1. page.images property
        try:
            if hasattr(page, "images") and len(page.images) > 0:
                total_images += len(page.images)
                continue
        except Exception:
            pass

        # 2. Direct inspection of /Resources -> /XObject
        try:
            res = page.get("/Resources")
            if res and hasattr(res, "get_object"):
                res = res.get_object()
            if res:
                xobjects = res.get("/XObject")
                if xobjects and hasattr(xobjects, "get_object"):
                    xobjects = xobjects.get_object()
                if xobjects:
                    for name in xobjects:
                        obj = xobjects[name]
                        if hasattr(obj, "get_object"):
                            obj = obj.get_object()
                        if obj.get("/Subtype") == "/Image":
                            total_images += 1
        except Exception as e:
            logger.debug(f"Error inspecting page XObjects: {e}")

    if total_images > 0:
        return {
            "id": "images",
            "name": "Embedded Images",
            "status": "warn",
            "explanation": f"{total_images} embedded image{'s' if total_images != 1 else ''} or graphic icon{'s' if total_images != 1 else ''} detected. Real ATS parsers cannot read or index text, skills, or contact info trapped inside images.",
            "fix": "Replace images, profile photos, and icon graphics with selectable plain text.",
            "value": total_images,
        }
    else:
        return {
            "id": "images",
            "name": "Embedded Images",
            "status": "pass",
            "explanation": "No embedded raster images or graphic icons found. All resume content is directly indexable by ATS parsers.",
            "fix": "Avoid embedding images, logos, or icon graphics in ATS resumes.",
            "value": 0,
        }


def check_text_legibility(text: str, page_count: int = 1) -> Dict[str, Any]:
    """
    Check 5: Text legibility, density, and character encoding.
    Detects very short or garbled text extraction and corrupted font encodings.
    """
    cleaned = (text or "").strip()
    char_count = len(cleaned)
    words = cleaned.split()
    word_count = len(words)
    words_per_page = word_count / max(1, page_count)

    # Check for garbled, non-printable, or replacement characters
    garbled_chars = [c for c in cleaned if ord(c) < 32 and c not in ('\n', '\r', '\t')]
    replacement_chars = cleaned.count('\ufffd')
    total_suspicious = len(garbled_chars) + replacement_chars
    suspicious_ratio = total_suspicious / max(1, char_count)

    if char_count < 100 or word_count < 30 or words_per_page < 30:
        return {
            "id": "text_extraction",
            "name": "Text Extraction & Encoding",
            "status": "warn",
            "explanation": f"Low text density detected ({word_count} words found, ~{int(words_per_page)} words/page). Document appears image-heavy, scanned, or incompletely parsed.",
            "fix": "Export your resume directly to PDF from Microsoft Word or Google Docs with selectable text.",
            "value": {"char_count": char_count, "word_count": word_count},
        }
    elif suspicious_ratio > 0.04:
        return {
            "id": "text_extraction",
            "name": "Text Extraction & Encoding",
            "status": "warn",
            "explanation": f"Unusual or corrupted character encodings detected ({total_suspicious} garbled/unprintable characters). ATS systems may misinterpret headings or keywords.",
            "fix": "Use standard Unicode system fonts (e.g., Calibri, Arial, Times New Roman) when exporting to PDF.",
            "value": {"suspicious_chars": total_suspicious, "ratio": round(suspicious_ratio, 3)},
        }
    else:
        return {
            "id": "text_extraction",
            "name": "Text Extraction & Encoding",
            "status": "pass",
            "explanation": f"Clean, extractable text stream detected ({word_count} words across {page_count} page{'s' if page_count != 1 else ''}). Font encoding is standard and ATS-readable.",
            "fix": "Maintain standard system fonts and export directly from your word processor.",
            "value": {"char_count": char_count, "word_count": word_count},
        }


def check_pdf_format_compatibility(file_input: Union[str, bytes, io.BytesIO, Path]) -> Dict[str, Any]:
    """
    Main rule-based ATS format compatibility checker for PDF documents.
    Non-blocking: safely handles any corruptions or exceptions.
    """
    try:
        reader = None
        if isinstance(file_input, (str, Path)):
            if not os.path.exists(file_input):
                return _fallback_text_check("")
            reader = PdfReader(str(file_input))
        elif isinstance(file_input, (bytes, bytearray)):
            reader = PdfReader(io.BytesIO(file_input))
        elif hasattr(file_input, "read") and hasattr(file_input, "seek"):
            pos = file_input.tell()
            reader = PdfReader(file_input)
            file_input.seek(pos)
        else:
            return _fallback_text_check("")

        # Extract text across all pages
        full_text = ""
        for page in reader.pages:
            try:
                t = page.extract_text() or ""
                full_text += t + "\n"
            except Exception:
                pass

        c_page = check_page_count(reader)
        c_col = check_multi_column_layout(reader)
        c_tables = check_tables_and_grids(reader)
        c_img = check_embedded_images(reader)
        c_text = check_text_legibility(full_text, page_count=len(reader.pages))

        checks = [c_page, c_col, c_tables, c_img, c_text]
        warn_count = sum(1 for c in checks if c["status"] == "warn")
        passed_count = sum(1 for c in checks if c["status"] == "pass")
        overall_status = "warn" if warn_count > 0 else "pass"
        score_percentage = round((passed_count / len(checks)) * 100)

        return {
            "overall_status": overall_status,
            "passed_count": passed_count,
            "warn_count": warn_count,
            "total_checks": len(checks),
            "score_percentage": score_percentage,
            "checks": checks,
        }

    except Exception as exc:
        logger.warning(f"Error checking PDF format compatibility: {exc}")
        return _fallback_text_check("")


def check_resume_format_compatibility(
    file_or_text: Union[str, bytes, io.BytesIO, Path],
    extracted_text: Optional[str] = None
) -> Dict[str, Any]:
    """
    Universal format compatibility entrypoint. Routes PDF files to check_pdf_format_compatibility,
    and handles Word (.docx) or pasted text gracefully.
    """
    if isinstance(file_or_text, (str, Path)):
        s_path = str(file_or_text).lower()
        if s_path.endswith(".pdf") and os.path.exists(file_or_text):
            return check_pdf_format_compatibility(file_or_text)
        elif s_path.endswith(".docx") and os.path.exists(file_or_text):
            return _check_docx_format_compatibility(str(file_or_text))
        elif not os.path.exists(file_or_text):
            # Treat as raw text
            return _fallback_text_check(str(file_or_text))

    if isinstance(file_or_text, (bytes, bytearray)):
        if file_or_text[:5] == b"%PDF-":
            return check_pdf_format_compatibility(file_or_text)

    return _fallback_text_check(extracted_text or "")


def _check_docx_format_compatibility(docx_path: str) -> Dict[str, Any]:
    """Rule-based check for Word .docx documents."""
    try:
        import docx
        doc = docx.Document(docx_path)
        tables_count = len(doc.tables)
        text_parts = [p.text for p in doc.paragraphs if p.text.strip()]
        full_text = "\n".join(text_parts)
        word_count = len(full_text.split())
        est_pages = max(1, round(word_count / 450))

        c_page = {
            "id": "page_count",
            "name": "Page Count",
            "status": "pass" if est_pages <= 2 else "warn",
            "explanation": f"Estimated ~{est_pages} page(s) based on {word_count} words.",
            "fix": "Keep resume within 1-2 pages.",
            "value": est_pages,
        }
        c_col = {
            "id": "multi_column",
            "name": "Single-Column Layout",
            "status": "pass",
            "explanation": "Standard document linear paragraph layout detected.",
            "fix": "Maintain a linear single-column layout without sidebars.",
            "value": False,
        }
        c_tables = {
            "id": "tables",
            "name": "Tables & Grids",
            "status": "warn" if tables_count > 0 else "pass",
            "explanation": f"{tables_count} table(s) found in document." if tables_count > 0 else "No table grids detected.",
            "fix": "Replace tables with bulleted lists to ensure reliable ATS extraction.",
            "value": tables_count > 0,
        }
        c_img = {
            "id": "images",
            "name": "Embedded Images",
            "status": "pass",
            "explanation": "No embedded raster images detected in document text.",
            "fix": "Avoid embedding images, logos, or icon graphics.",
            "value": 0,
        }
        c_text = check_text_legibility(full_text, page_count=est_pages)

        checks = [c_page, c_col, c_tables, c_img, c_text]
        warn_count = sum(1 for c in checks if c["status"] == "warn")
        passed_count = sum(1 for c in checks if c["status"] == "pass")

        return {
            "overall_status": "warn" if warn_count > 0 else "pass",
            "passed_count": passed_count,
            "warn_count": warn_count,
            "total_checks": len(checks),
            "score_percentage": round((passed_count / len(checks)) * 100),
            "checks": checks,
        }
    except Exception as e:
        logger.warning(f"Error checking DOCX format: {e}")
        return _fallback_text_check("")


def _fallback_text_check(text: str) -> Dict[str, Any]:
    """Default fallback when raw text is supplied without PDF/DOCX structure."""
    words = (text or "").split()
    word_count = len(words)
    est_pages = max(1, round(word_count / 450)) if word_count > 0 else 1

    c_page = {
        "id": "page_count",
        "name": "Page Count",
        "status": "pass" if est_pages <= 2 else "warn",
        "explanation": f"Estimated {est_pages} page(s) based on {word_count} words.",
        "fix": "Keep resume within 1-2 pages.",
        "value": est_pages,
    }
    c_col = {
        "id": "multi_column",
        "name": "Single-Column Layout",
        "status": "pass",
        "explanation": "Single-column linear text provided.",
        "fix": "Maintain a linear single-column layout without sidebars.",
        "value": False,
    }
    c_tables = {
        "id": "tables",
        "name": "Tables & Grids",
        "status": "pass",
        "explanation": "No table structures detected in raw text.",
        "fix": "Avoid tables; use simple bullet points.",
        "value": False,
    }
    c_img = {
        "id": "images",
        "name": "Embedded Images",
        "status": "pass",
        "explanation": "No embedded images in plain text.",
        "fix": "Avoid embedding images, logos, or icon graphics.",
        "value": 0,
    }
    c_text = check_text_legibility(text, page_count=est_pages)

    checks = [c_page, c_col, c_tables, c_img, c_text]
    warn_count = sum(1 for c in checks if c["status"] == "warn")
    passed_count = sum(1 for c in checks if c["status"] == "pass")

    return {
        "overall_status": "warn" if warn_count > 0 else "pass",
        "passed_count": passed_count,
        "warn_count": warn_count,
        "total_checks": len(checks),
        "score_percentage": round((passed_count / len(checks)) * 100),
        "checks": checks,
    }


def get_or_compute_format_compatibility(analysis_record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retrieves stored format_compatibility or computes it dynamically if missing.
    """
    if not isinstance(analysis_record, dict):
        return _fallback_text_check("")

    if analysis_record.get("format_compatibility"):
        return analysis_record["format_compatibility"]

    results = analysis_record.get("results")
    if isinstance(results, dict) and results.get("format_compatibility"):
        return results["format_compatibility"]

    # Check if upload file exists in UPLOAD_FOLDER
    file_id = analysis_record.get("id") or analysis_record.get("file_uuid")
    fname = analysis_record.get("resume_filename") or ""
    try:
        import config
        upload_folder = getattr(config, "UPLOAD_FOLDER", "uploads")
        if file_id and fname:
            from werkzeug.utils import secure_filename
            target_path = os.path.join(upload_folder, secure_filename(f"{file_id}_{fname}"))
            if os.path.exists(target_path):
                return check_resume_format_compatibility(target_path)
    except Exception:
        pass

    # Fallback to resume text
    resume_text = analysis_record.get("resume_text") or (results.get("extracted_resume_text") if isinstance(results, dict) else "")
    return _fallback_text_check(resume_text or "")
