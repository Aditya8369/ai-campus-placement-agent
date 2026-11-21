"""
Personalised Roadmap iCalendar (.ics) Generator (#647)
======================================================
Generates RFC 5545 compliant iCalendar (.ics) files from personalised preparation
roadmaps for seamless import into Google Calendar, Apple Calendar, and Outlook.

Acceptance Criteria:
1. The downloaded file imports correctly into Google Calendar and Apple Calendar.
2. Re-importing the same file does not create duplicate events (via stable deterministic UIDs).
3. Special characters in task titles are escaped correctly according to RFC 5545 §3.3.11.
4. Privacy: Does not include personal student data beyond task titles and links.
5. Unit tests validate the generated iCalendar structure.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple, Union


def escape_ics_text(value: Any) -> str:
    """
    Escapes text according to RFC 5545 §3.3.11:
    - Backslash (\\) -> \\\\
    - Semicolon (;) -> \\;
    - Comma (,) -> \\,
    - Newlines (\\r\\n, \\r, \\n) -> \\n (literal backslash-n)
    """
    if value is None:
        return ""
    text = str(value)
    # Must escape backslash first
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    return text


def fold_ics_line(line: str, max_octets: int = 75) -> str:
    """
    Folds an iCalendar content line according to RFC 5545 §3.1 so that
    no physical line exceeds max_octets (excluding CRLF). Continuation
    lines are prefixed with a single whitespace character (ASCII 32).
    """
    line_bytes = line.encode("utf-8")
    if len(line_bytes) <= max_octets:
        return line

    parts: List[str] = []
    current_limit = max_octets
    remaining = line

    while remaining:
        # Binary search for maximum character slice fitting within current_limit bytes
        low = 1
        high = len(remaining)
        best = 1
        while low <= high:
            mid = (low + high) // 2
            if len(remaining[:mid].encode("utf-8")) <= current_limit:
                best = mid
                low = mid + 1
            else:
                high = mid - 1

        chunk = remaining[:best]
        remaining = remaining[best:]

        if not parts:
            parts.append(chunk)
        else:
            parts.append(f" {chunk}")

        current_limit = max_octets - 1  # 1 octet reserved for the leading space

    return "\r\n".join(parts)


def extract_week_tasks(week_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extracts structured individual tasks from a week curriculum dictionary.
    Categorizes tasks across:
    - topics
    - coding_practice
    - practice_task
    - mini_projects
    - interview_questions
    - revision_tasks
    """
    tasks: List[Dict[str, Any]] = []

    # 1. Topics to Learn
    topics = week_data.get("topics") or []
    if isinstance(topics, list):
        for idx, item in enumerate(topics, 1):
            if isinstance(item, str) and item.strip():
                tasks.append({
                    "title": item.strip(),
                    "category": "Topic to Learn",
                    "type_code": "top",
                    "index": idx,
                })

    # 2. Coding Practice Tasks
    coding = week_data.get("coding_practice") or []
    if isinstance(coding, list):
        for idx, item in enumerate(coding, 1):
            if isinstance(item, str) and item.strip():
                tasks.append({
                    "title": item.strip(),
                    "category": "Coding Practice",
                    "type_code": "code",
                    "index": idx,
                })

    # 3. Weekly Practice Task (Single focused task per week)
    practice_task = week_data.get("practice_task")
    if isinstance(practice_task, str) and practice_task.strip():
        tasks.append({
            "title": practice_task.strip(),
            "category": "Weekly Practice Task",
            "type_code": "task",
            "index": 1,
        })

    # 4. Micro Projects
    projects = week_data.get("mini_projects") or []
    if isinstance(projects, list):
        for idx, item in enumerate(projects, 1):
            if isinstance(item, str) and item.strip():
                tasks.append({
                    "title": item.strip(),
                    "category": "Micro Project",
                    "type_code": "proj",
                    "index": idx,
                })

    # 5. Interview Questions
    questions = week_data.get("interview_questions") or []
    if isinstance(questions, list):
        for idx, item in enumerate(questions, 1):
            if isinstance(item, str) and item.strip():
                tasks.append({
                    "title": item.strip(),
                    "category": "Interview Prep Question",
                    "type_code": "q",
                    "index": idx,
                })

    # 6. Revision Tasks
    revision = week_data.get("revision_tasks") or []
    if isinstance(revision, list):
        for idx, item in enumerate(revision, 1):
            if isinstance(item, str) and item.strip():
                tasks.append({
                    "title": item.strip(),
                    "category": "Revision Task",
                    "type_code": "rev",
                    "index": idx,
                })

    return tasks


def generate_stable_task_uid(
    analysis_id: Optional[str],
    week_number: int,
    task_code: str,
    task_index: int,
    task_title: str,
    domain: str = "ai-campus-placement-agent",
) -> str:
    """
    Generates a deterministic and stable RFC 5545 UID for a roadmap task.
    Re-generating or re-importing the calendar with the same roadmap will produce
    the EXACT same UID, causing Google Calendar and Apple Calendar to UPDATE the event
    instead of creating duplicate events.
    """
    clean_id = (analysis_id or "roadmap").strip().lower()
    clean_id = re.sub(r"[^a-z0-9_-]", "_", clean_id)

    raw_seed = f"{clean_id}:w{week_number}:{task_code}:{task_index}:{task_title}"
    uid_digest = hashlib.sha256(raw_seed.encode("utf-8")).hexdigest()[:16]
    return f"roadmap-{clean_id}-w{week_number}-{task_code}{task_index}-{uid_digest}@{domain}"


def parse_start_date(start_date: Optional[Union[str, dt.date]]) -> dt.date:
    """Parses or defaults start date. Defaults to tomorrow."""
    if isinstance(start_date, dt.date):
        return start_date
    if isinstance(start_date, str) and start_date.strip():
        try:
            return dt.datetime.strptime(start_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            pass
    return dt.date.today() + dt.timedelta(days=1)


def parse_study_time(study_time: Optional[Union[str, dt.time]]) -> dt.time:
    """Parses or defaults daily study time. Defaults to 19:00 (7:00 PM evening)."""
    if isinstance(study_time, dt.time):
        return study_time
    if isinstance(study_time, str) and study_time.strip():
        for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p"):
            try:
                return dt.datetime.strptime(study_time.strip(), fmt).time()
            except ValueError:
                pass
    return dt.time(19, 0, 0)


def generate_roadmap_ics(
    roadmap_data: Union[Dict[str, Any], List[Dict[str, Any]]],
    start_date: Optional[Union[str, dt.date]] = None,
    daily_study_time: Optional[Union[str, dt.time]] = "19:00",
    duration_minutes: int = 60,
    all_day: bool = False,
    analysis_id: Optional[str] = None,
    company_name: Optional[str] = None,
    target_role: Optional[str] = None,
    app_base_url: Optional[str] = None,
) -> str:
    """
    Builds an RFC 5545 compliant iCalendar string (.ics) containing one event per task,
    spread over the weeks defined by the roadmap.

    Arguments:
        roadmap_data: Roadmap dictionary (containing 'plan') or list of week curriculum objects.
        start_date: Initial date of the roadmap (defaults to tomorrow).
        daily_study_time: Time of day for timed study sessions (default: 19:00 / 7:00 PM).
        duration_minutes: Duration of study session in minutes (default: 60).
        all_day: If True, emits all-day events (VALUE=DATE) instead of timed events.
        analysis_id: Optional analysis UUID for generating stable persistent UIDs.
        company_name: Target company name for event summaries and descriptions.
        target_role: Target job title.
        app_base_url: Base application URL for deep-linking directly to the dashboard roadmap.

    Returns:
        RFC 5545 formatted .ics content string with CRLF line endings.
    """
    # 1. Normalize plan weeks
    if isinstance(roadmap_data, dict):
        plan: List[Dict[str, Any]] = roadmap_data.get("plan") or []
        company_name = company_name or roadmap_data.get("company_name")
        target_role = target_role or roadmap_data.get("target_role")
    elif isinstance(roadmap_data, list):
        plan = roadmap_data
    else:
        plan = []

    # 2. Date & Time configurations
    resolved_start_date = parse_start_date(start_date)
    resolved_study_time = parse_study_time(daily_study_time)

    try:
        duration_int = max(15, min(480, int(duration_minutes)))
    except (ValueError, TypeError):
        duration_int = 60

    study_delta = dt.timedelta(minutes=duration_int)
    now_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Calendar display metadata
    calendar_name = f"{company_name} Study Roadmap" if company_name else "Placement Study Roadmap"
    calendar_desc = (
        f"Personalised preparation tasks and daily study schedule for {company_name or 'Campus Placements'}. "
        "Generated by AI Campus Placement Agent."
    )

    content_lines: List[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AI Campus Placement Agent//Roadmap Calendar Export//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_ics_text(calendar_name)}",
        f"X-WR-CALDESC:{escape_ics_text(calendar_desc)}",
    ]

    total_events = 0

    # 3. Iterate through weeks and spread tasks
    for week_idx, week_info in enumerate(plan):
        week_num = week_info.get("week_number") or (week_idx + 1)
        week_name = week_info.get("week") or f"Week {week_num}"
        week_skills = week_info.get("skills") or []
        week_skills_str = ", ".join(week_skills) if week_skills else ""

        # Calculate base date for this week (7 days per week)
        week_base_date = resolved_start_date + dt.timedelta(days=week_idx * 7)

        # Extract tasks for this week
        tasks = extract_week_tasks(week_info)
        if not tasks:
            # If no detailed subtasks, generate a single event for the week focus
            tasks = [{
                "title": f"Review {week_skills_str or week_name} Curriculum",
                "category": "Weekly Study Plan",
                "type_code": "focus",
                "index": 1,
            }]

        num_tasks = len(tasks)

        for task_idx, task in enumerate(tasks):
            # Spread tasks across days:
            # If <= 7 tasks, spread over distinct days (day 0 to day N-1).
            # If > 7 tasks, wrap around using modulo 7.
            if num_tasks <= 7:
                day_offset = task_idx
                session_time = resolved_study_time
            else:
                day_offset = task_idx % 7
                # Shift time by duration if multiple tasks fall on the same day
                sub_offset = (task_idx // 7) * duration_int
                base_dt = dt.datetime.combine(dt.date.today(), resolved_study_time) + dt.timedelta(minutes=sub_offset)
                session_time = base_dt.time()

            task_date = week_base_date + dt.timedelta(days=day_offset)

            # Generate stable deterministic UID
            uid = generate_stable_task_uid(
                analysis_id=analysis_id,
                week_number=week_num,
                task_code=task["type_code"],
                task_index=task["index"],
                task_title=task["title"],
            )

            # Build Event Summary
            task_title = task["title"]
            summary = f"Study: {task_title}"

            # Build Event Description (Zero personal data, only task and platform links)
            description_lines = [
                f"Curriculum: {week_name}" + (f" ({week_skills_str})" if week_skills_str else ""),
                f"Category: {task['category']}",
                f"Task: {task_title}",
            ]
            if company_name:
                description_lines.append(f"Target Company: {company_name}")
            if target_role:
                description_lines.append(f"Target Role: {target_role}")

            # Platform link
            if analysis_id:
                base = (app_base_url or "").rstrip("/")
                link = f"{base}/dashboard/{analysis_id}#roadmapSection" if base else f"/dashboard/{analysis_id}#roadmapSection"
                description_lines.append(f"Dashboard: {link}")

            description_lines.append("Tip: Mark this task complete on your placement dashboard when finished.")
            description_text = "\n".join(description_lines)

            # Construct VEVENT
            event_lines = [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now_utc}",
                f"SUMMARY:{escape_ics_text(summary)}",
                f"DESCRIPTION:{escape_ics_text(description_text)}",
                "CATEGORIES:Study,Placement Preparation,Roadmap",
                "STATUS:CONFIRMED",
                "SEQUENCE:0",
                "TRANSP:OPAQUE",
            ]

            if all_day:
                dtstart_val = task_date.strftime("%Y%m%d")
                dtend_val = (task_date + dt.timedelta(days=1)).strftime("%Y%m%d")
                event_lines.append(f"DTSTART;VALUE=DATE:{dtstart_val}")
                event_lines.append(f"DTEND;VALUE=DATE:{dtend_val}")
            else:
                start_dt = dt.datetime.combine(task_date, session_time)
                end_dt = start_dt + study_delta
                event_lines.append(f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}")
                event_lines.append(f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}")

            event_lines.append("END:VEVENT")
            content_lines.extend(event_lines)
            total_events += 1

    content_lines.append("END:VCALENDAR")

    # 4. Fold lines per RFC 5545 (<= 75 octets) and join with standard CRLF (\r\n)
    folded_lines = [fold_ics_line(l) for l in content_lines]
    return "\r\n".join(folded_lines) + "\r\n"
