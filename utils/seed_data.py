"""
utils/seed_data.py
Reproducible Local Development Seed Command & Safe Data Reset (#task-seed-command).

Enables contributors to quickly populate a local setup with safe, realistic synthetic
development data to test:
- Candidate Evaluation Dashboards (multi-version ATS score trends, skill gaps, roadmaps)
- Job Application Tracker (pipeline stages: Applied, Screening, Interviewing, Offer, Rejected)
- Mock Interview Simulator (question transcripts, STAR answers, score progression)
- Placement Reports, Certificates, Notes, and Saved Job Descriptions
- Clearly marked synthetic test accounts:
  * Student: contributor.demo@seed.local / Password123!
  * Admin: admin.demo@seed.local / AdminPassword123!

Safety & Isolation Guarantees:
- Targets a dedicated development database (placement_agent_dev.db) by default.
- Every synthetic entity is strictly identified by:
  * ID prefix: `seed_*`
  * User email domain: `@seed.local`
  * Visible tag/prefix: `[SEED]` or `[SAMPLE]`
- Safe Reset (`--reset`): Purges ONLY synthetic seed records, leaving real user records intact.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Ensure project root is in sys.path when script is invoked directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from werkzeug.security import generate_password_hash

import config
from db.migrations import init_db

logger = logging.getLogger(__name__)

# Reserved domain and prefixes for unambiguous synthetic seed data identification
SEED_EMAIL_DOMAIN = "@seed.local"
SEED_ID_PREFIX = "seed_"
SEED_TAG = "[SEED]"
DEV_DB_FILENAME = "placement_agent_dev.db"

# Default contributor test credentials
DEFAULT_STUDENT_EMAIL = f"contributor.demo{SEED_EMAIL_DOMAIN}"
DEFAULT_STUDENT_PASSWORD = "Password123!"
DEFAULT_STUDENT_ID = "seed_student_demo"

DEFAULT_ADMIN_EMAIL = f"admin.demo{SEED_EMAIL_DOMAIN}"
DEFAULT_ADMIN_PASSWORD = "AdminPassword123!"
DEFAULT_ADMIN_ID = "seed_admin_demo"


def resolve_target_database(
    db_path: Optional[Union[str, Path]] = None,
    use_dev: bool = False,
    use_app_db: bool = False,
) -> Path:
    """
    Resolves the target SQLite database path based on CLI flags and environment.
    Defaults to the isolated development database (placement_agent_dev.db) to ensure
    real application databases are never modified inadvertently.
    """
    if db_path:
        target = Path(db_path)
    elif use_app_db:
        target = Path(config.DATABASE_PATH)
    else:
        # Default mode: use isolated development database
        storage_dir = Path(getattr(config, "STORAGE_DIR", Path(".")))
        target = storage_dir / DEV_DB_FILENAME

    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def get_seed_status(db_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """
    Scans the target database and tallies seed vs non-seed records across all tables.
    Returns structured counts for verification.
    """
    target = resolve_target_database(db_path)
    if not target.exists():
        return {"database_exists": False, "target_path": str(target), "counts": {}}

    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    def _count(table: str, id_col: str = "id") -> Tuple[int, int]:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            total = cursor.fetchone()[0]
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {id_col} LIKE 'seed_%'")
            seed_count = cursor.fetchone()[0]
            return seed_count, total
        except sqlite3.OperationalError:
            return 0, 0

    # Users count (checked by seed_ prefix or @seed.local email)
    seed_users, total_users = 0, 0
    try:
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute(f"SELECT COUNT(*) FROM users WHERE id LIKE 'seed_%' OR email LIKE '%{SEED_EMAIL_DOMAIN}'")
        seed_users = cursor.fetchone()[0]
    except sqlite3.OperationalError:
        pass

    seed_analyses, total_analyses = _count("analyses")
    seed_interviews, total_interviews = _count("interviews")
    seed_apps, total_apps = _count("job_applications")
    seed_notes, total_notes = _count("interview_preparation_notes")
    seed_annos, total_annos = _count("analysis_annotations")
    seed_jds, total_jds = _count("saved_job_descriptions")
    seed_profiles, total_profiles = _count("student_profiles", "student_id")

    conn.close()

    return {
        "database_exists": True,
        "target_path": str(target),
        "is_dev_db": target.name == DEV_DB_FILENAME,
        "counts": {
            "users": {"seed": seed_users, "total": total_users, "user_created": total_users - seed_users},
            "analyses": {"seed": seed_analyses, "total": total_analyses, "user_created": total_analyses - seed_analyses},
            "interviews": {"seed": seed_interviews, "total": total_interviews, "user_created": total_interviews - seed_interviews},
            "job_applications": {"seed": seed_apps, "total": total_apps, "user_created": total_apps - seed_apps},
            "interview_notes": {"seed": seed_notes, "total": total_notes, "user_created": total_notes - seed_notes},
            "annotations": {"seed": seed_annos, "total": total_annos, "user_created": total_annos - seed_annos},
            "saved_job_descriptions": {"seed": seed_jds, "total": total_jds, "user_created": total_jds - seed_jds},
            "student_profiles": {"seed": seed_profiles, "total": total_profiles, "user_created": total_profiles - seed_profiles},
        }
    }


def reset_seed_data(
    db_path: Optional[Union[str, Path]] = None,
    reset_all: bool = False,
) -> Dict[str, int]:
    """
    Safely purges synthetic seed records without touching any user-created data.
    If reset_all is True, drops and rebuilds all tables via migrations.
    """
    target = resolve_target_database(db_path)
    if not target.exists():
        return {"deleted_seed_records": 0, "message": "Database file does not exist."}

    if reset_all:
        conn = sqlite3.connect(target)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [row[0] for row in cursor.fetchall()]
        for tbl in tables:
            cursor.execute(f"DROP TABLE IF EXISTS {tbl}")
        conn.commit()
        conn.close()

        # Re-initialize schema migrations
        init_db(target)
        return {"all_tables_reset": len(tables), "message": f"Completely reset all tables in {target.name}."}

    conn = sqlite3.connect(target)
    cursor = conn.cursor()
    deleted_counts: Dict[str, int] = {}

    tables_and_queries = [
        ("analyses", "DELETE FROM analyses WHERE id LIKE 'seed_%' OR student_id LIKE 'seed_%'"),
        ("interviews", "DELETE FROM interviews WHERE id LIKE 'seed_%' OR analysis_id LIKE 'seed_%'"),
        ("job_applications", "DELETE FROM job_applications WHERE id LIKE 'seed_%' OR student_id LIKE 'seed_%'"),
        ("interview_preparation_notes", "DELETE FROM interview_preparation_notes WHERE id LIKE 'seed_%' OR student_id LIKE 'seed_%'"),
        ("analysis_annotations", "DELETE FROM analysis_annotations WHERE id LIKE 'seed_%' OR student_id LIKE 'seed_%'"),
        ("saved_job_descriptions", "DELETE FROM saved_job_descriptions WHERE id LIKE 'seed_%' OR student_id LIKE 'seed_%'"),
        ("student_profiles", "DELETE FROM student_profiles WHERE id LIKE 'seed_%' OR student_id LIKE 'seed_%'"),
        ("users", f"DELETE FROM users WHERE id LIKE 'seed_%' OR email LIKE '%{SEED_EMAIL_DOMAIN}'"),
        ("batch_comparisons", "DELETE FROM batch_comparisons WHERE id LIKE 'seed_%' OR student_id LIKE 'seed_%'"),
        ("coding_submissions", "DELETE FROM coding_submissions WHERE id LIKE 'seed_%' OR student_id LIKE 'seed_%'"),
        ("technical_self_assessments", "DELETE FROM technical_self_assessments WHERE id LIKE 'seed_%' OR student_id LIKE 'seed_%'"),
        ("student_streaks", "DELETE FROM student_streaks WHERE student_id LIKE 'seed_%'"),
        ("preparation_activity_log", "DELETE FROM preparation_activity_log WHERE student_id LIKE 'seed_%'"),
        ("preparation_calendar_events", "DELETE FROM preparation_calendar_events WHERE id LIKE 'seed_%' OR student_id LIKE 'seed_%'"),
    ]

    for table_name, delete_sql in tables_and_queries:
        try:
            cursor.execute(delete_sql)
            deleted_counts[table_name] = cursor.rowcount
        except sqlite3.OperationalError:
            deleted_counts[table_name] = 0

    conn.commit()
    conn.close()

    total_deleted = sum(deleted_counts.values())
    return {
        "deleted_seed_records": total_deleted,
        "details": deleted_counts,
        "message": f"Successfully purged {total_deleted} seed records from {target.name}. All user-created data preserved.",
    }


# ==============================================================================
# Synthetic Seed Data Factory
# ==============================================================================

def seed_development_data(
    db_path: Optional[Union[str, Path]] = None,
    reset_first: bool = False,
    quiet: bool = False,
) -> Dict[str, Any]:
    """
    Populates the target database with reproducible synthetic test data across:
    1. Users (Demo student & Demo administrator)
    2. Candidate Student Profile
    3. Multi-version Analyses with ATS progressions (74% -> 82% -> 89%)
    4. Mock Interview Sessions with STAR evaluations & score trends
    5. Job Applications across all pipeline stages (Applied, Screening, Interviewing, Offer, Rejected)
    6. Interview Preparation Notes & Annotations
    7. Saved Job Descriptions & Calendar Milestones
    """
    target = resolve_target_database(db_path)
    # Ensure database tables exist via migrations
    init_db(target)

    if reset_first:
        reset_seed_data(target)

    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    now = dt.datetime.now(dt.timezone.utc)
    date_format = "%Y-%m-%d %H:%M:%S"

    # --------------------------------------------------------------------------
    # 1. Seed Users (Student & Admin)
    # --------------------------------------------------------------------------
    student_pw_hash = generate_password_hash(DEFAULT_STUDENT_PASSWORD)
    admin_pw_hash = generate_password_hash(DEFAULT_ADMIN_PASSWORD)

    cursor.execute("""
        INSERT OR REPLACE INTO users (
            id, name, email, password_hash, created_at,
            leaderboard_opt_in, is_verified
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        DEFAULT_STUDENT_ID,
        f"{SEED_TAG} Alex Chen (Demo Student)",
        DEFAULT_STUDENT_EMAIL,
        student_pw_hash,
        (now - dt.timedelta(days=30)).strftime(date_format),
        1,
        1,
    ))

    cursor.execute("""
        INSERT OR REPLACE INTO users (
            id, name, email, password_hash, created_at,
            leaderboard_opt_in, is_verified
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        DEFAULT_ADMIN_ID,
        f"{SEED_TAG} System Administrator (Demo Admin)",
        DEFAULT_ADMIN_EMAIL,
        admin_pw_hash,
        (now - dt.timedelta(days=45)).strftime(date_format),
        0,
        1,
    ))

    # --------------------------------------------------------------------------
    # 2. Seed Student Profile
    # --------------------------------------------------------------------------
    cursor.execute("""
        INSERT OR REPLACE INTO student_profiles (
            id, student_id, target_role, bio, skills,
            department, graduation_year, gpa, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "seed_profile_001",
        DEFAULT_STUDENT_ID,
        "Software Engineer (Backend)",
        f"{SEED_TAG} Computer Science senior focused on distributed systems, Python, and cloud infrastructure.",
        "Python, Flask, FastAPI, PostgreSQL, Docker, Redis, Git, Algorithms",
        "Computer Science & Engineering",
        2027,
        3.82,
        now.strftime(date_format),
    ))

    # --------------------------------------------------------------------------
    # 3. Seed Placement Analyses (3 Revisions for Trend Line Progression!)
    # --------------------------------------------------------------------------
    def _make_analysis_results(ats_score: int, match_pct: int, version: int) -> str:
        return json.dumps({
            "is_demo": True,
            "resume_analysis": {
                "ats_score": ats_score,
                "summary": f"{SEED_TAG} Candidate shows strong core foundations in algorithms and Python backend architectures (Revision #{version}).",
                "strengths": [
                    f"{SEED_TAG} Quantified impact across backend projects (reduced queue failure dropouts by 40%).",
                    f"{SEED_TAG} Clean section headers and algorithmic problem-solving track record.",
                    f"{SEED_TAG} Practical containerization exposure with Docker and Redis."
                ],
                "weaknesses": [
                    f"{SEED_TAG} Lacks production Kubernetes orchestration experience.",
                    f"{SEED_TAG} Could elaborate further on distributed consensus and caching trade-offs."
                ],
                "grammar_suggestions": [
                    "Use active, action-driven verbs for past internship experiences."
                ],
                "formatting_suggestions": [
                    "Ensure bullet indentations are standardized across all work experience entries."
                ],
                "project_feedback": "Projects demonstrate genuine systems engineering depth with clean test coverage.",
                "experience_feedback": "Internship bullets highlight practical agile development and microservice optimizations.",
                "missing_skills": ["Kubernetes", "Distributed System Design", "Redis Caching"],
                "overall_recommendation": "Strong candidate. Focus on distributed caching patterns to maximize placement chances.",
                "status": "available",
            },
            "job_match": {
                "match_percentage": match_pct,
                "matched_skills": ["Python", "Algorithms", "SQL", "REST APIs", "Docker", "Git"],
                "missing_skills": ["Kubernetes", "Distributed System Design", "Redis Caching"],
                "recommended_improvements": [
                    "Highlight distributed task processing and rate-limiting patterns.",
                    "Explicitly detail asynchronous task worker architectures in Python.",
                ],
                "top_5_resume_changes": [
                    "Include 'Distributed Systems' in primary skills block.",
                    "Highlight Redis LRU caching in project summaries.",
                    "Detail latency and throughput improvements.",
                    "Showcase automated GitHub Actions CI/CD workflows.",
                    "Align objective statement with Software Development Engineer roles.",
                ],
                "status": "available",
            },
            "skill_gap": [
                {
                    "skill": "Distributed System Design",
                    "importance": "High",
                    "difficulty": "Hard",
                    "learning_time": "3 weeks",
                    "learning_resource": "Designing Data-Intensive Applications & System Design Primer",
                    "project_suggestion": "Build a distributed URL shortener with consistent hashing.",
                    "priority": "High",
                },
                {
                    "skill": "Redis Caching Patterns",
                    "importance": "High",
                    "difficulty": "Medium",
                    "learning_time": "1-2 weeks",
                    "learning_resource": "Redis University (RU101) & Official Documentation",
                    "project_suggestion": "Implement cache-aside pattern with TTL eviction in Flask.",
                    "priority": "High",
                },
                {
                    "skill": "Kubernetes Orchestration",
                    "importance": "Medium",
                    "difficulty": "Hard",
                    "learning_time": "2 weeks",
                    "learning_resource": "Kubernetes for Beginners (CNCF)",
                    "project_suggestion": "Deploy microservices on Minikube with Ingress routing.",
                    "priority": "Medium",
                },
            ],
            "learning_roadmap": [
                {
                    "week": 1,
                    "title": "Week 1: Advanced Algorithms & Data Structures",
                    "topics": ["Tree and Graph Traversals", "Dynamic Programming", "Dijkstra & Topological Sort"],
                    "milestones": ["Solve 20 LeetCode Mediums", "Review time and space complexity"],
                },
                {
                    "week": 2,
                    "title": "Week 2: Backend Microservices & Asynchronous Queues",
                    "topics": ["FastAPI / Flask", "Celery Task Workers", "Redis Message Brokers"],
                    "milestones": ["Build an asynchronous worker pipeline", "Benchmarking throughput"],
                },
                {
                    "week": 3,
                    "title": "Week 3: Relational Database Optimization & Indexing",
                    "topics": ["B-Trees", "Composite Indexes", "Query Execution Plans", "Connection Pools"],
                    "milestones": ["Optimize slow SQL queries", "Write EXPLAIN ANALYZE reports"],
                },
                {
                    "week": 4,
                    "title": "Week 4: Distributed Systems & Scalability",
                    "topics": ["Load Balancing", "Consistent Hashing", "CAP Theorem", "Sharding"],
                    "milestones": ["Design a distributed key-value store architecture diagram"],
                },
                {
                    "week": 5,
                    "title": "Week 5: Mock Technical & Coding Interviews",
                    "topics": ["Live Code Editor Practice", "Clarifying Questions", "Edge Case Testing"],
                    "milestones": ["Complete 3 full mock interviews with STAR evaluations"],
                },
                {
                    "week": 6,
                    "title": "Week 6: Behavioral Interview Mastery & Recruiter Outreach",
                    "topics": ["STAR Method Stories", "Leadership Principles", "Compensation Research"],
                    "milestones": ["Draft tailored cover letters", "Prepare 5 STAR stories"],
                },
            ],
            "interview_questions": [
                {
                    "question": "How do you design a thread-safe distributed cache with LRU eviction?",
                    "category": "System Design",
                    "difficulty": "Hard",
                    "star_guidance": "Discuss doubly linked list + hash map, concurrency locks, and cache stampede prevention.",
                },
                {
                    "question": "Describe a challenging bug in an asynchronous task queue and how you resolved it.",
                    "category": "Behavioral / Technical",
                    "difficulty": "Medium",
                    "star_guidance": "Structure using Situation, Task, Action (debugging with logs/metrics), and Result (zero dropped jobs).",
                },
                {
                    "question": "Explain the differences between B-Tree indexes and Hash indexes in relational databases.",
                    "category": "Database Internals",
                    "difficulty": "Medium",
                    "star_guidance": "Contrast range queries, equality lookups, and disk page layout.",
                },
            ],
        })

    analyses_data = [
        ("seed_analysis_001", "Google", "alex_chen_synthetic_resume_v1.pdf", 1, 74, 70, (now - dt.timedelta(days=21))),
        ("seed_analysis_002", "Google", "alex_chen_synthetic_resume_v2.pdf", 2, 82, 79, (now - dt.timedelta(days=14))),
        ("seed_analysis_003", "Google", "alex_chen_synthetic_resume_v3.pdf", 3, 89, 86, (now - dt.timedelta(days=2))),
        ("seed_analysis_004", "Amazon", "alex_chen_synthetic_resume_v3.pdf", 1, 81, 84, (now - dt.timedelta(days=7))),
    ]

    for a_id, comp, r_file, v_num, ats, match_pct, a_date in analyses_data:
        cursor.execute("""
            INSERT OR REPLACE INTO analyses (
                id, resume_filename, company_name, job_description,
                results_json, student_id, version_number, target_role,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            a_id,
            r_file,
            comp,
            f"{SEED_TAG} {comp} Software Development Engineer (Campus Recruitment)",
            _make_analysis_results(ats, match_pct, v_num),
            DEFAULT_STUDENT_ID,
            v_num,
            "Software Engineer (Backend)",
            a_date.strftime(date_format),
        ))

    # --------------------------------------------------------------------------
    # 4. Seed Mock Interview Sessions (Score Progression Chart)
    # --------------------------------------------------------------------------
    interviews_data = [
        (
            "seed_interview_001",
            "seed_analysis_001",
            5,
            1,
            76,
            (now - dt.timedelta(days=18)),
        ),
        (
            "seed_interview_002",
            "seed_analysis_003",
            5,
            1,
            91,
            (now - dt.timedelta(days=1)),
        ),
        (
            "seed_interview_003",
            "seed_analysis_004",
            2,
            0,  # In-Progress mock session so contributors can test resume draft flows
            72,
            now,
        ),
    ]

    for i_id, a_id, q_idx, comp_flag, score, i_date in interviews_data:
        sample_questions = [
            {"id": 1, "question": f"{SEED_TAG} Tell me about a time you optimized a slow backend service.", "category": "Behavioral"},
            {"id": 2, "question": f"{SEED_TAG} How would you design a distributed rate limiter for API endpoints?", "category": "System Design"},
            {"id": 3, "question": f"{SEED_TAG} Explain how SQLite handles write-ahead logging (WAL) and concurrency.", "category": "Databases"},
            {"id": 4, "question": f"{SEED_TAG} Describe a conflict with a team member and how you reached consensus.", "category": "Behavioral"},
            {"id": 5, "question": f"{SEED_TAG} How do you protect a web application from prompt injection vulnerabilities?", "category": "Security"},
        ]
        sample_answers = [
            {
                "question_id": 1,
                "answer": f"{SEED_TAG} In our distributed worker queue, I observed 40% job drops due to unhandled broker disconnects. I introduced exponential backoff and connection pooling, cutting error rates to near zero.",
                "score": score,
                "evaluation": "Excellent STAR methodology and quantified impact metrics.",
                "readiness": "Interview Ready" if score >= 80 else "Moderate Fit",
            },
            {
                "question_id": 2,
                "answer": f"{SEED_TAG} I would use Redis with a sliding window counter algorithm and Lua script execution to prevent race conditions during high concurrent traffic spikes.",
                "score": score,
                "evaluation": "Strong architecture fundamentals and understanding of atomic operations.",
                "readiness": "Interview Ready" if score >= 80 else "Moderate Fit",
            },
        ]

        cursor.execute("""
            INSERT OR REPLACE INTO interviews (
                id, analysis_id, current_question_index, questions_json,
                answers_json, completed
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            i_id,
            a_id,
            q_idx,
            json.dumps(sample_questions),
            json.dumps(sample_answers),
            comp_flag,
        ))

    # --------------------------------------------------------------------------
    # 5. Seed Job Applications (Across All Pipeline Stages!)
    # --------------------------------------------------------------------------
    job_apps = [
        (
            "seed_app_001",
            "Google",
            f"{SEED_TAG} Software Development Engineer (SDE 1)",
            "Offer",
            (now - dt.timedelta(days=25)).strftime("%Y-%m-%d"),
            "https://careers.google.com/jobs/results/sample-sde-1",
            f"{SEED_TAG} Received written campus recruitment offer: $145,000 base + equity.",
            "Mountain View, CA / Hybrid",
            "Full-Time",
            "Entry-Level",
            (now + dt.timedelta(days=14)).strftime("%Y-%m-%d"),
            "seed_analysis_003",
        ),
        (
            "seed_app_002",
            "Microsoft",
            f"{SEED_TAG} Software Engineer - Azure Core",
            "Technical Interview",
            (now - dt.timedelta(days=15)).strftime("%Y-%m-%d"),
            "https://careers.microsoft.com/jobs/sample-azure",
            f"{SEED_TAG} Round 2 Virtual Onsite scheduled for distributed systems fundamentals.",
            "Redmond, WA",
            "Full-Time",
            "Entry-Level",
            (now + dt.timedelta(days=3)).strftime("%Y-%m-%d"),
            "seed_analysis_003",
        ),
        (
            "seed_app_003",
            "Amazon",
            f"{SEED_TAG} Systems Development Engineer",
            "Screening",
            (now - dt.timedelta(days=8)).strftime("%Y-%m-%d"),
            "https://amazon.jobs/en/jobs/sample-sde",
            f"{SEED_TAG} Recruiter screening completed; awaiting online technical assessment invitation.",
            "Seattle, WA",
            "Full-Time",
            "Entry-Level",
            (now + dt.timedelta(days=5)).strftime("%Y-%m-%d"),
            "seed_analysis_004",
        ),
        (
            "seed_app_004",
            "Stripe",
            f"{SEED_TAG} Backend Platform Engineer",
            "Applied",
            (now - dt.timedelta(days=3)).strftime("%Y-%m-%d"),
            "https://stripe.com/jobs/sample-backend",
            f"{SEED_TAG} Application submitted via university career fair referral portal.",
            "Remote",
            "Full-Time",
            "Entry-Level",
            (now + dt.timedelta(days=20)).strftime("%Y-%m-%d"),
            "seed_analysis_003",
        ),
        (
            "seed_app_005",
            "TechCorp Labs",
            f"{SEED_TAG} Junior Software Developer",
            "Rejected",
            (now - dt.timedelta(days=28)).strftime("%Y-%m-%d"),
            "https://techcorp.example/jobs/sample-junior",
            f"{SEED_TAG} Standard automated rejection email; role required 3+ years production Kubernetes.",
            "San Francisco, CA",
            "Full-Time",
            "Entry-Level",
            None,
            "seed_analysis_001",
        ),
    ]

    for app_id, comp, role, status, a_date, url, notes, loc, j_type, exp, deadline, a_ref in job_apps:
        cursor.execute("""
            INSERT OR REPLACE INTO job_applications (
                id, student_id, company_name, role_title, status,
                application_date, job_url, notes, location, job_type,
                experience_level, deadline_date, resume_analysis_id,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            app_id,
            DEFAULT_STUDENT_ID,
            comp,
            role,
            status,
            a_date,
            url,
            notes,
            loc,
            j_type,
            exp,
            deadline,
            a_ref,
            a_date,
        ))

    # --------------------------------------------------------------------------
    # 6. Seed Interview Preparation Notes
    # --------------------------------------------------------------------------
    notes_data = [
        (
            "seed_note_001",
            "Google",
            f"{SEED_TAG} System Design Cheatsheet: Consistent Hashing & LRU Cache",
            f"{SEED_TAG} Key talking points:\n1. Use a virtual node ring to balance partition distributions evenly.\n2. Combine Doubly Linked List + Hash Map to guarantee O(1) get and put operations in an LRU cache.\n3. Implement read-through caching with Redis to reduce PostgreSQL read load.",
            "System Design, Caching, Architecture",
            (now - dt.timedelta(days=4)),
        ),
        (
            "seed_note_002",
            "Microsoft",
            f"{SEED_TAG} Behavioral Prep: STAR Stories for Cloud Reliability",
            f"{SEED_TAG} Situation: High API latency on peak registration days.\nTask: Diagnose bottleneck without logging private user inputs.\nAction: Instrumented server timing metrics and added composite SQLite indexes.\nResult: 68% drop in p95 query latency.",
            "Behavioral, STAR, Leadership",
            (now - dt.timedelta(days=2)),
        ),
    ]

    for n_id, comp, title, content, tags, n_date in notes_data:
        cursor.execute("""
            INSERT OR REPLACE INTO interview_preparation_notes (
                id, student_id, company_name, title, content,
                tags, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            n_id,
            DEFAULT_STUDENT_ID,
            comp,
            title,
            content,
            tags,
            n_date.strftime(date_format),
            n_date.strftime(date_format),
        ))

    # --------------------------------------------------------------------------
    # 7. Seed Saved Job Descriptions
    # --------------------------------------------------------------------------
    saved_jds = [
        (
            "seed_jd_001",
            "Google",
            f"{SEED_TAG} SDE 1 - Distributed Systems",
            f"{SEED_TAG} Design, test, deploy, and maintain large-scale software solutions using Python, Go, and C++. Focus on high availability and developer platform services.",
            (now - dt.timedelta(days=10)),
        ),
        (
            "seed_jd_002",
            "Stripe",
            f"{SEED_TAG} Backend Platform Engineer - Infrastructure",
            f"{SEED_TAG} Build resilient payment infrastructure, distributed queues, and idempotency mechanisms powering billions of financial transactions globally.",
            (now - dt.timedelta(days=5)),
        ),
    ]

    for jd_id, comp, title, desc, jd_date in saved_jds:
        cursor.execute("""
            INSERT OR REPLACE INTO saved_job_descriptions (
                id, student_id, company_name, role_title,
                job_description, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            jd_id,
            DEFAULT_STUDENT_ID,
            comp,
            title,
            desc,
            jd_date.strftime(date_format),
        ))

    # --------------------------------------------------------------------------
    # 8. Seed Upcoming Calendar Events
    # --------------------------------------------------------------------------
    calendar_events = [
        (
            "seed_event_001",
            f"{SEED_TAG} Microsoft Onsite Virtual Interview",
            (now + dt.timedelta(days=3)).strftime("%Y-%m-%d"),
            "14:00",
            "Microsoft",
            f"{SEED_TAG} Technical round 2: Distributed systems and database indexing.",
            "Interview",
        ),
        (
            "seed_event_002",
            f"{SEED_TAG} Google Offer Acceptance Deadline",
            (now + dt.timedelta(days=14)).strftime("%Y-%m-%d"),
            "17:00",
            "Google",
            f"{SEED_TAG} Sign and return campus recruitment offer paperwork.",
            "Deadline",
        ),
    ]

    for ev_id, ev_title, ev_date, ev_time, ev_comp, ev_desc, ev_type in calendar_events:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO preparation_calendar_events (
                    id, student_id, event_title, event_date, event_time,
                    company_name, description, event_type, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ev_id,
                DEFAULT_STUDENT_ID,
                ev_title,
                ev_date,
                ev_time,
                ev_comp,
                ev_desc,
                ev_type,
                now.strftime(date_format),
            ))
        except sqlite3.OperationalError:
            pass

    # --------------------------------------------------------------------------
    # 9. Seed Multi-Company Batch Comparison
    # --------------------------------------------------------------------------
    batch_comp_results = {
        "is_demo": True,
        "companies": [
            {"company": "Google", "match_score": 86, "ats_score": 89, "offer_probability": "High", "tier": "Tier 1"},
            {"company": "Microsoft", "match_score": 82, "ats_score": 84, "offer_probability": "High", "tier": "Tier 1"},
            {"company": "Amazon", "match_score": 84, "ats_score": 81, "offer_probability": "Medium-High", "tier": "Tier 1"},
        ],
        "top_recommendation": "Google presents the highest alignment with current backend systems experience.",
    }
    cursor.execute("""
        INSERT OR REPLACE INTO batch_comparisons (
            id, student_id, resume_filename, companies_json, results_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (
        "seed_batch_001",
        DEFAULT_STUDENT_ID,
        "alex_chen_synthetic_resume_v3.pdf",
        json.dumps(["Google", "Microsoft", "Amazon"]),
        json.dumps(batch_comp_results),
        now.strftime(date_format),
    ))

    conn.commit()
    conn.close()

    status = get_seed_status(target)
    return {
        "status": "success",
        "target_path": str(target),
        "seeded_counts": {
            "users": 2,
            "analyses": 4,
            "interviews": 3,
            "job_applications": 5,
            "notes": 2,
            "saved_jds": 2,
            "calendar_events": 2,
            "batch_comparisons": 1,
        },
        "student_account": {
            "email": DEFAULT_STUDENT_EMAIL,
            "password": DEFAULT_STUDENT_PASSWORD,
            "role": "student",
        },
        "admin_account": {
            "email": DEFAULT_ADMIN_EMAIL,
            "password": DEFAULT_ADMIN_PASSWORD,
            "role": "admin",
        },
        "details": status,
    }


# ==============================================================================
# CLI Entrypoint & Formatted Output
# ==============================================================================

def print_seed_summary(result: Dict[str, Any]) -> None:
    """Prints a beautiful, formatted console summary of the seeded data and test credentials."""
    target_path = result.get("target_path", "unknown")
    counts = result.get("seeded_counts", {})
    student = result.get("student_account", {})
    admin = result.get("admin_account", {})

    print("\n" + "=" * 72)
    print("  🌱 AI Campus Placement Agent - Synthetic Development Seed Complete")
    print("=" * 72)
    print(f"Target Database: {target_path}")
    print("\n--- Seeded Entities ---")
    print(f"  • User Accounts:          {counts.get('users', 0)} (1 Student, 1 Administrator)")
    print(f"  • Resume Analyses:        {counts.get('analyses', 0)} (3 Google Revisions: 74% -> 82% -> 89% ATS, 1 Amazon)")
    print(f"  • Mock Interviews:        {counts.get('interviews', 0)} (Score progression: 76% -> 91% + 1 in-progress)")
    print(f"  • Job Applications:       {counts.get('job_applications', 0)} (Applied, Screening, Interviewing, Offer, Rejected)")
    print(f"  • Preparation Notes:      {counts.get('notes', 0)} (System Design & STAR tips)")
    print(f"  • Saved Job Descriptions: {counts.get('saved_jds', 0)}")
    print(f"  • Calendar Milestones:    {counts.get('calendar_events', 0)}")
    print(f"  • Multi-Company Compare:  {counts.get('batch_comparisons', 0)}")

    print("\n--- Contributor Test Logins ---")
    print(f"  [Student Account]")
    print(f"    Email:    {student.get('email')}")
    print(f"    Password: {student.get('password')}")
    print(f"  [Admin Account]")
    print(f"    Email:    {admin.get('email')}")
    print(f"    Password: {admin.get('password')}")

    print("\n--- Identification & Safety ---")
    print("  • All synthetic data is prefixed with [SEED] and uses the @seed.local domain.")
    print("  • To safely purge seed data: python utils/seed_data.py --reset")
    print("=" * 72 + "\n")


def print_status_report(status: Dict[str, Any]) -> None:
    """Prints current database counts and seed distribution."""
    target = status.get("target_path", "unknown")
    counts = status.get("counts", {})

    print("\n" + "=" * 72)
    print(f"  📊 Database Seed Inventory Status: {target}")
    print("=" * 72)
    print(f"{'Table / Entity':<28} {'Seed Records':<15} {'User Records':<15} {'Total'}")
    print("-" * 72)
    for name, c in counts.items():
        seed_c = c.get("seed", 0)
        user_c = c.get("user_created", 0)
        tot_c = c.get("total", 0)
        print(f"{name:<28} {seed_c:<15} {user_c:<15} {tot_c}")
    print("=" * 72 + "\n")


def main() -> int:
    """CLI handler for direct terminal invocation."""
    parser = argparse.ArgumentParser(
        description="Populate or reset synthetic local development seed data for AI Campus Placement Agent."
    )
    group_target = parser.add_mutually_exclusive_group()
    group_target.add_argument(
        "--dev", action="store_true", default=True,
        help="Target isolated development database (placement_agent_dev.db) [Default]",
    )
    group_target.add_argument(
        "--app-db", action="store_true",
        help="Target primary application database (placement_agent.db)",
    )
    group_target.add_argument(
        "--db-path", type=str,
        help="Target an explicit custom SQLite database path",
    )

    group_action = parser.add_mutually_exclusive_group()
    group_action.add_argument(
        "--reset", action="store_true",
        help="Safely purge ONLY synthetic seed data, preserving user-created data",
    )
    group_action.add_argument(
        "--reset-all", action="store_true",
        help="Completely reset and recreate all tables in the target database",
    )
    group_action.add_argument(
        "--status", action="store_true",
        help="Inspect count of seed records vs real user records in the target database",
    )

    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Suppress detailed console output",
    )

    args = parser.parse_args()

    # Determine target database
    target_path = resolve_target_database(
        db_path=args.db_path,
        use_dev=args.dev and not args.app_db,
        use_app_db=args.app_db,
    )

    if args.status:
        status = get_seed_status(target_path)
        if not args.quiet:
            print_status_report(status)
        return 0

    if args.reset:
        result = reset_seed_data(target_path, reset_all=False)
        if not args.quiet:
            print(f"\n[RESET] {result['message']}\n")
        return 0

    if args.reset_all:
        result = reset_seed_data(target_path, reset_all=True)
        if not args.quiet:
            print(f"\n[RESET ALL] {result['message']}\n")
        return 0

    # Default action: run seed
    seed_result = seed_development_data(target_path, reset_first=False, quiet=args.quiet)
    if not args.quiet:
        print_seed_summary(seed_result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
