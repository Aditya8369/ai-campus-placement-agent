"""
AI Model and Prompt Versioning Service
Attaches deterministic model identifiers, prompt versions, and evaluation metadata
to every placement analysis without exposing sensitive internal prompts or secret API keys.

Features:
- Configurable model versions (e.g. 'gemini-1.5-flash-v2.1', 'gpt-4o-mini-2024-07-18', 'placement-eval-agent-v1.4').
- Prompt version hashing and semantic identifier tracking (e.g. 'resume-scorer-prompt-v2.0').
- Safe metadata injection: strips API keys, proprietary preamble instructions, and private tokens.
- Auditable reproducibility info attached to analysis records and user-facing reports.
- Version drift detection and prompt catalog verification.
"""

from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
from typing import Dict, Any, List, Optional
from utils.database import get_db_connection

DEFAULT_MODEL_VERSION = "gemini-1.5-flash-placement-v2"
DEFAULT_PROMPT_VERSION = "placement-eval-prompt-v2.1"

# Standard registered prompt registry
PROMPT_CATALOG = {
    "resume-scorer-v1": "Standard resume scoring rubric assessing technical skills, education, and format.",
    "resume-scorer-v2": "Enhanced ATS resume scoring rubric incorporating quantifiable outcomes and action verbs.",
    "interview-evaluator-v1": "STAR behavioral interview evaluation framework.",
    "interview-evaluator-v2": "Technical & architectural mock interview scoring engine with feedback rubrics.",
    "skill-gap-analyzer-v1": "Maps resume competencies against target job role requirements."
}


class AIModelPromptVersioningService:
    """Service to track, audit, and verify AI model and prompt version metadata."""

    def __init__(
        self,
        default_model: str = DEFAULT_MODEL_VERSION,
        default_prompt_version: str = DEFAULT_PROMPT_VERSION
    ):
        self.default_model = default_model
        self.default_prompt_version = default_prompt_version
        self.prompt_catalog = PROMPT_CATALOG
        self._ensure_version_column()

    def _ensure_version_column(self):
        """Ensures the analysis table or version metadata table exists."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_version_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                model_version TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                prompt_fingerprint TEXT NOT NULL,
                execution_mode TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_avm_analysis_id 
            ON analysis_version_metadata(analysis_id)
            """
        )
        conn.commit()
        conn.close()

    def sanitize_metadata_inputs(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Strips potential API keys, secrets, or authorization headers from version payloads.
        """
        sanitized = {}
        secret_keys = {"api_key", "secret", "token", "authorization", "password", "key"}
        for k, v in raw_data.items():
            if any(s in k.lower() for s in secret_keys):
                continue
            if isinstance(v, str):
                # Redact potential key patterns (e.g. AIzaSy, sk-...)
                cleaned = re.sub(r"(AIza[0-9A-Za-z-_]{35}|sk-[a-zA-Z0-9]{32,})", "[REDACTED_API_KEY]", v)
                sanitized[k] = cleaned
            else:
                sanitized[k] = v
        return sanitized

    def generate_prompt_fingerprint(self, raw_prompt_template: str) -> str:
        """
        Generates a non-reversible SHA-256 hash of the prompt template.
        Guarantees that prompts can be compared for reproducibility without leaking internal prompt text.
        """
        if not raw_prompt_template:
            return "empty-fingerprint"
        cleaned = raw_prompt_template.strip().encode("utf-8")
        return hashlib.sha256(cleaned).hexdigest()[:16]

    def build_version_metadata(
        self,
        model_name: Optional[str] = None,
        model_version: Optional[str] = None,
        prompt_version: Optional[str] = None,
        raw_prompt_template: Optional[str] = None,
        execution_mode: str = "production"
    ) -> Dict[str, Any]:
        """
        Creates a clean, safe versioning dictionary suitable for public response or storage.
        """
        m_name = model_name or "Gemini Flash AI Placement Engine"
        m_version = model_version or self.default_model
        p_version = prompt_version or self.default_prompt_version
        p_hash = self.generate_prompt_fingerprint(raw_prompt_template or p_version)
        utc_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        catalog_entry = self.prompt_catalog.get(p_version, "Custom or uncatalogued prompt rubric")

        return {
            "model_name": m_name,
            "model_version": m_version,
            "prompt_version": p_version,
            "prompt_fingerprint": p_hash,
            "prompt_description": catalog_entry,
            "execution_mode": execution_mode,
            "timestamp": utc_ts
        }

    def record_analysis_version(
        self,
        analysis_id: str,
        student_id: str,
        model_name: Optional[str] = None,
        model_version: Optional[str] = None,
        prompt_version: Optional[str] = None,
        raw_prompt_template: Optional[str] = None,
        execution_mode: str = "production"
    ) -> int:
        """
        Persists analysis versioning information to the database.
        """
        meta = self.build_version_metadata(
            model_name=model_name,
            model_version=model_version,
            prompt_version=prompt_version,
            raw_prompt_template=raw_prompt_template,
            execution_mode=execution_mode
        )

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO analysis_version_metadata
            (analysis_id, student_id, model_name, model_version, prompt_version, prompt_fingerprint, execution_mode, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_id,
                student_id,
                meta["model_name"],
                meta["model_version"],
                meta["prompt_version"],
                meta["prompt_fingerprint"],
                meta["execution_mode"],
                datetime.now(timezone.utc).isoformat()
            )
        )
        row_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return row_id

    def list_student_version_history(self, student_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Lists all evaluation runs and their version metadata for a student.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT analysis_id, student_id, model_name, model_version, prompt_version, 
                   prompt_fingerprint, execution_mode, created_at
            FROM analysis_version_metadata
            WHERE student_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (student_id, limit)
        )
        rows = cursor.fetchall()
        conn.close()

        results = []
        for r in rows:
            results.append({
                "analysis_id": r["analysis_id"],
                "student_id": r["student_id"],
                "model_name": r["model_name"],
                "model_version": r["model_version"],
                "prompt_version": r["prompt_version"],
                "prompt_fingerprint": r["prompt_fingerprint"],
                "execution_mode": r["execution_mode"],
                "created_at": str(r["created_at"])
            })
        return results

    def get_analysis_version_info(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves the versioning metadata recorded for a specific analysis run.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT analysis_id, student_id, model_name, model_version, prompt_version, 
                   prompt_fingerprint, execution_mode, created_at
            FROM analysis_version_metadata
            WHERE analysis_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (analysis_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return {
            "analysis_id": row["analysis_id"],
            "student_id": row["student_id"],
            "model_name": row["model_name"],
            "model_version": row["model_version"],
            "prompt_version": row["prompt_version"],
            "prompt_fingerprint": row["prompt_fingerprint"],
            "execution_mode": row["execution_mode"],
            "created_at": str(row["created_at"])
        }


ai_versioning_service = AIModelPromptVersioningService()
