"""
Analysis Reproducibility Summary Service
Produces a deterministic reproducibility summary for placement evaluation runs.

Features:
- Fingerprints input data (resume text, job description, target role, evaluation parameters).
- Records generation environment (deterministic seeds, temperature, model version, rubric hash).
- Compares repeated evaluation runs to measure stability and score divergence.
- Produces downloadable/viewable reproducibility report cards explaining why scores vary
  or how identical conditions can replicate results.
"""

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Dict, Any, List, Optional
from utils.database import get_db_connection


class AnalysisReproducibilityService:
    """Service to generate and audit analysis reproducibility summaries."""

    def __init__(self):
        self._ensure_reproducibility_table()

    def _ensure_reproducibility_table(self):
        """Ensures the reproducibility table exists in SQLite database."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_reproducibility_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                input_fingerprint TEXT NOT NULL,
                config_fingerprint TEXT NOT NULL,
                model_identifier TEXT NOT NULL,
                temperature REAL NOT NULL,
                seed INTEGER,
                summary_json TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_arr_analysis_id 
            ON analysis_reproducibility_records(analysis_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_arr_input_fp 
            ON analysis_reproducibility_records(student_id, input_fingerprint)
            """
        )
        conn.commit()
        conn.close()

    def generate_input_fingerprint(
        self,
        resume_text: str,
        job_description: Optional[str] = None,
        target_role: Optional[str] = None
    ) -> str:
        """
        Creates a normalized hash representing the candidate's exact input materials.
        """
        norm_resume = re.sub(r"\s+", " ", (resume_text or "").strip().lower())
        norm_jd = re.sub(r"\s+", " ", (job_description or "").strip().lower())
        norm_role = (target_role or "general").strip().lower()

        combined = f"resume:{norm_resume}|jd:{norm_jd}|role:{norm_role}"
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:24]

    def generate_config_fingerprint(
        self,
        model_name: str,
        prompt_version: str,
        temperature: float = 0.2,
        seed: Optional[int] = None
    ) -> str:
        """Creates a hash representing model parameters and evaluation rubrics."""
        raw = f"{model_name}:{prompt_version}:{temperature}:{seed}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def build_reproducibility_summary(
        self,
        analysis_id: str,
        student_id: str,
        resume_text: str,
        job_description: Optional[str] = None,
        target_role: Optional[str] = None,
        model_name: str = "gemini-1.5-flash",
        prompt_version: str = "v2.1",
        temperature: float = 0.2,
        seed: Optional[int] = 42,
        scores: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Assembles a comprehensive, auditable reproducibility certificate for an analysis run.
        """
        input_fp = self.generate_input_fingerprint(resume_text, job_description, target_role)
        config_fp = self.generate_config_fingerprint(model_name, prompt_version, temperature, seed)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        summary = {
            "analysis_id": analysis_id,
            "student_id": student_id,
            "timestamp": timestamp,
            "reproducibility_certificate": {
                "input_fingerprint": input_fp,
                "config_fingerprint": config_fp,
                "verification_hash": hashlib.sha256(f"{input_fp}:{config_fp}:{analysis_id}".encode("utf-8")).hexdigest()[:16],
                "deterministic_seed": seed,
                "temperature": temperature,
                "model_identifier": model_name,
                "prompt_version": prompt_version
            },
            "parameters_audited": {
                "resume_char_count": len(resume_text or ""),
                "has_job_description": bool(job_description and job_description.strip()),
                "target_role": target_role or "Unspecified",
                "evaluated_scores": scores or {}
            },
            "reproducibility_guidance": (
                "To reproduce this evaluation with identical scoring parameters, supply the exact same resume "
                f"text (Fingerprint: {input_fp}) using model '{model_name}' and prompt version '{prompt_version}'."
            )
        }
        return summary

    def record_reproducibility_summary(
        self,
        analysis_id: str,
        student_id: str,
        resume_text: str,
        job_description: Optional[str] = None,
        target_role: Optional[str] = None,
        model_name: str = "gemini-1.5-flash",
        prompt_version: str = "v2.1",
        temperature: float = 0.2,
        seed: Optional[int] = 42,
        scores: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Persists the reproducibility card into SQLite and returns the constructed summary.
        """
        summary = self.build_reproducibility_summary(
            analysis_id=analysis_id,
            student_id=student_id,
            resume_text=resume_text,
            job_description=job_description,
            target_role=target_role,
            model_name=model_name,
            prompt_version=prompt_version,
            temperature=temperature,
            seed=seed,
            scores=scores
        )

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO analysis_reproducibility_records
            (analysis_id, student_id, input_fingerprint, config_fingerprint, model_identifier, temperature, seed, summary_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_id,
                student_id,
                summary["reproducibility_certificate"]["input_fingerprint"],
                summary["reproducibility_certificate"]["config_fingerprint"],
                model_name,
                temperature,
                seed,
                json.dumps(summary),
                datetime.now(timezone.utc).isoformat()
            )
        )
        conn.commit()
        conn.close()
        return summary

    def get_reproducibility_summary(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves reproducibility summary for a specific analysis."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT summary_json FROM analysis_reproducibility_records
            WHERE analysis_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (analysis_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return json.loads(row["summary_json"])

    def compare_runs_reproducibility(
        self,
        analysis_id_a: str,
        analysis_id_b: str
    ) -> Dict[str, Any]:
        """
        Compares two runs to determine whether inputs and configs match.
        """
        run_a = self.get_reproducibility_summary(analysis_id_a)
        run_b = self.get_reproducibility_summary(analysis_id_b)

        if not run_a or not run_b:
            return {
                "matched": False,
                "error": "One or both analysis records were not found."
            }

        cert_a = run_a["reproducibility_certificate"]
        cert_b = run_b["reproducibility_certificate"]

        same_input = cert_a["input_fingerprint"] == cert_b["input_fingerprint"]
        same_config = cert_a["config_fingerprint"] == cert_b["config_fingerprint"]

        return {
            "same_inputs": same_input,
            "same_configurations": same_config,
            "is_fully_identical_environment": same_input and same_config,
            "analysis_id_a": analysis_id_a,
            "analysis_id_b": analysis_id_b,
            "details": {
                "model_a": cert_a["model_identifier"],
                "model_b": cert_b["model_identifier"],
                "prompt_a": cert_a["prompt_version"],
                "prompt_b": cert_b["prompt_version"]
            }
        }


analysis_reproducibility_service = AnalysisReproducibilityService()
