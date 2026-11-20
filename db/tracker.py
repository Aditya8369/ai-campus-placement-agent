"""
Job Application & Progress Tracker Repository (db/tracker.py)
=============================================================
Handles database operations for job applications, status transitions, deadlines (#477),
preparation calendar events, company preparation checklists, recently viewed jobs,
saved job descriptions, and job contacts.
"""

from __future__ import annotations

import csv
import datetime
import io
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from db.connection import get_connection, transaction

logger = logging.getLogger(__name__)


def save_job_application(
    app_id: str,
    student_id: str,
    company_name: str,
    role_title: str,
    status: str = "Applied",
    application_date: Optional[str] = None,
    job_url: Optional[str] = None,
    job_description: Optional[str] = None,
    notes: Optional[str] = None,
    location: str = "Remote",
    job_type: str = "Full-Time",
    experience_level: str = "Entry-Level",
    resume_analysis_id: Optional[str] = None,
    resume_filename: Optional[str] = None,
    resume_version: Optional[int] = None,
    job_description_snapshot: Optional[str] = None,
    deadline_date: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    """
    Saves or updates a candidate job application record (#143, #193, #298, #477).
    Guarantees deadline_date is persisted reliably.
    """
    date_str = application_date or datetime.date.today().isoformat()
    clean_deadline = deadline_date.strip() if deadline_date and isinstance(deadline_date, str) else None

    with transaction(db_path) as cursor:
        cursor.execute(
            """
            INSERT OR REPLACE INTO job_applications (
                id, student_id, company_name, role_title, status, application_date,
                job_url, job_description, notes, location, job_type, experience_level,
                resume_analysis_id, resume_filename, resume_version, job_description_snapshot,
                deadline_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                app_id,
                student_id.strip() if student_id else "default_student",
                company_name.strip(),
                role_title.strip(),
                status.strip(),
                date_str,
                (job_url or "").strip(),
                (job_description or "").strip(),
                (notes or "").strip(),
                (location or "Remote").strip(),
                (job_type or "Full-Time").strip(),
                (experience_level or "Entry-Level").strip(),
                (resume_analysis_id or "").strip() or None,
                (resume_filename or "").strip() or None,
                resume_version,
                (job_description_snapshot or "").strip() or None,
                clean_deadline,
            ),
        )
        logger.info(f"Saved job application {app_id} for student {student_id}")


def get_job_applications(
    student_id: str,
    status_filter: Optional[str] = None,
    search_query: Optional[str] = None,
    location_filter: Optional[str] = None,
    job_type_filter: Optional[str] = None,
    experience_level_filter: Optional[str] = None,
    sort_by: str = "recent",
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves all job application records for a student with optional filters."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            conditions = ["student_id = ?"]
            params: List[Any] = [student_id.strip() if student_id else "default_student"]

            if status_filter and status_filter.strip() and status_filter.strip().lower() not in ("all", "any"):
                conditions.append("LOWER(status) = LOWER(?)")
                params.append(status_filter.strip())

            if search_query and search_query.strip():
                kw = f"%{search_query.strip().lower()}%"
                conditions.append(
                    "(LOWER(company_name) LIKE ? OR LOWER(role_title) LIKE ? OR LOWER(job_description) LIKE ?)"
                )
                params.extend([kw, kw, kw])

            if location_filter and location_filter.strip() and location_filter.strip().lower() not in ("all", "any"):
                conditions.append("LOWER(location) LIKE LOWER(?)")
                params.append(f"%{location_filter.strip()}%")

            if job_type_filter and job_type_filter.strip() and job_type_filter.strip().lower() not in ("all", "any"):
                conditions.append("LOWER(job_type) = LOWER(?)")
                params.append(job_type_filter.strip())

            if (
                experience_level_filter
                and experience_level_filter.strip()
                and experience_level_filter.strip().lower() not in ("all", "any")
            ):
                conditions.append("LOWER(experience_level) = LOWER(?)")
                params.append(experience_level_filter.strip())

            where_clause = f"WHERE {' AND '.join(conditions)}"

            if sort_by == "oldest":
                order_clause = "ORDER BY application_date ASC, created_at ASC"
            elif sort_by == "company":
                order_clause = "ORDER BY company_name ASC"
            else:
                order_clause = "ORDER BY application_date DESC, created_at DESC"

            query = f"SELECT * FROM job_applications {where_clause} {order_clause}"
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Error retrieving job applications for student {student_id}: {e}")
        return []


def delete_job_application(
    app_id: str,
    student_id: str,
    db_path: Optional[str] = None,
) -> bool:
    """Deletes a specific job application record owned by student_id."""
    try:
        with transaction(db_path) as cursor:
            cursor.execute(
                "DELETE FROM job_applications WHERE id = ? AND student_id = ?",
                (app_id, student_id),
            )
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting job application {app_id}: {e}")
        return False


def update_job_application_status(
    app_id: str,
    student_id: str,
    new_status: str,
    db_path: Optional[str] = None,
) -> bool:
    """Updates the pipeline status of a specific job application."""
    try:
        with transaction(db_path) as cursor:
            cursor.execute(
                "UPDATE job_applications SET status = ? WHERE id = ? AND student_id = ?",
                (new_status.strip(), app_id, student_id),
            )
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating job application status for {app_id}: {e}")
        return False


def get_job_application_by_id(
    app_id: str,
    student_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves a single job application record owned by student_id."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM job_applications WHERE id = ? AND student_id = ?",
                (app_id.strip(), student_id.strip() if student_id else "default_student"),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Error retrieving job application {app_id}: {e}")
        return None


def update_job_application(
    app_id: str,
    student_id: str,
    company_name: str,
    role_title: str,
    status: str = "Applied",
    application_date: Optional[str] = None,
    job_url: Optional[str] = None,
    job_description: Optional[str] = None,
    notes: Optional[str] = None,
    location: str = "Remote",
    job_type: str = "Full-Time",
    experience_level: str = "Entry-Level",
    resume_analysis_id: Optional[str] = None,
    resume_filename: Optional[str] = None,
    resume_version: Optional[int] = None,
    job_description_snapshot: Optional[str] = None,
    deadline_date: Optional[str] = None,
    db_path: Optional[str] = None,
) -> bool:
    """Updates an existing job application record with new details, including deadline_date (#477)."""
    try:
        clean_deadline = (
            deadline_date.strip() if deadline_date and isinstance(deadline_date, str) else deadline_date
        )
        with transaction(db_path) as cursor:
            cursor.execute(
                """
                UPDATE job_applications SET
                    company_name = ?,
                    role_title = ?,
                    status = ?,
                    application_date = coalesce(?, application_date),
                    job_url = ?,
                    job_description = ?,
                    notes = ?,
                    location = ?,
                    job_type = ?,
                    experience_level = ?,
                    resume_analysis_id = ?,
                    resume_filename = ?,
                    resume_version = ?,
                    job_description_snapshot = ?,
                    deadline_date = ?
                WHERE id = ? AND student_id = ?
                """,
                (
                    company_name.strip(),
                    role_title.strip(),
                    status.strip(),
                    application_date,
                    (job_url or "").strip(),
                    (job_description or "").strip(),
                    (notes or "").strip(),
                    (location or "Remote").strip(),
                    (job_type or "Full-Time").strip(),
                    (experience_level or "Entry-Level").strip(),
                    (resume_analysis_id or "").strip() or None,
                    (resume_filename or "").strip() or None,
                    resume_version,
                    (job_description_snapshot or "").strip() or None,
                    clean_deadline,
                    app_id.strip(),
                    student_id.strip() if student_id else "default_student",
                ),
            )
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating job application {app_id}: {e}")
        return False


def get_application_stage_counts(
    student_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, int]:
    """Returns pipeline counts for all application stages."""
    counts = {
        "Applied": 0,
        "Assessment": 0,
        "Interview": 0,
        "Selected": 0,
        "Rejected": 0,
        "Total": 0,
    }
    apps = get_job_applications(student_id=student_id, db_path=db_path)
    for a in apps:
        st = (a.get("status") or "Applied").strip()
        if st == "Offered":
            st = "Selected"
        if st in counts:
            counts[st] += 1
        else:
            counts["Applied"] += 1
    counts["Total"] = len(apps)
    return counts


def get_application_funnel_analytics(
    student_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Builds a user-scoped application funnel summary from current application stages."""
    counts = get_application_stage_counts(student_id, db_path=db_path)
    total = counts["Total"]
    interview_count = counts["Interview"] + counts["Selected"]
    offer_count = counts["Selected"]
    reliable = total >= 5

    return {
        "total_applications": total,
        "stage_counts": counts,
        "interview_count": interview_count,
        "offer_count": offer_count,
        "sample_size": total,
        "minimum_sample_size": 5,
        "has_enough_data": reliable,
        "interview_rate": round(interview_count / total * 100, 1) if reliable else None,
        "offer_rate": round(offer_count / total * 100, 1) if reliable else None,
        "calculation_note": (
            "Interview reach counts applications currently at Interview or Selected; "
            "offers are applications currently marked Selected."
        ),
        "reliability_note": (
            "Rates are shown after at least 5 application records; with fewer records, "
            "counts are useful for tracking but too small for a reliable success rate."
        ),
    }


def export_job_applications_csv(
    student_id: str,
    status_filter: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Generates standard RFC-4180 CSV export content for a student's job applications."""
    applications = get_job_applications(student_id=student_id, status_filter=status_filter, db_path=db_path)
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    writer.writerow([
        "Application ID",
        "Company Name",
        "Role Title",
        "Status",
        "Application Date",
        "Job Posting URL",
        "Job Description / Requirements",
        "Interview / Follow-up Notes",
        "Created At",
    ])

    for app_item in applications:
        writer.writerow([
            app_item.get("id", ""),
            app_item.get("company_name", ""),
            app_item.get("role_title", ""),
            app_item.get("status", ""),
            app_item.get("application_date", ""),
            app_item.get("job_url", ""),
            app_item.get("job_description", ""),
            app_item.get("notes", ""),
            app_item.get("created_at", ""),
        ])

    return output.getvalue()


def export_job_applications_json(
    student_id: str,
    status_filter: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Generates structured JSON export payload for a student's job applications."""
    applications = get_job_applications(student_id=student_id, status_filter=status_filter, db_path=db_path)
    status_counts: Dict[str, int] = {}
    for item in applications:
        st = item.get("status", "Unknown")
        status_counts[st] = status_counts.get(st, 0) + 1

    return {
        "export_version": "1.0",
        "student_id": student_id.strip() if student_id else "default_student",
        "total_applications": len(applications),
        "status_distribution": status_counts,
        "applications": applications,
    }


def export_job_applications_markdown(
    student_id: str,
    status_filter: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Generates a readable Markdown summary table of job applications."""
    applications = get_job_applications(student_id=student_id, status_filter=status_filter, db_path=db_path)
    lines = [
        f"# Job Applications Report - Candidate: {student_id}",
        "",
        f"- **Total Applications**: {len(applications)}",
        f"- **Filter Applied**: {status_filter or 'All'}",
        "",
        "| ID | Company | Role | Status | Applied Date | Job Link | Notes |",
        "|---|---|---|---|---|---|---|",
    ]

    for item in applications:
        app_id = item.get("id", "")
        comp = item.get("company_name", "").replace("|", "\\|")
        role = item.get("role_title", "").replace("|", "\\|")
        st = item.get("status", "")
        dt = item.get("application_date", "") or "-"
        url = item.get("job_url", "")
        link_str = f"[Link]({url})" if url else "-"
        notes = (item.get("notes") or "-").replace("\n", " ").replace("|", "\\|")
        lines.append(f"| {app_id} | {comp} | {role} | {st} | {dt} | {link_str} | {notes} |")

    lines.append("")
    return "\n".join(lines)


def get_job_applications_export_summary(
    student_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Provides aggregated analytics metadata for candidate job applications export."""
    applications = get_job_applications(student_id=student_id, db_path=db_path)
    stages = {"Applied": 0, "Assessment": 0, "Interview": 0, "Selected": 0, "Rejected": 0}
    companies = set()
    for item in applications:
        st = item.get("status", "Applied")
        if st in stages:
            stages[st] += 1
        else:
            stages[st] = 1
        comp = item.get("company_name")
        if comp:
            companies.add(comp)

    return {
        "student_id": student_id,
        "total_records": len(applications),
        "unique_companies_count": len(companies),
        "stage_breakdown": stages,
        "ready_for_export": True,
    }


def save_calendar_event(
    event_id: str,
    student_id: str,
    title: str,
    event_type: str,
    event_date: str,
    event_time: Optional[str] = None,
    company_name: Optional[str] = None,
    description: Optional[str] = None,
    priority: str = "Medium",
    completed: bool = False,
    db_path: Optional[str] = None,
) -> str:
    """Creates or updates a candidate placement preparation calendar event."""
    effective_student_id = (student_id or "default_student").strip()
    with transaction(db_path) as cursor:
        cursor.execute(
            """
            INSERT OR REPLACE INTO preparation_calendar_events (
                id, student_id, title, event_type, event_date, event_time,
                company_name, description, priority, completed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                effective_student_id,
                title.strip(),
                event_type.strip().lower(),
                event_date.strip(),
                (event_time or "").strip(),
                (company_name or "").strip(),
                (description or "").strip(),
                priority.strip(),
                1 if completed else 0,
            ),
        )
        logger.info(f"Saved calendar event {event_id} for student {effective_student_id}")
        return event_id


def get_calendar_events(
    student_id: str,
    month: Optional[str] = None,
    event_type: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves all calendar preparation events for a student."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            effective_student_id = (student_id or "default_student").strip()
            conditions = ["student_id = ?"]
            params: List[Any] = [effective_student_id]

            if month and len(month.strip()) == 7:
                conditions.append("event_date LIKE ?")
                params.append(f"{month.strip()}%")

            if event_type and event_type.strip() and event_type.strip().lower() not in ("all", "any"):
                conditions.append("event_type = ?")
                params.append(event_type.strip().lower())

            where_clause = f"WHERE {' AND '.join(conditions)}"
            query = f"SELECT * FROM preparation_calendar_events {where_clause} ORDER BY event_date ASC, event_time ASC"

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Error retrieving calendar events for {student_id}: {e}")
        return []


def update_calendar_event(
    event_id: str,
    student_id: str,
    title: str,
    event_type: str,
    event_date: str,
    event_time: Optional[str] = None,
    company_name: Optional[str] = None,
    description: Optional[str] = None,
    priority: str = "Medium",
    completed: bool = False,
    db_path: Optional[str] = None,
) -> bool:
    """Updates an existing calendar event owned by student_id."""
    try:
        effective_student_id = (student_id or "default_student").strip()
        with transaction(db_path) as cursor:
            cursor.execute(
                """
                UPDATE preparation_calendar_events
                SET title = ?, event_type = ?, event_date = ?, event_time = ?,
                    company_name = ?, description = ?, priority = ?, completed = ?
                WHERE id = ? AND student_id = ?
                """,
                (
                    title.strip(),
                    event_type.strip().lower(),
                    event_date.strip(),
                    (event_time or "").strip(),
                    (company_name or "").strip(),
                    (description or "").strip(),
                    priority.strip(),
                    1 if completed else 0,
                    event_id,
                    effective_student_id,
                ),
            )
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating calendar event {event_id}: {e}")
        return False


def delete_calendar_event(
    event_id: str,
    student_id: str,
    db_path: Optional[str] = None,
) -> bool:
    """Deletes a calendar event owned by student_id."""
    try:
        effective_student_id = (student_id or "default_student").strip()
        with transaction(db_path) as cursor:
            cursor.execute(
                "DELETE FROM preparation_calendar_events WHERE id = ? AND student_id = ?",
                (event_id, effective_student_id),
            )
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting calendar event {event_id}: {e}")
        return False


def get_default_company_checklist(company_name: str) -> Dict[str, Any]:
    """Returns the foundational company checklist tasks structured across rounds."""
    comp = (company_name or "General").strip()

    return {
        "Aptitude & Logical Reasoning": [
            {"id": "apt_01", "task": f"Quantitative Aptitude: Speed, Distance, Work & Time for {comp}", "completed": False},
            {"id": "apt_02", "task": "Data Interpretation & Logical Puzzles (Seating arrangements & Syllogisms)", "completed": False},
            {"id": "apt_03", "task": "Verbal Ability & Reading Comprehension Practice", "completed": False},
        ],
        "Coding & Data Structures": [
            {"id": "code_01", "task": f"Top 20 Most Frequent LeetCode Questions asked at {comp}", "completed": False},
            {"id": "code_02", "task": "Arrays, Strings, HashMaps & Sliding Window problem sets", "completed": False},
            {"id": "code_03", "task": "Trees, Graphs & Dynamic Programming fundamentals", "completed": False},
            {"id": "code_04", "task": f"Timed 60-minute Online Assessment Simulation for {comp}", "completed": False},
        ],
        "Technical Concepts & CS Fundamentals": [
            {"id": "tech_01", "task": "DBMS & SQL: Indexing, Transactions, ACID Properties, Normalization", "completed": False},
            {"id": "tech_02", "task": "Operating Systems: Process vs Thread, Virtual Memory, Concurrency & Deadlocks", "completed": False},
            {"id": "tech_03", "task": "Computer Networks: TCP/IP vs UDP, DNS, HTTP/HTTPS, WebSockets", "completed": False},
            {"id": "tech_04", "task": "Object Oriented Programming (OOP) & Clean System Design principles", "completed": False},
        ],
        "HR, Culture & Behavioral (STAR)": [
            {"id": "hr_01", "task": f"Company Deep Dive: Core values, business model, and leadership principles of {comp}", "completed": False},
            {"id": "hr_02", "task": "Prepare 'Tell Me About Yourself' 90-second elevator pitch", "completed": False},
            {"id": "hr_03", "task": "Structure 3 impactful project stories using the STAR methodology", "completed": False},
            {"id": "hr_04", "task": f"Prepare 3 thoughtful questions to ask the interviewer about {comp}", "completed": False},
        ],
    }


def get_company_checklist(
    student_id: str,
    company_name: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieves or initializes the student's company-specific preparation checklist."""
    effective_student_id = (student_id or "default_student").strip()
    comp = (company_name or "Google").strip()

    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM company_preparation_checklists
                WHERE student_id = ? AND LOWER(company_name) = LOWER(?)
                """,
                (effective_student_id, comp),
            )
            row = cursor.fetchone()

            if row:
                rec = dict(row)
                try:
                    checklist_data = json.loads(rec.get("checklist_json", "{}"))
                except Exception:
                    checklist_data = get_default_company_checklist(comp)
            else:
                checklist_data = get_default_company_checklist(comp)
                save_company_checklist(effective_student_id, comp, checklist_data, db_path=db_path)

            total_tasks = 0
            completed_tasks = 0
            category_stats = {}

            for cat_name, task_list in checklist_data.items():
                cat_total = len(task_list)
                cat_done = sum(1 for t in task_list if t.get("completed"))
                total_tasks += cat_total
                completed_tasks += cat_done
                category_stats[cat_name] = {
                    "total": cat_total,
                    "completed": cat_done,
                    "percentage": round((cat_done / cat_total * 100), 1) if cat_total else 0.0,
                }

            overall_percentage = round((completed_tasks / total_tasks * 100), 1) if total_tasks else 0.0

            return {
                "student_id": effective_student_id,
                "company_name": comp,
                "checklist": checklist_data,
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "overall_percentage": overall_percentage,
                "category_stats": category_stats,
            }

    except Exception as e:
        logger.error(f"Error fetching company checklist for {company_name}: {e}")
        default_data = get_default_company_checklist(company_name)
        return {
            "student_id": student_id,
            "company_name": company_name,
            "checklist": default_data,
            "total_tasks": 15,
            "completed_tasks": 0,
            "overall_percentage": 0.0,
            "category_stats": {},
        }


def save_company_checklist(
    student_id: str,
    company_name: str,
    checklist_data: Dict[str, Any],
    db_path: Optional[str] = None,
) -> bool:
    """Saves candidate progress for a specific target company."""
    try:
        effective_student_id = (student_id or "default_student").strip()
        comp = (company_name or "Google").strip()

        total_tasks = 0
        completed_tasks = 0
        for task_list in checklist_data.values():
            total_tasks += len(task_list)
            completed_tasks += sum(1 for t in task_list if t.get("completed"))

        pct = round((completed_tasks / total_tasks * 100), 1) if total_tasks else 0.0
        rec_id = f"chk-{effective_student_id}-{comp.lower().replace(' ', '_')}"

        with transaction(db_path) as cursor:
            cursor.execute(
                """
                INSERT INTO company_preparation_checklists (
                    id, student_id, company_name, checklist_json, completion_percentage, updated_at
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(student_id, company_name) DO UPDATE SET
                    checklist_json = excluded.checklist_json,
                    completion_percentage = excluded.completion_percentage,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (rec_id, effective_student_id, comp, json.dumps(checklist_data), pct),
            )
            return True
    except Exception as e:
        logger.error(f"Error saving checklist for {company_name}: {e}")
        return False


def reset_company_checklist(
    student_id: str,
    company_name: str,
    db_path: Optional[str] = None,
) -> bool:
    """Resets all tasks to uncompleted for the target company checklist."""
    default_data = get_default_company_checklist(company_name)
    return save_company_checklist(student_id, company_name, default_data, db_path=db_path)


def record_viewed_job(
    student_id: str,
    job_id: str,
    company_name: str,
    role_title: str,
    location: str = "Remote",
    salary_range: Optional[str] = None,
    apply_url: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Records or bumps a job into the student's recently viewed list."""
    rec_id = f"viewed-{uuid.uuid4().hex[:12]}"
    s_id = (student_id or "default_student").strip()
    j_id = str(job_id).strip()
    comp = str(company_name).strip()
    role = str(role_title).strip()
    loc = (location or "Remote").strip()
    sal = salary_range.strip() if salary_range else None
    url = apply_url.strip() if apply_url else None
    viewed_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")

    with transaction(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO recently_viewed_jobs (
                id, student_id, job_id, company_name, role_title, location, salary_range, apply_url, viewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(student_id, job_id) DO UPDATE SET
                company_name = excluded.company_name,
                role_title = excluded.role_title,
                location = excluded.location,
                salary_range = excluded.salary_range,
                apply_url = excluded.apply_url,
                viewed_at = excluded.viewed_at
            """,
            (rec_id, s_id, j_id, comp, role, loc, sal, url, viewed_at),
        )

        cursor.execute(
            "SELECT * FROM recently_viewed_jobs WHERE student_id = ? AND job_id = ?",
            (s_id, j_id),
        )
        row = cursor.fetchone()
        return dict(row) if row else {}


def get_recently_viewed_jobs(
    student_id: str,
    limit: int = 10,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves the list of jobs recently viewed by a specific student."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            s_id = (student_id or "default_student").strip()
            lim = max(1, min(int(limit), 50)) if limit else 10
            cursor.execute(
                """
                SELECT id, student_id, job_id, company_name, role_title, location, salary_range, apply_url, viewed_at
                FROM recently_viewed_jobs
                WHERE student_id = ?
                ORDER BY viewed_at DESC, rowid DESC
                LIMIT ?
                """,
                (s_id, lim),
            )
            return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching recently viewed jobs for student {student_id}: {e}")
        return []


def remove_recently_viewed_job(
    student_id: str,
    job_id: str,
    db_path: Optional[str] = None,
) -> bool:
    """Removes a single viewed job entry from student history."""
    try:
        with transaction(db_path) as cursor:
            s_id = (student_id or "default_student").strip()
            cursor.execute(
                "DELETE FROM recently_viewed_jobs WHERE student_id = ? AND job_id = ?",
                (s_id, str(job_id).strip()),
            )
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error removing viewed job {job_id} for student {student_id}: {e}")
        return False


def clear_recently_viewed_jobs(
    student_id: str,
    db_path: Optional[str] = None,
) -> int:
    """Clears all viewed job history for the given student."""
    try:
        with transaction(db_path) as cursor:
            s_id = (student_id or "default_student").strip()
            cursor.execute("DELETE FROM recently_viewed_jobs WHERE student_id = ?", (s_id,))
            return cursor.rowcount
    except Exception as e:
        logger.error(f"Error clearing viewed jobs for student {student_id}: {e}")
        return 0


def create_saved_job_description(
    student_id: str,
    company_name: str,
    role_title: str,
    source: str,
    description: str,
    notes: str = "",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates a private saved job description for the specified student."""
    saved_id = f"saved-jd-{uuid.uuid4().hex[:12]}"
    effective_student_id = (student_id or "").strip()
    values = (
        saved_id,
        effective_student_id,
        (company_name or "").strip(),
        (role_title or "").strip(),
        (source or "").strip(),
        (description or "").strip(),
        (notes or "").strip(),
    )
    with transaction(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO saved_job_descriptions
                (id, student_id, company_name, role_title, source, description, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        cursor.execute(
            "SELECT * FROM saved_job_descriptions WHERE id = ? AND student_id = ?",
            (saved_id, effective_student_id),
        )
        row = cursor.fetchone()
        return dict(row) if row else {}


def get_saved_job_descriptions(
    student_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Returns only the saved job descriptions owned by the specified student."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        effective_student_id = (student_id or "").strip()
        cursor.execute(
            """
            SELECT id, student_id, company_name, role_title, source, description,
                   notes, created_at, updated_at
            FROM saved_job_descriptions
            WHERE student_id = ?
            ORDER BY updated_at DESC, created_at DESC
            """,
            (effective_student_id,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_saved_job_description_by_id(
    saved_id: str,
    student_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Gets one saved job description only when it belongs to the student."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM saved_job_descriptions
            WHERE id = ? AND student_id = ?
            """,
            ((saved_id or "").strip(), (student_id or "").strip()),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def update_saved_job_description(
    saved_id: str,
    student_id: str,
    company_name: str,
    role_title: str,
    source: str,
    description: str,
    notes: str = "",
    db_path: Optional[str] = None,
) -> bool:
    """Updates a saved job description after checking student ownership."""
    try:
        with transaction(db_path) as cursor:
            cursor.execute(
                """
                UPDATE saved_job_descriptions
                SET company_name = ?, role_title = ?, source = ?, description = ?,
                    notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND student_id = ?
                """,
                (
                    (company_name or "").strip(),
                    (role_title or "").strip(),
                    (source or "").strip(),
                    (description or "").strip(),
                    (notes or "").strip(),
                    (saved_id or "").strip(),
                    (student_id or "").strip(),
                ),
            )
            return cursor.rowcount > 0
    except Exception:
        logger.exception("Error updating saved job description %s", saved_id)
        return False


def delete_saved_job_description(
    saved_id: str,
    student_id: str,
    db_path: Optional[str] = None,
) -> bool:
    """Deletes a saved job description after checking student ownership."""
    try:
        with transaction(db_path) as cursor:
            cursor.execute(
                """
                DELETE FROM saved_job_descriptions
                WHERE id = ? AND student_id = ?
                """,
                ((saved_id or "").strip(), (student_id or "").strip()),
            )
            return cursor.rowcount > 0
    except Exception:
        logger.exception("Error deleting saved job description %s", saved_id)
        return False


def save_job_contact(
    contact_id: str,
    application_id: str,
    student_id: str,
    name: str,
    role: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    notes: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Saves a recruiter or company contact person linked to a job application."""
    effective_id = contact_id or f"cnt-{uuid.uuid4().hex[:12]}"
    with transaction(db_path) as cursor:
        cursor.execute(
            """
            INSERT OR REPLACE INTO job_application_contacts (
                id, application_id, student_id, name, role, email, phone, linkedin_url, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                effective_id,
                application_id.strip(),
                student_id.strip() if student_id else "default_student",
                name.strip(),
                (role or "").strip(),
                (email or "").strip(),
                (phone or "").strip(),
                (linkedin_url or "").strip(),
                (notes or "").strip(),
            ),
        )
        return effective_id


def get_job_contacts(
    application_id: str,
    student_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves contacts for a specific job application owned by student."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM job_application_contacts
                WHERE application_id = ? AND student_id = ?
                ORDER BY created_at ASC
                """,
                (application_id.strip(), student_id.strip() if student_id else "default_student"),
            )
            return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching contacts for application {application_id}: {e}")
        return []


def delete_job_contact(
    contact_id: str,
    student_id: str,
    db_path: Optional[str] = None,
) -> bool:
    """Deletes a job contact owned by student."""
    try:
        with transaction(db_path) as cursor:
            cursor.execute(
                "DELETE FROM job_application_contacts WHERE id = ? AND student_id = ?",
                (contact_id.strip(), student_id.strip() if student_id else "default_student"),
            )
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting job contact {contact_id}: {e}")
        return False
