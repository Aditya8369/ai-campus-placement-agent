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


