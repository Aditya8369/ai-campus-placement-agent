"""
File Validation Feedback Service (#507)

Provides real-time, user-friendly file validation for drag-and-drop and file input uploads.
Checks before sending to heavy AI analysis pipelines:
- Supported file types (.pdf, .docx, .txt) based on extension and magic byte inspection
- Maximum file size limits (default 5MB or configurable)
- Empty or zero-byte file detection
- PDF/DOCX password encryption detection
- Replacement warnings for previously uploaded/active files
- Clear, plain-language actionable feedback messages (never exposing internal library stack traces)
- MIME-type inspection, binary magic signature verification, and sanitization tips
"""

import io
import os
import re
import unicodedata
import zipfile
from typing import Dict, Any, Optional, List

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
DEFAULT_MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

# Reserved device stems on Windows filesystems (#692)
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
}

# Recognized magic header bytes
MAGIC_SIGNATURES = {
    "pdf": b"%PDF-",
    "docx_zip": b"PK\x03\x04",
    "docx_ole_encrypted": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
}


def sanitize_filename(
    filename: Optional[str],
    default: str = "document.pdf",
    max_length: int = 120
) -> str:
    """
    Sanitizes an uploaded or user-provided filename into a safe, deterministic string (#692).
    - Strips directory traversal components ('..', '/', '\\')
    - Strips null bytes and unprintable/control characters
    - Normalizes Unicode with NFKC
    - Eliminates dangerous characters (<>:"/\\|?*)
    - Protects Windows reserved device stems (CON, PRN, AUX, NUL, COM*, LPT*)
    - Prevents hidden dot-files or trailing space/dot issues
    - Clamps length to max_length while preserving the file extension
    - Always returns a valid, non-empty filename string safe for disk operations
    """
    if max_length < 5:
        max_length = 5
    safe_default = os.path.basename(default.strip()) if default and default.strip() else "document.pdf"
    default_stem, default_ext = os.path.splitext(safe_default)
    if not default_ext:
        default_ext = ".pdf"
    if not default_stem:
        default_stem = "document"

    if not filename or not isinstance(filename, str):
        return f"{default_stem}{default_ext}"[:max_length]

    # Normalize Unicode NFKC
    raw = unicodedata.normalize("NFKC", filename)

    # Remove null bytes and ASCII/Unicode control characters
    raw = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", raw)

    # Standardize path separators and strip directory components
    raw = raw.replace("\\", "/")
    basename = raw.split("/")[-1].strip()

    # Remove path traversal patterns
    basename = re.sub(r"\.\.+", ".", basename)

    # Remove characters forbidden on POSIX/Windows filesystems
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", basename)

    # Collapse multiple consecutive underscores or spaces
    cleaned = re.sub(r"[_\s]+", "_", cleaned).strip(" ._")

    if not cleaned:
        return f"{default_stem}{default_ext}"[:max_length]

    # Split stem and extension
    stem, ext = os.path.splitext(cleaned)
    ext = ext.strip()
    if ext and len(ext) > 10:
        stem = f"{stem}{ext}"
        ext = default_ext
    elif not ext:
        ext = default_ext

    ext = re.sub(r"[^a-zA-Z0-9.]", "", ext)
    if not ext.startswith("."):
        ext = f".{ext}"

    clean_stem = stem.strip(" ._")
    if clean_stem.upper() in WINDOWS_RESERVED_NAMES or not clean_stem:
        clean_stem = f"file_{clean_stem}" if clean_stem else default_stem

    allowed_stem_len = max(1, max_length - len(ext))
    clean_stem = clean_stem[:allowed_stem_len].rstrip(" ._")
    if not clean_stem:
        clean_stem = default_stem[:allowed_stem_len]

    return f"{clean_stem}{ext}"


class FileValidationFeedbackService:
    """Service to validate resume upload files and format plain-language feedback."""

    def __init__(self, max_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES):
        self.max_size_bytes = max_size_bytes
        self.allowed_extensions = ALLOWED_EXTENSIONS

    def check_is_password_protected_pdf(self, file_bytes: bytes) -> bool:
        """
        Detects if a PDF file is encrypted or password-protected.
        """
        if not file_bytes:
            return False
        try:
            # Check for /Encrypt dictionary indicator in PDF header/trailer
            if b"/Encrypt" in file_bytes:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                return reader.is_encrypted
        except Exception:
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                return reader.is_encrypted
            except Exception:
                pass
        return False

    def check_is_password_protected_docx(self, file_bytes: bytes) -> bool:
        """
        Detects if a DOCX file is encrypted. Standard encrypted DOCX files are OLE compound documents (EncryptedPackage).
        """
        if not file_bytes:
            return False
        try:
            # DOCX is a zip archive containing [Content_Types].xml.
            # If it's password encrypted via Office, it's an OLE container starting with \xD0\xCF\x11\xE0
            if file_bytes.startswith(MAGIC_SIGNATURES["docx_ole_encrypted"]):
                return True
            with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
                # Test opening entries
                for zinfo in zf.infolist():
                    if zinfo.flag_bits & 0x1:
                        return True
        except zipfile.BadZipFile:
            # Could be encrypted or corrupted
            if b"EncryptedPackage" in file_bytes or file_bytes.startswith(MAGIC_SIGNATURES["docx_ole_encrypted"]):
                return True
        except Exception:
            pass
        return False

    def inspect_magic_header(self, filename: str, file_bytes: bytes) -> Dict[str, Any]:
        """
        Inspects binary signatures to confirm file content matches its declared extension.
        """
        _, ext = os.path.splitext(filename.lower())
        if ext == ".pdf":
            if file_bytes and not file_bytes.startswith(b"%PDF-"):
                return {
                    "matches_signature": False,
                    "warning": "The file has a .pdf extension but lacks standard PDF header markers."
                }
        elif ext == ".docx":
            if file_bytes and not file_bytes.startswith(b"PK\x03\x04") and not file_bytes.startswith(MAGIC_SIGNATURES["docx_ole_encrypted"]):
                return {
                    "matches_signature": False,
                    "warning": "The file has a .docx extension but does not appear to be a valid Word OpenXML package."
                }
        return {"matches_signature": True, "warning": None}

    def generate_sanitization_tips(self, file_status: str) -> List[str]:
        """Returns helpful plain-English remediation tips based on the validation failure reason."""
        tips = {
            "UNSUPPORTED_TYPE": [
                "Convert your document to PDF (.pdf) or Microsoft Word (.docx).",
                "If using Google Docs, click File -> Download -> PDF Document (.pdf).",
                "Ensure the file name ends with .pdf, .docx, or .txt."
            ],
            "EMPTY_FILE": [
                "Open the document on your computer to verify that text is visible.",
                "Ensure the file finished downloading or exporting before uploading.",
                "Save the document again to confirm content is written to disk."
            ],
            "FILE_TOO_LARGE": [
                "Remove heavy images, portfolio scans, or decorative background artwork.",
                "Use an online PDF compressor or re-save using standard quality settings.",
                "Ensure your resume is within the 1-2 page standard for campus placements."
            ],
            "PASSWORD_PROTECTED": [
                "Open the file in Adobe Acrobat, Word, or Chrome and print/save without a password.",
                "In Microsoft Word: File -> Info -> Protect Document -> Encrypt with Password (clear the password).",
                "In Google Docs: Ensure document link permissions allow public viewing or download."
            ],
            "ACCEPTED": [
                "Your document is valid and safe for automated placement parsing.",
                "ATS scoring will extract your contact info, skills, education, and projects."
            ]
        }
        return tips.get(file_status, ["Please verify your file format and try again."])

    def validate_file(
        self,
        filename: str,
        file_bytes: bytes,
        has_existing_file: bool = False,
        existing_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Performs full file inspection and returns structured feedback with plain-English reasons.
        """
        cleaned_filename = os.path.basename(filename or "unknown").strip()
        _, ext = os.path.splitext(cleaned_filename.lower())
        file_size = len(file_bytes)

        # 1. Check supported extension
        if ext not in self.allowed_extensions:
            tips = self.generate_sanitization_tips("UNSUPPORTED_TYPE")
            return {
                "is_valid": False,
                "status": "UNSUPPORTED_TYPE",
                "filename": cleaned_filename,
                "file_size": file_size,
                "badge": "Unsupported Format",
                "badge_color": "danger",
                "message": (
                    f"'{cleaned_filename}' is not a supported file type. "
                    "Please upload your resume as a PDF (.pdf), Word document (.docx), or plain text file (.txt)."
                ),
                "tips": tips,
                "safe_to_continue": False,
                "will_replace": False
            }

        # 2. Check empty or zero-byte file
        if file_size == 0:
            tips = self.generate_sanitization_tips("EMPTY_FILE")
            return {
                "is_valid": False,
                "status": "EMPTY_FILE",
                "filename": cleaned_filename,
                "file_size": 0,
                "badge": "Empty File",
                "badge_color": "danger",
                "message": (
                    f"'{cleaned_filename}' appears to be completely empty (0 KB). "
                    "Please select a file that contains your resume text."
                ),
                "tips": tips,
                "safe_to_continue": False,
                "will_replace": False
            }

        # 3. Check file size limits
        if file_size > self.max_size_bytes:
            size_mb = round(file_size / (1024 * 1024), 2)
            limit_mb = round(self.max_size_bytes / (1024 * 1024), 1)
            tips = self.generate_sanitization_tips("FILE_TOO_LARGE")
            return {
                "is_valid": False,
                "status": "FILE_TOO_LARGE",
                "filename": cleaned_filename,
                "file_size": file_size,
                "badge": "File Too Large",
                "badge_color": "danger",
                "message": (
                    f"'{cleaned_filename}' ({size_mb} MB) exceeds the maximum allowed size of {limit_mb} MB. "
                    "Please compress your document or export it without heavy background images."
                ),
                "tips": tips,
                "safe_to_continue": False,
                "will_replace": False
            }

        # 4. Check password protection
        if ext == ".pdf" and self.check_is_password_protected_pdf(file_bytes):
            tips = self.generate_sanitization_tips("PASSWORD_PROTECTED")
            return {
                "is_valid": False,
                "status": "PASSWORD_PROTECTED",
                "filename": cleaned_filename,
                "file_size": file_size,
                "badge": "Password Protected",
                "badge_color": "danger",
                "message": (
                    f"'{cleaned_filename}' is locked with a password. Automated placement analysis cannot read "
                    "password-protected documents. Please remove the password and re-upload."
                ),
                "tips": tips,
                "safe_to_continue": False,
                "will_replace": False
            }

        if ext == ".docx" and self.check_is_password_protected_docx(file_bytes):
            tips = self.generate_sanitization_tips("PASSWORD_PROTECTED")
            return {
                "is_valid": False,
                "status": "PASSWORD_PROTECTED",
                "filename": cleaned_filename,
                "file_size": file_size,
                "badge": "Password Protected",
                "badge_color": "danger",
                "message": (
                    f"'{cleaned_filename}' is encrypted with a password. Please remove the password protection in "
                    "Microsoft Word or Google Docs before uploading."
                ),
                "tips": tips,
                "safe_to_continue": False,
                "will_replace": False
            }

        # 5. Check if replacing existing file
        will_replace = has_existing_file and bool(existing_filename)
        replace_notice = ""
        if will_replace:
            replace_notice = f" Note: Continuing will replace your previously uploaded resume ('{existing_filename}')."

        magic_check = self.inspect_magic_header(cleaned_filename, file_bytes)
        size_kb = round(file_size / 1024, 1)
        tips = self.generate_sanitization_tips("ACCEPTED")

        return {
            "is_valid": True,
            "status": "ACCEPTED",
            "filename": cleaned_filename,
            "file_size": file_size,
            "file_size_formatted": f"{size_kb} KB",
            "badge": "Ready for Analysis",
            "badge_color": "success",
            "message": f"'{cleaned_filename}' ({size_kb} KB) is verified and ready for AI placement analysis.{replace_notice}",
            "magic_warning": magic_check.get("warning"),
            "tips": tips,
            "safe_to_continue": True,
            "will_replace": will_replace,
            "existing_filename": existing_filename
        }


file_validation_service = FileValidationFeedbackService()
