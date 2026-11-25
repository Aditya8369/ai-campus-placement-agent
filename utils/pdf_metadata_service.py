import io
import os
import re
import logging
from typing import Any, Dict, Optional, Tuple, Union

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except ImportError:
        PdfReader = None
        PdfWriter = None

logger = logging.getLogger(__name__)

SUSPICIOUS_FILENAME_KEYWORDS = [
    r"v\d+",
    r"ver\d+",
    r"version\d*",
    r"final",
    r"draft",
    r"copy",
    r"latest",
    r"new",
    r"updated",
    r"temp",
    r"edit",
    r"rev\d*",
    r"download",
    r"\(\d+\)",
]

GENERIC_FILENAMES = {
    "resume.pdf",
    "cv.pdf",
    "my_resume.pdf",
    "myresume.pdf",
    "document.pdf",
    "doc.pdf",
    "untitled.pdf",
    "file.pdf",
    "curriculum_vitae.pdf",
}

TEMPLATE_AUTHOR_HINTS = [
    "canva",
    "template",
    "word",
    "microsoft",
    "adobe",
    "latex",
    "overleaf",
    "mac",
    "apple",
    "user",
    "admin",
    "administrator",
    "author",
    "unknown",
    "fresher",
    "student",
    "hp",
    "dell",
    "lenovo",
    "owner",
]


def read_pdf_metadata(file_input: Union[str, bytes, io.BytesIO]) -> Dict[str, Optional[str]]:
    """
    Safely extract standard PDF metadata (author, title, creator, producer, creation_date).
    Does not crash on corrupt, empty, or non-PDF files.
    """
    metadata: Dict[str, Optional[str]] = {
        "author": None,
        "title": None,
        "creator": None,
        "producer": None,
        "creation_date": None,
    }

    if PdfReader is None:
        return metadata

    try:
        reader = None
        if isinstance(file_input, str):
            if not os.path.exists(file_input) or os.path.getsize(file_input) == 0:
                return metadata
            reader = PdfReader(file_input)
        elif isinstance(file_input, bytes):
            if len(file_input) == 0:
                return metadata
            reader = PdfReader(io.BytesIO(file_input))
        elif isinstance(file_input, io.BytesIO):
            pos = file_input.tell()
            file_input.seek(0)
            reader = PdfReader(file_input)
            file_input.seek(pos)

        if reader and reader.metadata:
            meta = reader.metadata
            metadata["author"] = str(meta.author).strip() if getattr(meta, "author", None) else None
            metadata["title"] = str(meta.title).strip() if getattr(meta, "title", None) else None
            metadata["creator"] = str(meta.creator).strip() if getattr(meta, "creator", None) else None
            metadata["producer"] = str(meta.producer).strip() if getattr(meta, "producer", None) else None

            creation_date = getattr(meta, "creation_date", None)
            if not creation_date and hasattr(meta, "get"):
                creation_date = meta.get("/CreationDate")
            metadata["creation_date"] = str(creation_date).strip() if creation_date else None

    except Exception as e:
        logger.debug(f"Error reading PDF metadata: {e}")

    return metadata


def generate_suggested_filename(candidate_name: Optional[str] = None, target_role: Optional[str] = None) -> str:
    """
    Suggests a clean filename matching the pattern: FirstName_LastName_Role.pdf
    """
    def sanitize(text: str) -> str:
        clean = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_")
        return clean or "Resume"

    first_last = "FirstName_LastName"
    if candidate_name and candidate_name.strip():
        parts = [p.capitalize() for p in re.split(r"\s+", candidate_name.strip()) if p]
        if parts:
            if len(parts) == 1:
                first_last = f"{parts[0]}_Resume"
            else:
                first_last = f"{parts[0]}_{parts[-1]}"

    role = "Role"
    if target_role and target_role.strip():
        role_parts = [p.capitalize() for p in re.split(r"\s+", target_role.strip()) if p]
        if role_parts:
            role = "_".join(role_parts[:3])

    suggested = f"{sanitize(first_last)}_{sanitize(role)}.pdf"
    return suggested


def analyze_pdf_metadata_hygiene(
    metadata: Dict[str, Optional[str]],
    filename: Optional[str] = None,
    candidate_name: Optional[str] = None,
    target_role: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Inspects PDF metadata and file naming for privacy, professionalism, and recruiter hygiene.
    Acceptance criteria:
    - Files without metadata show no warnings (unless filename itself is unprofessional).
    - If author or title is present and suspicious/mismatched, raise a warning.
    - Suggests clean file name pattern (FirstName_LastName_Role.pdf).
    """
    warnings = []

    clean_pattern = "FirstName_LastName_Role.pdf"
    suggested_filename = generate_suggested_filename(candidate_name, target_role)

    author = metadata.get("author") if metadata else None
    title = metadata.get("title") if metadata else None
    creator = metadata.get("creator") if metadata else None
    producer = metadata.get("producer") if metadata else None

    # 1. Author inspection
    if author:
        author_lower = author.lower()
        if any(h in author_lower for h in TEMPLATE_AUTHOR_HINTS):
            warnings.append({
                "type": "author_template",
                "field": "author",
                "value": author,
                "message": f"PDF Author metadata is set to '{author}', which appears to be from a software template or generic account.",
                "suggestion": "Recruiters and ATS can see this metadata. Download a cleaned metadata-free copy.",
            })
        elif candidate_name and candidate_name.strip():
            cand_tokens = set(re.findall(r"\w+", candidate_name.lower()))
            author_tokens = set(re.findall(r"\w+", author_lower))
            overlap = cand_tokens.intersection(author_tokens)
            if cand_tokens and not overlap and len(cand_tokens) >= 1:
                warnings.append({
                    "type": "author_mismatch",
                    "field": "author",
                    "value": author,
                    "message": f"PDF Author metadata shows '{author}', which does not match your profile name '{candidate_name.strip()}'.",
                    "suggestion": "This may expose someone else's name if you cloned another person's resume template.",
                })

    # 2. Title inspection
    if title:
        title_lower = title.lower()
        generic_titles = ["untitled", "document", "microsoft word", "resume template", "cv template", "template", "presentation"]
        if any(gt in title_lower for gt in generic_titles) or re.search(r"v\d+|final|draft|copy", title_lower):
            warnings.append({
                "type": "title_unprofessional",
                "field": "title",
                "value": title,
                "message": f"PDF Title metadata is set to '{title}', which looks like a template default or draft title.",
                "suggestion": "Clear title metadata before submitting to recruiters.",
            })

    # 3. Software/Tool leakage
    if creator and any(tool in creator.lower() for tool in ["canva", "ilovepdf", "smallpdf", "sejda", "word"]):
        warnings.append({
            "type": "tool_leakage",
            "field": "creator",
            "value": creator,
            "message": f"PDF Creator tool is '{creator}'.",
            "suggestion": "Some recruiters check metadata to see how the document was compiled.",
        })

    # 4. Filename inspection
    if filename:
        base_name = os.path.basename(filename).strip()
        base_name_lower = base_name.lower()

        if base_name_lower in GENERIC_FILENAMES:
            warnings.append({
                "type": "filename_generic",
                "field": "filename",
                "value": base_name,
                "message": f"Filename '{base_name}' is generic.",
                "suggestion": f"Use a distinct name following the standard pattern: {clean_pattern} (e.g. {suggested_filename}).",
            })
        else:
            name_without_ext = os.path.splitext(base_name_lower)[0]
            matched_patterns = []
            for pat in SUSPICIOUS_FILENAME_KEYWORDS:
                if re.search(r"(?:^|[\W_])" + pat + r"(?:$|[\W_])", name_without_ext) or re.search(pat, name_without_ext):
                    matched_patterns.append(pat.replace("\\", ""))

            if matched_patterns:
                warnings.append({
                    "type": "filename_versioning",
                    "field": "filename",
                    "value": base_name,
                    "message": f"Filename '{base_name}' contains draft/version indicators ({', '.join(sorted(set(matched_patterns)))}).",
                    "suggestion": f"Recruiters see file names like 'final_v3'. Rename using the recommended format: {clean_pattern}.",
                })

    has_warnings = len(warnings) > 0
    has_any_metadata = any(bool(v) for v in [author, title, creator, producer])

    return {
        "has_warnings": has_warnings,
        "warnings": warnings,
        "metadata": {
            "author": author,
            "title": title,
            "creator": creator,
            "producer": producer,
        },
        "filename": filename,
        "clean_filename_pattern": clean_pattern,
        "suggested_filename": suggested_filename,
        "has_any_metadata": has_any_metadata,
        "is_clean": (not has_warnings and not has_any_metadata),
    }


def strip_pdf_metadata(file_input: Union[str, bytes, io.BytesIO]) -> io.BytesIO:
    """
    Creates a new PDF copy in memory with all metadata stripped (author, title, creator, producer, etc.).
    Returns an in-memory BytesIO object.
    Acceptance criterion: The cleaned copy contains no author or title metadata.
    """
    if PdfReader is None or PdfWriter is None:
        raise RuntimeError("PDF library is not available.")

    reader = None
    if isinstance(file_input, str):
        reader = PdfReader(file_input)
    elif isinstance(file_input, bytes):
        reader = PdfReader(io.BytesIO(file_input))
    elif isinstance(file_input, io.BytesIO):
        pos = file_input.tell()
        file_input.seek(0)
        reader = PdfReader(file_input)
        file_input.seek(pos)
    else:
        raise ValueError("Invalid file_input type for strip_pdf_metadata")

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    # Empty metadata ensures author, title, creator, and producer are completely stripped
    writer.add_metadata({})
    try:
        # Clear default library injection (e.g. {'/Producer': 'PyPDF2'})
        if hasattr(writer, "_info") and writer._info:
            info_obj = writer._info.get_object() if hasattr(writer._info, "get_object") else writer._info
            if hasattr(info_obj, "clear"):
                info_obj.clear()
    except Exception:
        pass

    out_stream = io.BytesIO()
    writer.write(out_stream)
    out_stream.seek(0)
    return out_stream


def get_or_compute_pdf_metadata_hygiene(analysis_record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retrieves stored pdf_metadata_hygiene or dynamically analyzes it from stored files if available.
    """
    if not isinstance(analysis_record, dict):
        return analyze_pdf_metadata_hygiene({}, filename="resume.pdf")

    # Check in results
    results = analysis_record.get("results")
    if isinstance(results, dict) and results.get("pdf_metadata_hygiene"):
        return results["pdf_metadata_hygiene"]

    if analysis_record.get("pdf_metadata_hygiene"):
        return analysis_record["pdf_metadata_hygiene"]

    # Try inspecting stored file in upload folder if exists
    file_id = analysis_record.get("id") or analysis_record.get("file_uuid")
    fname = analysis_record.get("resume_filename") or "resume.pdf"
    candidate_name = None
    target_role = analysis_record.get("target_role") or analysis_record.get("company_name")

    if isinstance(results, dict):
        cand_info = results.get("candidate_info") or results.get("resume_analysis", {})
        if isinstance(cand_info, dict):
            candidate_name = cand_info.get("name") or cand_info.get("candidate_name")

    try:
        import config
        from werkzeug.utils import secure_filename
        upload_folder = getattr(config, "UPLOAD_FOLDER", "uploads")
        if file_id and fname:
            target_path = os.path.join(upload_folder, secure_filename(f"{file_id}_{fname}"))
            if os.path.exists(target_path) and fname.lower().endswith(".pdf"):
                meta = read_pdf_metadata(target_path)
                return analyze_pdf_metadata_hygiene(
                    meta,
                    filename=fname,
                    candidate_name=candidate_name,
                    target_role=target_role,
                )
    except Exception as e:
        logger.debug(f"Could not compute pdf metadata hygiene from stored file: {e}")

    # Fallback with filename check and empty metadata
    return analyze_pdf_metadata_hygiene(
        {},
        filename=fname,
        candidate_name=candidate_name,
        target_role=target_role,
    )
