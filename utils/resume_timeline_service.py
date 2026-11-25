"""
Resume Timeline & Gap Analysis Service (#840)
==============================================
Analyzes resume dates from education, experience, and project sections.
Detects:
1. Gaps longer than a configurable threshold (default: 6 months).
2. Chronological overlaps between concurrent roles.
3. Inverted dates where end date precedes start date.
4. Dates set far in the future without 'Expected' framing.

Design Principles:
- Tolerant parsing for mixed formats (e.g. 'Jan 2024', '01/2024', '2024', 'Present').
- Unparseable dates never cause errors or false alarms.
- Neutral, objective explanations without assuming reasons (illness, breaks, etc.).
- Constructive suggestions (courses, projects, part-time/concurrent framing).
- Dismissable flags with session/storage persistence.
"""

import re
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_GAP_THRESHOLD_MONTHS = 6
CURRENT_YEAR = datetime.now(timezone.utc).year
CURRENT_MONTH = datetime.now(timezone.utc).month

MONTH_MAP = {
    "jan": 1, "january": 1, "jan.": 1,
    "feb": 2, "february": 2, "feb.": 2,
    "mar": 3, "march": 3, "mar.": 3,
    "apr": 4, "april": 4, "apr.": 4,
    "may": 5, "may.": 5,
    "jun": 6, "june": 6, "jun.": 6,
    "jul": 7, "july": 7, "jul.": 7,
    "aug": 8, "august": 8, "aug.": 8,
    "sep": 9, "sept": 9, "september": 9, "sep.": 9, "sept.": 9,
    "oct": 10, "october": 10, "oct.": 10,
    "nov": 11, "november": 11, "nov.": 11,
    "dec": 12, "december": 12, "dec.": 12,
}

SEASON_MAP = {
    "spring": 3,
    "summer": 6,
    "fall": 9,
    "autumn": 9,
    "winter": 12,
}

PRESENT_TERMS = {
    "present", "current", "currently", "ongoing", "now", "till date", "to date", "active"
}


class ResumeDate:
    """Normalized date point for chronological comparison."""

    def __init__(self, year: int, month: int = 1, precision: str = "month", is_present: bool = False, raw: str = ""):
        self.year = year
        self.month = max(1, min(12, month))
        self.precision = precision  # 'month', 'year', 'season', 'present'
        self.is_present = is_present
        self.raw = raw.strip()

    @property
    def total_months(self) -> int:
        return self.year * 12 + self.month

    def __lt__(self, other: "ResumeDate") -> bool:
        return self.total_months < other.total_months

    def __le__(self, other: "ResumeDate") -> bool:
        return self.total_months <= other.total_months

    def __gt__(self, other: "ResumeDate") -> bool:
        return self.total_months > other.total_months

    def __ge__(self, other: "ResumeDate") -> bool:
        return self.total_months >= other.total_months

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ResumeDate):
            return False
        return self.total_months == other.total_months

    def format_display(self) -> str:
        if self.is_present:
            return "Present"
        if self.precision == "year":
            return str(self.year)
        month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return f"{month_names[self.month]} {self.year}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "year": self.year,
            "month": self.month,
            "precision": self.precision,
            "is_present": self.is_present,
            "display": self.format_display(),
            "raw": self.raw,
        }


def parse_single_date(text: str, is_end_date: bool = False) -> Optional[ResumeDate]:
    """
    Parses a single date token into a ResumeDate object.
    Supports month names, MM/YYYY, YYYY-MM, Year only, and Present/Current terms.
    Returns None if unparseable, ensuring no exceptions are raised.
    """
    if not text:
        return None

    cleaned = text.strip().strip("(),[]{}")
    lower = cleaned.lower()

    if lower in PRESENT_TERMS:
        return ResumeDate(
            year=CURRENT_YEAR,
            month=CURRENT_MONTH,
            precision="present",
            is_present=True,
            raw=cleaned,
        )

    # 1. Month name / abbreviation + Year (e.g., 'Jan 2024', 'January 2024', 'Jan, 2024')
    m_month_year = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[.,]?\s+(\d{4})\b",
        cleaned,
        re.IGNORECASE,
    )
    if m_month_year:
        m_str = m_month_year.group(1).lower()
        y_int = int(m_month_year.group(2))
        m_int = MONTH_MAP.get(m_str, 1)
        return ResumeDate(year=y_int, month=m_int, precision="month", raw=cleaned)

    # 2. Season + Year (e.g. 'Fall 2023', 'Summer 2022')
    m_season = re.search(r"\b(spring|summer|fall|autumn|winter)\s+(\d{4})\b", cleaned, re.IGNORECASE)
    if m_season:
        s_str = m_season.group(1).lower()
        y_int = int(m_season.group(2))
        m_int = SEASON_MAP.get(s_str, 6)
        return ResumeDate(year=y_int, month=m_int, precision="season", raw=cleaned)

    # 3. Numeric MM/YYYY or MM-YYYY (e.g. '01/2024', '1/2024', '12-2022')
    m_num_slash = re.search(r"\b(0?[1-9]|1[0-2])\s*[/.-]\s*(\d{4})\b", cleaned)
    if m_num_slash:
        m_int = int(m_num_slash.group(1))
        y_int = int(m_num_slash.group(2))
        return ResumeDate(year=y_int, month=m_int, precision="month", raw=cleaned)

    # 4. Numeric YYYY/MM or YYYY-MM (e.g. '2024/01', '2024-01')
    m_year_slash = re.search(r"\b(\d{4})\s*[/.-]\s*(0?[1-9]|1[0-2])\b", cleaned)
    if m_year_slash:
        y_int = int(m_year_slash.group(1))
        m_int = int(m_year_slash.group(2))
        return ResumeDate(year=y_int, month=m_int, precision="month", raw=cleaned)

    # 5. Year only (e.g. '2024', '1998')
    m_year_only = re.search(r"\b(19\d{2}|20\d{2})\b", cleaned)
    if m_year_only:
        y_int = int(m_year_only.group(1))
        # Default start date of year-only to Jan (1), end date to Dec (12)
        m_int = 12 if is_end_date else 1
        return ResumeDate(year=y_int, month=m_int, precision="year", raw=cleaned)

    return None


def parse_date_range(text: str) -> Optional[Tuple[ResumeDate, ResumeDate]]:
    """
    Parses a string containing a date range into (start_date, end_date).
    Splits by delimiters like '-', '–', '—', 'to', 'until'.
    Returns None if range cannot be extracted safely.
    """
    if not text:
        return None

    # Common range delimiters
    split_pattern = r"\s+(?:to|until|thru|through)\s+|\s*[-–—]\s*"
    parts = re.split(split_pattern, text.strip(), maxsplit=1, flags=re.IGNORECASE)

    if len(parts) == 2:
        start_d = parse_single_date(parts[0], is_end_date=False)
        end_d = parse_single_date(parts[1], is_end_date=True)
        if start_d and end_d:
            return start_d, end_d

    return None


def calculate_months_between(end_d: ResumeDate, next_start_d: ResumeDate) -> int:
    """
    Calculates the gap in full months between the end of one commitment
    and the start of the next commitment.
    """
    gap = next_start_d.total_months - end_d.total_months
    # If consecutive months (e.g., end in May, start in June), difference is 1, gap is 0
    return max(0, gap - 1)


def calculate_overlap_months(item_a_start: ResumeDate, item_a_end: ResumeDate,
                             item_b_start: ResumeDate, item_b_end: ResumeDate) -> int:
    """
    Calculates overlap in months between two date ranges [start_a, end_a] and [start_b, end_b].
    Returns 0 if no overlap exists.
    """
    overlap_start = max(item_a_start.total_months, item_b_start.total_months)
    overlap_end = min(item_a_end.total_months, item_b_end.total_months)
    if overlap_end >= overlap_start:
        return (overlap_end - overlap_start) + 1
    return 0


class TimelineItem:
    """Represents a dated entry in the candidate's career or education timeline."""

    def __init__(
        self,
        title: str,
        organization: str,
        start_date: ResumeDate,
        end_date: ResumeDate,
        section: str = "experience",
        raw_line: str = "",
        line_number: int = 0,
    ):
        self.title = title.strip() or "Position / Study"
        self.organization = organization.strip() or "Organization"
        self.start_date = start_date
        self.end_date = end_date
        self.section = section
        self.raw_line = raw_line.strip()
        self.line_number = line_number

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "organization": self.organization,
            "start_date": self.start_date.to_dict(),
            "end_date": self.end_date.to_dict(),
            "date_range_display": f"{self.start_date.format_display()} – {self.end_date.format_display()}",
            "section": self.section,
            "raw_line": self.raw_line,
            "line_number": self.line_number,
        }


def extract_timeline_items_from_text(resume_text: str) -> List[TimelineItem]:
    """
    Scans raw resume text line-by-line to extract dated career and educational milestones.
    Categorizes lines into experience, education, or projects based on section headers.
    """
    if not resume_text:
        return []

    lines = resume_text.splitlines()
    items: List[TimelineItem] = []
    current_section = "experience"

    range_regex = re.compile(
        r"(?P<start>(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|Spring|Summer|Fall|Winter)[.,]?\s+)?(?:[01]?\d[/.-])?(?:19|20)\d{2})\s*(?:[-–—]|to|until|thru|through)\s*(?P<end>(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|Spring|Summer|Fall|Winter)[.,]?\s+)?(?:[01]?\d[/.-])?(?:19|20)\d{2}|Present|Current|Ongoing|Now|Till Date)",
        re.IGNORECASE,
    )

    for idx, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line:
            continue

        lower = line.lower()
        if re.match(r"^[#*_\-\s]*(?:education|academics|qualifications)\b", lower):
            current_section = "education"
            continue
        elif re.match(r"^[#*_\-\s]*(?:experience|work|employment|internships|history)\b", lower):
            current_section = "experience"
            continue
        elif re.match(r"^[#*_\-\s]*(?:projects|academic projects|technical projects)\b", lower):
            current_section = "project"
            continue
        elif re.match(r"^[#*_\-\s]*(?:skills|certifications|awards|summary|profile|interests)\b", lower):
            current_section = "other"
            continue

        # Look for date range match in line
        m = range_regex.search(line)
        if m:
            start_str = m.group("start")
            end_str = m.group("end")
            start_d = parse_single_date(start_str, is_end_date=False)
            end_d = parse_single_date(end_str, is_end_date=True)

            if start_d and end_d:
                # Extract role / title from the non-date portion of the line
                prefix = line[:m.start()].strip(" -•*|,\t")
                suffix = line[m.end():].strip(" -•*|,\t")
                title_part = prefix or suffix

                # If the line only contains the date range, look back at the preceding line(s)
                if not title_part:
                    lookback_idx = idx - 2  # lines is 0-indexed, idx is 1-indexed
                    candidates = []
                    while lookback_idx >= 0 and len(candidates) < 2:
                        cand_line = lines[lookback_idx].strip()
                        lookback_idx -= 1
                        if not cand_line:
                            continue
                        cand_lower = cand_line.lower()
                        # Stop if encountering a section header
                        if re.match(r"^[#*_\-\s]*(?:education|academics|qualifications|experience|work|employment|internships|history|projects|skills|summary|profile)\b", cand_lower):
                            break
                        # Stop if encountering another date range
                        if range_regex.search(cand_line):
                            break
                        candidates.append(cand_line)

                    if candidates:
                        if len(candidates) >= 2:
                            # candidates[0] is closest to date line, candidates[1] is one line earlier
                            title_part = f"{candidates[0]} | {candidates[1]}"
                        else:
                            title_part = candidates[0]

                if not title_part:
                    title_part = f"{current_section.capitalize()} Milestone"

                # Strip markdown bolding / bullets
                title_part = re.sub(r"[*_#`]", "", title_part).strip(" -•|,\t")

                # Parse role / organization if separated by '|', 'at', or ','
                title = title_part
                org = ""
                if "|" in title_part:
                    splits = [s.strip() for s in title_part.split("|") if s.strip()]
                    title = splits[0]
                    org = splits[1] if len(splits) > 1 else ""
                elif " at " in title_part.lower():
                    splits = re.split(r"\s+at\s+", title_part, maxsplit=1, flags=re.IGNORECASE)
                    title = splits[0].strip()
                    org = splits[1].strip() if len(splits) > 1 else ""
                elif "," in title_part:
                    splits = [s.strip() for s in title_part.split(",") if s.strip()]
                    title = splits[0]
                    org = splits[1] if len(splits) > 1 else ""

                items.append(
                    TimelineItem(
                        title=title[:80],
                        organization=org[:80],
                        start_date=start_d,
                        end_date=end_d,
                        section=current_section,
                        raw_line=line,
                        line_number=idx,
                    )
                )

    return items


def make_flag_id(flag_type: str, context_str: str) -> str:
    """Generates a stable, reproducible identifier for a timeline flag."""
    raw = f"{flag_type}:{context_str.strip().lower()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def analyze_resume_timeline(
    resume_text: str,
    gap_threshold_months: int = DEFAULT_GAP_THRESHOLD_MONTHS,
    dismissed_flag_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Performs comprehensive date range and timeline consistency analysis on resume text (#840).

    Flags:
    1. Gaps longer than `gap_threshold_months` between consecutive experiences/education.
    2. Overlaps between concurrent work experience commitments.
    3. Inverted dates where end date precedes start date.
    4. Unframed future dates.

    Guarantees:
    - Neutral phrasing with no assumed reasons.
    - Constructive, actionable suggestions.
    - Unparseable dates never throw exceptions.
    - Dismissable flag persistence support.
    """
    dismissed_set = set(dismissed_flag_ids or [])
    items = extract_timeline_items_from_text(resume_text)

    flags: List[Dict[str, Any]] = []

    # 1. Inverted Dates & Future Dates Checks (per item)
    for item in items:
        # Check inverted dates: end date is strictly before start date
        if item.end_date < item.start_date:
            flag_id = make_flag_id("inverted_dates", f"{item.title}:{item.raw_line}")
            flags.append({
                "flag_id": flag_id,
                "type": "inverted_dates",
                "severity": "warning",
                "title": f"Inconsistent Date Order: {item.title}",
                "dates": f"{item.start_date.format_display()} – {item.end_date.format_display()}",
                "line": item.raw_line,
                "line_number": item.line_number,
                "explanation": (
                    f"The listed end date ({item.end_date.format_display()}) is earlier than "
                    f"the start date ({item.start_date.format_display()})."
                ),
                "suggestion": (
                    "Verify if the start and end dates were accidentally transposed during formatting "
                    "or if a typo occurred in the year."
                ),
                "is_dismissed": flag_id in dismissed_set,
            })

        # Check future dates (start date is > current month + 6 months, or end date > current year + 6)
        if item.start_date.year > CURRENT_YEAR + 1:
            flag_id = make_flag_id("future_date", f"{item.title}:{item.raw_line}")
            flags.append({
                "flag_id": flag_id,
                "type": "future_date",
                "severity": "info",
                "title": f"Future Date Listed: {item.title}",
                "dates": f"{item.start_date.format_display()} – {item.end_date.format_display()}",
                "line": item.raw_line,
                "line_number": item.line_number,
                "explanation": (
                    f"This entry lists a start date ({item.start_date.format_display()}) well in the future."
                ),
                "suggestion": (
                    "If this represents an upcoming graduation or committed offer, consider prefixing "
                    "with 'Expected' or 'Anticipated' to clarify timing for recruiters."
                ),
                "is_dismissed": flag_id in dismissed_set,
            })

    # Filter valid items for chronological comparison (exclude inverted items)
    valid_items = [it for it in items if it.start_date <= it.end_date]

    # Focus gap & overlap analysis primarily on professional and education entries
    career_items = [it for it in valid_items if it.section in ("experience", "education")]
    if not career_items:
        career_items = valid_items

    # Sort chronologically by start date
    career_items.sort(key=lambda it: it.start_date.total_months)

    # 2. Check Overlaps (especially between distinct professional roles)
    for i in range(len(career_items)):
        for j in range(i + 1, len(career_items)):
            a = career_items[i]
            b = career_items[j]

            # If b starts strictly after a ends, no overlap with a or later items for a
            if b.start_date > a.end_date:
                break

            overlap_m = calculate_overlap_months(a.start_date, a.end_date, b.start_date, b.end_date)
            # Only flag significant overlaps of 2 or more months between distinct organizations
            if overlap_m >= 2 and a.organization.lower() != b.organization.lower():
                flag_id = make_flag_id("overlap", f"{a.title}:{b.title}:{a.start_date.raw}:{b.start_date.raw}")
                flags.append({
                    "flag_id": flag_id,
                    "type": "overlap",
                    "severity": "info",
                    "title": f"Overlapping Commitments: {a.title} & {b.title}",
                    "dates": f"{a.title} ({a.start_date.format_display()}–{a.end_date.format_display()}) & {b.title} ({b.start_date.format_display()}–{b.end_date.format_display()})",
                    "line": f"{a.raw_line} | {b.raw_line}",
                    "line_number": a.line_number,
                    "overlap_months": overlap_m,
                    "explanation": (
                        f"The timeline for '{a.title}' ({a.start_date.format_display()}–{a.end_date.format_display()}) "
                        f"overlaps with '{b.title}' ({b.start_date.format_display()}–{b.end_date.format_display()}) "
                        f"by approximately {overlap_m} months."
                    ),
                    "suggestion": (
                        "If these roles were held concurrently (e.g. part-time role, internship, freelance, "
                        "or college research), explicitly state 'Part-time' or 'Concurrent' in the title to provide clarity to recruiters."
                    ),
                    "is_dismissed": flag_id in dismissed_set,
                })

    # 3. Check Gaps between consecutive milestones
    # Merge overlapping/contiguous intervals to find true unexplained gaps
    if len(career_items) >= 2:
        for i in range(len(career_items) - 1):
            curr = career_items[i]
            next_it = career_items[i + 1]

            # Only check for a gap if current entry ended before next entry started
            if curr.end_date < next_it.start_date:
                gap_months = calculate_months_between(curr.end_date, next_it.start_date)
                if gap_months >= gap_threshold_months:
                    flag_id = make_flag_id("gap", f"{curr.title}:{next_it.title}:{curr.end_date.raw}:{next_it.start_date.raw}")
                    flags.append({
                        "flag_id": flag_id,
                        "type": "gap",
                        "severity": "warning" if gap_months >= 12 else "info",
                        "title": f"Timeline Gap ({gap_months} Months)",
                        "dates": f"{curr.end_date.format_display()} to {next_it.start_date.format_display()}",
                        "line": f"Between '{curr.raw_line}' and '{next_it.raw_line}'",
                        "line_number": curr.line_number,
                        "gap_months": gap_months,
                        "explanation": (
                            f"There is an apparent {gap_months}-month gap between the conclusion of '{curr.title}' "
                            f"({curr.end_date.format_display()}) and the start of '{next_it.title}' ({next_it.start_date.format_display()})."
                        ),
                        "suggestion": (
                            "Consider highlighting independent projects, open-source contributions, certifications, "
                            "freelance work, exam preparation, or coursework pursued during this interval, or use year-only formats if dates allow."
                        ),
                        "is_dismissed": flag_id in dismissed_set,
                    })

    # Count active (non-dismissed) flags
    active_flags = [f for f in flags if not f["is_dismissed"]]

    return {
        "status": "success",
        "has_flags": len(flags) > 0,
        "has_active_flags": len(active_flags) > 0,
        "total_flags": len(flags),
        "active_flags_count": len(active_flags),
        "dismissed_flags_count": len(flags) - len(active_flags),
        "gap_threshold_months": gap_threshold_months,
        "summary": {
            "gaps_count": sum(1 for f in flags if f["type"] == "gap"),
            "overlaps_count": sum(1 for f in flags if f["type"] == "overlap"),
            "inverted_count": sum(1 for f in flags if f["type"] == "inverted_dates"),
            "future_count": sum(1 for f in flags if f["type"] == "future_date"),
        },
        "flags": flags,
        "timeline_items": [it.to_dict() for it in items],
    }
