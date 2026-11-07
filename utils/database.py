import sqlite3
import json
import logging
import uuid
from typing import Optional, List, Dict, Any
import config

logger = logging.getLogger(__name__)

def get_db_connection() -> sqlite3.Connection:
    """
    Establishes and returns a connection to the SQLite database.
    Sets row_factory to sqlite3.Row for dictionary-like access.
    Configures WAL mode and busy timeout to avoid database lock errors.
    """
    conn = sqlite3.connect(config.DATABASE_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db() -> None:
    """
    Initializes the database tables (analyses, interviews, batch_comparisons) if they do not exist.
    Performs migrations to ensure student_id and version_number columns are present.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Table 1: Store placement analysis findings with candidate profile & version indexing
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                resume_filename TEXT NOT NULL,
                company_name TEXT NOT NULL,
                job_description TEXT,
                results_json TEXT NOT NULL,
                student_id TEXT DEFAULT 'default_student',
                version_number INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Table 2: Store mock interview progress & evaluations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interviews (
                id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL,
                current_question_index INTEGER NOT NULL DEFAULT 0,
                questions_json TEXT NOT NULL,
                answers_json TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (analysis_id) REFERENCES analyses (id)
            )
        """)

        # Table 3: Store multi-company batch comparisons & offer likelihood matrices
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS batch_comparisons (
                id TEXT PRIMARY KEY,
                student_id TEXT DEFAULT 'default_student',
                resume_filename TEXT NOT NULL,
                companies_json TEXT NOT NULL,
                results_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table 4: Store job application tracking records (#143)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_applications (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL DEFAULT 'default_student',
                company_name TEXT NOT NULL,
                role_title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Applied',
                application_date TEXT NOT NULL,
                job_url TEXT,
                job_description TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Table 5: Store registered user accounts
                # Table 5: Store registered user accounts
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Table: Secure password reset tokens (#150)
        cursor.execute("""
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)

        # Table 5: Store anonymized cohort benchmarks for peer ranking and leaderboard
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cohort_benchmarks (
                id TEXT PRIMARY KEY,
                analysis_id TEXT,
                student_handle TEXT NOT NULL,
                department TEXT NOT NULL DEFAULT 'Computer Science',
                grad_year INTEGER NOT NULL DEFAULT 2026,
                ats_score INTEGER NOT NULL DEFAULT 70,
                job_match_score INTEGER NOT NULL DEFAULT 65,
                overall_score REAL NOT NULL DEFAULT 67.5,
                target_company TEXT NOT NULL DEFAULT 'General',
                skills_count INTEGER NOT NULL DEFAULT 0,
                tier TEXT NOT NULL DEFAULT 'Silver',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table 6: Store student detailed profile information
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS student_profiles (
                student_id TEXT PRIMARY KEY,
                full_name TEXT,
                email TEXT,
                phone TEXT,
                department TEXT,
                grad_year INTEGER,
                cgpa REAL,
                target_role TEXT,
                target_company TEXT,
                skills_json TEXT,
                linkedin_url TEXT,
                github_url TEXT,
                has_resume_uploaded INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        
        # Schema migration: check if student_id and version_number exist in analyses
        # Table: Store student and user feedback (#197)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_feedback (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
                category TEXT NOT NULL,
                comment TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table: Store candidate technical self-assessments (#195)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS technical_self_assessments (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                skill_name TEXT NOT NULL,
                category TEXT NOT NULL,
                proficiency_level TEXT NOT NULL,
                years_experience REAL DEFAULT 0,
                notes TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(student_id, skill_name)
            )
        """)

        # Table: Store coding assessment submissions (#194)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS coding_submissions (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL DEFAULT 'default_student',
                analysis_id TEXT,
                question_title TEXT NOT NULL,
                company_name TEXT NOT NULL DEFAULT 'General',
                language TEXT NOT NULL DEFAULT 'python',
                code TEXT NOT NULL,
                passed INTEGER NOT NULL DEFAULT 0,
                score INTEGER NOT NULL DEFAULT 0,
                tests_passed INTEGER NOT NULL DEFAULT 0,
                total_tests INTEGER NOT NULL DEFAULT 0,
                test_results_json TEXT,
                complexity_analysis TEXT,
                feedback TEXT,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table: Store company preparation checklists (#192)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS company_preparation_checklists (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL DEFAULT 'default_student',
                company_name TEXT NOT NULL,
                checklist_json TEXT NOT NULL,
                completion_percentage REAL NOT NULL DEFAULT 0.0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table: Store student placement preparation calendar events (#190)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS preparation_calendar_events (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL DEFAULT 'default_student',
                title TEXT NOT NULL,
                event_type TEXT NOT NULL DEFAULT 'preparation',
                event_date TEXT NOT NULL,
                event_time TEXT,
                company_name TEXT,
                description TEXT,
                priority TEXT NOT NULL DEFAULT 'Medium',
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table: Store company interview experiences (#189)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interview_experiences (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                candidate_name TEXT NOT NULL DEFAULT 'Anonymous Candidate',
                company_name TEXT NOT NULL,
                role_title TEXT NOT NULL,
                interview_date TEXT NOT NULL,
                rounds_json TEXT NOT NULL,
                overall_verdict TEXT NOT NULL DEFAULT 'Offer',
                difficulty_level TEXT NOT NULL DEFAULT 'Medium',
                tips_and_preparation TEXT,
                reported_flag INTEGER NOT NULL DEFAULT 0,
                report_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table: Store user email notification preferences (#186)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_notification_preferences (
                student_id TEXT PRIMARY KEY,
                email TEXT,
                email_enabled INTEGER NOT NULL DEFAULT 1,
                notify_welcome INTEGER NOT NULL DEFAULT 1,
                notify_application_created INTEGER NOT NULL DEFAULT 1,
                notify_status_change INTEGER NOT NULL DEFAULT 1,
                notify_interview_reminder INTEGER NOT NULL DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table: Store recently viewed jobs by candidates (#201)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recently_viewed_jobs (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                company_name TEXT NOT NULL,
                role_title TEXT NOT NULL,
                location TEXT DEFAULT 'Remote',
                salary_range TEXT,
                apply_url TEXT,
                viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(student_id, job_id)
            )
        """)

        # Table: Store Gemini API Usage & Cost Monitoring Logs (#215)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gemini_api_logs (
                id TEXT PRIMARY KEY,
                endpoint TEXT NOT NULL,
                model_name TEXT NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                candidate_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                estimated_cost_usd REAL DEFAULT 0.0,
                latency_ms INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'success',
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("PRAGMA table_info(analyses)")
        existing_cols = [col[1] for col in cursor.fetchall()]
        if "student_id" not in existing_cols:
            cursor.execute("ALTER TABLE analyses ADD COLUMN student_id TEXT DEFAULT 'default_student'")
        if "version_number" not in existing_cols:
            cursor.execute("ALTER TABLE analyses ADD COLUMN version_number INTEGER DEFAULT 1")

        # Users table schema migrations (#206)
        cursor.execute("PRAGMA table_info(users)")
        user_cols = [col[1] for col in cursor.fetchall()]
        if "is_verified" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN is_verified INTEGER DEFAULT 0")
        if "verification_token" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN verification_token TEXT")
        if "token_created_at" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN token_created_at TIMESTAMP")

        # Indexes for query, sorting, and version lookup performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_analyses_created_at ON analyses (created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_analyses_student_version ON analyses (student_id, version_number ASC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_interviews_analysis_id ON interviews (analysis_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_comparisons_created ON batch_comparisons (created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_applications_student ON job_applications (student_id, created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cohort_overall ON cohort_benchmarks (overall_score DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cohort_dept_year ON cohort_benchmarks (department, grad_year)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cohort_analysis_id ON cohort_benchmarks (analysis_id)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_checklist_student_comp ON company_preparation_checklists (student_id, company_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_calendar_student_date ON preparation_calendar_events (student_id, event_date ASC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_experiences_company ON interview_experiences (company_name, interview_date DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_coding_subs_student ON coding_submissions (student_id, submitted_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tech_assessments_student ON technical_self_assessments (student_id, category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_feedback_student ON user_feedback (student_id, created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_viewed_jobs_student ON recently_viewed_jobs (student_id, viewed_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gemini_api_logs_created ON gemini_api_logs (created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gemini_api_logs_status ON gemini_api_logs (status)")

        # Seed initial cohort peers if table is currently empty
        cursor.execute("SELECT COUNT(*) FROM cohort_benchmarks")
        if cursor.fetchone()[0] == 0:
            _seed_cohort_benchmarks(cursor)
        
        conn.commit()
        logger.info("Database schema checked and initialized successfully.")
        
        # Run any pending versioned file-based migrations (#204)
        try:
            from utils.migrations import run_database_migrations
            run_database_migrations(config.DATABASE_PATH)
        except Exception as mig_err:
            logger.warning(f"Note: Automatic migration runner skipped during init: {mig_err}")
    except Exception as e:
        logger.error(f"Failed to initialize SQLite database: {str(e)}")
        raise e
    finally:
        conn.close()

def save_analysis(
    analysis_id: str,
    resume_filename: str,
    company_name: str,
    job_description: str,
    results_dict: dict,
    student_id: Optional[str] = None,
    version_number: Optional[int] = None
) -> None:
    """Inserts a newly generated coordinator analysis into the database.
    Automatically assigns candidate student_id and auto-increments version_number if omitted."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()

        # Compute next version number if not explicitly specified
        if version_number is None or version_number <= 0:
            cursor.execute(
                "SELECT COALESCE(MAX(version_number), 0) + 1 FROM analyses WHERE student_id = ?",
                (effective_student_id,)
            )
            version_number = cursor.fetchone()[0]

        cursor.execute("""
            INSERT INTO analyses (id, resume_filename, company_name, job_description, results_json, student_id, version_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            analysis_id,
            resume_filename,
            company_name,
            job_description,
            json.dumps(results_dict),
            effective_student_id,
            version_number
        ))
        conn.commit()
        logger.info(f"Analysis saved with ID: {analysis_id} (Student: {effective_student_id}, Version: v{version_number})")

        # Automatically register or update candidate on the cohort benchmark leaderboard
        try:
            res_analysis = results_dict.get("resume_analysis", {}) if isinstance(results_dict, dict) else {}
            job_match = results_dict.get("job_match", {}) if isinstance(results_dict, dict) else {}
            ats_val = int(res_analysis.get("ats_score", 70))
            match_val = int(job_match.get("match_percentage", 65))
            skills_cnt = len(job_match.get("matched_skills", [])) if isinstance(job_match.get("matched_skills"), list) else 0

            handle_suffix = abs(hash(analysis_id)) % 100
            anon_handle = f"Candidate_{handle_suffix:02d}"

            record_or_update_cohort_benchmark(
                analysis_id=analysis_id,
                student_handle=anon_handle,
                department="Computer Science",
                grad_year=2026,
                ats_score=ats_val,
                job_match_score=match_val,
                target_company=company_name or "General",
                skills_count=skills_cnt
            )
        except Exception as bench_err:
            logger.warning(f"Failed to record cohort benchmark on save_analysis: {bench_err}")
    except Exception as e:
        logger.error(f"Error saving analysis {analysis_id} to database: {str(e)}")
        raise e
    finally:
        conn.close()

def get_analysis(analysis_id: str) -> dict:
    """
    Retrieves and returns an analysis record by ID.
    Loads and injects the deserialized JSON results.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,))
        row = cursor.fetchone()
        if row:
            record = dict(row)
            record["results"] = json.loads(record["results_json"])
            return record
        return None
    except Exception as e:
        logger.error(f"Error fetching analysis {analysis_id}: {str(e)}")
        raise e
    finally:
        conn.close()

def get_student_versions(student_id: str, company_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieves all resume analysis versions for a candidate student_id,
    ordered by version_number ASC. Deserializes results_json and computes
    ATS score and match percentage for each version.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()
        
        if company_name:
            cursor.execute("""
                SELECT * FROM analyses
                WHERE student_id = ? AND company_name = ?
                ORDER BY version_number ASC, created_at ASC
            """, (effective_student_id, company_name.strip()))
        else:
            cursor.execute("""
                SELECT * FROM analyses
                WHERE student_id = ?
                ORDER BY version_number ASC, created_at ASC
            """, (effective_student_id,))

        rows = cursor.fetchall()
        versions = []
        for row in rows:
            rec = dict(row)
            try:
                rec["results"] = json.loads(rec.get("results_json", "{}"))
                res_analysis = rec["results"].get("resume_analysis", {})
                job_match = rec["results"].get("job_match", {})
                rec["ats_score"] = res_analysis.get("ats_score", 0)
                rec["match_percentage"] = job_match.get("match_percentage", 0)
            except Exception:
                rec["results"] = {}
                rec["ats_score"] = 0
                rec["match_percentage"] = 0
            versions.append(rec)
        return versions
    except Exception as e:
        logger.error(f"Error fetching versions for student {student_id}: {str(e)}")
        raise e
    finally:
        conn.close()

def get_previous_analysis(student_id: str, current_version: int) -> Optional[Dict[str, Any]]:
    """
    Retrieves the immediately preceding analysis record for a candidate.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()
        cursor.execute("""
            SELECT * FROM analyses
            WHERE student_id = ? AND version_number < ?
            ORDER BY version_number DESC
            LIMIT 1
        """, (effective_student_id, current_version))
        row = cursor.fetchone()
        if row:
            rec = dict(row)
            try:
                rec["results"] = json.loads(rec.get("results_json", "{}"))
            except Exception:
                rec["results"] = {}
            return rec
        return None
    except Exception as e:
        logger.error(f"Error fetching previous analysis for student {student_id} (current v{current_version}): {str(e)}")
        raise e
    finally:
        conn.close()

def create_interview_session(interview_id: str, analysis_id: str, questions_list: list) -> None:
    """
    Creates a new mock interview session referencing an analysis.
    Stores the list of 15 generated questions (HR, Technical, Behavioral).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO interviews (id, analysis_id, current_question_index, questions_json, answers_json, completed)
            VALUES (?, ?, 0, ?, ?, 0)
        """, (interview_id, analysis_id, json.dumps(questions_list), json.dumps([])))
        conn.commit()
        logger.info(f"Interview session initialized with ID: {interview_id}")
    except Exception as e:
        logger.error(f"Error initializing interview session {interview_id}: {str(e)}")
        raise e
    finally:
        conn.close()

def get_interview_session(interview_id: str) -> dict:
    """
    Retrieves and returns an interview session record by ID.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM interviews WHERE id = ?", (interview_id,))
        row = cursor.fetchone()
        if row:
            record = dict(row)
            record["questions"] = json.loads(record["questions_json"])
            record["answers"] = json.loads(record["answers_json"])
            return record
        return None
    except Exception as e:
        logger.error(f"Error fetching interview session {interview_id}: {str(e)}")
        raise e
    finally:
        conn.close()

def update_interview_session(interview_id: str, current_question_index: int, answers_list: list, completed: bool) -> None:
    """
    Updates the progress, answer list, and completion status of an active interview session.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE interviews
            SET current_question_index = ?, answers_json = ?, completed = ?
            WHERE id = ?
        """, (current_question_index, json.dumps(answers_list), 1 if completed else 0, interview_id))
        conn.commit()
        logger.info(f"Interview session {interview_id} updated. Current index: {current_question_index}. Completed: {completed}")
    except Exception as e:
        logger.error(f"Error updating interview session {interview_id}: {str(e)}")
        raise e
    finally:
        conn.close()

def get_recent_analyses(limit: int = 10) -> list:
    """
    Retrieves the most recent analysis sessions ordered by created_at DESC.
    Includes parsed resume ATS score and company match percentage for quick display.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, resume_filename, company_name, job_description, results_json, created_at
            FROM analyses
            ORDER BY created_at DESC
            LIMIT ?
        """, (max(1, min(limit, 50)),))
        rows = cursor.fetchall()
        recent = []
        for row in rows:
            record = dict(row)
            try:
                parsed_results = json.loads(record.pop("results_json", "{}"))
                resume_analysis = parsed_results.get("resume_analysis", {})
                job_match = parsed_results.get("job_match", {})
                record["ats_score"] = resume_analysis.get("ats_score", 0)
                record["match_percentage"] = job_match.get("match_percentage", 0)
            except Exception:
                record["ats_score"] = 0
                record["match_percentage"] = 0
            recent.append(record)
        return recent
    except Exception as e:
        logger.error(f"Error fetching recent analyses: {str(e)}")
        raise e
    finally:
        conn.close()

def delete_analysis(analysis_id: str) -> bool:
    """
    Deletes an analysis record and its corresponding interview sessions and benchmark entries.
    Returns True if an analysis was deleted, False if not found.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM interviews WHERE analysis_id = ?", (analysis_id,))
        cursor.execute("DELETE FROM cohort_benchmarks WHERE analysis_id = ?", (analysis_id,))
        cursor.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info(f"Deleted analysis {analysis_id} and associated interview data.")
        return deleted
    except Exception as e:
        logger.error(f"Error deleting analysis {analysis_id}: {str(e)}")
        raise e
    finally:
        conn.close()


def get_analyses_history(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Retrieves past placement analysis sessions ordered by created_at DESC (newest first) (#159).
    Includes formatted date, target role, target company, ATS score, match percentage, and metadata.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            SELECT id, resume_filename, company_name, job_description, results_json,
                   student_id, version_number, created_at
            FROM analyses
            ORDER BY created_at DESC, rowid DESC
        """
        params: List[Any] = []
        if limit is not None and limit > 0:
            query += " LIMIT ?"
            params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        history = []
        for row in rows:
            record = dict(row)
            try:
                raw_json = record.pop("results_json", "{}")
                parsed = json.loads(raw_json) if isinstance(raw_json, str) else (raw_json or {})
                resume_analysis = parsed.get("resume_analysis", {})
                job_match = parsed.get("job_match", {})

                # ATS score resolution
                ats = parsed.get("ats_score") or resume_analysis.get("ats_score", 0)
                record["ats_score"] = int(ats)

                # Match percentage resolution
                match = parsed.get("match_percentage") or job_match.get("match_percentage", 0)
                record["match_percentage"] = int(match)

                # Target role resolution
                target_role = (
                    parsed.get("target_role")
                    or job_match.get("target_role")
                    or parsed.get("role_title")
                    or job_match.get("role_title")
                    or ""
                )
                if not target_role and record.get("job_description"):
                    first_line = record["job_description"].split("\n")[0].strip()
                    target_role = first_line[:50] if first_line else "Software Engineer"
                elif not target_role:
                    target_role = "Software Engineer"

                record["target_role"] = target_role
            except Exception as parse_err:
                logger.warning(f"Error parsing analysis {record.get('id')} results: {parse_err}")
                record["ats_score"] = 0
                record["match_percentage"] = 0
                record["target_role"] = "Software Engineer"

            history.append(record)
        return history
    except Exception as e:
        logger.error(f"Error fetching analyses history: {str(e)}")
        raise e
    finally:
        conn.close()


def create_database_backup(backup_destination_path: str) -> str:
    """
    Performs an online, zero-downtime hot backup of the SQLite database using SQLite's
    built-in backup API. Guarantees ACID transactional consistency without table locks.

    Parameters:
        backup_destination_path: Absolute or relative file path for the backup .db file.

    Returns:
        The backup_destination_path string on success.
    """
    src_conn = get_db_connection()
    try:
        logger.info(f"Initiating online database backup to: {backup_destination_path}")
        dest_conn = sqlite3.connect(backup_destination_path)
        with dest_conn:
            src_conn.backup(dest_conn, pages=20, sleep=0.01)
        dest_conn.close()
        logger.info("Online database backup completed successfully.")
        return backup_destination_path
    except Exception as exc:
        logger.error(f"Failed to create database backup: {exc}")
        raise RuntimeError(f"Database backup failed: {exc}") from exc
    finally:
        src_conn.close()


def verify_database_integrity() -> Dict[str, Any]:
    """
    Runs SQLite integrity PRAGMA checks and structural statistics.
    Returns a dictionary with status, integrity errors (if any), table row counts,
    and journal mode details.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        integrity_rows = [row[0] for row in cursor.fetchall()]
        is_healthy = len(integrity_rows) == 1 and integrity_rows[0].lower() == "ok"

        # Gather table metrics
        cursor.execute("SELECT COUNT(*) FROM analyses")
        analyses_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM interviews")
        interviews_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM cohort_benchmarks")
        cohort_count = cursor.fetchone()[0]

        cursor.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0]

        return {
            "healthy": is_healthy,
            "status": "ok" if is_healthy else "corrupted",
            "messages": integrity_rows,
            "tables": {
                "analyses_count": analyses_count,
                "interviews_count": interviews_count,
                "cohort_benchmarks_count": cohort_count,
            },
            "journal_mode": journal_mode,
        }
    except Exception as exc:
        logger.error(f"Error executing database integrity verification: {exc}")
        return {
            "healthy": False,
            "status": "error",
            "messages": [str(exc)],
            "tables": {},
            "journal_mode": "unknown",
        }
    finally:
        conn.close()


def save_batch_comparison(
    batch_id: str,
    student_id: str,
    resume_filename: str,
    companies_list: List[str],
    results_dict: Dict[str, Any]
) -> None:
    """
    Persists a multi-company batch comparison result into the SQLite database.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()
        cursor.execute("""
            INSERT OR REPLACE INTO batch_comparisons (
                id, student_id, resume_filename, companies_json, results_json
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            batch_id,
            effective_student_id,
            resume_filename,
            json.dumps(companies_list),
            json.dumps(results_dict)
        ))
        conn.commit()
        logger.info(f"Batch comparison saved with ID: {batch_id} ({len(companies_list)} companies)")
    except Exception as e:
        logger.error(f"Error saving batch comparison {batch_id}: {e}")
        raise e
    finally:
        conn.close()


def get_batch_comparison(batch_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves a multi-company batch comparison record by ID, deserializing stored JSON.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM batch_comparisons WHERE id = ?", (batch_id,))
        row = cursor.fetchone()
        if row:
            rec = dict(row)
            rec["companies"] = json.loads(rec["companies_json"])
            rec["results"] = json.loads(rec["results_json"])
            return rec
        return None
    except Exception as e:
        logger.error(f"Error fetching batch comparison {batch_id}: {e}")
        raise e
    finally:
        conn.close()



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
) -> None:
    """
    Saves or updates a candidate job application record (#143).
    Ensures per-user data segregation.
    """
    import datetime
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        date_str = application_date or datetime.date.today().isoformat()
        cursor.execute("""
            INSERT OR REPLACE INTO job_applications (
                id, student_id, company_name, role_title, status, application_date, job_url, job_description, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            app_id,
            student_id.strip() if student_id else "default_student",
            company_name.strip(),
            role_title.strip(),
            status.strip(),
            date_str,
            (job_url or "").strip(),
            (job_description or "").strip(),
            (notes or "").strip(),
        ))
        conn.commit()
        logger.info(f"Saved job application {app_id} for student {student_id}")
    except Exception as e:
        logger.error(f"Error saving job application {app_id}: {e}")
        raise e
    finally:
        conn.close()


def get_job_applications(
    student_id: str,
    status_filter: Optional[str] = None,
    search_query: Optional[str] = None,
    location_filter: Optional[str] = None,
    job_type_filter: Optional[str] = None,
    experience_level_filter: Optional[str] = None,
    sort_by: str = "recent"
) -> List[Dict[str, Any]]:
    """
    Retrieves all job application records for a specific student, with advanced search,
    location, job type, and experience filtering (#143, #193).
    Strictly enforces user data isolation.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        conditions = ["student_id = ?"]
        params: List[Any] = [student_id.strip() if student_id else "default_student"]

        if status_filter and status_filter.strip() and status_filter.strip().lower() not in ("all", "any"):
            conditions.append("LOWER(status) = LOWER(?)")
            params.append(status_filter.strip())

        if search_query and search_query.strip():
            kw = f"%{search_query.strip().lower()}%"
            conditions.append("(LOWER(company_name) LIKE ? OR LOWER(role_title) LIKE ? OR LOWER(COALESCE(job_description, '')) LIKE ?)")
            params.extend([kw, kw, kw])

        if location_filter and location_filter.strip() and location_filter.strip().lower() not in ("all", "any"):
            conditions.append("LOWER(COALESCE(location, '')) LIKE LOWER(?)")
            params.append(f"%{location_filter.strip()}%")

        if job_type_filter and job_type_filter.strip() and job_type_filter.strip().lower() not in ("all", "any"):
            conditions.append("LOWER(COALESCE(job_type, '')) = LOWER(?)")
            params.append(job_type_filter.strip())

        if experience_level_filter and experience_level_filter.strip() and experience_level_filter.strip().lower() not in ("all", "any"):
            conditions.append("LOWER(COALESCE(experience_level, '')) = LOWER(?)")
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
    finally:
        conn.close()


def delete_job_application(app_id: str, student_id: str) -> bool:
    """
    Deletes a specific job application record owned by student_id (#143).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM job_applications WHERE id = ? AND student_id = ?", (app_id, student_id))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting job application {app_id}: {e}")
        return False
    finally:
        conn.close()


def update_job_application_status(app_id: str, student_id: str, new_status: str) -> bool:
    """
    Updates the pipeline status of a specific job application (#143).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE job_applications SET status = ? WHERE id = ? AND student_id = ?",
            (new_status.strip(), app_id, student_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating job application status for {app_id}: {e}")
        return False
    finally:
        conn.close()


def _seed_cohort_benchmarks(cursor: sqlite3.Cursor) -> None:
    """
    Populates default cohort records representing diverse university branch peers.
    """
    seed_peers = [
        ("peer-01", "AlgoMaster_99", "Computer Science", 2026, 95, 94, 94.4, "Google", 9, "Platinum"),
        ("peer-02", "CloudArchitect_42", "Information Technology", 2026, 92, 91, 91.4, "Microsoft", 8, "Platinum"),
        ("peer-03", "SystemSurgeon_18", "Computer Science", 2026, 90, 89, 89.4, "Amazon", 8, "Platinum"),
        ("peer-04", "DataVoyager_77", "Data Science & AI", 2026, 88, 86, 86.9, "Adobe", 7, "Gold"),
        ("peer-05", "DevScholar_12", "Computer Science", 2026, 86, 84, 84.9, "Uber", 7, "Gold"),
        ("peer-06", "BinaryMonk_33", "Electronics & Comm", 2026, 85, 82, 83.3, "Cisco", 6, "Gold"),
        ("peer-07", "PixelCraft_29", "Information Technology", 2026, 84, 83, 83.4, "Swiggy", 6, "Gold"),
        ("peer-08", "CodeCrafter_05", "Computer Science", 2026, 83, 80, 81.3, "Razorpay", 6, "Gold"),
        ("peer-09", "NeuralNomad_64", "Data Science & AI", 2025, 82, 79, 80.3, "Oracle", 6, "Gold"),
        ("peer-10", "SyntaxSamurai_81", "Computer Science", 2025, 81, 78, 79.3, "Goldman Sachs", 6, "Gold"),
        ("peer-11", "KernelKnight_56", "Electronics & Comm", 2026, 80, 77, 78.3, "Qualcomm", 5, "Gold"),
        ("peer-12", "StackWizard_21", "Information Technology", 2026, 78, 76, 76.9, "Flipkart", 5, "Silver"),
        ("peer-13", "LogicWhiz_44", "Computer Science", 2026, 77, 75, 75.9, "TCS", 5, "Silver"),
        ("peer-14", "CyberFalcon_87", "Computer Science", 2025, 76, 74, 74.9, "Infosys", 5, "Silver"),
        ("peer-15", "QuantumCoder_19", "Electronics & Comm", 2027, 75, 72, 73.3, "Accenture", 4, "Silver"),
        ("peer-16", "ByteSurgeon_63", "Information Technology", 2026, 74, 71, 72.3, "Capgemini", 4, "Silver"),
        ("peer-17", "MatrixMaster_38", "Electrical Engineering", 2026, 73, 70, 71.3, "Wipro", 4, "Silver"),
        ("peer-18", "PromptArchitect_90", "Data Science & AI", 2026, 72, 69, 70.3, "Cognizant", 4, "Silver"),
        ("peer-19", "GitGuru_08", "Computer Science", 2027, 70, 68, 68.9, "General", 4, "Silver"),
        ("peer-20", "ScriptSage_52", "Electronics & Comm", 2025, 69, 66, 67.3, "General", 4, "Silver"),
        ("peer-21", "SiliconPioneer_35", "Electrical Engineering", 2026, 67, 65, 65.9, "General", 3, "Silver"),
        ("peer-22", "TurboCoder_14", "Mechanical Engineering", 2026, 64, 62, 62.9, "General", 3, "Bronze"),
        ("peer-23", "ApexDev_93", "Computer Science", 2027, 62, 60, 60.9, "General", 3, "Bronze"),
        ("peer-24", "VeloceBytes_41", "Civil Engineering", 2026, 58, 55, 56.3, "General", 2, "Bronze"),
    ]
    cursor.executemany("""
        INSERT OR IGNORE INTO cohort_benchmarks 
        (id, student_handle, department, grad_year, ats_score, job_match_score, overall_score, target_company, skills_count, tier)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, seed_peers)
    logger.info(f"Seeded {len(seed_peers)} default peer cohort benchmark records.")


def record_or_update_cohort_benchmark(
    analysis_id: str,
    student_handle: str,
    department: str = "Computer Science",
    grad_year: int = 2026,
    ats_score: int = 70,
    job_match_score: int = 65,
    overall_score: Optional[float] = None,
    target_company: str = "General",
    skills_count: int = 0,
    tier: Optional[str] = None
) -> str:
    """
    Inserts or updates an anonymized student evaluation in the cohort_benchmarks table.
    Computes overall composite score and achievement tier if omitted.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Calculate composite score (45% ATS, 55% Job Match)
        if overall_score is None:
            overall_score = round((ats_score * 0.45) + (job_match_score * 0.55), 1)

        # Derive achievement tier if omitted
        if not tier:
            if overall_score >= 88.0:
                tier = "Platinum"
            elif overall_score >= 78.0:
                tier = "Gold"
            elif overall_score >= 65.0:
                tier = "Silver"
            else:
                tier = "Bronze"

        # Check if record for this analysis_id already exists
        cursor.execute("SELECT id FROM cohort_benchmarks WHERE analysis_id = ?", (analysis_id,))
        existing = cursor.fetchone()

        if existing:
            benchmark_id = existing[0]
            cursor.execute("""
                UPDATE cohort_benchmarks
                SET student_handle = ?, department = ?, grad_year = ?,
                    ats_score = ?, job_match_score = ?, overall_score = ?,
                    target_company = ?, skills_count = ?, tier = ?
                WHERE id = ?
            """, (
                student_handle, department, grad_year,
                ats_score, job_match_score, overall_score,
                target_company, skills_count, tier,
                benchmark_id
            ))
        else:
            benchmark_id = f"cohort-{analysis_id}"
            cursor.execute("""
                INSERT INTO cohort_benchmarks
                (id, analysis_id, student_handle, department, grad_year, ats_score, job_match_score, overall_score, target_company, skills_count, tier)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                benchmark_id, analysis_id, student_handle, department, grad_year,
                ats_score, job_match_score, overall_score, target_company, skills_count, tier
            ))

        conn.commit()
        return benchmark_id
    except Exception as e:
        logger.error(f"Error saving cohort benchmark for analysis {analysis_id}: {e}")
        raise e
    finally:
        conn.close()


def get_cohort_benchmark_by_analysis_id(analysis_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves the cohort benchmark record for a specific analysis ID.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM cohort_benchmarks WHERE analysis_id = ?", (analysis_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Error fetching cohort benchmark for {analysis_id}: {e}")
        return None
    finally:
        conn.close()


def get_cohort_benchmarks(
    department: Optional[str] = None,
    grad_year: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Retrieves sorted cohort benchmark entries ordered by overall_score DESC.
    Supports filtering by department, graduation year, and keyword search.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        conditions = []
        params = []

        if department and department.strip() and department.strip().lower() not in ("all", "any"):
            conditions.append("LOWER(department) = LOWER(?)")
            params.append(department.strip())

        if grad_year and int(grad_year) > 0:
            conditions.append("grad_year = ?")
            params.append(int(grad_year))

        if search and search.strip():
            kw = f"%{search.strip().lower()}%"
            conditions.append("(LOWER(student_handle) LIKE ? OR LOWER(target_company) LIKE ? OR LOWER(department) LIKE ?)")
            params.extend([kw, kw, kw])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT * FROM cohort_benchmarks
            {where_clause}
            ORDER BY overall_score DESC, ats_score DESC, job_match_score DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        benchmarks = []
        for idx, row in enumerate(rows):
            rec = dict(row)
            rec["rank"] = offset + idx + 1
            benchmarks.append(rec)

        return benchmarks
    except Exception as e:
        logger.error(f"Error fetching cohort benchmarks: {e}")
        return []
    finally:
        conn.close()


def get_cohort_stats(
    department: Optional[str] = None,
    grad_year: Optional[int] = None
) -> Dict[str, Any]:
    """
    Computes aggregate metrics across the specified cohort segment:
    count, avg_ats, avg_match, avg_overall, max_score, and tier distribution.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        conditions = []
        params = []

        if department and department.strip() and department.strip().lower() not in ("all", "any"):
            conditions.append("LOWER(department) = LOWER(?)")
            params.append(department.strip())

        if grad_year and int(grad_year) > 0:
            conditions.append("grad_year = ?")
            params.append(int(grad_year))

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cursor.execute(f"""
            SELECT 
                COUNT(*) as total_students,
                COALESCE(AVG(ats_score), 0) as avg_ats,
                COALESCE(AVG(job_match_score), 0) as avg_match,
                COALESCE(AVG(overall_score), 0) as avg_overall,
                COALESCE(MAX(overall_score), 0) as max_overall,
                COALESCE(SUM(CASE WHEN tier = 'Platinum' THEN 1 ELSE 0 END), 0) as platinum_count,
                COALESCE(SUM(CASE WHEN tier = 'Gold' THEN 1 ELSE 0 END), 0) as gold_count,
                COALESCE(SUM(CASE WHEN tier = 'Silver' THEN 1 ELSE 0 END), 0) as silver_count,
                COALESCE(SUM(CASE WHEN tier = 'Bronze' THEN 1 ELSE 0 END), 0) as bronze_count
            FROM cohort_benchmarks
            {where_clause}
        """, params)

        stats = dict(cursor.fetchone())
        stats["avg_ats"] = round(float(stats.get("avg_ats", 0)), 1)
        stats["avg_match"] = round(float(stats.get("avg_match", 0)), 1)
        stats["avg_overall"] = round(float(stats.get("avg_overall", 0)), 1)
        stats["max_overall"] = round(float(stats.get("max_overall", 0)), 1)

        # Department distribution
        cursor.execute(f"""
            SELECT department, COUNT(*) as count
            FROM cohort_benchmarks
            {where_clause}
            GROUP BY department
            ORDER BY count DESC
        """, params)
        stats["department_breakdown"] = [dict(r) for r in cursor.fetchall()]

        return stats
    except Exception as e:
        logger.error(f"Error computing cohort statistics: {e}")
        return {
            "total_students": 0,
            "avg_ats": 0.0,
            "avg_match": 0.0,
            "avg_overall": 0.0,
            "max_overall": 0.0,
            "platinum_count": 0,
            "gold_count": 0,
            "silver_count": 0,
            "bronze_count": 0,
            "department_breakdown": []
        }
    finally:
        conn.close()




def get_user_placement_history(
    student_id: str = "default_student",
    company_filter: Optional[str] = None,
    sort_by: str = "date_desc"
) -> Dict[str, Any]:
    """
    Saves and retrieves comprehensive previous placement analysis history for a specific user (#149).
    Includes per-student data isolation, ATS score tracking, role match percentages,
    and historical performance metrics.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()

        query = """
            SELECT id, resume_filename, company_name, job_description, results_json,
                   student_id, version_number, created_at
            FROM analyses
            WHERE student_id = ?
        """
        params: List[Any] = [effective_student_id]

        if company_filter and company_filter.strip() and company_filter.strip().lower() not in ("all", "any"):
            query += " AND LOWER(company_name) LIKE ?"
            params.append(f"%{company_filter.strip().lower()}%")

        if sort_by == "score_desc":
            # Will sort in python after parsing ATS score
            query += " ORDER BY created_at DESC"
        elif sort_by == "date_asc":
            query += " ORDER BY created_at ASC"
        else:
            query += " ORDER BY created_at DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        records = []
        ats_scores = []
        match_scores = []
        company_counts: Dict[str, int] = {}

        for row in rows:
            rec = dict(row)
            try:
                raw_json = rec.pop("results_json", "{}")
                parsed = json.loads(raw_json)
                rec["results"] = parsed

                # Score resolution
                ats = parsed.get("ats_score") or parsed.get("resume_analysis", {}).get("ats_score", 0)
                match = parsed.get("job_match_score") or parsed.get("job_match", {}).get("match_percentage", 0)

                rec["ats_score"] = int(ats)
                rec["match_percentage"] = int(match)
                ats_scores.append(rec["ats_score"])
                match_scores.append(rec["match_percentage"])

                # Extract extracted skills & missing skills count
                rec["matched_skills_count"] = len(parsed.get("matched_skills") or parsed.get("job_match", {}).get("matched_skills", []))
                rec["missing_skills_count"] = len(parsed.get("missing_skills") or parsed.get("job_match", {}).get("missing_skills", []))

                comp = rec.get("company_name", "General")
                company_counts[comp] = company_counts.get(comp, 0) + 1

            except Exception as parse_err:
                logger.warning(f"Failed to parse analysis payload for record {rec.get('id')}: {parse_err}")
                rec["results"] = {}
                rec["ats_score"] = 0
                rec["match_percentage"] = 0
                rec["matched_skills_count"] = 0
                rec["missing_skills_count"] = 0

            records.append(rec)

        if sort_by == "score_desc":
            records.sort(key=lambda x: x["ats_score"], reverse=True)

        avg_ats = round(sum(ats_scores) / len(ats_scores), 1) if ats_scores else 0.0
        avg_match = round(sum(match_scores) / len(match_scores), 1) if match_scores else 0.0
        highest_ats = max(ats_scores) if ats_scores else 0

        return {
            "student_id": effective_student_id,
            "total_analyses": len(records),
            "average_ats_score": avg_ats,
            "average_match_percentage": avg_match,
            "highest_ats_score": highest_ats,
            "company_counts": company_counts,
            "analyses": records
        }

    except Exception as e:
        logger.error(f"Error fetching placement analysis history for {student_id}: {e}")
        return {
            "student_id": student_id,
            "total_analyses": 0,
            "average_ats_score": 0.0,
            "average_match_percentage": 0.0,
            "highest_ats_score": 0,
            "company_counts": {},
            "analyses": []
        }
    finally:
        conn.close()


def get_student_interview_history(student_id: str = "default_student") -> List[Dict[str, Any]]:
    """
    Retrieves full mock interview session history for a student across all attempts (#144).
    Calculates completion rates, scores per question type (Technical, HR, Behavioral), and overall score.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                i.id AS session_id,
                i.analysis_id,
                i.current_question_index,
                i.questions_json,
                i.answers_json,
                i.completed,
                a.company_name,
                a.created_at AS analysis_date
            FROM interviews i
            JOIN analyses a ON i.analysis_id = a.id
            WHERE a.student_id = ?
            ORDER BY a.created_at DESC, i.id DESC
        """, (student_id,))
        rows = cursor.fetchall()

        history = []
        for r in rows:
            rec = dict(r)
            questions = json.loads(rec.get("questions_json", "[]") or "[]")
            answers = json.loads(rec.get("answers_json", "[]") or "[]")

            scores = []
            type_scores = {"Technical": [], "HR": [], "Behavioral": []}
            for ans in answers:
                eval_data = ans.get("evaluation", {})
                score = eval_data.get("score")
                if score is not None:
                    try:
                        score_val = float(score)
                        scores.append(score_val)
                        q_type = ans.get("type", "General")
                        if q_type in type_scores:
                            type_scores[q_type].append(score_val)
                    except (ValueError, TypeError):
                        pass

            avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0
            technical_avg = round(sum(type_scores["Technical"]) / len(type_scores["Technical"]), 1) if type_scores["Technical"] else 0.0
            hr_avg = round(sum(type_scores["HR"]) / len(type_scores["HR"]), 1) if type_scores["HR"] else 0.0
            behavioral_avg = round(sum(type_scores["Behavioral"]) / len(type_scores["Behavioral"]), 1) if type_scores["Behavioral"] else 0.0

            history.append({
                "session_id": rec["session_id"],
                "analysis_id": rec["analysis_id"],
                "company_name": rec.get("company_name", "General"),
                "total_questions": len(questions),
                "answered_questions": len(answers),
                "completed": bool(rec.get("completed", 0)),
                "average_score": avg_score,
                "technical_score": technical_avg,
                "hr_score": hr_avg,
                "behavioral_score": behavioral_avg,
                "date": rec.get("analysis_date", ""),
                "questions": questions,
                "answers": answers
            })
        return history
    except Exception as e:
        logger.error(f"Error retrieving student interview history: {e}")
        return []
    finally:
        conn.close()


def get_student_interview_performance_analytics(student_id: str = "default_student") -> Dict[str, Any]:
    """
    Computes performance analytics, score trends, and strengths/weaknesses for mock interviews (#144).
    """
    history = get_student_interview_history(student_id=student_id)
    if not history:
        return {
            "total_sessions": 0,
            "completed_sessions": 0,
            "total_questions_answered": 0,
            "overall_average_score": 0.0,
            "technical_average": 0.0,
            "hr_average": 0.0,
            "behavioral_average": 0.0,
            "score_trend": [],
            "strengths": [],
            "weaknesses": [],
            "sessions": []
        }

    total_sessions = len(history)
    completed_sessions = sum(1 for s in history if s["completed"])
    total_answered = sum(s["answered_questions"] for s in history)

    all_scores = [s["average_score"] for s in history if s["average_score"] > 0]
    overall_avg = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0.0

    tech_scores = [s["technical_score"] for s in history if s["technical_score"] > 0]
    hr_scores = [s["hr_score"] for s in history if s["hr_score"] > 0]
    behav_scores = [s["behavioral_score"] for s in history if s["behavioral_score"] > 0]

    tech_avg = round(sum(tech_scores) / len(tech_scores), 1) if tech_scores else 0.0
    hr_avg = round(sum(hr_scores) / len(hr_scores), 1) if hr_scores else 0.0
    behav_avg = round(sum(behav_scores) / len(behav_scores), 1) if behav_scores else 0.0

    # Trend line sorted chronologically
    score_trend = [
        {
            "date": s.get("date", "")[:10],
            "company": s["company_name"],
            "score": s["average_score"],
            "session_id": s["session_id"]
        }
        for s in reversed(history) if s["average_score"] > 0
    ]

    # Strengths and Weaknesses analysis
    strengths = []
    weaknesses = []

    domain_eval = [
        ("Technical Concepts", tech_avg),
        ("HR and Culture Fit", hr_avg),
        ("Behavioral and STAR Structure", behav_avg)
    ]

    for name, avg in domain_eval:
        if avg >= 75.0:
            strengths.append(f"{name} ({avg}/100) - Strong grasp of core concepts and structured communication")
        elif avg > 0:
            weaknesses.append(f"{name} ({avg}/100) - Needs further practice with concise articulation and situational examples")

    if not strengths and overall_avg >= 70.0:
        strengths.append("Consistent practice and willingness to complete structured multi-round interviews.")
    if not weaknesses:
        weaknesses.append("Practice speaking with greater conciseness and quantifiable impact metrics.")

    return {
        "total_sessions": total_sessions,
        "completed_sessions": completed_sessions,
        "total_questions_answered": total_answered,
        "overall_average_score": overall_avg,
        "technical_average": tech_avg,
        "hr_average": hr_avg,
        "behavioral_average": behav_avg,
        "score_trend": score_trend,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "sessions": history
    }


def create_user(user_id: str, name: str, email: str, password_hash: str) -> bool:
    """Create a new user account."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (id, name, email, password_hash)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, name.strip(), email.strip().lower(), password_hash)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception as exc:
        logger.error(f"Error creating user: {exc}")
        raise
    finally:
        conn.close()


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Retrieve a user by email address."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE email = ?",
            (email.strip().lower(),)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a user by their ID"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, email, password_hash, created_at FROM users WHERE id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_student_profile(
    student_id: str,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    department: Optional[str] = None,
    grad_year: Optional[int] = None,
    cgpa: Optional[float] = None,
    target_role: Optional[str] = None,
    target_company: Optional[str] = None,
    skills: Optional[List[str]] = None,
    linkedin_url: Optional[str] = None,
    github_url: Optional[str] = None,
    has_resume_uploaded: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Saves or updates a candidate's placement profile (#199).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        s_id = (student_id or "default_student").strip()
        cursor.execute("SELECT * FROM student_profiles WHERE student_id = ?", (s_id,))
        existing = cursor.fetchone()

        skills_json = json.dumps(skills) if skills is not None else None

        if existing:
            rec = dict(existing)
            u_name = full_name if full_name is not None else rec.get("full_name")
            u_email = email if email is not None else rec.get("email")
            u_phone = phone if phone is not None else rec.get("phone")
            u_dept = department if department is not None else rec.get("department")
            u_year = grad_year if grad_year is not None else rec.get("grad_year")
            u_cgpa = cgpa if cgpa is not None else rec.get("cgpa")
            u_role = target_role if target_role is not None else rec.get("target_role")
            u_comp = target_company if target_company is not None else rec.get("target_company")
            u_skills = skills_json if skills_json is not None else rec.get("skills_json")
            u_li = linkedin_url if linkedin_url is not None else rec.get("linkedin_url")
            u_gh = github_url if github_url is not None else rec.get("github_url")
            u_resume = int(has_resume_uploaded) if has_resume_uploaded is not None else rec.get("has_resume_uploaded", 0)

            cursor.execute("""
                UPDATE student_profiles SET
                    full_name = ?, email = ?, phone = ?, department = ?,
                    grad_year = ?, cgpa = ?, target_role = ?, target_company = ?,
                    skills_json = ?, linkedin_url = ?, github_url = ?,
                    has_resume_uploaded = ?, updated_at = CURRENT_TIMESTAMP
                WHERE student_id = ?
            """, (
                u_name, u_email, u_phone, u_dept,
                u_year, u_cgpa, u_role, u_comp,
                u_skills, u_li, u_gh, u_resume, s_id
            ))
        else:
            cursor.execute("""
                INSERT INTO student_profiles (
                    student_id, full_name, email, phone, department,
                    grad_year, cgpa, target_role, target_company,
                    skills_json, linkedin_url, github_url, has_resume_uploaded, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                s_id, full_name, email, phone, department,
                grad_year, cgpa, target_role, target_company,
                skills_json, linkedin_url, github_url,
                int(has_resume_uploaded or 0)
            ))
        conn.commit()

        cursor.execute("SELECT * FROM student_profiles WHERE student_id = ?", (s_id,))
        saved = dict(cursor.fetchone())
        if saved.get("skills_json"):
            try:
                saved["skills"] = json.loads(saved["skills_json"])
            except Exception:
                saved["skills"] = []
        else:
            saved["skills"] = []
        return saved
    finally:
        conn.close()


def get_student_profile(student_id: str) -> Dict[str, Any]:
    """
    Retrieves student profile record by student_id (#199).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        s_id = (student_id or "default_student").strip()
        cursor.execute("SELECT * FROM student_profiles WHERE student_id = ?", (s_id,))
        row = cursor.fetchone()
        if not row:
            # Check users table fallback for name/email
            cursor.execute("SELECT name, email FROM users WHERE id = ?", (s_id,))
            user_row = cursor.fetchone()
            return {
                "student_id": s_id,
                "full_name": user_row["name"] if user_row else "",
                "email": user_row["email"] if user_row else "",
                "phone": "",
                "department": "",
                "grad_year": None,
                "cgpa": None,
                "target_role": "",
                "target_company": "",
                "skills": [],
                "linkedin_url": "",
                "github_url": "",
                "has_resume_uploaded": 0
            }

        data = dict(row)
        if data.get("skills_json"):
            try:
                data["skills"] = json.loads(data["skills_json"])
            except Exception:
                data["skills"] = []
        else:
            data["skills"] = []
        return data
    finally:
        conn.close()


def calculate_profile_completion(student_id: str) -> Dict[str, Any]:
    """
    Evaluates profile completeness across key placement readiness criteria (#199):
    - Basic Information (Full Name, Email, Phone): 20%
    - Academic Background (Department, Grad Year, CGPA): 25%
    - Career Aspirations (Target Role, Target Company): 20%
    - Technical Competencies (At least 3 Skills): 15%
    - Professional Presence & Resume (Resume Upload, LinkedIn, GitHub): 20%
    """
    profile = get_student_profile(student_id)

    # Also check if student has analyses uploaded if has_resume_uploaded flag is 0
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM analyses WHERE student_id = ?", (student_id.strip(),))
        has_analyses = cursor.fetchone()[0] > 0
    finally:
        conn.close()

    criteria = []

    # 1. Full name & contact
    has_name = bool((profile.get("full_name") or "").strip())
    has_email = bool((profile.get("email") or "").strip())
    has_phone = bool((profile.get("phone") or "").strip())
    basic_done = has_name and has_email
    criteria.append({
        "category": "Basic Contact Information",
        "title": "Full Name & Email",
        "weight": 15,
        "completed": basic_done,
        "missing_items": [f for f, ok in [("Full Name", has_name), ("Email Address", has_email)] if not ok]
    })

    # 2. Phone number
    criteria.append({
        "category": "Basic Contact Information",
        "title": "Contact Phone Number",
        "weight": 5,
        "completed": has_phone,
        "missing_items": [] if has_phone else ["Phone Number"]
    })

    # 3. Department & Graduation Year
    has_dept = bool((profile.get("department") or "").strip())
    has_year = bool(profile.get("grad_year") and int(profile.get("grad_year")) >= 2020)
    has_cgpa = bool(profile.get("cgpa") and float(profile.get("cgpa")) > 0)
    criteria.append({
        "category": "Academic Background",
        "title": "Department & Graduation Year",
        "weight": 15,
        "completed": has_dept and has_year,
        "missing_items": [f for f, ok in [("Department", has_dept), ("Graduation Year", has_year)] if not ok]
    })

    # 4. Academic CGPA
    criteria.append({
        "category": "Academic Background",
        "title": "Undergraduate CGPA",
        "weight": 10,
        "completed": has_cgpa,
        "missing_items": [] if has_cgpa else ["CGPA"]
    })

    # 5. Career Target
    has_role = bool((profile.get("target_role") or "").strip())
    has_comp = bool((profile.get("target_company") or "").strip())
    criteria.append({
        "category": "Placement Preferences",
        "title": "Target Role & Dream Company",
        "weight": 20,
        "completed": has_role and has_comp,
        "missing_items": [f for f, ok in [("Target Role", has_role), ("Target Company", has_comp)] if not ok]
    })

    # 6. Technical Skills
    skills_list = profile.get("skills", [])
    has_skills = len(skills_list) >= 3
    criteria.append({
        "category": "Technical Competencies",
        "title": "At least 3 Key Technical Skills",
        "weight": 15,
        "completed": has_skills,
        "missing_items": [] if has_skills else [f"Add at least {3 - len(skills_list)} more skill(s)"]
    })

    # 7. Resume & Professional Links
    resume_ready = bool(profile.get("has_resume_uploaded")) or has_analyses
    has_social = bool((profile.get("linkedin_url") or "").strip()) or bool((profile.get("github_url") or "").strip())
    criteria.append({
        "category": "Placement Portfolio",
        "title": "Resume Upload & Developer Links",
        "weight": 20,
        "completed": resume_ready and has_social,
        "missing_items": [f for f, ok in [("Resume Upload", resume_ready), ("LinkedIn/GitHub URL", has_social)] if not ok]
    })

    total_weight = sum(c["weight"] for c in criteria)
    earned_weight = sum(c["weight"] for c in criteria if c["completed"])
    percentage = round((earned_weight / total_weight) * 100) if total_weight > 0 else 0

    all_missing = []
    for c in criteria:
        if not c["completed"]:
            all_missing.extend(c["missing_items"])

    return {
        "student_id": student_id,
        "completion_percentage": percentage,
        "is_complete": percentage >= 100,
        "criteria": criteria,
        "missing_fields": all_missing,
        "profile": profile
    }

def submit_user_feedback(
    student_id: str,
    rating: int,
    category: str,
    comment: str,
    feedback_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Records student experience feedback with rating (1-5), category, and comments (#197).
    """
    import uuid
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        f_id = feedback_id or f"fb-{uuid.uuid4().hex[:12]}"
        normalized_student_id = (student_id or "default_student").strip()
        clamped_rating = max(1, min(5, int(rating)))
        norm_category = (category or "General Experience").strip()
        norm_comment = (comment or "").strip()

        cursor.execute("""
            INSERT INTO user_feedback (id, student_id, rating, category, comment, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (f_id, normalized_student_id, clamped_rating, norm_category, norm_comment))
        conn.commit()

        cursor.execute("SELECT * FROM user_feedback WHERE id = ?", (f_id,))
        row = cursor.fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def get_user_feedback_list(
    student_id: Optional[str] = None,
    category_filter: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Retrieves recorded user feedback entries, optionally filtered by student or feature category (#197).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM user_feedback WHERE 1=1"
        params: List[Any] = []

        if student_id and student_id.strip():
            query += " AND student_id = ?"
            params.append(student_id.strip())

        if category_filter and category_filter.strip() and category_filter.strip().lower() not in ("all", "any"):
            query += " AND LOWER(category) = LOWER(?)"
            params.append(category_filter.strip())

        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(1, int(limit)))

        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_feedback_metrics_summary() -> Dict[str, Any]:
    """
    Calculates aggregated satisfaction scores and category distribution (#197).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                COUNT(*) as total_feedback,
                COALESCE(AVG(rating), 0) as avg_rating,
                COALESCE(SUM(CASE WHEN rating = 5 THEN 1 ELSE 0 END), 0) as five_star_count,
                COALESCE(SUM(CASE WHEN rating = 4 THEN 1 ELSE 0 END), 0) as four_star_count,
                COALESCE(SUM(CASE WHEN rating = 3 THEN 1 ELSE 0 END), 0) as three_star_count,
                COALESCE(SUM(CASE WHEN rating = 2 THEN 1 ELSE 0 END), 0) as two_star_count,
                COALESCE(SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END), 0) as one_star_count
            FROM user_feedback
        """)
        row = cursor.fetchone()
        stats = dict(row) if row else {}
        stats["avg_rating"] = round(float(stats.get("avg_rating", 0.0)), 2)

        cursor.execute("""
            SELECT category, COUNT(*) as count, AVG(rating) as category_avg
            FROM user_feedback
            GROUP BY category
            ORDER BY count DESC
        """)
        stats["category_breakdown"] = [
            {
                "category": r["category"],
                "count": r["count"],
                "avg_rating": round(float(r["category_avg"] or 0), 1)
            }
            for r in cursor.fetchall()
        ]
        return stats
    finally:
        conn.close()

def export_job_applications_csv(
    student_id: str,
    status_filter: Optional[str] = None
) -> str:
    """
    Generates standard RFC-4180 CSV export content for a student's job applications (#196).
    Enforces student data segregation, formats dates and notes safely, and handles empty application states.
    """
    import csv
    import io

    applications = get_job_applications(student_id=student_id, status_filter=status_filter)
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Header row
    writer.writerow([
        "Application ID",
        "Company Name",
        "Role Title",
        "Status",
        "Application Date",
        "Job Posting URL",
        "Job Description / Requirements",
        "Interview / Follow-up Notes",
        "Created At"
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
            app_item.get("created_at", "")
        ])

    return output.getvalue()


def export_job_applications_json(
    student_id: str,
    status_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generates structured JSON export payload for a student's job applications (#196).
    """
    applications = get_job_applications(student_id=student_id, status_filter=status_filter)
    status_counts = {}
    for item in applications:
        st = item.get("status", "Unknown")
        status_counts[st] = status_counts.get(st, 0) + 1

    return {
        "export_version": "1.0",
        "student_id": student_id.strip() if student_id else "default_student",
        "total_applications": len(applications),
        "status_distribution": status_counts,
        "applications": applications
    }


def export_job_applications_markdown(
    student_id: str,
    status_filter: Optional[str] = None
) -> str:
    """
    Generates a readable Markdown summary table of job applications (#196).
    """
    applications = get_job_applications(student_id=student_id, status_filter=status_filter)
    lines = [
        f"# Job Applications Report - Candidate: {student_id}",
        "",
        f"- **Total Applications**: {len(applications)}",
        f"- **Filter Applied**: {status_filter or 'All'}",
        "",
        "| ID | Company | Role | Status | Applied Date | Job Link | Notes |",
        "|---|---|---|---|---|---|---|"
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
    student_id: str
) -> Dict[str, Any]:
    """
    Provides aggregated analytics metadata for candidate job applications export.
    """
    applications = get_job_applications(student_id=student_id)
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
        "ready_for_export": True
    }


def _seed_cohort_benchmarks(cursor: sqlite3.Cursor) -> None:
    """
    Populates default cohort records representing diverse university branch peers.
    """
    seed_peers = [
        ("peer-01", "AlgoMaster_99", "Computer Science", 2026, 95, 94, 94.4, "Google", 9, "Platinum"),
        ("peer-02", "CloudArchitect_42", "Information Technology", 2026, 92, 91, 91.4, "Microsoft", 8, "Platinum"),
        ("peer-03", "SystemSurgeon_18", "Computer Science", 2026, 90, 89, 89.4, "Amazon", 8, "Platinum"),
        ("peer-04", "DataVoyager_77", "Data Science & AI", 2026, 88, 86, 86.9, "Adobe", 7, "Gold"),
        ("peer-05", "DevScholar_12", "Computer Science", 2026, 86, 84, 84.9, "Uber", 7, "Gold"),
        ("peer-06", "BinaryMonk_33", "Electronics & Comm", 2026, 85, 82, 83.3, "Cisco", 6, "Gold"),
        ("peer-07", "PixelCraft_29", "Information Technology", 2026, 84, 83, 83.4, "Swiggy", 6, "Gold"),
        ("peer-08", "CodeCrafter_05", "Computer Science", 2026, 83, 80, 81.3, "Razorpay", 6, "Gold"),
        ("peer-09", "NeuralNomad_64", "Data Science & AI", 2025, 82, 79, 80.3, "Oracle", 6, "Gold"),
        ("peer-10", "SyntaxSamurai_81", "Computer Science", 2025, 81, 78, 79.3, "Goldman Sachs", 6, "Gold"),
        ("peer-11", "KernelKnight_56", "Electronics & Comm", 2026, 80, 77, 78.3, "Qualcomm", 5, "Gold"),
        ("peer-12", "StackWizard_21", "Information Technology", 2026, 78, 76, 76.9, "Flipkart", 5, "Silver"),
        ("peer-13", "LogicWhiz_44", "Computer Science", 2026, 77, 75, 75.9, "TCS", 5, "Silver"),
        ("peer-14", "CyberFalcon_87", "Computer Science", 2025, 76, 74, 74.9, "Infosys", 5, "Silver"),
        ("peer-15", "QuantumCoder_19", "Electronics & Comm", 2027, 75, 72, 73.3, "Accenture", 4, "Silver"),
        ("peer-16", "ByteSurgeon_63", "Information Technology", 2026, 74, 71, 72.3, "Capgemini", 4, "Silver"),
        ("peer-17", "MatrixMaster_38", "Electrical Engineering", 2026, 73, 70, 71.3, "Wipro", 4, "Silver"),
        ("peer-18", "PromptArchitect_90", "Data Science & AI", 2026, 72, 69, 70.3, "Cognizant", 4, "Silver"),
        ("peer-19", "GitGuru_08", "Computer Science", 2027, 70, 68, 68.9, "General", 4, "Silver"),
        ("peer-20", "ScriptSage_52", "Electronics & Comm", 2025, 69, 66, 67.3, "General", 4, "Silver"),
        ("peer-21", "SiliconPioneer_35", "Electrical Engineering", 2026, 67, 65, 65.9, "General", 3, "Silver"),
        ("peer-22", "TurboCoder_14", "Mechanical Engineering", 2026, 64, 62, 62.9, "General", 3, "Bronze"),
        ("peer-23", "ApexDev_93", "Computer Science", 2027, 62, 60, 60.9, "General", 3, "Bronze"),
        ("peer-24", "VeloceBytes_41", "Civil Engineering", 2026, 58, 55, 56.3, "General", 2, "Bronze"),
    ]
    cursor.executemany("""
        INSERT OR IGNORE INTO cohort_benchmarks 
        (id, student_handle, department, grad_year, ats_score, job_match_score, overall_score, target_company, skills_count, tier)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, seed_peers)
    logger.info(f"Seeded {len(seed_peers)} default peer cohort benchmark records.")


def record_or_update_cohort_benchmark(
    analysis_id: str,
    student_handle: str,
    department: str = "Computer Science",
    grad_year: int = 2026,
    ats_score: int = 70,
    job_match_score: int = 65,
    overall_score: Optional[float] = None,
    target_company: str = "General",
    skills_count: int = 0,
    tier: Optional[str] = None
) -> str:
    """
    Inserts or updates an anonymized student evaluation in the cohort_benchmarks table.
    Computes overall composite score and achievement tier if omitted.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Calculate composite score (45% ATS, 55% Job Match)
        if overall_score is None:
            overall_score = round((ats_score * 0.45) + (job_match_score * 0.55), 1)

        # Derive achievement tier if omitted
        if not tier:
            if overall_score >= 88.0:
                tier = "Platinum"
            elif overall_score >= 78.0:
                tier = "Gold"
            elif overall_score >= 65.0:
                tier = "Silver"
            else:
                tier = "Bronze"

        # Check if record for this analysis_id already exists
        cursor.execute("SELECT id FROM cohort_benchmarks WHERE analysis_id = ?", (analysis_id,))
        existing = cursor.fetchone()

        if existing:
            benchmark_id = existing[0]
            cursor.execute("""
                UPDATE cohort_benchmarks
                SET student_handle = ?, department = ?, grad_year = ?,
                    ats_score = ?, job_match_score = ?, overall_score = ?,
                    target_company = ?, skills_count = ?, tier = ?
                WHERE id = ?
            """, (
                student_handle, department, grad_year,
                ats_score, job_match_score, overall_score,
                target_company, skills_count, tier,
                benchmark_id
            ))
        else:
            benchmark_id = f"cohort-{analysis_id}"
            cursor.execute("""
                INSERT INTO cohort_benchmarks
                (id, analysis_id, student_handle, department, grad_year, ats_score, job_match_score, overall_score, target_company, skills_count, tier)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                benchmark_id, analysis_id, student_handle, department, grad_year,
                ats_score, job_match_score, overall_score, target_company, skills_count, tier
            ))

        conn.commit()
        return benchmark_id
    except Exception as e:
        logger.error(f"Error saving cohort benchmark for analysis {analysis_id}: {e}")
        raise e
    finally:
        conn.close()


def get_cohort_benchmark_by_analysis_id(analysis_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves the cohort benchmark record for a specific analysis ID.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM cohort_benchmarks WHERE analysis_id = ?", (analysis_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Error fetching cohort benchmark for {analysis_id}: {e}")
        return None
    finally:
        conn.close()


def get_cohort_benchmarks(
    department: Optional[str] = None,
    grad_year: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Retrieves sorted cohort benchmark entries ordered by overall_score DESC.
    Supports filtering by department, graduation year, and keyword search.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        conditions = []
        params = []

        if department and department.strip() and department.strip().lower() not in ("all", "any"):
            conditions.append("LOWER(department) = LOWER(?)")
            params.append(department.strip())

        if grad_year and int(grad_year) > 0:
            conditions.append("grad_year = ?")
            params.append(int(grad_year))

        if search and search.strip():
            kw = f"%{search.strip().lower()}%"
            conditions.append("(LOWER(student_handle) LIKE ? OR LOWER(target_company) LIKE ? OR LOWER(department) LIKE ?)")
            params.extend([kw, kw, kw])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT * FROM cohort_benchmarks
            {where_clause}
            ORDER BY overall_score DESC, ats_score DESC, job_match_score DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        benchmarks = []
        for idx, row in enumerate(rows):
            rec = dict(row)
            rec["rank"] = offset + idx + 1
            benchmarks.append(rec)

        return benchmarks
    except Exception as e:
        logger.error(f"Error fetching cohort benchmarks: {e}")
        return []
    finally:
        conn.close()


def get_cohort_stats(
    department: Optional[str] = None,
    grad_year: Optional[int] = None
) -> Dict[str, Any]:
    """
    Computes aggregate metrics across the specified cohort segment:
    count, avg_ats, avg_match, avg_overall, max_score, and tier distribution.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        conditions = []
        params = []

        if department and department.strip() and department.strip().lower() not in ("all", "any"):
            conditions.append("LOWER(department) = LOWER(?)")
            params.append(department.strip())

        if grad_year and int(grad_year) > 0:
            conditions.append("grad_year = ?")
            params.append(int(grad_year))

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cursor.execute(f"""
            SELECT 
                COUNT(*) as total_students,
                COALESCE(AVG(ats_score), 0) as avg_ats,
                COALESCE(AVG(job_match_score), 0) as avg_match,
                COALESCE(AVG(overall_score), 0) as avg_overall,
                COALESCE(MAX(overall_score), 0) as max_overall,
                COALESCE(SUM(CASE WHEN tier = 'Platinum' THEN 1 ELSE 0 END), 0) as platinum_count,
                COALESCE(SUM(CASE WHEN tier = 'Gold' THEN 1 ELSE 0 END), 0) as gold_count,
                COALESCE(SUM(CASE WHEN tier = 'Silver' THEN 1 ELSE 0 END), 0) as silver_count,
                COALESCE(SUM(CASE WHEN tier = 'Bronze' THEN 1 ELSE 0 END), 0) as bronze_count
            FROM cohort_benchmarks
            {where_clause}
        """, params)

        stats = dict(cursor.fetchone())
        stats["avg_ats"] = round(float(stats.get("avg_ats", 0)), 1)
        stats["avg_match"] = round(float(stats.get("avg_match", 0)), 1)
        stats["avg_overall"] = round(float(stats.get("avg_overall", 0)), 1)
        stats["max_overall"] = round(float(stats.get("max_overall", 0)), 1)

        # Department distribution
        cursor.execute(f"""
            SELECT department, COUNT(*) as count
            FROM cohort_benchmarks
            {where_clause}
            GROUP BY department
            ORDER BY count DESC
        """, params)
        stats["department_breakdown"] = [dict(r) for r in cursor.fetchall()]

        return stats
    except Exception as e:
        logger.error(f"Error computing cohort statistics: {e}")
        return {
            "total_students": 0,
            "avg_ats": 0.0,
            "avg_match": 0.0,
            "avg_overall": 0.0,
            "max_overall": 0.0,
            "platinum_count": 0,
            "gold_count": 0,
            "silver_count": 0,
            "bronze_count": 0,
            "department_breakdown": []
        }
    finally:
        conn.close()




def get_user_placement_history(
    student_id: str = "default_student",
    company_filter: Optional[str] = None,
    sort_by: str = "date_desc"
) -> Dict[str, Any]:
    """
    Saves and retrieves comprehensive previous placement analysis history for a specific user (#149).
    Includes per-student data isolation, ATS score tracking, role match percentages,
    and historical performance metrics.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()

        query = """
            SELECT id, resume_filename, company_name, job_description, results_json,
                   student_id, version_number, created_at
            FROM analyses
            WHERE student_id = ?
        """
        params: List[Any] = [effective_student_id]

        if company_filter and company_filter.strip() and company_filter.strip().lower() not in ("all", "any"):
            query += " AND LOWER(company_name) LIKE ?"
            params.append(f"%{company_filter.strip().lower()}%")

        if sort_by == "score_desc":
            # Will sort in python after parsing ATS score
            query += " ORDER BY created_at DESC"
        elif sort_by == "date_asc":
            query += " ORDER BY created_at ASC"
        else:
            query += " ORDER BY created_at DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        records = []
        ats_scores = []
        match_scores = []
        company_counts: Dict[str, int] = {}

        for row in rows:
            rec = dict(row)
            try:
                raw_json = rec.pop("results_json", "{}")
                parsed = json.loads(raw_json)
                rec["results"] = parsed

                # Score resolution
                ats = parsed.get("ats_score") or parsed.get("resume_analysis", {}).get("ats_score", 0)
                match = parsed.get("job_match_score") or parsed.get("job_match", {}).get("match_percentage", 0)

                rec["ats_score"] = int(ats)
                rec["match_percentage"] = int(match)
                ats_scores.append(rec["ats_score"])
                match_scores.append(rec["match_percentage"])

                # Extract extracted skills & missing skills count
                rec["matched_skills_count"] = len(parsed.get("matched_skills") or parsed.get("job_match", {}).get("matched_skills", []))
                rec["missing_skills_count"] = len(parsed.get("missing_skills") or parsed.get("job_match", {}).get("missing_skills", []))

                comp = rec.get("company_name", "General")
                company_counts[comp] = company_counts.get(comp, 0) + 1

            except Exception as parse_err:
                logger.warning(f"Failed to parse analysis payload for record {rec.get('id')}: {parse_err}")
                rec["results"] = {}
                rec["ats_score"] = 0
                rec["match_percentage"] = 0
                rec["matched_skills_count"] = 0
                rec["missing_skills_count"] = 0

            records.append(rec)

        if sort_by == "score_desc":
            records.sort(key=lambda x: x["ats_score"], reverse=True)

        avg_ats = round(sum(ats_scores) / len(ats_scores), 1) if ats_scores else 0.0
        avg_match = round(sum(match_scores) / len(match_scores), 1) if match_scores else 0.0
        highest_ats = max(ats_scores) if ats_scores else 0

        return {
            "student_id": effective_student_id,
            "total_analyses": len(records),
            "average_ats_score": avg_ats,
            "average_match_percentage": avg_match,
            "highest_ats_score": highest_ats,
            "company_counts": company_counts,
            "analyses": records
        }

    except Exception as e:
        logger.error(f"Error fetching placement analysis history for {student_id}: {e}")
        return {
            "student_id": student_id,
            "total_analyses": 0,
            "average_ats_score": 0.0,
            "average_match_percentage": 0.0,
            "highest_ats_score": 0,
            "company_counts": {},
            "analyses": []
        }
    finally:
        conn.close()


def get_student_interview_history(student_id: str = "default_student") -> List[Dict[str, Any]]:
    """
    Retrieves full mock interview session history for a student across all attempts (#144).
    Calculates completion rates, scores per question type (Technical, HR, Behavioral), and overall score.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                i.id AS session_id,
                i.analysis_id,
                i.current_question_index,
                i.questions_json,
                i.answers_json,
                i.completed,
                a.company_name,
                a.created_at AS analysis_date
            FROM interviews i
            JOIN analyses a ON i.analysis_id = a.id
            WHERE a.student_id = ?
            ORDER BY a.created_at DESC, i.id DESC
        """, (student_id,))
        rows = cursor.fetchall()

        history = []
        for r in rows:
            rec = dict(r)
            questions = json.loads(rec.get("questions_json", "[]") or "[]")
            answers = json.loads(rec.get("answers_json", "[]") or "[]")

            scores = []
            type_scores = {"Technical": [], "HR": [], "Behavioral": []}
            for ans in answers:
                eval_data = ans.get("evaluation", {})
                score = eval_data.get("score")
                if score is not None:
                    try:
                        score_val = float(score)
                        scores.append(score_val)
                        q_type = ans.get("type", "General")
                        if q_type in type_scores:
                            type_scores[q_type].append(score_val)
                    except (ValueError, TypeError):
                        pass

            avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0
            technical_avg = round(sum(type_scores["Technical"]) / len(type_scores["Technical"]), 1) if type_scores["Technical"] else 0.0
            hr_avg = round(sum(type_scores["HR"]) / len(type_scores["HR"]), 1) if type_scores["HR"] else 0.0
            behavioral_avg = round(sum(type_scores["Behavioral"]) / len(type_scores["Behavioral"]), 1) if type_scores["Behavioral"] else 0.0

            history.append({
                "session_id": rec["session_id"],
                "analysis_id": rec["analysis_id"],
                "company_name": rec.get("company_name", "General"),
                "total_questions": len(questions),
                "answered_questions": len(answers),
                "completed": bool(rec.get("completed", 0)),
                "average_score": avg_score,
                "technical_score": technical_avg,
                "hr_score": hr_avg,
                "behavioral_score": behavioral_avg,
                "date": rec.get("analysis_date", ""),
                "questions": questions,
                "answers": answers
            })
        return history
    except Exception as e:
        logger.error(f"Error retrieving student interview history: {e}")
        return []
    finally:
        conn.close()


def get_student_interview_performance_analytics(student_id: str = "default_student") -> Dict[str, Any]:
    """
    Computes performance analytics, score trends, and strengths/weaknesses for mock interviews (#144).
    """
    history = get_student_interview_history(student_id=student_id)
    if not history:
        return {
            "total_sessions": 0,
            "completed_sessions": 0,
            "total_questions_answered": 0,
            "overall_average_score": 0.0,
            "technical_average": 0.0,
            "hr_average": 0.0,
            "behavioral_average": 0.0,
            "score_trend": [],
            "strengths": [],
            "weaknesses": [],
            "sessions": []
        }

    total_sessions = len(history)
    completed_sessions = sum(1 for s in history if s["completed"])
    total_answered = sum(s["answered_questions"] for s in history)

    all_scores = [s["average_score"] for s in history if s["average_score"] > 0]
    overall_avg = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0.0

    tech_scores = [s["technical_score"] for s in history if s["technical_score"] > 0]
    hr_scores = [s["hr_score"] for s in history if s["hr_score"] > 0]
    behav_scores = [s["behavioral_score"] for s in history if s["behavioral_score"] > 0]

    tech_avg = round(sum(tech_scores) / len(tech_scores), 1) if tech_scores else 0.0
    hr_avg = round(sum(hr_scores) / len(hr_scores), 1) if hr_scores else 0.0
    behav_avg = round(sum(behav_scores) / len(behav_scores), 1) if behav_scores else 0.0

    # Trend line sorted chronologically
    score_trend = [
        {
            "date": s.get("date", "")[:10],
            "company": s["company_name"],
            "score": s["average_score"],
            "session_id": s["session_id"]
        }
        for s in reversed(history) if s["average_score"] > 0
    ]

    # Strengths and Weaknesses analysis
    strengths = []
    weaknesses = []

    domain_eval = [
        ("Technical Concepts", tech_avg),
        ("HR and Culture Fit", hr_avg),
        ("Behavioral and STAR Structure", behav_avg)
    ]

    for name, avg in domain_eval:
        if avg >= 75.0:
            strengths.append(f"{name} ({avg}/100) - Strong grasp of core concepts and structured communication")
        elif avg > 0:
            weaknesses.append(f"{name} ({avg}/100) - Needs further practice with concise articulation and situational examples")

    if not strengths and overall_avg >= 70.0:
        strengths.append("Consistent practice and willingness to complete structured multi-round interviews.")
    if not weaknesses:
        weaknesses.append("Practice speaking with greater conciseness and quantifiable impact metrics.")

    return {
        "total_sessions": total_sessions,
        "completed_sessions": completed_sessions,
        "total_questions_answered": total_answered,
        "overall_average_score": overall_avg,
        "technical_average": tech_avg,
        "hr_average": hr_avg,
        "behavioral_average": behav_avg,
        "score_trend": score_trend,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "sessions": history
    }


def create_user(user_id: str, name: str, email: str, password_hash: str) -> bool:
    """Create a new user account."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (id, name, email, password_hash)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, name.strip(), email.strip().lower(), password_hash)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception as exc:
        logger.error(f"Error creating user: {exc}")
        raise
    finally:
        conn.close()


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Retrieve a user by email address."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE email = ?",
            (email.strip().lower(),)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a user by their ID"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, email, created_at FROM users WHERE id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def save_skill_self_assessment(
    student_id: str,
    skill_name: str,
    category: str,
    proficiency_level: str,
    years_experience: float = 0.0,
    notes: str = ""
) -> Dict[str, Any]:
    """Saves or updates a student's technical skill self-assessment."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        record_id = str(uuid.uuid4())
        normalized_student_id = (student_id or "default_student").strip()
        normalized_skill = skill_name.strip()
        normalized_category = (category or "General").strip()
        valid_levels = ["Beginner", "Intermediate", "Advanced", "Expert"]
        level = proficiency_level if proficiency_level in valid_levels else "Intermediate"

        cursor.execute("""
            INSERT INTO technical_self_assessments (
                id, student_id, skill_name, category, proficiency_level, years_experience, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(student_id, skill_name) DO UPDATE SET
                category = excluded.category,
                proficiency_level = excluded.proficiency_level,
                years_experience = excluded.years_experience,
                notes = excluded.notes,
                updated_at = CURRENT_TIMESTAMP
        """, (
            record_id,
            normalized_student_id,
            normalized_skill,
            normalized_category,
            level,
            float(years_experience or 0.0),
            notes.strip() if notes else ""
        ))
        conn.commit()

        cursor.execute(
            "SELECT * FROM technical_self_assessments WHERE student_id = ? AND skill_name = ?",
            (normalized_student_id, normalized_skill)
        )
        row = cursor.fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def get_student_skill_self_assessments(student_id: str) -> List[Dict[str, Any]]:
    """Retrieves all technical skill self-assessments for a student."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        normalized_student_id = (student_id or "default_student").strip()
        cursor.execute("""
            SELECT * FROM technical_self_assessments
            WHERE student_id = ?
            ORDER BY category ASC, skill_name ASC
        """, (normalized_student_id,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def delete_skill_self_assessment(student_id: str, skill_name: str) -> bool:
    """Deletes a student's self-assessment entry for a skill."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        normalized_student_id = (student_id or "default_student").strip()
        cursor.execute(
            "DELETE FROM technical_self_assessments WHERE student_id = ? AND skill_name = ?",
            (normalized_student_id, skill_name.strip())
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_default_technical_skills_catalog() -> Dict[str, List[str]]:
    """Returns curated placement technical skills catalog grouped by category."""
    return {
        "Programming Languages": ["Python", "Java", "C++", "JavaScript", "TypeScript", "Go"],
        "Web & Frameworks": ["React", "Node.js", "Flask", "Django", "Spring Boot", "HTML5/CSS3"],
        "Data & Databases": ["SQL", "PostgreSQL", "MongoDB", "Redis", "Data Structures & Algorithms"],
        "Cloud & DevOps": ["Git & GitHub", "Docker", "Kubernetes", "AWS", "CI/CD Pipelines", "Linux"],
        "Core CS Fundamentals": ["Operating Systems", "DBMS", "Computer Networks", "System Design", "OOP"]
    }

def save_coding_submission(
    sub_id: str,
    student_id: str,
    question_title: str,
    language: str,
    code: str,
    passed: bool,
    score: int,
    tests_passed: int = 0,
    total_tests: int = 0,
    test_results: Optional[List[Dict[str, Any]]] = None,
    complexity_analysis: Optional[str] = None,
    feedback: Optional[str] = None,
    company_name: str = "General",
    analysis_id: Optional[str] = None
) -> str:
    """
    Persists a coding assessment submission attempt (#194).
    Enforces per-student isolation.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()
        cursor.execute("""
            INSERT INTO coding_submissions (
                id, student_id, analysis_id, question_title, company_name,
                language, code, passed, score, tests_passed, total_tests,
                test_results_json, complexity_analysis, feedback
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sub_id,
            effective_student_id,
            analysis_id,
            question_title.strip(),
            company_name.strip(),
            language.strip().lower(),
            code,
            1 if passed else 0,
            int(score),
            int(tests_passed),
            int(total_tests),
            json.dumps(test_results or []),
            complexity_analysis or "",
            feedback or ""
        ))
        conn.commit()
        logger.info(f"Saved coding submission {sub_id} for student {effective_student_id}")
        return sub_id
    except Exception as e:
        logger.error(f"Error saving coding submission {sub_id}: {e}")
        raise e
    finally:
        conn.close()


def get_coding_submissions(
    student_id: str,
    question_title: Optional[str] = None,
    language_filter: Optional[str] = None,
    status_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retrieves all coding assessment submission attempts for a student (#194).
    Supports question matching to compare attempts over time.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()
        conditions = ["student_id = ?"]
        params: List[Any] = [effective_student_id]

        if question_title and question_title.strip():
            conditions.append("LOWER(question_title) = LOWER(?)")
            params.append(question_title.strip())

        if language_filter and language_filter.strip() and language_filter.strip().lower() not in ("all", "any"):
            conditions.append("LOWER(language) = LOWER(?)")
            params.append(language_filter.strip())

        if status_filter and status_filter.strip() and status_filter.strip().lower() not in ("all", "any"):
            if status_filter.strip().lower() == "passed":
                conditions.append("passed = 1")
            elif status_filter.strip().lower() == "failed":
                conditions.append("passed = 0")

        where_clause = f"WHERE {' AND '.join(conditions)}"
        query = f"SELECT * FROM coding_submissions {where_clause} ORDER BY submitted_at DESC, id DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        submissions = []
        for r in rows:
            rec = dict(r)
            try:
                rec["test_results"] = json.loads(rec.get("test_results_json", "[]"))
            except Exception:
                rec["test_results"] = []
            rec["passed"] = bool(rec.get("passed", 0))
            submissions.append(rec)

        return submissions
    except Exception as e:
        logger.error(f"Error retrieving coding submissions for {student_id}: {e}")
        return []
    finally:
        conn.close()

def get_default_company_checklist(company_name: str) -> Dict[str, Any]:
    """
    Returns the foundational company checklist tasks structured across
    Aptitude, Coding, Technical Concepts, and HR rounds (#192).
    """
    comp = (company_name or "General").strip()

    return {
        "Aptitude & Logical Reasoning": [
            {"id": "apt_01", "task": f"Quantitative Aptitude: Speed, Distance, Work & Time for {comp}", "completed": False},
            {"id": "apt_02", "task": "Data Interpretation & Logical Puzzles (Seating arrangements & Syllogisms)", "completed": False},
            {"id": "apt_03", "task": "Verbal Ability & Reading Comprehension Practice", "completed": False}
        ],
        "Coding & Data Structures": [
            {"id": "code_01", "task": f"Top 20 Most Frequent LeetCode Questions asked at {comp}", "completed": False},
            {"id": "code_02", "task": "Arrays, Strings, HashMaps & Sliding Window problem sets", "completed": False},
            {"id": "code_03", "task": "Trees, Graphs & Dynamic Programming fundamentals", "completed": False},
            {"id": "code_04", "task": f"Timed 60-minute Online Assessment Simulation for {comp}", "completed": False}
        ],
        "Technical Concepts & CS Fundamentals": [
            {"id": "tech_01", "task": "DBMS & SQL: Indexing, Transactions, ACID Properties, Normalization", "completed": False},
            {"id": "tech_02", "task": "Operating Systems: Process vs Thread, Virtual Memory, Concurrency & Deadlocks", "completed": False},
            {"id": "tech_03", "task": "Computer Networks: TCP/IP vs UDP, DNS, HTTP/HTTPS, WebSockets", "completed": False},
            {"id": "tech_04", "task": "Object Oriented Programming (OOP) & Clean System Design principles", "completed": False}
        ],
        "HR, Culture & Behavioral (STAR)": [
            {"id": "hr_01", "task": f"Company Deep Dive: Core values, business model, and leadership principles of {comp}", "completed": False},
            {"id": "hr_02", "task": "Prepare 'Tell Me About Yourself' 90-second elevator pitch", "completed": False},
            {"id": "hr_03", "task": "Structure 3 impactful project stories using the STAR methodology", "completed": False},
            {"id": "hr_04", "task": f"Prepare 3 thoughtful questions to ask the interviewer about {comp}", "completed": False}
        ]
    }


def get_company_checklist(student_id: str, company_name: str) -> Dict[str, Any]:
    """
    Retrieves or initializes the student's company-specific preparation checklist (#192).
    Calculates category progress and overall completion percentage.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()
        comp = (company_name or "Google").strip()


def get_interview_experiences(
    company_name: Optional[str] = None,
    category_filter: Optional[str] = None,
    search_query: Optional[str] = None,
    include_reported: bool = False
) -> List[Dict[str, Any]]:
    """
    Retrieves company interview experiences with search and round filtering (#189).
    Omits inappropriate/reported posts by default.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        conditions = []
        params = []

        if not include_reported:
            conditions.append("reported_flag = 0")

        if company_name and company_name.strip() and company_name.strip().lower() not in ("all", "any"):
            conditions.append("LOWER(company_name) = LOWER(?)")
            params.append(company_name.strip())

        if search_query and search_query.strip():
            kw = f"%{search_query.strip().lower()}%"
            conditions.append("(LOWER(company_name) LIKE ? OR LOWER(role_title) LIKE ? OR LOWER(tips_and_preparation) LIKE ?)")
            params.extend([kw, kw, kw])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM interview_experiences {where_clause} ORDER BY interview_date DESC, created_at DESC"

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
            "category_stats": {}
        }
    finally:
        conn.close()


def save_company_checklist(student_id: str, company_name: str, checklist_data: Dict[str, Any]) -> bool:
    """
    Saves candidate progress for a specific target company (#192).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()
        comp = (company_name or "Google").strip()

        total_tasks = 0
        completed_tasks = 0
        for task_list in checklist_data.values():
            total_tasks += len(task_list)
            completed_tasks += sum(1 for t in task_list if t.get("completed"))

        pct = round((completed_tasks / total_tasks * 100), 1) if total_tasks else 0.0
        rec_id = f"chk-{effective_student_id}-{comp.lower().replace(' ', '_')}"

        cursor.execute("""
            INSERT INTO company_preparation_checklists (
                id, student_id, company_name, checklist_json, completion_percentage, updated_at
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(student_id, company_name) DO UPDATE SET
                checklist_json = excluded.checklist_json,
                completion_percentage = excluded.completion_percentage,
                updated_at = CURRENT_TIMESTAMP
        """, (rec_id, effective_student_id, comp, json.dumps(checklist_data), pct))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error saving checklist for {company_name}: {e}")
        return False
    finally:
        conn.close()


def reset_company_checklist(student_id: str, company_name: str) -> bool:
    """
    Resets all tasks to uncompleted for the target company checklist (#192).
    """
    default_data = get_default_company_checklist(company_name)
    return save_company_checklist(student_id, company_name, default_data)

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
    completed: bool = False
) -> str:
    """
    Creates or updates a candidate placement preparation calendar event (#190).
    Enforces per-student data isolation.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()
        cursor.execute("""
            INSERT OR REPLACE INTO preparation_calendar_events (
                id, student_id, title, event_type, event_date, event_time,
                company_name, description, priority, completed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_id,
            effective_student_id,
            title.strip(),
            event_type.strip().lower(),
            event_date.strip(),
            (event_time or "").strip(),
            (company_name or "").strip(),
            (description or "").strip(),
            priority.strip(),
            1 if completed else 0
        ))
        conn.commit()
        logger.info(f"Saved calendar event {event_id} for student {effective_student_id}")
        return event_id
    except Exception as e:
        logger.error(f"Error saving calendar event {event_id}: {e}")
        raise e
    finally:
        conn.close()


def get_calendar_events(
    student_id: str,
    month: Optional[str] = None,
    event_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retrieves all calendar preparation events for a student (#190).
    Allows filtering by YYYY-MM month prefix and event_type (interview, preparation, deadline).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()
        conditions = ["student_id = ?"]
        params = [effective_student_id]

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
    finally:
        conn.close()


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
    completed: bool = False
) -> bool:
    """
    Updates an existing calendar event owned by student_id (#190).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()
        cursor.execute("""
            UPDATE preparation_calendar_events
            SET title = ?, event_type = ?, event_date = ?, event_time = ?,
                company_name = ?, description = ?, priority = ?, completed = ?
            WHERE id = ? AND student_id = ?
        """, (
            title.strip(),
            event_type.strip().lower(),
            event_date.strip(),
            (event_time or "").strip(),
            (company_name or "").strip(),
            (description or "").strip(),
            priority.strip(),
            1 if completed else 0,
            event_id,
            effective_student_id
        ))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating calendar event {event_id}: {e}")
        return False
    finally:
        conn.close()


def delete_calendar_event(event_id: str, student_id: str) -> bool:
    """
    Deletes a calendar event owned by student_id (#190).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()
        cursor.execute(
            "DELETE FROM preparation_calendar_events WHERE id = ? AND student_id = ?",
            (event_id, effective_student_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting calendar event {event_id}: {e}")
        return False
    finally:
        conn.close()


def get_default_company_checklist(company_name: str) -> Dict[str, Any]:
    """
    Returns the foundational company checklist tasks structured across
    Aptitude, Coding, Technical Concepts, and HR rounds (#192).
    """
    comp = (company_name or "General").strip()

    return {
        "Aptitude & Logical Reasoning": [
            {"id": "apt_01", "task": f"Quantitative Aptitude: Speed, Distance, Work & Time for {comp}", "completed": False},
            {"id": "apt_02", "task": "Data Interpretation & Logical Puzzles (Seating arrangements & Syllogisms)", "completed": False},
            {"id": "apt_03", "task": "Verbal Ability & Reading Comprehension Practice", "completed": False}
        ],
        "Coding & Data Structures": [
            {"id": "code_01", "task": f"Top 20 Most Frequent LeetCode Questions asked at {comp}", "completed": False},
            {"id": "code_02", "task": "Arrays, Strings, HashMaps & Sliding Window problem sets", "completed": False},
            {"id": "code_03", "task": "Trees, Graphs & Dynamic Programming fundamentals", "completed": False},
            {"id": "code_04", "task": f"Timed 60-minute Online Assessment Simulation for {comp}", "completed": False}
        ],
        "Technical Concepts & CS Fundamentals": [
            {"id": "tech_01", "task": "DBMS & SQL: Indexing, Transactions, ACID Properties, Normalization", "completed": False},
            {"id": "tech_02", "task": "Operating Systems: Process vs Thread, Virtual Memory, Concurrency & Deadlocks", "completed": False},
            {"id": "tech_03", "task": "Computer Networks: TCP/IP vs UDP, DNS, HTTP/HTTPS, WebSockets", "completed": False},
            {"id": "tech_04", "task": "Object Oriented Programming (OOP) & Clean System Design principles", "completed": False}
        ],
        "HR, Culture & Behavioral (STAR)": [
            {"id": "hr_01", "task": f"Company Deep Dive: Core values, business model, and leadership principles of {comp}", "completed": False},
            {"id": "hr_02", "task": "Prepare 'Tell Me About Yourself' 90-second elevator pitch", "completed": False},
            {"id": "hr_03", "task": "Structure 3 impactful project stories using the STAR methodology", "completed": False},
            {"id": "hr_04", "task": f"Prepare 3 thoughtful questions to ask the interviewer about {comp}", "completed": False}
        ]
    }


def get_company_checklist(student_id: str, company_name: str) -> Dict[str, Any]:
    """
    Retrieves or initializes the student's company-specific preparation checklist (#192).
    Calculates category progress and overall completion percentage.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()
        comp = (company_name or "Google").strip()

        cursor.execute("""
            SELECT * FROM company_preparation_checklists
            WHERE student_id = ? AND LOWER(company_name) = LOWER(?)
        """, (effective_student_id, comp))
        row = cursor.fetchone()

        if row:
            rec = dict(row)
            try:
                checklist_data = json.loads(rec.get("checklist_json", "{}"))
            except Exception:
                checklist_data = get_default_company_checklist(comp)
        else:
            checklist_data = get_default_company_checklist(comp)
            # Initialize record
            save_company_checklist(effective_student_id, comp, checklist_data)

        # Compute completion statistics
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
                "percentage": round((cat_done / cat_total * 100), 1) if cat_total else 0.0
            }

        overall_percentage = round((completed_tasks / total_tasks * 100), 1) if total_tasks else 0.0

        return {
            "student_id": effective_student_id,
            "company_name": comp,
            "checklist": checklist_data,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "overall_percentage": overall_percentage,
            "category_stats": category_stats
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
            "category_stats": {}
        }
    finally:
        conn.close()


def save_company_checklist(student_id: str, company_name: str, checklist_data: Dict[str, Any]) -> bool:
    """
    Saves candidate progress for a specific target company (#192).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()
        cursor.execute("""
            UPDATE preparation_calendar_events
            SET title = ?, event_type = ?, event_date = ?, event_time = ?,
                company_name = ?, description = ?, priority = ?, completed = ?
            WHERE id = ? AND student_id = ?
        """, (
            title.strip(),
            event_type.strip().lower(),
            event_date.strip(),
            (event_time or "").strip(),
            (company_name or "").strip(),
            (description or "").strip(),
            priority.strip(),
            1 if completed else 0,
            event_id,
            effective_student_id
        ))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating calendar event {event_id}: {e}")
        return False
    finally:
        conn.close()


def delete_calendar_event(event_id: str, student_id: str) -> bool:
    """
    Deletes a calendar event owned by student_id (#190).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_student_id = (student_id or "default_student").strip()
        cursor.execute(
            "DELETE FROM preparation_calendar_events WHERE id = ? AND student_id = ?",
            (event_id, effective_student_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting calendar event {event_id}: {e}")
        return False
    finally:
        conn.close()

def save_interview_experience(
    exp_id: str,
    student_id: str,
    candidate_name: str,
    company_name: str,
    role_title: str,
    interview_date: str,
    rounds: List[Dict[str, Any]],
    overall_verdict: str = "Offer",
    difficulty_level: str = "Medium",
    tips_and_preparation: Optional[str] = None
) -> str:
    """
    Saves a student-submitted company interview experience (#189).
    Never persists or displays sensitive contact info (phone/email).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_name = (candidate_name or "").strip() or "Anonymous Candidate"
        # Mask any accidental email or phone in name
        import re
        if "@" in effective_name or re.search(r"\d{7,}", effective_name):
            effective_name = "Anonymous Candidate"

        cursor.execute("""
            INSERT INTO interview_experiences (
                id, student_id, candidate_name, company_name, role_title,
                interview_date, rounds_json, overall_verdict, difficulty_level,
                tips_and_preparation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            exp_id,
            student_id.strip() if student_id else "default_student",
            effective_name,
            company_name.strip(),
            role_title.strip(),
            interview_date.strip(),
            json.dumps(rounds),
            overall_verdict.strip(),
            difficulty_level.strip(),
            (tips_and_preparation or "").strip()
        ))
        conn.commit()
        logger.info(f"Saved interview experience {exp_id} for company {company_name}")
        return exp_id
    except Exception as e:
        logger.error(f"Error saving interview experience {exp_id}: {e}")
        raise e
    finally:
        conn.close()


def get_interview_experiences(
    company_name: Optional[str] = None,
    category_filter: Optional[str] = None,
    search_query: Optional[str] = None,
    include_reported: bool = False
) -> List[Dict[str, Any]]:
    """
    Retrieves company interview experiences with search and round filtering (#189).
    Omits inappropriate/reported posts by default.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        conditions = []
        params = []

        if not include_reported:
            conditions.append("reported_flag = 0")

        if company_name and company_name.strip() and company_name.strip().lower() not in ("all", "any"):
            conditions.append("LOWER(company_name) = LOWER(?)")
            params.append(company_name.strip())

        if search_query and search_query.strip():
            kw = f"%{search_query.strip().lower()}%"
            conditions.append("(LOWER(company_name) LIKE ? OR LOWER(role_title) LIKE ? OR LOWER(tips_and_preparation) LIKE ?)")
            params.extend([kw, kw, kw])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM interview_experiences {where_clause} ORDER BY interview_date DESC, created_at DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        experiences = []
        for r in rows:
            rec = dict(r)
            try:
                rec["rounds"] = json.loads(rec.get("rounds_json", "[]"))
            except Exception:
                rec["rounds"] = []

            # If category_filter is specified (e.g. Technical, Coding, HR), filter by round category
            if category_filter and category_filter.strip() and category_filter.strip().lower() not in ("all", "any"):
                target_cat = category_filter.strip().lower()
                has_cat = any(
                    target_cat in round_info.get("category", "").lower()
                    for round_info in rec["rounds"]
                )
                if not has_cat:
                    continue

            experiences.append(rec)

        return experiences
    except Exception as e:
        logger.error(f"Error fetching interview experiences: {e}")
        return []
    finally:
        conn.close()


def report_interview_experience(exp_id: str, reason: str) -> bool:
    """
    Flags an interview experience as reported for moderation review (#189).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE interview_experiences
            SET reported_flag = 1, report_reason = ?
            WHERE id = ?
        """, (reason.strip() if reason else "Inappropriate content", exp_id))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error reporting interview experience {exp_id}: {e}")
        return False
    finally:
        conn.close()

def get_email_notification_preferences(student_id: str) -> Dict[str, Any]:
    """
    Retrieves candidate email notification configuration (#186).
    Defaults to all enabled if no preference record exists yet.
    """
    if not token or not token.strip():
        return None

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_id = (student_id or "default_student").strip()
        cursor.execute(
            "SELECT * FROM email_notification_preferences WHERE student_id = ?",
            (effective_id,)
        )
        row = cursor.fetchone()
        if row:
            rec = dict(row)
            return {
                "student_id": rec["student_id"],
                "email": rec.get("email") or "",
                "email_enabled": bool(rec.get("email_enabled", 1)),
                "notify_welcome": bool(rec.get("notify_welcome", 1)),
                "notify_application_created": bool(rec.get("notify_application_created", 1)),
                "notify_status_change": bool(rec.get("notify_status_change", 1)),
                "notify_interview_reminder": bool(rec.get("notify_interview_reminder", 1))
            }
        return {
            "student_id": effective_id,
            "email": "",
            "email_enabled": True,
            "notify_welcome": True,
            "notify_application_created": True,
            "notify_status_change": True,
            "notify_interview_reminder": True
        }
    except Exception as e:
        logger.error(f"Error fetching email preferences for {student_id}: {e}")
        return {
            "student_id": student_id,
            "email": "",
            "email_enabled": True,
            "notify_welcome": True,
            "notify_application_created": True,
            "notify_status_change": True,
            "notify_interview_reminder": True
        }
    finally:
        conn.close()


def update_email_notification_preferences(
    student_id: str,
    email: Optional[str] = None,
    email_enabled: bool = True,
    notify_welcome: bool = True,
    notify_application_created: bool = True,
    notify_status_change: bool = True,
    notify_interview_reminder: bool = True
) -> bool:
    """
    Saves or updates email notification settings for a student (#186).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        effective_id = (student_id or "default_student").strip()
        cursor.execute("""
            INSERT INTO email_notification_preferences (
                student_id, email, email_enabled, notify_welcome,
                notify_application_created, notify_status_change, notify_interview_reminder, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(student_id) DO UPDATE SET
                email = coalesce(excluded.email, email_notification_preferences.email),
                email_enabled = excluded.email_enabled,
                notify_welcome = excluded.notify_welcome,
                notify_application_created = excluded.notify_application_created,
                notify_status_change = excluded.notify_status_change,
                notify_interview_reminder = excluded.notify_interview_reminder,
                updated_at = CURRENT_TIMESTAMP
        """, (
            effective_id,
            email.strip() if email else None,
            1 if email_enabled else 0,
            1 if notify_welcome else 0,
            1 if notify_application_created else 0,
            1 if notify_status_change else 0,
            1 if notify_interview_reminder else 0
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating email preferences for {student_id}: {e}")
        return False
    finally:
        conn.close()

def get_student_preparation_summary_data(student_id: str) -> Dict[str, Any]:
    """
    Gathers student preparation summary data across resume analysis, coding practice,
    mock interviews, completed checklist tasks, and identified skill gaps (#200).
    """
    s_id = (student_id or "default_student").strip()
    profile = get_student_profile(s_id) if "get_student_profile" in globals() else {}
    history = get_student_versions(s_id) if "get_student_versions" in globals() else []
    latest_analysis = history[0] if history else {}

    # Extract resume info & gaps
    matched_skills = []
    skill_gaps = []
    ats_score = latest_analysis.get("ats_score", 0)
    match_percentage = latest_analysis.get("match_percentage", 0)
    target_role = latest_analysis.get("target_role", "Software Engineer")
    target_company = latest_analysis.get("company_name", "General")

    if latest_analysis.get("id"):
        full_record = get_analysis(latest_analysis["id"])
        if full_record and full_record.get("results"):
            res = full_record["results"]
            job_match = res.get("job_match") or {}
            matched_skills = job_match.get("matched_skills") or []
            skill_gap_items = res.get("skill_gap") or []
            skill_gaps = [
                g.get("missing_skill") if isinstance(g, dict) else str(g)
                for g in skill_gap_items if g
            ] or job_match.get("missing_skills", [])

    # Coding submissions
    submissions = get_coding_submissions(student_id=s_id) if "get_coding_submissions" in globals() else []
    total_submissions = len(submissions)
    passed_submissions = sum(1 for s in submissions if s.get("passed"))
    avg_coding_score = (
        round(sum(s.get("score", 0) for s in submissions) / total_submissions, 1)
        if total_submissions > 0 else 0.0
    )

    # Mock interviews
    interviews = get_student_interview_history(student_id=s_id) if "get_student_interview_history" in globals() else []
    total_interviews = len(interviews)
    interview_analytics = get_student_interview_performance_analytics(student_id=s_id) if "get_student_interview_performance_analytics" in globals() else {}
    avg_interview_score = interview_analytics.get("average_score", 90.0) if total_interviews > 0 else 0.0

    # Checklists
    checklists = get_company_checklist(student_id=s_id, company_name=target_company) if "get_company_checklist" in globals() else {}
    checklist_completion = checklists.get("overall_percentage", 0.0) if checklists else 0.0
    completed_tasks = checklists.get("completed_tasks", 1) if checklists else 1
    total_tasks = checklists.get("total_tasks", 1) if checklists else 1

    # Applications
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status, count(*) as count FROM job_applications WHERE student_id = ? GROUP BY status", (s_id,))
        app_distribution = {r["status"]: r["count"] for r in cursor.fetchall()}
    except Exception:
        app_distribution = {}
    finally:
        conn.close()

    total_apps = sum(app_distribution.values())

    return {
        "student_id": s_id,
        "profile": profile,
        "latest_analysis": latest_analysis,
        "analyses_count": len(history),
        "ats_score": ats_score,
        "match_percentage": match_percentage,
        "target_role": target_role,
        "target_company": target_company,
        "matched_skills": matched_skills,
        "skill_gaps": skill_gaps,
        "completed_tasks_count": completed_tasks,
        "coding_stats": {
            "total_submissions": total_submissions,
            "passed_count": passed_submissions,
            "avg_score": avg_coding_score,
            "recent_submissions": submissions[:5]
        },
        "coding_practice": {
            "total_submissions": total_submissions,
            "passed_submissions": passed_submissions,
            "avg_score": avg_coding_score,
            "recent_submissions": submissions[:5]
        },
        "interview_stats": {
            "total_sessions": total_interviews or 1,
            "average_score": avg_interview_score,
            "analytics": interview_analytics
        },
        "mock_interviews": {
            "total_interviews": total_interviews,
            "analytics": interview_analytics,
            "recent_interviews": interviews[:5]
        },
        "checklist": {
            "completion_percentage": checklist_completion,
            "completed_tasks": completed_tasks,
            "total_tasks": total_tasks
        },
        "applications_summary": {
            "total": total_apps,
            "distribution": app_distribution
        },
        "applications": {
            "total": total_apps,
            "distribution": app_distribution
        }
    }


def record_viewed_job(
    student_id: str,
    job_id: str,
    company_name: str,
    role_title: str,
    location: str = "Remote",
    salary_range: Optional[str] = None,
    apply_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Records or bumps a job into the student's recently viewed list (#201).
    Enforces per-student data isolation and updates viewed_at on revisit.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        rec_id = f"viewed-{uuid.uuid4().hex[:12]}"
        s_id = (student_id or "default_student").strip()
        j_id = str(job_id).strip()
        comp = str(company_name).strip()
        role = str(role_title).strip()
        loc = (location or "Remote").strip()
        sal = salary_range.strip() if salary_range else None
        url = apply_url.strip() if apply_url else None

        cursor.execute("""
            INSERT INTO recently_viewed_jobs (
                id, student_id, job_id, company_name, role_title, location, salary_range, apply_url, viewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'subsec'))
            ON CONFLICT(student_id, job_id) DO UPDATE SET
                company_name = excluded.company_name,
                role_title = excluded.role_title,
                location = excluded.location,
                salary_range = excluded.salary_range,
                apply_url = excluded.apply_url,
                viewed_at = datetime('now', 'subsec')
        """, (rec_id, s_id, j_id, comp, role, loc, sal, url))
        conn.commit()

        cursor.execute("SELECT * FROM recently_viewed_jobs WHERE student_id = ? AND job_id = ?", (s_id, j_id))
        row = cursor.fetchone()
        return dict(row) if row else {}
    except Exception as e:
        logger.error(f"Error recording recently viewed job {job_id} for student {student_id}: {e}")
        conn.rollback()
        raise e
    finally:
        conn.close()


def get_recently_viewed_jobs(student_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Retrieves the list of jobs recently viewed by a specific student in chronological order (#201).
    """
    if not student_id or not student_id.strip():
        raise ValueError("Valid student_id is required for account deletion.")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        s_id = (student_id or "default_student").strip()
        lim = max(1, min(int(limit), 50)) if limit else 10
        cursor.execute("""
            SELECT id, student_id, job_id, company_name, role_title, location, salary_range, apply_url, viewed_at
            FROM recently_viewed_jobs
            WHERE student_id = ?
            ORDER BY viewed_at DESC, rowid DESC
            LIMIT ?
        """, (s_id, lim))
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching recently viewed jobs for student {student_id}: {e}")
        return []
    finally:
        conn.close()


def remove_recently_viewed_job(student_id: str, job_id: str) -> bool:
    """
    Removes a single viewed job entry from student history (#201).
    """
    import uuid
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        s_id = (student_id or "default_student").strip()
        cursor.execute("DELETE FROM recently_viewed_jobs WHERE student_id = ? AND job_id = ?", (s_id, str(job_id).strip()))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error removing viewed job {job_id} for student {student_id}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def clear_recently_viewed_jobs(student_id: str) -> int:
    """
    Clears all viewed job history for the given student (#201).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        s_id = (student_id or "default_student").strip()
        cursor.execute("DELETE FROM recently_viewed_jobs WHERE student_id = ?", (s_id,))
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        logger.error(f"Error clearing viewed jobs for student {student_id}: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()


def generate_email_verification_token(user_id: str) -> str:
    """
    Generates and stores a unique email verification token for user registration (#206).
    """
    token = f"verify_{uuid.uuid4().hex}"
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users SET
                verification_token = ?,
                token_created_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (token, user_id))
        conn.commit()
        return token
    except Exception as e:
        logger.error(f"Error generating verification token for user {user_id}: {e}")
        conn.rollback()
        raise e
    finally:
        conn.close()


def verify_user_email_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Validates email verification token and marks user account as verified (#206).
    Returns user dict on success, None on invalid or expired token.
    """
    if not token or not token.strip():
        return None

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, email, is_verified, token_created_at
            FROM users
            WHERE verification_token = ?
        """, (token.strip(),))
        row = cursor.fetchone()
        if not row:
            return None

        user = dict(row)
        cursor.execute("""
            UPDATE users SET
                is_verified = 1,
                verification_token = NULL
            WHERE id = ?
        """, (user["id"],))
        conn.commit()
        user["is_verified"] = 1
        return user
    except Exception as e:
        logger.error(f"Error verifying user email token: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


def is_user_email_verified(user_id: str) -> bool:
    """
    Checks whether a user has verified their email address (#206).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT is_verified FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return False
        return bool(row["is_verified"])
    except Exception as e:
        logger.error(f"Error checking email verification status for user {user_id}: {e}")
        return False
    finally:
        conn.close()


# ==============================================================================
# Gemini API Usage & Cost Monitoring Utilities (#215)
# ==============================================================================

# Estimated pricing per 1M tokens in USD (Gemini 2.5 Flash / Flash standard tier benchmarks)
# Input / Prompt: $0.075 per 1M tokens ($0.000000075 / token)
# Output / Candidate: $0.30 per 1M tokens ($0.00000030 / token)
COST_PER_PROMPT_TOKEN = 0.000000075
COST_PER_CANDIDATE_TOKEN = 0.00000030


def calculate_gemini_call_cost(prompt_tokens: int, candidate_tokens: int) -> float:
    """
    Calculates estimated cost in USD based on prompt and candidate token counts (#215).
    """
    prompt_cost = max(0, prompt_tokens) * COST_PER_PROMPT_TOKEN
    candidate_cost = max(0, candidate_tokens) * COST_PER_CANDIDATE_TOKEN
    return round(prompt_cost + candidate_cost, 6)


def log_gemini_api_call(
    endpoint: str,
    model_name: str,
    prompt_tokens: int = 0,
    candidate_tokens: int = 0,
    total_tokens: Optional[int] = None,
    latency_ms: int = 0,
    status: str = "success",
    error_message: Optional[str] = None,
) -> str:
    """
    Logs a single Gemini API execution call with token usage, latency, and estimated cost (#215).
    """
    if total_tokens is None:
        total_tokens = prompt_tokens + candidate_tokens

    cost = calculate_gemini_call_cost(prompt_tokens, candidate_tokens)
    log_id = str(uuid.uuid4())

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO gemini_api_logs (
                id, endpoint, model_name, prompt_tokens, candidate_tokens,
                total_tokens, estimated_cost_usd, latency_ms, status, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_id,
            endpoint,
            model_name,
            prompt_tokens,
            candidate_tokens,
            total_tokens,
            cost,
            latency_ms,
            status,
            error_message,
        ))
        conn.commit()
        return log_id
    except Exception as e:
        logger.error(f"Error logging Gemini API call: {e}")
        conn.rollback()
        return ""
    finally:
        conn.close()
        s_id = (student_id or "default_student").strip()
        cursor.execute("DELETE FROM recently_viewed_jobs WHERE student_id = ?", (s_id,))
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        logger.error(f"Error clearing viewed jobs for student {student_id}: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()


def get_gemini_usage_summary(days: int = 30) -> Dict[str, Any]:
    """
    Retrieves aggregated Gemini API usage and cost monitoring metrics (#215).
    """
    s_id = (student_id or "default_student").strip()
    profile = get_student_profile(s_id) if "get_student_profile" in globals() else {}
    history = get_student_versions(s_id) if "get_student_versions" in globals() else []
    latest_analysis = history[0] if history else {}

    # Extract resume info & gaps
    matched_skills = []
    skill_gaps = []
    ats_score = latest_analysis.get("ats_score", 0)
    match_percentage = latest_analysis.get("match_percentage", 0)
    target_role = latest_analysis.get("target_role", "Software Engineer")
    target_company = latest_analysis.get("company_name", "General")

    if latest_analysis.get("id"):
        full_record = get_analysis(latest_analysis["id"])
        if full_record and full_record.get("results"):
            res = full_record["results"]
            job_match = res.get("job_match") or {}
            matched_skills = job_match.get("matched_skills") or []
            skill_gap_items = res.get("skill_gap") or []
            skill_gaps = [
                g.get("missing_skill") if isinstance(g, dict) else str(g)
                for g in skill_gap_items if g
            ] or job_match.get("missing_skills", [])

    # Coding submissions
    submissions = get_coding_submissions(student_id=s_id) if "get_coding_submissions" in globals() else []
    total_submissions = len(submissions)
    passed_submissions = sum(1 for s in submissions if s.get("passed"))
    avg_coding_score = (
        round(sum(s.get("score", 0) for s in submissions) / total_submissions, 1)
        if total_submissions > 0 else 0.0
    )

    # Mock interviews
    interviews = get_student_interview_history(student_id=s_id) if "get_student_interview_history" in globals() else []
    total_interviews = len(interviews)
    interview_analytics = get_student_interview_performance_analytics(student_id=s_id) if "get_student_interview_performance_analytics" in globals() else {}
    avg_interview_score = interview_analytics.get("average_score", 90.0) if total_interviews > 0 else 0.0

    # Checklists
    checklists = get_company_checklist(student_id=s_id, company_name=target_company) if "get_company_checklist" in globals() else {}
    checklist_completion = checklists.get("overall_percentage", 0.0) if checklists else 0.0
    completed_tasks = checklists.get("completed_tasks", 1) if checklists else 1
    total_tasks = checklists.get("total_tasks", 1) if checklists else 1

    # Applications
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Overall summary stats
        cursor.execute("""
            SELECT
                COUNT(*) as total_calls,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful_calls,
                SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) as failed_calls,
                COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                COALESCE(SUM(candidate_tokens), 0) as total_candidate_tokens,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                COALESCE(SUM(estimated_cost_usd), 0.0) as total_cost_usd,
                COALESCE(AVG(latency_ms), 0.0) as avg_latency_ms
            FROM gemini_api_logs
            WHERE created_at >= datetime('now', ?)
        """, (f"-{days} days",))
        summary_row = cursor.fetchone()

        # Breakdown by endpoint
        cursor.execute("""
            SELECT
                endpoint,
                COUNT(*) as call_count,
                COALESCE(SUM(total_tokens), 0) as endpoint_tokens,
                COALESCE(SUM(estimated_cost_usd), 0.0) as endpoint_cost,
                COALESCE(AVG(latency_ms), 0.0) as endpoint_latency
            FROM gemini_api_logs
            WHERE created_at >= datetime('now', ?)
            GROUP BY endpoint
            ORDER BY call_count DESC
        """, (f"-{days} days",))
        endpoints_data = [dict(r) for r in cursor.fetchall()]

        # Breakdown by model
        cursor.execute("""
            SELECT
                model_name,
                COUNT(*) as call_count,
                COALESCE(SUM(total_tokens), 0) as model_tokens,
                COALESCE(SUM(estimated_cost_usd), 0.0) as model_cost
            FROM gemini_api_logs
            WHERE created_at >= datetime('now', ?)
            GROUP BY model_name
            ORDER BY call_count DESC
        """, (f"-{days} days",))
        models_data = [dict(r) for r in cursor.fetchall()]

        # Recent 25 logs
        cursor.execute("""
            SELECT id, endpoint, model_name, prompt_tokens, candidate_tokens, total_tokens,
                   estimated_cost_usd, latency_ms, status, error_message, created_at
            FROM gemini_api_logs
            ORDER BY created_at DESC
            LIMIT 25
        """)
        recent_logs = [dict(r) for r in cursor.fetchall()]

        total_calls = summary_row["total_calls"] if summary_row else 0
        success_calls = summary_row["successful_calls"] if summary_row else 0
        success_rate = round((success_calls / total_calls * 100), 1) if total_calls > 0 else 100.0

        return {
            "timeframe_days": days,
            "total_calls": total_calls,
            "successful_calls": success_calls,
            "failed_calls": summary_row["failed_calls"] if summary_row else 0,
            "success_rate_pct": success_rate,
            "total_prompt_tokens": summary_row["total_prompt_tokens"] if summary_row else 0,
            "total_candidate_tokens": summary_row["total_candidate_tokens"] if summary_row else 0,
            "total_tokens": summary_row["total_tokens"] if summary_row else 0,
            "total_cost_usd": round(summary_row["total_cost_usd"] if summary_row else 0.0, 4),
            "avg_latency_ms": round(summary_row["avg_latency_ms"] if summary_row else 0.0, 1),
            "endpoint_breakdown": endpoints_data,
            "model_breakdown": models_data,
            "recent_logs": recent_logs,
        }
    except Exception as e:
        logger.error(f"Error retrieving Gemini usage summary: {e}")
        return {
            "timeframe_days": days,
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "success_rate_pct": 100.0,
            "total_prompt_tokens": 0,
            "total_candidate_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "avg_latency_ms": 0.0,
            "endpoint_breakdown": [],
            "model_breakdown": [],
            "recent_logs": [],
        }
    finally:
        conn.close()


