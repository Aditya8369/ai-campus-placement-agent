"""
Calendar Timezone Handling Service (#261).
Provides:
- Timezone detection, configuration, and persistence per student.
- Cross-platform timezone resolution using dateutil.tz / zoneinfo with UTC fallback.
- Conversion between local wall-clock event datetimes and UTC storage representations.
- Offset and daylight saving time (DST) calculations.
- Fallback strategies to UTC or client timezone settings.
- IANA timezone validation and curated list of common world timezones.
- Timezone-aware date/time formatting for student UI and calendar displays.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, List, Optional
from dateutil import tz as dtz

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

DEFAULT_FALLBACK_TIMEZONE = "UTC"

COMMON_TIMEZONES = [
    {"tz_id": "UTC", "label": "UTC (Coordinated Universal Time)", "offset": "+00:00"},
    {"tz_id": "Asia/Kolkata", "label": "India Standard Time (IST) - Asia/Kolkata", "offset": "+05:30"},
    {"tz_id": "America/New_York", "label": "Eastern Time (US & Canada) - New York", "offset": "-05:00"},
    {"tz_id": "America/Chicago", "label": "Central Time (US & Canada) - Chicago", "offset": "-06:00"},
    {"tz_id": "America/Denver", "label": "Mountain Time (US & Canada) - Denver", "offset": "-07:00"},
    {"tz_id": "America/Los_Angeles", "label": "Pacific Time (US & Canada) - Los Angeles", "offset": "-08:00"},
    {"tz_id": "Europe/London", "label": "Greenwich Mean Time / British Summer Time - London", "offset": "+00:00"},
    {"tz_id": "Europe/Berlin", "label": "Central European Time - Berlin, Paris", "offset": "+01:00"},
    {"tz_id": "Asia/Singapore", "label": "Singapore Time (SGT) - Singapore", "offset": "+08:00"},
    {"tz_id": "Asia/Tokyo", "label": "Japan Standard Time (JST) - Tokyo", "offset": "+09:00"},
    {"tz_id": "Australia/Sydney", "label": "Australian Eastern Time - Sydney", "offset": "+10:00"},
    {"tz_id": "Asia/Dubai", "label": "Gulf Standard Time (GST) - Dubai", "offset": "+04:00"},
]


def init_timezone_table() -> None:
    """Initialize table storing student timezone preferences."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS student_timezone_settings (
                user_id TEXT PRIMARY KEY,
                timezone_id TEXT NOT NULL DEFAULT 'UTC',
                auto_detect BOOLEAN NOT NULL DEFAULT 1,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_tz_object(tz_id: str) -> dt.tzinfo:
    """Get timezone object via dateutil.tz with fallback to UTC."""
    if not tz_id or tz_id.upper() in {"UTC", "GMT", "ETC/UTC"}:
        return dtz.UTC

    tz_obj = dtz.gettz(tz_id.strip())
    if tz_obj is None:
        raise ValueError(f"Unknown timezone identifier: {tz_id}")
    return tz_obj


def is_valid_timezone(tz_id: str) -> bool:
    """Validate whether tz_id is a recognized IANA timezone identifier."""
    if not tz_id or not isinstance(tz_id, str):
        return False
    clean = tz_id.strip()
    if clean.upper() in {"UTC", "GMT", "ETC/UTC"}:
        return True
    try:
        return dtz.gettz(clean) is not None
    except Exception:
        return False


def get_student_timezone(user_id: Any) -> str:
    """
    Retrieve configured timezone for a given student.
    Returns 'UTC' if unconfigured or invalid.
    """
    init_timezone_table()
    user_str = str(user_id)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT timezone_id FROM student_timezone_settings WHERE user_id = ?",
            (user_str,),
        )
        row = cursor.fetchone()
        if row and row["timezone_id"] and is_valid_timezone(row["timezone_id"]):
            return row["timezone_id"]
        return DEFAULT_FALLBACK_TIMEZONE
    finally:
        conn.close()


def set_student_timezone(
    user_id: Any,
    timezone_id: str,
    auto_detect: bool = False,
) -> Dict[str, Any]:
    """
    Persist student timezone setting. Validates timezone against standard timezones.
    """
    init_timezone_table()
    user_str = str(user_id)
    tz_clean = timezone_id.strip() if timezone_id else DEFAULT_FALLBACK_TIMEZONE

    if not is_valid_timezone(tz_clean):
        raise ValueError(f"Invalid IANA timezone identifier: {timezone_id}")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO student_timezone_settings (user_id, timezone_id, auto_detect, last_updated)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                timezone_id = excluded.timezone_id,
                auto_detect = excluded.auto_detect,
                last_updated = CURRENT_TIMESTAMP
            """,
            (user_str, tz_clean, 1 if auto_detect else 0),
        )
        conn.commit()
    finally:
        conn.close()

    return get_student_timezone_info(user_str)


def get_student_timezone_info(user_id: Any) -> Dict[str, Any]:
    """
    Get enriched timezone metadata including current offset, abbreviation, and DST status.
    """
    tz_id = get_student_timezone(user_id)
    tz_obj = get_tz_object(tz_id)

    now_local = dt.datetime.now(tz_obj)
    offset = now_local.utcoffset()
    total_seconds = int(offset.total_seconds()) if offset else 0
    sign = "+" if total_seconds >= 0 else "-"
    abs_seconds = abs(total_seconds)
    hours = abs_seconds // 3600
    minutes = (abs_seconds % 3600) // 60
    formatted_offset = f"{sign}{hours:02d}:{minutes:02d}"

    dst_delta = now_local.dst()
    is_dst = bool(dst_delta and dst_delta.total_seconds() != 0)

    tz_name = now_local.tzname() or tz_id

    return {
        "user_id": str(user_id),
        "timezone_id": tz_id,
        "offset": formatted_offset,
        "offset_minutes": total_seconds // 60,
        "abbreviation": tz_name,
        "is_dst": is_dst,
        "current_local_time": now_local.strftime("%Y-%m-%d %H:%M:%S"),
        "available_timezones": COMMON_TIMEZONES,
    }


def convert_local_to_utc(
    date_str: str,
    time_str: str,
    timezone_id: str,
) -> Dict[str, str]:
    """
    Convert a student local date ("YYYY-MM-DD") and time ("HH:MM") in timezone_id
    into UTC datetime string ("YYYY-MM-DDTHH:MM:SSZ").
    """
    if not is_valid_timezone(timezone_id):
        timezone_id = DEFAULT_FALLBACK_TIMEZONE

    tz_obj = get_tz_object(timezone_id)
    
    clean_time = time_str.strip() if time_str else "00:00"
    if len(clean_time) == 5:
        clean_time += ":00"

    full_dt_str = f"{date_str.strip()} {clean_time}"
    naive_dt = dt.datetime.strptime(full_dt_str, "%Y-%m-%d %H:%M:%S")
    local_dt = naive_dt.replace(tzinfo=tz_obj)
    utc_dt = local_dt.astimezone(dtz.UTC)

    return {
        "utc_iso": utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "utc_date": utc_dt.strftime("%Y-%m-%d"),
        "utc_time": utc_dt.strftime("%H:%M:%S"),
    }


def convert_utc_to_local(
    utc_iso_or_datetime: str,
    target_timezone_id: str,
) -> Dict[str, str]:
    """
    Convert UTC timestamp to local target timezone representation.
    """
    if not is_valid_timezone(target_timezone_id):
        target_timezone_id = DEFAULT_FALLBACK_TIMEZONE

    target_tz = get_tz_object(target_timezone_id)
    clean_str = utc_iso_or_datetime.strip().rstrip("Z")
    
    if "T" in clean_str:
        naive_dt = dt.datetime.fromisoformat(clean_str)
    else:
        naive_dt = dt.datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")

    utc_dt = naive_dt.replace(tzinfo=dtz.UTC)
    local_dt = utc_dt.astimezone(target_tz)
    tz_name = local_dt.tzname() or target_timezone_id

    return {
        "local_date": local_dt.strftime("%Y-%m-%d"),
        "local_time": local_dt.strftime("%H:%M"),
        "local_datetime_str": local_dt.strftime("%Y-%m-%d %I:%M %p"),
        "timezone": target_timezone_id,
        "abbreviation": tz_name,
    }


def format_event_for_student(
    event: Dict[str, Any],
    student_timezone_id: str,
) -> Dict[str, Any]:
    """
    Enrich raw calendar event dictionary with timezone-aware localized date, time, and label.
    """
    event_out = dict(event)
    orig_date = event.get("event_date", "")
    orig_time = event.get("event_time", "00:00")
    
    try:
        conv = convert_local_to_utc(orig_date, orig_time, student_timezone_id)
        local_repr = convert_utc_to_local(conv["utc_iso"], student_timezone_id)
        event_out["display_date"] = local_repr["local_date"]
        event_out["display_time"] = local_repr["local_time"]
        event_out["display_datetime"] = local_repr["local_datetime_str"]
        event_out["display_timezone"] = local_repr["timezone"]
        event_out["tz_abbreviation"] = local_repr["abbreviation"]
    except Exception as e:
        logger.warning(f"Could not localize calendar event: {e}")
        event_out["display_date"] = orig_date
        event_out["display_time"] = orig_time
        event_out["display_datetime"] = f"{orig_date} {orig_time}"
        event_out["display_timezone"] = student_timezone_id
        event_out["tz_abbreviation"] = "UTC"

    return event_out
