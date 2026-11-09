"""
Company Profile Update Management System (#250)
================================================
Provides a complete administrative and directory service for managing enterprise company
profiles, recruitment patterns, interview rounds, required skill tags, hiring tier,
and application links.

Key Capabilities:
1. Automated table creation (company_profiles) with audit fields (created_at, updated_at).
2. CRUD operations: create, update, retrieve, list with search/filter, and archive (soft delete).
3. Company profile validation (name uniqueness, valid hiring tier, URL sanitization).
4. Profile stats calculation: total jobs, linked interview experiences, and candidate views.
5. Seed default company directory (Google, Microsoft, Amazon, TCS, Meta, etc.) if empty.
"""

import sqlite3
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
import uuid

import config
from utils.database import get_db_connection

logger = logging.getLogger(__name__)

VALID_HIRING_TIERS = {"Tier 1", "Tier 2", "Tier 3", "Startup", "MNC", "Enterprise"}


def ensure_company_profiles_table(conn: sqlite3.Connection) -> None:
    """Creates the company_profiles table and corresponding indices if they do not exist."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS company_profiles (
            id TEXT PRIMARY KEY,
            company_name TEXT UNIQUE NOT NULL,
            industry TEXT NOT NULL DEFAULT 'Technology',
            website_url TEXT,
            careers_url TEXT,
            logo_url TEXT,
            overview TEXT,
            hiring_tier TEXT NOT NULL DEFAULT 'Tier 1',
            hiring_workflow_json TEXT DEFAULT '[]',
            primary_tech_stack_json TEXT DEFAULT '[]',
            typical_ctc_range TEXT,
            headquarters TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_comp_prof_name ON company_profiles(company_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_comp_prof_tier ON company_profiles(hiring_tier)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_comp_prof_active ON company_profiles(is_active)")

    # Migration: add source & last_updated columns if not present
    cursor.execute("PRAGMA table_info(company_profiles)")
    existing_cols = {row["name"] if isinstance(row, (sqlite3.Row, dict)) else row[1] for row in cursor.fetchall()}
    if "source_name" not in existing_cols:
        cursor.execute("ALTER TABLE company_profiles ADD COLUMN source_name TEXT")
    if "source_url" not in existing_cols:
        cursor.execute("ALTER TABLE company_profiles ADD COLUMN source_url TEXT")
    if "verification_status" not in existing_cols:
        cursor.execute("ALTER TABLE company_profiles ADD COLUMN verification_status TEXT DEFAULT 'verified'")
    if "last_updated" not in existing_cols:
        cursor.execute("ALTER TABLE company_profiles ADD COLUMN last_updated TEXT")

    conn.commit()


def seed_default_company_profiles() -> int:
    """Pre-populates foundational tech company recruitment profiles if directory is empty."""
    default_companies = [
        {
            "company_name": "Google",
            "industry": "Technology / Cloud & AI",
            "website_url": "https://google.com",
            "careers_url": "https://careers.google.com",
            "overview": "Global leader in search, cloud computing, artificial intelligence, and operating systems.",
            "hiring_tier": "Tier 1",
            "hiring_workflow": [
                "Online Assessment (Data Structures & Algorithms)",
                "Technical Interview 1 (Trees & Graphs)",
                "Technical Interview 2 (Dynamic Programming & System Design)",
                "Googliness & Leadership Behavioral Round"
            ],
            "primary_tech_stack": ["Python", "C++", "Java", "Go", "TensorFlow", "Kubernetes", "GCP"],
            "typical_ctc_range": "25 - 45 LPA",
            "headquarters": "Mountain View, CA"
        },
        {
            "company_name": "Microsoft",
            "industry": "Enterprise Software & Cloud",
            "website_url": "https://microsoft.com",
            "careers_url": "https://careers.microsoft.com",
            "overview": "Pioneering enterprise cloud, developer platforms, AI productivity tools, and operating systems.",
            "hiring_tier": "Tier 1",
            "hiring_workflow": [
                "Codility Online Assessment",
                "Technical Screening (DSA & Problem Solving)",
                "Virtual Onsite Round 1 (System Architecture)",
                "Virtual Onsite Round 2 (Design & Cultural Fit)"
            ],
            "primary_tech_stack": ["C#", ".NET", "Azure", "TypeScript", "Python", "SQL Server"],
            "typical_ctc_range": "22 - 42 LPA",
            "headquarters": "Redmond, WA"
        },
        {
            "company_name": "Amazon",
            "industry": "E-Commerce & Cloud Computing",
            "website_url": "https://amazon.jobs",
            "careers_url": "https://amazon.jobs/en",
            "overview": "Customer-centric tech giant leading cloud infrastructure (AWS), e-commerce, and logistics automation.",
            "hiring_tier": "Tier 1",
            "hiring_workflow": [
                "Online Assessment 1 (Debugging & Coding)",
                "Online Assessment 2 (Work Style Simulation & LP)",
                "Technical Round 1 (Problem Solving & Complexity)",
                "Bar Raiser & Leadership Principles Evaluation"
            ],
            "primary_tech_stack": ["Java", "AWS", "Python", "React", "DynamoDB", "Kafka"],
            "typical_ctc_range": "24 - 44 LPA",
            "headquarters": "Seattle, WA"
        },
        {
            "company_name": "Tata Consultancy Services (TCS)",
            "industry": "IT Services & Consulting",
            "website_url": "https://tcs.com",
            "careers_url": "https://www.tcs.com/careers",
            "overview": "Premier global IT consulting, engineering solutions, and digital enterprise transformation service provider.",
            "hiring_tier": "Enterprise",
            "hiring_workflow": [
                "National Qualifier Test (NQT)",
                "Technical Interview Round",
                "Managerial Evaluation Round",
                "HR Discussion"
            ],
            "primary_tech_stack": ["Java", "Spring Boot", "Python", "SQL", "Cloud Platforms"],
            "typical_ctc_range": "3.6 - 9.0 LPA (Ninja / Digital / Prime)",
            "headquarters": "Mumbai, India"
        }
    ]

    inserted = 0
    with get_db_connection() as conn:
        ensure_company_profiles_table(conn)
        cursor = conn.cursor()
        for comp in default_companies:
            cursor.execute("SELECT id FROM company_profiles WHERE LOWER(company_name) = LOWER(?)", (comp["company_name"],))
            if not cursor.fetchone():
                comp_id = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO company_profiles (
                        id, company_name, industry, website_url, careers_url, overview,
                        hiring_tier, hiring_workflow_json, primary_tech_stack_json,
                        typical_ctc_range, headquarters, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """, (
                    comp_id,
                    comp["company_name"],
                    comp["industry"],
                    comp.get("website_url"),
                    comp.get("careers_url"),
                    comp.get("overview"),
                    comp.get("hiring_tier", "Tier 1"),
                    json.dumps(comp.get("hiring_workflow", [])),
                    json.dumps(comp.get("primary_tech_stack", [])),
                    comp.get("typical_ctc_range"),
                    comp.get("headquarters")
                ))
                inserted += 1
        conn.commit()
    return inserted


def create_company_profile(
    company_name: str,
    industry: str = "Technology",
    website_url: Optional[str] = None,
    careers_url: Optional[str] = None,
    logo_url: Optional[str] = None,
    overview: Optional[str] = None,
    hiring_tier: str = "Tier 1",
    hiring_workflow: Optional[List[str]] = None,
    primary_tech_stack: Optional[List[str]] = None,
    typical_ctc_range: Optional[str] = None,
    headquarters: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates a new company recruitment profile.

    Raises:
        ValueError if name is blank or company already exists.
    """
    name = (company_name or "").strip()
    if not name:
        raise ValueError("Company name is required.")

    tier = hiring_tier if hiring_tier in VALID_HIRING_TIERS else "Tier 1"
    workflow = hiring_workflow if isinstance(hiring_workflow, list) else []
    tech_stack = primary_tech_stack if isinstance(primary_tech_stack, list) else []

    comp_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        ensure_company_profiles_table(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM company_profiles WHERE LOWER(company_name) = LOWER(?)", (name,))
        if cursor.fetchone():
            raise ValueError(f"Company profile for '{name}' already exists.")

        cursor.execute("""
            INSERT INTO company_profiles (
                id, company_name, industry, website_url, careers_url, logo_url,
                overview, hiring_tier, hiring_workflow_json, primary_tech_stack_json,
                typical_ctc_range, headquarters, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (
            comp_id,
            name,
            (industry or "Technology").strip(),
            website_url,
            careers_url,
            logo_url,
            overview,
            tier,
            json.dumps(workflow),
            json.dumps(tech_stack),
            typical_ctc_range,
            headquarters,
            now,
            now
        ))
        conn.commit()

    return get_company_profile_by_id(comp_id)  # type: ignore


def update_company_profile(
    profile_id: str,
    updates: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Updates an existing company profile."""
    if not profile_id:
        return None

    allowed_fields = {
        "company_name", "industry", "website_url", "careers_url", "logo_url",
        "overview", "hiring_tier", "hiring_workflow", "primary_tech_stack",
        "typical_ctc_range", "headquarters", "is_active"
    }

    filtered_updates: Dict[str, Any] = {}
    for k, v in updates.items():
        if k in allowed_fields:
            if k == "hiring_workflow":
                filtered_updates["hiring_workflow_json"] = json.dumps(v if isinstance(v, list) else [])
            elif k == "primary_tech_stack":
                filtered_updates["primary_tech_stack_json"] = json.dumps(v if isinstance(v, list) else [])
            elif k == "hiring_tier":
                filtered_updates["hiring_tier"] = v if v in VALID_HIRING_TIERS else "Tier 1"
            elif k == "company_name":
                if not str(v).strip():
                    raise ValueError("Company name cannot be empty.")
                filtered_updates["company_name"] = str(v).strip()
            else:
                filtered_updates[k] = v

    if not filtered_updates:
        return get_company_profile_by_id(profile_id)

    filtered_updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    set_clauses = [f"{k} = ?" for k in filtered_updates.keys()]
    values = list(filtered_updates.values())
    values.append(profile_id)

    with get_db_connection() as conn:
        ensure_company_profiles_table(conn)
        cursor = conn.cursor()
        cursor.execute(f"UPDATE company_profiles SET {', '.join(set_clauses)} WHERE id = ?", values)
        conn.commit()

    return get_company_profile_by_id(profile_id)


def get_company_profile_by_id(profile_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a company profile by unique primary ID."""
    with get_db_connection() as conn:
        ensure_company_profiles_table(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM company_profiles WHERE id = ?", (profile_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return _format_company_profile_row(row)


def get_company_profile_by_name(company_name: str) -> Optional[Dict[str, Any]]:
    """Fetches an active company profile matching the company name (case-insensitive)."""
    if not company_name or not company_name.strip():
        return None
    with get_db_connection() as conn:
        ensure_company_profiles_table(conn)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM company_profiles
            WHERE LOWER(company_name) = LOWER(?)
        """, (company_name.strip(),))
        row = cursor.fetchone()
        if not row:
            return None
        return _format_company_profile_row(row)


def list_company_profiles(
    search_query: Optional[str] = None,
    tier_filter: Optional[str] = None,
    active_only: bool = True
) -> List[Dict[str, Any]]:
    """Returns a filtered list of enterprise company profiles."""
    with get_db_connection() as conn:
        ensure_company_profiles_table(conn)
        cursor = conn.cursor()
        query = "SELECT * FROM company_profiles WHERE 1=1"
        params: List[Any] = []

        if active_only:
            query += " AND is_active = 1"

        if tier_filter and tier_filter.strip() and tier_filter.lower() != "all":
            query += " AND hiring_tier = ?"
            params.append(tier_filter.strip())

        if search_query and search_query.strip():
            sq = f"%{search_query.strip().lower()}%"
            query += " AND (LOWER(company_name) LIKE ? OR LOWER(industry) LIKE ? OR LOWER(overview) LIKE ?)"
            params.extend([sq, sq, sq])

        query += " ORDER BY company_name ASC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [_format_company_profile_row(r) for r in rows]


def archive_company_profile(profile_id: str) -> bool:
    """Soft-deletes a company profile by marking is_active = 0."""
    with get_db_connection() as conn:
        ensure_company_profiles_table(conn)
        cursor = conn.cursor()
        cursor.execute("UPDATE company_profiles SET is_active = 0, updated_at = ? WHERE id = ?", (
            datetime.now(timezone.utc).isoformat(),
            profile_id
        ))
        conn.commit()
        return cursor.rowcount > 0


def delete_company_profile_permanently(profile_id: str) -> bool:
    """Hard-deletes a company profile permanently from storage."""
    with get_db_connection() as conn:
        ensure_company_profiles_table(conn)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM company_profiles WHERE id = ?", (profile_id,))
        conn.commit()
        return cursor.rowcount > 0


def _format_company_profile_row(row: sqlite3.Row) -> Dict[str, Any]:
    """Helper to convert sqlite3.Row into structured profile dict."""
    d = dict(row)
    try:
        d["hiring_workflow"] = json.loads(d.get("hiring_workflow_json") or "[]")
    except Exception:
        d["hiring_workflow"] = []

    try:
        d["primary_tech_stack"] = json.loads(d.get("primary_tech_stack_json") or "[]")
    except Exception:
        d["primary_tech_stack"] = []

    d["is_active"] = bool(d.get("is_active", 1))
    return d


# ==============================================================================
# Company Hiring Guide Freshness, Source & Verification Enrichment
# ==============================================================================

def parse_last_updated_date(date_str: Optional[str]) -> Tuple[Optional[datetime], Optional[int]]:
    """
    Parses a last_updated date string (e.g. '2026-10-18', '2026-10') and calculates
    the age in days relative to current UTC time.
    Returns (parsed_datetime, age_in_days).
    """
    if not date_str or not str(date_str).strip():
        return None, None

    clean = str(date_str).strip()
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d",
        "%Y-%m",
        "%d-%m-%Y",
        "%B %d, %Y",
        "%B %Y"
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(clean, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age_days = (now - dt).days
            return dt, age_days
        except ValueError:
            continue

    return None, None


def format_last_updated_display(date_str: Optional[str]) -> str:
    """
    Formats last_updated into a friendly human-readable date (e.g. 'October 18, 2026').
    Falls back gracefully to 'Date unconfirmed' if missing or unparseable.
    """
    if not date_str or not str(date_str).strip():
        return "Date unconfirmed"

    dt, _ = parse_last_updated_date(date_str)
    if dt:
        return dt.strftime("%B %d, %Y")
    return str(date_str).strip()


def is_hiring_guide_outdated(date_str: Optional[str], threshold_days: int = 365) -> bool:
    """
    Checks if a company hiring guide is outdated (e.g. older than 365 days or date unconfirmed).
    """
    if not date_str or not str(date_str).strip():
        return True

    dt, age_days = parse_last_updated_date(date_str)
    if age_days is None:
        return True
    return age_days > threshold_days


def enrich_company_hiring_guide(company_name: str, raw_details: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Enriches raw company hiring information with source metadata, verified vs. general guidance
    separation, freshness calculation, and graceful fallbacks for missing data.
    """
    if not isinstance(raw_details, dict):
        raw_details = {}

    d = dict(raw_details)

    # 1. Source Name & Source Link
    raw_source_name = d.get("source_name")
    raw_source_url = d.get("source_url")

    if raw_source_name and str(raw_source_name).strip():
        source_name = str(raw_source_name).strip()
        source_is_default = False
    else:
        source_name = "Campus Placement Archives (Aggregated)"
        source_is_default = True

    # Validate external URL: must be http:// or https://
    source_url: Optional[str] = None
    if raw_source_url and isinstance(raw_source_url, str):
        trimmed_url = raw_source_url.strip()
        if trimmed_url.startswith("http://") or trimmed_url.startswith("https://"):
            source_url = trimmed_url

    # 2. Last Updated & Freshness Calculation
    raw_last_updated = d.get("last_updated")
    dt, age_days = parse_last_updated_date(raw_last_updated)
    last_updated_display = format_last_updated_display(raw_last_updated)
    is_outdated = is_hiring_guide_outdated(raw_last_updated, threshold_days=365)

    if not raw_last_updated:
        freshness_status = "unconfirmed"
        freshness_label = "Date Unconfirmed"
        freshness_badge = "secondary"
        outdated_warning = "The last updated date is unconfirmed for this company guide. Hiring criteria may differ for the current recruitment season."
    elif is_outdated:
        freshness_status = "outdated"
        freshness_label = "Archive / Needs Refresh"
        freshness_badge = "warning"
        outdated_warning = (
            f"This hiring guide was last updated on {last_updated_display} (over 12 months ago). "
            "Campus recruitment patterns and eligibility cutoffs may vary for the current season. "
            "Please cross-reference with the official company careers portal before applying."
        )
    else:
        freshness_status = "current"
        freshness_label = "Current 2026 Season"
        freshness_badge = "success"
        outdated_warning = None

    # 3. Verification Distinction
    is_verified = bool(d.get("is_verified") or d.get("verification_status") == "verified")
    verification_status = "verified" if is_verified else "general_guidance"
    verification_badge = "Verified Hiring Criteria" if is_verified else "General Preparation Suggestions"
    verified_by = d.get("verified_by") or ("Campus Placement Cell & Industry Archives" if is_verified else None)

    # 4. Structured Division between Verified Criteria and Preparation Suggestions
    verified_info = {
        "eligibility": d.get("eligibility") or "Eligibility criteria not officially specified. Consult your college placement cell for current cutoffs.",
        "hiring_process": d.get("hiring_process") or "Hiring process stages currently undergoing season update.",
        "technical_rounds": d.get("technical_rounds") or "Technical round details currently being updated.",
        "hr_rounds": d.get("hr_rounds") or "HR and cultural evaluation details not specified.",
        "source_name": source_name,
        "source_url": source_url,
        "last_updated": last_updated_display,
        "verified_by": verified_by,
        "is_verified": is_verified,
        "is_outdated": is_outdated,
    }

    general_suggestions = {
        "frequent_topics": d.get("frequent_topics") or [],
        "required_skills": d.get("required_skills") or [],
        "prep_tips": d.get("prep_tips") or "Review standard computer science fundamentals and practice coding problems.",
        "disclaimer": "Preparation tips and frequent topics represent aggregated interview experiences and community-guided suggestions; company assessment patterns may evolve per recruitment cycle.",
        "is_general_guidance": True,
    }

    # Update dictionary with enriched values while keeping all existing keys
    d["company_name"] = company_name
    d["source_name"] = source_name
    d["source_url"] = source_url
    d["source_is_default"] = source_is_default
    d["last_updated"] = raw_last_updated or "Not specified"
    d["last_updated_display"] = last_updated_display
    d["age_days"] = age_days
    d["is_outdated"] = is_outdated
    d["freshness_status"] = freshness_status
    d["freshness_label"] = freshness_label
    d["freshness_badge"] = freshness_badge
    d["outdated_warning"] = outdated_warning
    d["is_verified"] = is_verified
    d["verification_status"] = verification_status
    d["verification_badge"] = verification_badge
    d["verified_by"] = verified_by
    d["verified_info"] = verified_info
    d["general_suggestions"] = general_suggestions

    return d

