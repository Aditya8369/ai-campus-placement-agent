"""
Resume Page-Level PDF Issue Detector & Layout Diagnostics (#597).
==================================================================
Identifies parsing, formatting, and layout problems on a page-by-page basis
for PDF resumes (tables, images, multi-column sidebars, low text legibility,
and unusual reading orders) to help students avoid silent ATS filtering.
"""

import io
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from PyPDF2 import PdfReader

logger = logging.getLogger(__name__)


def detect_page_tables(page, page_text: str) -> Dict[str, Any]:
    """
    Detects table grids or tab/pipe structured columns on a specific page.
    """
    has_tables = False
    table_type = None

    try:
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
            m_line = re.search(r'([-\d.]+)\s+([-\d.]+)\s+m\s+([-\d.]+)\s+([-\d.]+)\s+l', line)
            if m_line:
                x1, y1, x2, y2 = map(float, m_line.groups())
                if abs(y1 - y2) <= 1.5 and abs(x1 - x2) > 25:
                    h_lines += 1
                elif abs(x1 - x2) <= 1.5 and abs(y1 - y2) > 25:
                    v_lines += 1

            m_re = re.search(r'([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+re', line)
            if m_re:
                w, h = float(m_re.group(3)), float(m_re.group(4))
                if abs(w) > 20 and abs(h) > 10:
                    rectangles += 1

        if (h_lines >= 2 and v_lines >= 2) or rectangles >= 3:
            has_tables = True
            table_type = "Vector Grid / Cell Borders"
    except Exception as exc:
        logger.debug("Error checking vector paths for page table: %s", exc)

    if not has_tables:
        tab_rows = [l for l in page_text.splitlines() if l.count("\t") >= 2]
        pipe_rows = [l for l in page_text.splitlines() if l.strip().startswith("|") and l.strip().endswith("|") and l.count("|") >= 3]
        if len(tab_rows) >= 3:
            has_tables = True
            table_type = "Tab-Delimited Matrix"
        elif len(pipe_rows) >= 2:
            has_tables = True
            table_type = "Pipe-Separated Grid"

    return {
        "detected": has_tables,
        "detail": table_type if has_tables else None
    }


def detect_page_images(page) -> Dict[str, Any]:
    """
    Detects raster images, profile pictures, or graphic skill-meters on a specific page.
    """
    image_count = 0
    try:
        if hasattr(page, "images") and len(page.images) > 0:
            image_count = len(page.images)
    except Exception:
        pass

    if image_count == 0:
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
                            image_count += 1
        except Exception as exc:
            logger.debug("Error inspecting page image XObjects: %s", exc)

    return {
        "detected": image_count > 0,
        "count": image_count
    }


def detect_page_columns(page) -> Dict[str, Any]:
    """
    Detects two-column or multi-column layout on a single page using text coordinates.
    """
    multi_col = False
    evidence = []
    chunks: List[Dict[str, Any]] = []

    def visitor(text, cm, tm, font_dict, font_size):
        if text and text.strip():
            chunks.append({
                "text": text,
                "x": tm[4],
                "y": tm[5],
                "w": len(text) * (font_size * 0.5 if font_size else 6)
            })

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:
        pass

    if chunks:
        width = float(page.mediabox.width) if hasattr(page, "mediabox") and page.mediabox else 612.0
        lines_by_y: Dict[int, List[Dict[str, Any]]] = {}
        for c in chunks:
            y_bucket = int(round(c["y"] / 10.0)) * 10
            lines_by_y.setdefault(y_bucket, []).append(c)

        concurrent_lines = 0
        date_pattern = re.compile(
            r"^(?:\d{4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}|present|\d{2}/\d{4})",
            re.IGNORECASE
        )

        for _, line_chunks in lines_by_y.items():
            left = [c for c in line_chunks if c["x"] + c.get("w", 0) <= width * 0.55]
            right = [c for c in line_chunks if c["x"] >= width * 0.45]
            if left and right:
                l_text = " ".join(c["text"] for c in left).strip()
                r_text = " ".join(c["text"] for c in right).strip()
                if len(l_text) >= 10 and len(r_text) >= 15 and not date_pattern.match(r_text):
                    concurrent_lines += 1
                    if len(evidence) < 2:
                        evidence.append(f"{l_text[:20]}... | {r_text[:20]}...")

        if concurrent_lines >= 3:
            multi_col = True

    if not multi_col:
        try:
            page_text = page.extract_text() or ""
            pipe_lines = [l for l in page_text.splitlines() if l.count("|") == 1 and len(l) > 25]
            if len(pipe_lines) >= 4:
                multi_col = True
                evidence.append("Vertical pipe divider separating columns")
        except Exception:
            pass

    return {
        "detected": multi_col,
        "evidence": evidence
    }


def analyze_pdf_page_issues(file_input: Union[str, bytes, io.BytesIO, Path]) -> Dict[str, Any]:
    """
    Performs comprehensive page-by-page PDF issue detection for ATS compliance (#597).

    Returns:
        Dict with overall stats, list of pages with flags, and actionable guidance.
    """
    try:
        reader = None
        if isinstance(file_input, (str, Path)):
            if not os.path.exists(file_input):
                return _empty_page_report("File not found on disk.")
            reader = PdfReader(str(file_input))
        elif isinstance(file_input, (bytes, bytearray)):
            reader = PdfReader(io.BytesIO(file_input))
        elif hasattr(file_input, "read") and hasattr(file_input, "seek"):
            pos = file_input.tell()
            reader = PdfReader(file_input)
            file_input.seek(pos)
        else:
            return _empty_page_report("Unsupported input type.")

        total_pages = len(reader.pages)
        if total_pages == 0:
            return _empty_page_report("PDF has 0 pages.")

        pages_report = []
        problem_page_numbers = []
        all_issues_summary = []

        for idx, page in enumerate(reader.pages):
            page_num = idx + 1
            page_issues = []

            # 1. Text extraction on this page
            try:
                p_text = page.extract_text() or ""
            except Exception as e:
                p_text = ""
                page_issues.append({
                    "code": "EXTRACTION_CRASH",
                    "type": "Extraction Failure",
                    "severity": "high",
                    "description": f"Page text could not be extracted due to a parser error: {str(e)}",
                    "suggested_layout": "Re-export PDF with standard text encoding from Google Docs or Word.",
                    "undistributed_info": "All textual contact information, skills, and dates on this page."
                })

            words = p_text.split()
            word_count = len(words)
            char_count = len(p_text.strip())

            # 2. Low text density / image-only page check
            if char_count < 60 and word_count < 15:
                page_issues.append({
                    "code": "LOW_TEXT_DENSITY",
                    "type": "Image-Only or Blank Page",
                    "severity": "high",
                    "description": f"Page {page_num} contains very few readable text characters ({word_count} words). ATS systems will treat this page as blank or unindexable.",
                    "suggested_layout": "Convert graphic certificates, portfolio scans, or image headers into selectable text.",
                    "undistributed_info": "Skills, certificates, or text embedded directly inside scanned images."
                })

            # 3. Corrupted font encodings / suspicious characters
            garbled = [c for c in p_text if ord(c) < 32 and c not in ('\n', '\r', '\t')]
            if len(garbled) > 10 or p_text.count('\ufffd') > 3:
                page_issues.append({
                    "code": "CORRUPTED_ENCODING",
                    "type": "Unusual Font Encoding",
                    "severity": "medium",
                    "description": f"Page {page_num} contains unprintable or non-standard character glyphs.",
                    "suggested_layout": "Use standard universal fonts such as Arial, Calibri, or Times New Roman.",
                    "undistributed_info": "Special bullet characters, symbols, or custom icons."
                })

            # 4. Multi-column sidebar check
            col_res = detect_page_columns(page)
            if col_res["detected"]:
                page_issues.append({
                    "code": "MULTI_COLUMN",
                    "type": "Multi-Column or Sidebar Layout",
                    "severity": "medium",
                    "description": f"Page {page_num} uses a 2-column or sidebar design. ATS parsers read horizontally across columns, scrambling sentences and mixing project descriptions with skills.",
                    "suggested_layout": "Single-column top-to-bottom layout with clear uppercase section headers.",
                    "undistributed_info": "Project bullets, skill lists, or side-by-side experience details."
                })

            # 5. Table & Grid detection
            tbl_res = detect_page_tables(page, p_text)
            if tbl_res["detected"]:
                page_issues.append({
                    "code": "TABLE_GRID",
                    "type": "Table Grid or Matrix",
                    "severity": "medium",
                    "description": f"Page {page_num} contains table grid lines or tabular formatting ({tbl_res['detail'] or 'border lines'}).",
                    "suggested_layout": "Simple bulleted lists rather than tables for Education and Technical Skills.",
                    "undistributed_info": "Degree names, institution names, and GPA fields placed in table cells."
                })

            # 6. Embedded raster images
            img_res = detect_page_images(page)
            if img_res["detected"]:
                page_issues.append({
                    "code": "EMBEDDED_IMAGES",
                    "type": "Embedded Graphics / Icons",
                    "severity": "low",
                    "description": f"Page {page_num} has {img_res['count']} embedded graphic icon(s) or image(s). ATS parsers cannot read contact links or proficiency bars trapped in graphics.",
                    "suggested_layout": "Text labels for contact methods (e.g., 'GitHub:', 'Email:') instead of icon glyphs.",
                    "undistributed_info": "Social links, star ratings, or contact handles represented by pictures."
                })

            has_problem = len(page_issues) > 0
            if has_problem:
                problem_page_numbers.append(page_num)
                for issue in page_issues:
                    all_issues_summary.append(f"Page {page_num}: {issue['type']}")

            # Snippet of readable text for thumbnail preview representation
            snippet = " ".join(p_text.split()[:40]) + ("..." if len(words) > 40 else "")

            pages_report.append({
                "page_number": page_num,
                "has_issues": has_problem,
                "issue_count": len(page_issues),
                "word_count": word_count,
                "char_count": char_count,
                "snippet": snippet,
                "issues": page_issues,
            })

        has_any_issues = len(problem_page_numbers) > 0
        overall_status = "issues_detected" if has_any_issues else "clean"

        return {
            "success": True,
            "total_pages": total_pages,
            "problem_page_count": len(problem_page_numbers),
            "problem_page_numbers": problem_page_numbers,
            "overall_status": overall_status,
            "pages": pages_report,
            "summary_message": (
                f"Detected formatting issues on page(s): {', '.join(map(str, problem_page_numbers))}."
                if has_any_issues else
                "All resume pages exhibit standard single-column ATS-friendly layouts."
            ),
            "general_recommendations": [
                "Keep resume formatting in a clean, single-column linear layout.",
                "Replace table matrices and graphic star-ratings with plain bulleted text.",
                "Ensure standard system fonts (Calibri, Arial, Helvetica) are used when exporting to PDF."
            ]
        }

    except Exception as exc:
        logger.warning("Error in analyze_pdf_page_issues: %s", exc)
        return _empty_page_report(f"Analysis error: {str(exc)}")


def _empty_page_report(message: str) -> Dict[str, Any]:
    return {
        "success": False,
        "total_pages": 0,
        "problem_page_count": 0,
        "problem_page_numbers": [],
        "overall_status": "error",
        "pages": [],
        "summary_message": message,
        "general_recommendations": []
    }
