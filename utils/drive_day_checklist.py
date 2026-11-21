"""
Drive Day Practical Readiness Checklist Service (utils/drive_day_checklist.py)
=============================================================================
Manages practical checklists for on-campus and virtual placement drive days (#651).
Groups items into:
- Documents & IDs (resumes, ID cards, academic records, photos)
- Technical Setup (battery, internet backup, audio/video test, IDEs)
- Logistics & Venue (reporting time, commute buffer, dress code, company portal)
- Mindset & Final Strategy (sleep, self-intro rehearsal, company research, poise)

Provides offline and online presets, per-user and per-application checklist persistence,
progress calculation ("7 of 12 ready"), and 48-hour drive day reminders.
"""

import copy
import datetime
import json
import logging
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Tuple

import config

logger = logging.getLogger(__name__)

CATEGORIES = ["documents", "technical_setup", "logistics", "mindset"]

CATEGORY_METADATA = {
    "documents": {
        "key": "documents",
        "title": "Documents & Credentials",
        "icon": "fa-id-card text-primary",
        "badge_class": "bg-primary-subtle text-primary border-primary-subtle",
        "description": "Physical and digital paperwork, certificates, photo IDs, and portfolio copies.",
    },
    "technical_setup": {
        "key": "technical_setup",
        "title": "Technical & Hardware Setup",
        "icon": "fa-laptop-code text-info",
        "badge_class": "bg-info-subtle text-info border-info-subtle",
        "description": "Power backup, internet redundancy, audio/video checks, and testing platforms.",
    },
    "logistics": {
        "key": "logistics",
        "title": "Logistics & Venue",
        "icon": "fa-route text-danger",
        "badge_class": "bg-danger-subtle text-danger border-danger-subtle",
        "description": "Commute buffer, venue reporting time, formal dress code, and portal profile.",
    },
    "mindset": {
        "key": "mindset",
        "title": "Mindset & Strategy",
        "icon": "fa-brain text-success",
        "badge_class": "bg-success-subtle text-success border-success-subtle",
        "description": "Restful sleep, self-introduction, company insights, and composure.",
    },
}

DEFAULT_OFFLINE_CHECKLIST: Dict[str, List[Dict[str, Any]]] = {
    "documents": [
        {
            "id": "off_doc_1",
            "text": "3-5 printed copies of updated resume in a clean professional folder",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "off_doc_2",
            "text": "College ID card and Government Photo ID (Aadhar / Passport / PAN / Driving License)",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "off_doc_3",
            "text": "Originals & photocopies of 10th, 12th, and college semester mark sheets / transcripts",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "off_doc_4",
            "text": "Recent passport-size photographs (at least 4 copies)",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "off_doc_5",
            "text": "Stationery kit (2 black/blue ballpoint pens, pencil, eraser, and notepad for rough work)",
            "completed": False,
            "is_custom": False,
        },
    ],
    "technical_setup": [
        {
            "id": "off_tech_1",
            "text": "Laptop fully charged (100%) and charger / extension cord packed",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "off_tech_2",
            "text": "Mobile hotspot configured & tested on phone with a full battery and power bank",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "off_tech_3",
            "text": "Offline copies of resume, GitHub portfolio, and project presentations stored on USB drive",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "off_tech_4",
            "text": "Required test software, compilers, and IDEs pre-installed and tested offline",
            "completed": False,
            "is_custom": False,
        },
    ],
    "logistics": [
        {
            "id": "off_log_1",
            "text": "Venue location confirmed (block, hall, room number) and route mapped with 30-min buffer",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "off_log_2",
            "text": "Reporting time verified with placement cell schedule and alarm set with travel buffer",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "off_log_3",
            "text": "Formal interview dress code ironed, neat formal shoes polished, and hair groomed",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "off_log_4",
            "text": "Company placement registration portal profile completed and admit card / hall ticket printed",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "off_log_5",
            "text": "Water bottle, light energy snacks, and handkerchief / hand sanitizer packed",
            "completed": False,
            "is_custom": False,
        },
    ],
    "mindset": [
        {
            "id": "off_mind_1",
            "text": "7+ hours of quality sleep the night before the drive (no late-night cramming)",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "off_mind_2",
            "text": "Target company overview, mission, core products, and recent tech news reviewed",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "off_mind_3",
            "text": "Elevator pitch & 60-second self-introduction rehearsed out loud",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "off_mind_4",
            "text": "Top 3 technical projects and STAR behavioral stories refreshed",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "off_mind_5",
            "text": "2-3 insightful questions prepared to ask the interview panel at the end",
            "completed": False,
            "is_custom": False,
        },
    ],
}

DEFAULT_ONLINE_CHECKLIST: Dict[str, List[Dict[str, Any]]] = {
    "documents": [
        {
            "id": "on_doc_1",
            "text": "Digital PDF of updated resume ready on desktop for immediate screen share or upload",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "on_doc_2",
            "text": "Scanned PDF copies of College ID, Govt ID, and academic mark sheets in an easily accessible folder",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "on_doc_3",
            "text": "Digital passport photo and transparent signature image files ready for portal verification",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "on_doc_4",
            "text": "Notepad and working pen next to laptop for rough work during coding / math rounds",
            "completed": False,
            "is_custom": False,
        },
    ],
    "technical_setup": [
        {
            "id": "on_tech_1",
            "text": "Laptop plugged into charger with uninterrupted power source / power bank ready",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "on_tech_2",
            "text": "High-speed stable internet tested with mobile hotspot standing by as secondary failover",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "on_tech_3",
            "text": "Webcam, internal microphone, and wired headphones / headset tested for audio clarity",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "on_tech_4",
            "text": "Interview platform (Zoom, Teams, Google Meet, HackerRank) installed, updated, and permissions granted",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "on_tech_5",
            "text": "All unnecessary browser tabs, background apps, notifications, and gaming/torrent software closed",
            "completed": False,
            "is_custom": False,
        },
    ],
    "logistics": [
        {
            "id": "on_log_1",
            "text": "Quiet, private, well-lit room selected with light source facing you (not behind you)",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "on_log_2",
            "text": "Clean, distraction-free desk and professional background (or neutral virtual background)",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "on_log_3",
            "text": "Interview meeting link and meeting ID / passcode checked and saved 30 minutes in advance",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "on_log_4",
            "text": "Formal dress code worn (full formal attire, not just upper half) to maintain confident posture",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "on_log_5",
            "text": "Glass of water and notepad placed within arm's reach",
            "completed": False,
            "is_custom": False,
        },
    ],
    "mindset": [
        {
            "id": "on_mind_1",
            "text": "7+ hours of quality sleep the night before the drive",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "on_mind_2",
            "text": "Company overview, key tech stack, and job description requirements reviewed",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "on_mind_3",
            "text": "Elevator pitch & self-introduction practiced looking directly into the webcam",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "on_mind_4",
            "text": "STAR method answers and live coding think-aloud practice refreshed",
            "completed": False,
            "is_custom": False,
        },
        {
            "id": "on_mind_5",
            "text": "Positive breathing exercises done 10 minutes before joining the interview lobby",
            "completed": False,
            "is_custom": False,
        },
    ],
}


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Provides thread-safe connection to the SQLite database."""
    target_path = db_path or getattr(config, "DATABASE_PATH", "campus_agent.db")
    conn = sqlite3.connect(target_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_drive_day_checklist_table(conn: Optional[sqlite3.Connection] = None) -> None:
    """Ensures the drive_day_checklists table exists."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS drive_day_checklists (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL DEFAULT 'default_student',
                application_id TEXT DEFAULT '',
                drive_mode TEXT NOT NULL DEFAULT 'offline',
                checklist_json TEXT NOT NULL,
                total_items INTEGER NOT NULL DEFAULT 0,
                completed_items INTEGER NOT NULL DEFAULT 0,
                completion_percentage REAL NOT NULL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(student_id, application_id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_drive_day_checklists_student ON drive_day_checklists(student_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_drive_day_checklists_app ON drive_day_checklists(application_id)
        """)
        conn.commit()
    finally:
        if close_conn:
            conn.close()


def get_default_checklist(drive_mode: str = "offline") -> Dict[str, List[Dict[str, Any]]]:
    """Returns a deepcopy of default checklist items for offline or online drive modes."""
    mode = (drive_mode or "offline").strip().lower()
    if mode == "online":
        return copy.deepcopy(DEFAULT_ONLINE_CHECKLIST)
    return copy.deepcopy(DEFAULT_OFFLINE_CHECKLIST)


def calculate_checklist_progress(
    checklist: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, Any]:
    """
    Computes total items, completed count, completion percentage, and category breakdown.
    Example: 7 of 12 ready (58.3%).
    """
    total = 0
    completed = 0
    category_stats = {}

    for cat in CATEGORIES:
        items = checklist.get(cat, [])
        cat_total = len(items)
        cat_completed = sum(1 for it in items if bool(it.get("completed")))
        cat_pct = round((cat_completed / cat_total * 100), 1) if cat_total > 0 else 0.0

        category_stats[cat] = {
            "total": cat_total,
            "completed": cat_completed,
            "percentage": cat_pct,
            "ready_label": f"{cat_completed} of {cat_total} ready",
            "meta": CATEGORY_METADATA.get(cat, {}),
        }
        total += cat_total
        completed += cat_completed

    percentage = round((completed / total * 100), 1) if total > 0 else 0.0
    ready_label = f"{completed} of {total} ready"

    return {
        "total_items": total,
        "completed_items": completed,
        "completion_percentage": percentage,
        "progress_label": ready_label,
        "category_stats": category_stats,
        "all_completed": completed == total and total > 0,
    }


def get_drive_day_checklist(
    student_id: str,
    application_id: Optional[str] = None,
    drive_mode: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Retrieves or initializes the student's drive day checklist for a given application or standalone.
    """
    init_drive_day_checklist_table()
    effective_student_id = (student_id or "default_student").strip()
    clean_app_id = (application_id or "").strip()

    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM drive_day_checklists
            WHERE student_id = ? AND application_id = ?
            """,
            (effective_student_id, clean_app_id),
        )
        row = cursor.fetchone()

        if row:
            try:
                checklist_data = json.loads(row["checklist_json"])
            except Exception:
                checklist_data = get_default_checklist(row["drive_mode"])

            # Ensure all standard categories exist
            for cat in CATEGORIES:
                if cat not in checklist_data:
                    checklist_data[cat] = []

            mode = drive_mode or row["drive_mode"]
            progress = calculate_checklist_progress(checklist_data)

            return {
                "id": row["id"],
                "student_id": effective_student_id,
                "application_id": clean_app_id,
                "drive_mode": row["drive_mode"],
                "checklist": checklist_data,
                "total_items": progress["total_items"],
                "completed_items": progress["completed_items"],
                "completion_percentage": progress["completion_percentage"],
                "progress_label": progress["progress_label"],
                "category_stats": progress["category_stats"],
                "all_completed": progress["all_completed"],
                "updated_at": row["updated_at"],
            }
        else:
            # Initialize new checklist with defaults
            mode = (drive_mode or "offline").strip().lower()
            default_items = get_default_checklist(mode)
            progress = calculate_checklist_progress(default_items)
            rec_id = f"chk_{uuid.uuid4().hex[:12]}"

            cursor.execute(
                """
                INSERT INTO drive_day_checklists (
                    id, student_id, application_id, drive_mode,
                    checklist_json, total_items, completed_items,
                    completion_percentage, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    rec_id,
                    effective_student_id,
                    clean_app_id,
                    mode,
                    json.dumps(default_items),
                    progress["total_items"],
                    progress["completed_items"],
                    progress["completion_percentage"],
                ),
            )
            conn.commit()

            return {
                "id": rec_id,
                "student_id": effective_student_id,
                "application_id": clean_app_id,
                "drive_mode": mode,
                "checklist": default_items,
                "total_items": progress["total_items"],
                "completed_items": progress["completed_items"],
                "completion_percentage": progress["completion_percentage"],
                "progress_label": progress["progress_label"],
                "category_stats": progress["category_stats"],
                "all_completed": progress["all_completed"],
                "updated_at": datetime.datetime.now().isoformat(),
            }
    finally:
        conn.close()


def save_drive_day_checklist(
    student_id: str,
    application_id: Optional[str],
    drive_mode: str,
    checklist: Dict[str, List[Dict[str, Any]]],
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Persists updated checklist items, recalculates progress counters, and returns updated record."""
    init_drive_day_checklist_table()
    effective_student_id = (student_id or "default_student").strip()
    clean_app_id = (application_id or "").strip()
    mode = (drive_mode or "offline").strip().lower()

    # Ensure all categories are present
    for cat in CATEGORIES:
        if cat not in checklist:
            checklist[cat] = []

    progress = calculate_checklist_progress(checklist)
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id FROM drive_day_checklists
            WHERE student_id = ? AND application_id = ?
            """,
            (effective_student_id, clean_app_id),
        )
        existing = cursor.fetchone()

        if existing:
            rec_id = existing["id"]
            cursor.execute(
                """
                UPDATE drive_day_checklists
                SET drive_mode = ?,
                    checklist_json = ?,
                    total_items = ?,
                    completed_items = ?,
                    completion_percentage = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    mode,
                    json.dumps(checklist),
                    progress["total_items"],
                    progress["completed_items"],
                    progress["completion_percentage"],
                    rec_id,
                ),
            )
        else:
            rec_id = f"chk_{uuid.uuid4().hex[:12]}"
            cursor.execute(
                """
                INSERT INTO drive_day_checklists (
                    id, student_id, application_id, drive_mode,
                    checklist_json, total_items, completed_items,
                    completion_percentage, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    rec_id,
                    effective_student_id,
                    clean_app_id,
                    mode,
                    json.dumps(checklist),
                    progress["total_items"],
                    progress["completed_items"],
                    progress["completion_percentage"],
                ),
            )
        conn.commit()

        return {
            "id": rec_id,
            "student_id": effective_student_id,
            "application_id": clean_app_id,
            "drive_mode": mode,
            "checklist": checklist,
            "total_items": progress["total_items"],
            "completed_items": progress["completed_items"],
            "completion_percentage": progress["completion_percentage"],
            "progress_label": progress["progress_label"],
            "category_stats": progress["category_stats"],
            "all_completed": progress["all_completed"],
        }
    finally:
        conn.close()


def toggle_checklist_item(
    student_id: str,
    application_id: Optional[str],
    item_id: str,
    completed: bool,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Toggles an item's completed state and recalculates progress."""
    record = get_drive_day_checklist(student_id, application_id, db_path=db_path)
    checklist = record["checklist"]

    found = False
    for cat in CATEGORIES:
        for it in checklist.get(cat, []):
            if str(it.get("id")) == str(item_id):
                it["completed"] = bool(completed)
                found = True
                break
        if found:
            break

    if not found:
        raise ValueError(f"Checklist item '{item_id}' not found.")

    return save_drive_day_checklist(
        student_id=student_id,
        application_id=application_id,
        drive_mode=record["drive_mode"],
        checklist=checklist,
        db_path=db_path,
    )


def add_checklist_item(
    student_id: str,
    application_id: Optional[str],
    category: str,
    text: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Adds a custom item to a specified category."""
    clean_cat = (category or "").strip().lower()
    if clean_cat not in CATEGORIES:
        clean_cat = "documents"

    clean_text = (text or "").strip()
    if not clean_text:
        raise ValueError("Item text cannot be empty.")

    record = get_drive_day_checklist(student_id, application_id, db_path=db_path)
    checklist = record["checklist"]

    new_id = f"custom_{uuid.uuid4().hex[:8]}"
    new_item = {
        "id": new_id,
        "text": clean_text,
        "completed": False,
        "is_custom": True,
    }

    if clean_cat not in checklist:
        checklist[clean_cat] = []
    checklist[clean_cat].append(new_item)

    return save_drive_day_checklist(
        student_id=student_id,
        application_id=application_id,
        drive_mode=record["drive_mode"],
        checklist=checklist,
        db_path=db_path,
    )


def rename_checklist_item(
    student_id: str,
    application_id: Optional[str],
    item_id: str,
    new_text: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Renames an existing checklist item."""
    clean_text = (new_text or "").strip()
    if not clean_text:
        raise ValueError("Item text cannot be empty.")

    record = get_drive_day_checklist(student_id, application_id, db_path=db_path)
    checklist = record["checklist"]

    found = False
    for cat in CATEGORIES:
        for it in checklist.get(cat, []):
            if str(it.get("id")) == str(item_id):
                it["text"] = clean_text
                found = True
                break
        if found:
            break

    if not found:
        raise ValueError(f"Checklist item '{item_id}' not found.")

    return save_drive_day_checklist(
        student_id=student_id,
        application_id=application_id,
        drive_mode=record["drive_mode"],
        checklist=checklist,
        db_path=db_path,
    )


def delete_checklist_item(
    student_id: str,
    application_id: Optional[str],
    item_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Deletes an item from the checklist and updates progress."""
    record = get_drive_day_checklist(student_id, application_id, db_path=db_path)
    checklist = record["checklist"]

    found = False
    for cat in CATEGORIES:
        orig_len = len(checklist.get(cat, []))
        checklist[cat] = [it for it in checklist.get(cat, []) if str(it.get("id")) != str(item_id)]
        if len(checklist[cat]) < orig_len:
            found = True
            break

    if not found:
        raise ValueError(f"Checklist item '{item_id}' not found.")

    return save_drive_day_checklist(
        student_id=student_id,
        application_id=application_id,
        drive_mode=record["drive_mode"],
        checklist=checklist,
        db_path=db_path,
    )


def reset_drive_day_checklist(
    student_id: str,
    application_id: Optional[str],
    drive_mode: str = "offline",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Resets the checklist back to default items for offline or online mode."""
    mode = (drive_mode or "offline").strip().lower()
    default_items = get_default_checklist(mode)
    return save_drive_day_checklist(
        student_id=student_id,
        application_id=application_id,
        drive_mode=mode,
        checklist=default_items,
        db_path=db_path,
    )


def switch_drive_mode(
    student_id: str,
    application_id: Optional[str],
    new_drive_mode: str,
    reload_defaults: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Switches the drive mode (offline or online), optionally resetting items."""
    mode = (new_drive_mode or "offline").strip().lower()
    if reload_defaults:
        return reset_drive_day_checklist(
            student_id=student_id,
            application_id=application_id,
            drive_mode=mode,
            db_path=db_path,
        )

    record = get_drive_day_checklist(student_id, application_id, db_path=db_path)
    return save_drive_day_checklist(
        student_id=student_id,
        application_id=application_id,
        drive_mode=mode,
        checklist=record["checklist"],
        db_path=db_path,
    )


def parse_date_string(date_val: Any) -> Optional[datetime.datetime]:
    """Helper attempting to parse varied date representations into a naive datetime."""
    if not date_val or not isinstance(date_val, str):
        return None

    clean = date_val.strip()
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.datetime.strptime(clean, fmt)
        except ValueError:
            continue
    return None


def get_dashboard_drive_reminder(
    student_id: str, db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Checks if the student has any tracked application with an upcoming drive or deadline
    within 2 days (48 hours) where the drive day checklist is incomplete (< 100% ready).
    Returns reminder data dictionary or None (#651).
    """
    effective_student_id = (student_id or "default_student").strip()
    now = datetime.datetime.now()
    two_days_later = now + datetime.timedelta(days=2, hours=1)

    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM job_applications
            WHERE student_id = ?
            ORDER BY application_date DESC
            """,
            (effective_student_id,),
        )
        apps = [dict(row) for row in cursor.fetchall()]

        candidates = []
        for app in apps:
            deadline_str = app.get("deadline_date") or app.get("application_date")
            dt = parse_date_string(deadline_str)
            if not dt:
                continue

            # Check if within 2 days (between now and now + 48 hours)
            diff = dt - now
            diff_secs = diff.total_seconds()
            if 0 <= diff_secs <= (2 * 86400):
                chk = get_drive_day_checklist(effective_student_id, application_id=app["id"], db_path=db_path)
                if chk["completion_percentage"] < 100.0:
                    if diff_secs < 86400:
                        hrs = max(1, int(diff_secs // 3600))
                        time_str = f"{hrs} hour{'s' if hrs != 1 else ''}"
                    else:
                        dys = max(1, int(diff_secs // 86400))
                        time_str = f"{dys} day{'s' if dys != 1 else ''}"

                    candidates.append({
                        "application_id": app["id"],
                        "company_name": app.get("company_name", "Target Company"),
                        "role_title": app.get("role_title", "Software Engineer"),
                        "deadline_date": deadline_str,
                        "time_remaining_str": time_str,
                        "seconds_left": diff_secs,
                        "total_items": chk["total_items"],
                        "completed_items": chk["completed_items"],
                        "completion_percentage": chk["completion_percentage"],
                        "progress_label": chk["progress_label"],
                    })

        if not candidates:
            return None

        # Return the earliest upcoming deadline
        candidates.sort(key=lambda c: c["seconds_left"])
        return candidates[0]
    finally:
        conn.close()
