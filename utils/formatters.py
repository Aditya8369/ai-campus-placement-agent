"""
Regional Formatting & Localization Helpers (#650)
=================================================
Provides consistent Indian localization helpers and template filters across the platform:
1. `format_date_ist`: e.g. "21 Nov 2026"
2. `format_datetime_ist`: e.g. "21 Nov 2026, 6:30 PM IST"
3. `format_time_ist`: e.g. "6:30 PM IST"
4. `format_inr`: Indian digit grouping ("12,34,567") and optional LPA / Crore display ("12 LPA", "1.2 Cr")
5. `format_lpa` / `format_crore`: Quick shortcuts for placement packages.

Timestamps in the database remain strictly in UTC. Conversions happen only on display.
Timezone is configurable via DISPLAY_TIMEZONE in config.py (defaults to Asia/Kolkata).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Optional, Tuple, Union

try:
    from dateutil import tz, parser
except ImportError:
    tz = None  # type: ignore
    parser = None  # type: ignore

try:
    import zoneinfo
except ImportError:
    zoneinfo = None  # type: ignore

logger = logging.getLogger(__name__)

# Canonical IST timezone definition (+05:30 with permanent zero DST)
IST_TZ = dt.timezone(dt.timedelta(hours=5, minutes=30), name="IST")


def get_display_timezone(tz_name: Optional[str] = None) -> dt.tzinfo:
    """
    Resolves the configured display timezone with rock-solid fallback to IST (Asia/Kolkata).
    """
    if not tz_name:
        try:
            from flask import current_app
            tz_name = current_app.config.get("DISPLAY_TIMEZONE") or current_app.config.get("TIMEZONE")
        except Exception:
            tz_name = None

    if not tz_name:
        try:
            import config
            tz_name = getattr(config, "DISPLAY_TIMEZONE", getattr(config, "TIMEZONE", "Asia/Kolkata"))
        except Exception:
            tz_name = "Asia/Kolkata"

    tz_clean = (tz_name or "Asia/Kolkata").strip()

    if tz_clean in ("Asia/Kolkata", "Asia/Calcutta", "IST", "Asia/Colombo"):
        return IST_TZ

    if tz_clean.upper() in ("UTC", "GMT", "ETC/UTC"):
        return dt.timezone.utc

    if tz is not None:
        try:
            t = tz.gettz(tz_clean)
            if t is not None:
                return t
        except Exception:
            pass

    if zoneinfo is not None:
        try:
            return zoneinfo.ZoneInfo(tz_clean)
        except Exception:
            pass

    return IST_TZ


def parse_utc_datetime(val: Any) -> Tuple[Optional[dt.datetime], bool]:
    """
    Parses a raw database or model timestamp into a UTC-aware datetime.
    Returns:
        (utc_datetime, has_time_component)
    """
    if val is None or val == "":
        return None, False

    if isinstance(val, dt.datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=dt.timezone.utc), True
        return val.astimezone(dt.timezone.utc), True

    if isinstance(val, dt.date):
        return dt.datetime(val.year, val.month, val.day, tzinfo=dt.timezone.utc), False

    if isinstance(val, (int, float)):
        try:
            return dt.datetime.fromtimestamp(float(val), tz=dt.timezone.utc), True
        except (ValueError, OverflowError, OSError):
            return None, False

    s = str(val).strip()
    if not s:
        return None, False

    # Standard YYYY-MM-DD date-only check
    if len(s) == 10 and s.count("-") == 2:
        try:
            parts = [int(p) for p in s.split("-")]
            return dt.datetime(parts[0], parts[1], parts[2], tzinfo=dt.timezone.utc), False
        except (ValueError, IndexError):
            pass

    # Try dateutil parser if available
    if parser is not None:
        try:
            parsed = parser.parse(s)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=dt.timezone.utc), True
            return parsed.astimezone(dt.timezone.utc), True
        except (ValueError, TypeError, OverflowError):
            pass

    # Fallback to standard ISO / SQL datetime formats
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
    ):
        try:
            d = dt.datetime.strptime(s.rstrip("Z"), fmt)
            return d.replace(tzinfo=dt.timezone.utc), True
        except ValueError:
            continue

    return None, False


def format_date_ist(
    val: Any,
    default: str = "",
    tz_name: Optional[str] = None
) -> str:
    """
    Formats a date or UTC timestamp string into standard Indian format (e.g. "21 Nov 2026").
    """
    if val is None or val == "":
        return default

    dt_utc, has_time = parse_utc_datetime(val)
    if dt_utc is None:
        return str(val) if val else default

    # Date-only values (e.g. 2026-11-21) are already local dates
    if not has_time:
        return dt_utc.strftime("%d %b %Y")

    # Timestamp with time component: convert UTC to display timezone (e.g. IST)
    target_tz = get_display_timezone(tz_name)
    local_dt = dt_utc.astimezone(target_tz)
    return local_dt.strftime("%d %b %Y")


def format_datetime_ist(
    val: Any,
    default: str = "",
    tz_name: Optional[str] = None
) -> str:
    """
    Formats a UTC timestamp string into standard Indian datetime format (e.g. "21 Nov 2026, 6:30 PM IST").
    """
    if val is None or val == "":
        return default

    dt_utc, has_time = parse_utc_datetime(val)
    if dt_utc is None:
        return str(val) if val else default

    target_tz = get_display_timezone(tz_name)
    local_dt = dt_utc.astimezone(target_tz)

    date_str = local_dt.strftime("%d %b %Y")
    if not has_time:
        return date_str

    time_str = local_dt.strftime("%I:%M %p").lstrip("0")
    if not time_str or time_str.startswith(":"):
        time_str = "12" + time_str

    tz_label = local_dt.tzname()
    if not tz_label or tz_label in ("+0530", "+05:30", "Asia/Kolkata", "Asia/Calcutta"):
        tz_label = "IST"

    return f"{date_str}, {time_str} {tz_label}"


def format_time_ist(
    val: Any,
    default: str = "",
    tz_name: Optional[str] = None
) -> str:
    """
    Formats the time component of a UTC timestamp or time string into IST (e.g. "6:30 PM IST").
    """
    if val is None or val == "":
        return default

    # Check if input is a simple HH:MM string (e.g. "18:30" or "06:30")
    val_str = str(val).strip()
    if len(val_str) in (5, 8) and ":" in val_str and "-" not in val_str:
        try:
            parts = [int(p) for p in val_str.split(":")[:2]]
            naive_time = dt.time(parts[0], parts[1])
            temp_dt = dt.datetime.combine(dt.date.today(), naive_time)
            formatted_time = temp_dt.strftime("%I:%M %p").lstrip("0")
            return f"{formatted_time} IST"
        except (ValueError, IndexError):
            pass

    dt_utc, has_time = parse_utc_datetime(val)
    if dt_utc is None or not has_time:
        return default

    target_tz = get_display_timezone(tz_name)
    local_dt = dt_utc.astimezone(target_tz)
    time_str = local_dt.strftime("%I:%M %p").lstrip("0")
    tz_label = local_dt.tzname() or "IST"
    if tz_label in ("+0530", "+05:30", "Asia/Kolkata"):
        tz_label = "IST"

    return f"{time_str} {tz_label}"


def format_indian_number(
    num: Union[int, float, str],
    decimals: Optional[int] = None
) -> str:
    """
    Formats a numeric value using the Indian numbering system digit grouping:
    - Rightmost 3 digits grouped together: e.g. 1,000
    - Remaining digits grouped in pairs of 2: e.g. 1,00,000 (1 Lakh), 12,34,567, 1,00,00,000 (1 Crore)
    """
    if num is None:
        return ""

    if isinstance(num, str):
        cleaned = num.replace("₹", "").replace(",", "").replace("$", "").replace(" ", "").strip()
        if not cleaned:
            return ""
        try:
            num = float(cleaned) if "." in cleaned else int(cleaned)
        except ValueError:
            return str(num)

    is_negative = num < 0
    abs_num = abs(num)

    if decimals is not None:
        formatted_float = f"{abs_num:.{decimals}f}"
        int_part, frac_part = formatted_float.split(".")
    else:
        if isinstance(abs_num, float) and not abs_num.is_integer():
            formatted_float = f"{abs_num:.2f}".rstrip("0").rstrip(".")
            if "." in formatted_float:
                int_part, frac_part = formatted_float.split(".")
            else:
                int_part = formatted_float
                frac_part = ""
        else:
            int_part = str(int(round(abs_num)))
            frac_part = ""

    if len(int_part) <= 3:
        grouped = int_part
    else:
        last_three = int_part[-3:]
        remaining = int_part[:-3]
        groups = []
        while len(remaining) > 2:
            groups.insert(0, remaining[-2:])
            remaining = remaining[:-2]
        if remaining:
            groups.insert(0, remaining)
        grouped = ",".join(groups) + "," + last_three

    result = f"{grouped}.{frac_part}" if frac_part else grouped
    return f"-{result}" if is_negative else result


def format_inr(
    val: Any,
    lpa: bool = False,
    symbol: bool = False,
    cr: bool = False,
    decimals: Optional[int] = None,
    default: str = ""
) -> str:
    """
    Formats monetary salary/package values according to Indian conventions (#650):
    - Default: Indian digit grouping, e.g. "12,34,567" (symbol=True: "₹12,34,567")
    - lpa=True: Optional LPA display, e.g. "12 LPA", "12.5 LPA" (symbol=True: "₹12 LPA")
    - cr=True: Optional Crore display, e.g. "1 Cr", "1.2 Cr" (symbol=True: "₹1 Cr")
    """
    if val is None or val == "":
        return default

    # Clean string representation
    if isinstance(val, str):
        cleaned = val.replace("₹", "").replace(",", "").replace("$", "").replace(" ", "").strip()
        if not cleaned:
            return default
        try:
            num = float(cleaned) if "." in cleaned else int(cleaned)
        except ValueError:
            return str(val)
    elif isinstance(val, (int, float)):
        num = val
    else:
        return str(val)

    is_negative = num < 0
    abs_num = abs(num)
    currency_prefix = "₹" if symbol else ""

    if cr:
        crores = abs_num / 10000000.0 if abs_num >= 1000 else abs_num
        c_str = f"{int(crores)}" if float(crores).is_integer() else f"{crores:.2f}".rstrip("0").rstrip(".")
        res = f"{currency_prefix}{c_str} Cr"
        return f"-{res}" if is_negative else res

    if lpa:
        # If value is >= 1000, convert raw rupees to lakhs (e.g. 1200000 -> 12 LPA)
        # If value is already in lakhs (e.g. 12 or 12.5), format directly
        lakhs = abs_num / 100000.0 if abs_num >= 1000 else abs_num
        l_str = f"{int(lakhs)}" if float(lakhs).is_integer() else f"{lakhs:.2f}".rstrip("0").rstrip(".")
        res = f"{currency_prefix}{l_str} LPA"
        return f"-{res}" if is_negative else res

    grouped_num = format_indian_number(abs_num, decimals=decimals)
    if is_negative:
        return f"-{currency_prefix}{grouped_num}"
    return f"{currency_prefix}{grouped_num}"


def format_lpa(val: Any, symbol: bool = False, default: str = "") -> str:
    """Shortcut helper to display compensation packages in LPA (e.g. '12 LPA' or '₹12 LPA')."""
    return format_inr(val, lpa=True, symbol=symbol, default=default)


def format_crore(val: Any, symbol: bool = False, default: str = "") -> str:
    """Shortcut helper to display high-tier packages in Crores (e.g. '1.2 Cr' or '₹1.2 Cr')."""
    return format_inr(val, cr=True, symbol=symbol, default=default)


def format_inr_words(val: Any, symbol: bool = False, default: str = "") -> str:
    """
    Formats amounts in friendly Indian denominations (Crores, Lakhs, Thousands).
    e.g. 10000000 -> "1 Crore", 1250000 -> "12.5 Lakhs".
    """
    if val is None or val == "":
        return default

    try:
        num = float(str(val).replace("₹", "").replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return str(val)

    is_negative = num < 0
    abs_num = abs(num)
    currency_prefix = "₹" if symbol else ""

    if abs_num >= 10000000:
        cr = abs_num / 10000000.0
        cr_str = f"{int(cr)}" if cr.is_integer() else f"{cr:.2f}".rstrip("0").rstrip(".")
        unit = "Crore" if cr_str == "1" else "Crores"
        res = f"{currency_prefix}{cr_str} {unit}"
    elif abs_num >= 100000:
        lakh = abs_num / 100000.0
        l_str = f"{int(lakh)}" if lakh.is_integer() else f"{lakh:.2f}".rstrip("0").rstrip(".")
        unit = "Lakh" if l_str == "1" else "Lakhs"
        res = f"{currency_prefix}{l_str} {unit}"
    elif abs_num >= 1000:
        th = abs_num / 1000.0
        t_str = f"{int(th)}" if th.is_integer() else f"{th:.2f}".rstrip("0").rstrip(".")
        res = f"{currency_prefix}{t_str} Thousand"
    else:
        res = f"{currency_prefix}{format_indian_number(abs_num)}"

    return f"-{res}" if is_negative else res
