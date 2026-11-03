import sqlite3
import json
import logging
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
        
        # Schema migration: check if student_id and version_number exist in analyses
        cursor.execute("PRAGMA table_info(analyses)")
        existing_cols = [col[1] for col in cursor.fetchall()]
        if "student_id" not in existing_cols:
            cursor.execute("ALTER TABLE analyses ADD COLUMN student_id TEXT DEFAULT 'default_student'")
        if "version_number" not in existing_cols:
            cursor.execute("ALTER TABLE analyses ADD COLUMN version_number INTEGER DEFAULT 1")

        # Indexes for query, sorting, and version lookup performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_analyses_created_at ON analyses (created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_analyses_student_version ON analyses (student_id, version_number ASC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_interviews_analysis_id ON interviews (analysis_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_comparisons_created ON batch_comparisons (created_at DESC)")
        
        conn.commit()
        logger.info("Database schema checked and initialized successfully.")
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
    """
    Inserts a newly generated coordinator analysis into the database.
    Automatically assigns candidate student_id and auto-increments version_number if omitted.
    """
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
    Deletes an analysis record and its corresponding interview sessions.
    Returns True if an analysis was deleted, False if not found.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM interviews WHERE analysis_id = ?", (analysis_id,))
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

        cursor.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0]

        return {
            "healthy": is_healthy,
            "status": "ok" if is_healthy else "corrupted",
            "messages": integrity_rows,
            "tables": {
                "analyses_count": analyses_count,
                "interviews_count": interviews_count,
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
