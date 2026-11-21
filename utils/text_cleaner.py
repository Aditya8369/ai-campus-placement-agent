"""
Resume Text Cleaner and Artifact Normalizer (#645).
===================================================
Normalizes PDF and document extraction artifacts before downstream ATS evaluation,
skill gap extraction, and preparation roadmap generation:

Key Capabilities:
1. Unicode NFKC Normalization & Typographic Ligature Expansion:
   - Expands common typographic ligatures (e.g. "ﬁ" -> "fi", "ﬂ" -> "fl", "ﬀ" -> "ff",
     "ﬃ" -> "ffi", "ﬄ" -> "ffl", "ﬅ" -> "ft", "ﬆ" -> "st").
   - Applies Unicode NFKC normalization for canonical decomposition and compatibility.
2. Hyphenated Line Breaks Joining:
   - Recombines words split across line breaks by line-end hyphens (e.g. "develop-\nment" -> "development").
   - Retains genuine hyphenated words within a single line (e.g. "full-stack", "object-oriented", "end-to-end").
3. Standard Bullet Glyphs Mapping:
   - Maps Private Use Area (PUA) bullet symbols (\uE000-\uF8FF, \uF000-\uF8FF) and varied
     bullet glyphs (e.g. ➢, ▪, ‣, ◦, ●, ★) to standard bullet format ("• ").
4. Layout and Whitespace Collapsing:
   - Converts non-breaking and unusual spaces (\u00A0, \u2000-\u200A) to standard spaces.
   - Strips zero-width and invisible control characters (\u200B, \u200C, \u200D, \uFEFF, \u00AD).
   - Collapses doubled spaces and excessive intra-line whitespace to single spaces.
   - Cleans up trailing line whitespace and trims excessive vertical spacing (>2 newlines).
5. Repeated Headers and Footers Removal:
   - Identifies and eliminates recurrent running headers, page numbers, or confidentiality
     footers that repeat across multiple pages of multi-page resumes.
6. Semantic Integrity Preservation:
   - Preserves programming language and skill names containing symbols and digits
     (e.g. "C++", "C#", ".NET", "Node.js", "Vue.js", "CI/CD", "TCP/IP", "A/B testing").
7. In-Memory Raw Text Debugging:
   - Retains the un-normalized raw text strictly in memory for debugging and inspection.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# In-memory debugging cache for raw, un-normalized resume text (zero disk persistence)
_RAW_TEXT_IN_MEMORY_STORE: Dict[str, str] = {}
_LAST_RAW_RESUME_TEXT: Optional[str] = None
_MAX_DEBUG_CACHE_ENTRIES = 50

# Typographic ligatures mapping
LIGATURE_MAPPING: Dict[str, str] = {
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬀ": "ff",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "ft",
    "ﬆ": "st",
    "æ": "ae",
    "Æ": "AE",
    "œ": "oe",
    "Œ": "OE",
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "ft",
    "\ufb06": "st",
}

# Regex to match bullet glyphs at start of a line or after whitespace
BULLET_START_PATTERN = re.compile(
    r"^([ \t]*)[•‣⁃◦∙▪▫■□●○◆◇▶►▸✓✔★☆➢➤\uf000-\uf8ff\ue000-\uf8ff]+[ \t]*",
    re.MULTILINE,
)

# Regex to match isolated mid-line bullet separators
BULLET_INLINE_PATTERN = re.compile(
    r"[ \t]+[•‣⁃◦∙▪▫■□●○◆◇▶►▸✓✔★☆➢➤\uf000-\uf8ff\ue000-\uf8ff][ \t]+"
)

# Regex matching words split by hyphen at line break
# Group 1: at least 2 letters before hyphen; Group 2: at least 2 letters on the next line
LINE_BREAK_HYPHEN_PATTERN = re.compile(
    r"([A-Za-z]{2,})-[ \t]*[\r\n]+[ \t]*([A-Za-z]{2,})"
)

# Soft hyphen line break or inline pattern
SOFT_HYPHEN_PATTERN = re.compile(r"([A-Za-z]+)\u00ad[ \t]*[\r\n]*[ \t]*([A-Za-z]+)")

# Regex matching standalone page numbers (e.g., "Page 1 of 3", "1 / 2", "- 2 -", "Page 2")
PAGE_NUMBER_LINE_PATTERN = re.compile(
    r"^(?:page\s*\d+(?:\s*(?:of|\/)\s*\d+)?|\d+\s*(?:of|\/)\s*\d+|-\s*\d+\s*-)$",
    re.IGNORECASE,
)

# Standard section titles that should NOT be mistaken for repeated page headers
EXCLUDED_SECTION_HEADINGS: Set[str] = {
    "education",
    "skills",
    "technical skills",
    "experience",
    "work experience",
    "professional experience",
    "projects",
    "academic projects",
    "certifications",
    "summary",
    "professional summary",
    "achievements",
    "publications",
}


def store_raw_resume_text(raw_text: str, identifier: Optional[str] = None) -> None:
    """Stores un-normalized resume text in memory for debugging inspection."""
    global _LAST_RAW_RESUME_TEXT
    _LAST_RAW_RESUME_TEXT = raw_text
    if identifier:
        if len(_RAW_TEXT_IN_MEMORY_STORE) >= _MAX_DEBUG_CACHE_ENTRIES:
            # Evict oldest entry
            oldest_key = next(iter(_RAW_TEXT_IN_MEMORY_STORE))
            _RAW_TEXT_IN_MEMORY_STORE.pop(oldest_key, None)
        _RAW_TEXT_IN_MEMORY_STORE[str(identifier)] = raw_text


def get_last_raw_resume_text() -> Optional[str]:
    """Retrieves the most recent un-normalized raw resume text kept in memory."""
    return _LAST_RAW_RESUME_TEXT


def get_raw_resume_text(identifier: str) -> Optional[str]:
    """Retrieves raw resume text by identifier from the in-memory debugging cache."""
    return _RAW_TEXT_IN_MEMORY_STORE.get(str(identifier))


def clear_raw_text_cache() -> None:
    """Clears the in-memory debugging raw text store."""
    global _LAST_RAW_RESUME_TEXT
    _RAW_TEXT_IN_MEMORY_STORE.clear()
    _LAST_RAW_RESUME_TEXT = None


def expand_ligatures(text: str) -> str:
    """
    Expands typographical ligatures and applies Unicode NFKC normalization.
    Ensures 'ﬁnance' -> 'finance' and 'ﬂow' -> 'flow'.
    """
    if not text:
        return ""

    # Replace explicit ligature characters
    for lig, replacement in LIGATURE_MAPPING.items():
        if lig in text:
            text = text.replace(lig, replacement)

    # Unicode NFKC normalization decomposes remaining compatibility characters
    text = unicodedata.normalize("NFKC", text)

    # Re-apply mapping in case normalization decomposed characters into related glyphs
    for lig, replacement in LIGATURE_MAPPING.items():
        if lig in text:
            text = text.replace(lig, replacement)

    return text


def join_hyphenated_line_breaks(text: str) -> str:
    """
    Recombines words split across line breaks by line-end hyphens.
    
    Examples:
    - 'develop-\\nment' -> 'development'
    - 'experi-\\n  ence' -> 'experience'
    
    Genuine single-line hyphenated words ('full-stack', 'object-oriented', 'end-to-end')
    are preserved without modification.
    """
    if not text:
        return ""

    # First handle soft hyphens
    text = SOFT_HYPHEN_PATTERN.sub(r"\1\2", text)
    text = text.replace("\u00ad", "")

    # Recombine line-break hyphens
    return LINE_BREAK_HYPHEN_PATTERN.sub(r"\1\2", text)


def normalize_bullets(text: str) -> str:
    """
    Maps Private Use Area (PUA) bullet symbols and varied Unicode bullet glyphs
    to a standard bullet point marker ('• ').
    """
    if not text:
        return ""

    # Normalize line-start bullets
    text = BULLET_START_PATTERN.sub(r"\1• ", text)

    # Normalize mid-line bullet separators (e.g. "Python • Django • React")
    text = BULLET_INLINE_PATTERN.sub(r" • ", text)

    # Clean any remaining rogue Private Use Area symbols that have no valid text meaning
    text = re.sub(r"[\ue000-\uf8ff]", "", text)

    return text


def collapse_whitespace(text: str) -> str:
    """
    Collapses horizontal doubled spaces, non-breaking spaces, and excessive line breaks:
    - Replaces non-breaking space (\\u00A0) and Unicode spaces with standard space.
    - Strips zero-width spaces (\\u200B, \\u200C, \\u200D, \\uFEFF).
    - Collapses multiple horizontal spaces or tabs into a single space.
    - Trims trailing spaces on lines.
    - Collapses 3 or more consecutive line breaks into 2 line breaks.
    """
    if not text:
        return ""

    # Strip zero-width invisible markers
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)

    # Convert non-breaking and special Unicode spaces to standard space
    text = re.sub(r"[\u00a0\u2000-\u200a\u202f\u205f\u3000]", " ", text)

    # Collapse multiple horizontal spaces and tabs into a single space on each line
    lines = text.splitlines()
    cleaned_lines: List[str] = []
    for line in lines:
        cleaned_line = re.sub(r"[ \t]+", " ", line).strip()
        cleaned_lines.append(cleaned_line)

    text = "\n".join(cleaned_lines)

    # Collapse 3 or more consecutive line breaks into at most 2 line breaks
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def remove_repeated_headers_and_footers(pages: List[str]) -> str:
    """
    Detects and strips repetitive running headers, page numbers, or footers
    that recur across most pages of a multi-page resume.
    """
    if not pages:
        return ""

    if len(pages) == 1:
        # Single page: just strip standalone page numbers
        lines = [line.strip() for line in pages[0].splitlines()]
        filtered = [l for l in lines if not PAGE_NUMBER_LINE_PATTERN.match(l)]
        return "\n".join(filtered)

    total_pages = len(pages)
    page_lines_list: List[List[str]] = [
        [line.strip() for line in p.splitlines() if line.strip()]
        for p in pages
    ]

    # Track how many distinct pages each top line and bottom line appears in
    page_top_counts: Dict[str, int] = defaultdict(int)
    page_bottom_counts: Dict[str, int] = defaultdict(int)

    for p_lines in page_lines_list:
        if not p_lines:
            continue
        # Header candidate lines (first 2 non-empty lines)
        top_candidates = set(p_lines[:2])
        for line in top_candidates:
            if line.lower() not in EXCLUDED_SECTION_HEADINGS:
                page_top_counts[line] += 1

        # Footer candidate lines (last 2 non-empty lines)
        bottom_candidates = set(p_lines[-2:])
        for line in bottom_candidates:
            if line.lower() not in EXCLUDED_SECTION_HEADINGS:
                page_bottom_counts[line] += 1

    # Appears on at least 2 pages (or more than half the pages for 3+ pages)
    threshold = 2 if total_pages <= 3 else (total_pages // 2)

    repeated_headers = {
        line for line, count in page_top_counts.items()
        if count >= threshold and len(line) <= 120
    }
    repeated_footers = {
        line for line, count in page_bottom_counts.items()
        if count >= threshold and len(line) <= 120
    }

    cleaned_pages: List[str] = []
    for p_lines in page_lines_list:
        cleaned_lines: List[str] = []
        n_lines = len(p_lines)
        for idx, line in enumerate(p_lines):
            # Header check
            if idx < 2 and line in repeated_headers:
                continue
            # Footer check
            if idx >= n_lines - 2 and line in repeated_footers:
                continue
            # Page number line check
            if PAGE_NUMBER_LINE_PATTERN.match(line):
                continue
            cleaned_lines.append(line)

        cleaned_pages.append("\n".join(cleaned_lines))

    return "\n\n".join(p for p in cleaned_pages if p.strip())


def normalize_resume_text(
    text: str,
    pages_text: Optional[List[str]] = None,
    store_raw: bool = True,
    text_id: Optional[str] = None,
) -> str:
    """
    Main entry point for resume text artifact normalization (#645).
    
    Parameters:
        text: Raw extracted resume text.
        pages_text: Optional list of per-page text strings for multi-page header/footer deduplication.
        store_raw: Whether to retain the un-normalized raw text in memory for debugging.
        text_id: Optional identifier (file path or UUID) to index the raw text.

    Returns:
        Cleaned, normalized resume text ready for downstream ATS and skill gap processing.
    """
    if not text or not isinstance(text, str):
        return ""

    if store_raw:
        store_raw_resume_text(text, identifier=text_id)

    # 1. Expand ligatures and apply Unicode NFKC normalization
    normalized = expand_ligatures(text)

    # 2. Join words split across line breaks by hyphens
    normalized = join_hyphenated_line_breaks(normalized)

    # 3. Standardize bullet glyphs
    normalized = normalize_bullets(normalized)

    # 4. Remove repeated headers/footers if multi-page text is provided
    if pages_text and len(pages_text) > 1:
        normalized_pages = [
            collapse_whitespace(normalize_bullets(join_hyphenated_line_breaks(expand_ligatures(p))))
            for p in pages_text
        ]
        normalized = remove_repeated_headers_and_footers(normalized_pages)
    elif "\x0c" in normalized:
        # Form-feed delimited multi-page text
        raw_pages = [p for p in normalized.split("\x0c") if p.strip()]
        if len(raw_pages) > 1:
            normalized = remove_repeated_headers_and_footers(raw_pages)

    # 5. Collapse spaces, tabs, and excessive blank lines
    normalized = collapse_whitespace(normalized)

    return normalized
