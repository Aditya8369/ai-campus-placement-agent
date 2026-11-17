"""
Secure Account Recovery Code Service (#406).

Provides an optional, high-security one-time recovery code system:
- Generates sets of cryptographically strong recovery codes (e.g. 10 codes formatted as XXXX-XXXX-XXXX).
- Hashes codes using salted SHA-256 before database storage; plaintext codes are NEVER persisted.
- Automatically invalidates any existing recovery codes when a new set is generated.
- Single-use consumption: each code is irrevocably consumed upon successful authentication.
- Ephemeral display policy: Plaintext codes are displayed to the user strictly once during generation.
- Downloadable formatted text file generation and clipboard formatting.
- Unsaved warning tracking to prevent accidental navigation loss.
"""

from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import re
import secrets
from typing import Dict, Any, List, Optional, Tuple, Union
from utils.database import get_db_connection, get_user_by_id

logger = logging.getLogger(__name__)

# Base32-like alphabet avoiding visual ambiguities (0/O, 1/I, L)
SAFE_RECOVERY_CHARSET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
DEFAULT_CODE_COUNT = 10
CODE_SECTION_LENGTH = 4
CODE_SECTIONS = 3  # e.g., ABCD-EFGH-JKMN (12 chars of entropy = ~60 bits per code)


class AccountRecoveryCodeService:
    """Service to handle generation, hashing, verification, and audit of recovery codes."""

    def __init__(self, code_count: int = DEFAULT_CODE_COUNT):
        self.code_count = code_count
        self._ensure_table()

    def _ensure_table(self):
        """Ensures the account_recovery_codes table exists."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS account_recovery_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                is_consumed INTEGER DEFAULT 0,
                consumed_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                generation_batch_id TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_arc_user_batch 
            ON account_recovery_codes(user_id, generation_batch_id, is_consumed)
            """
        )
        conn.commit()
        conn.close()

    def generate_raw_code(self) -> str:
        """
        Generate a single human-readable one-time recovery code.
        Format: 'XXXX-XXXX-XXXX'
        """
        sections = []
        for _ in range(CODE_SECTIONS):
            part = "".join(secrets.choice(SAFE_RECOVERY_CHARSET) for _ in range(CODE_SECTION_LENGTH))
            sections.append(part)
        return "-".join(sections)

    def normalize_code(self, raw_code: str) -> str:
        """
        Normalize recovery code by stripping hyphens, spaces, and converting to uppercase.
        """
        if not raw_code:
            return ""
        return re.sub(r"[^A-Za-z0-9]", "", raw_code).strip().upper()

    def hash_recovery_code(self, raw_code: str, salt: Optional[str] = None) -> Tuple[str, str]:
        """
        Hash recovery code using salted SHA-256.
        Returns (code_hash, salt).
        """
        code_salt = salt or secrets.token_hex(16)
        normalized = self.normalize_code(raw_code)
        salted_data = f"{code_salt}:{normalized}".encode("utf-8")
        code_hash = hashlib.sha256(salted_data).hexdigest()
        return code_hash, code_salt

    def verify_code_hash(self, raw_code: str, stored_hash: str, salt: str) -> bool:
        """
        Constant-time verification of code against stored hash and salt.
        """
        computed_hash, _ = self.hash_recovery_code(raw_code, salt=salt)
        return hmac.compare_digest(computed_hash, stored_hash)

    def generate_new_code_set(self, user_id: str, count: Optional[int] = None) -> Dict[str, Any]:
        """
        Generates a fresh set of recovery codes for a user.
        CRITICAL: Automatically invalidates all existing recovery codes for this user.
        Returns the plaintext codes strictly for one-time display.
        """
        total_codes = count or self.code_count
        batch_id = f"batch_{secrets.token_hex(12)}"
        now_iso = datetime.now(timezone.utc).isoformat()

        raw_codes = [self.generate_raw_code() for _ in range(total_codes)]

        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. Invalidate previous codes by removing or marking obsolete
        cursor.execute(
            """
            DELETE FROM account_recovery_codes
            WHERE user_id = ?
            """,
            (user_id,)
        )

        # 2. Insert new hashed codes
        for code in raw_codes:
            code_hash, salt = self.hash_recovery_code(code)
            cursor.execute(
                """
                INSERT INTO account_recovery_codes
                (user_id, code_hash, salt, is_consumed, created_at, generation_batch_id)
                VALUES (?, ?, ?, 0, ?, ?)
                """,
                (user_id, code_hash, salt, now_iso, batch_id)
            )

        conn.commit()
        conn.close()

        logger.info("Generated new recovery code set for user %s (batch: %s, count: %d)", user_id, batch_id, total_codes)

        return {
            "user_id": user_id,
            "batch_id": batch_id,
            "created_at": now_iso,
            "total_count": total_codes,
            "recovery_codes": raw_codes,  # Plaintext returned ONCE only
            "instruction": "Save these codes securely now. They will not be shown again."
        }

    def get_recovery_codes_status(self, user_id: str) -> Dict[str, Any]:
        """
        Returns metadata about current recovery codes without exposing plaintext or hashes.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 
                COUNT(*) as total_count,
                SUM(CASE WHEN is_consumed = 0 THEN 1 ELSE 0 END) as remaining_count,
                SUM(CASE WHEN is_consumed = 1 THEN 1 ELSE 0 END) as consumed_count,
                MAX(created_at) as last_generated_at,
                generation_batch_id
            FROM account_recovery_codes
            WHERE user_id = ?
            GROUP BY generation_batch_id
            ORDER BY id DESC LIMIT 1
            """,
            (user_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return {
                "has_codes": False,
                "total_count": 0,
                "remaining_count": 0,
                "consumed_count": 0,
                "last_generated_at": None,
                "batch_id": None
            }

        return {
            "has_codes": row["remaining_count"] > 0 or row["total_count"] > 0,
            "total_count": row["total_count"],
            "remaining_count": row["remaining_count"] or 0,
            "consumed_count": row["consumed_count"] or 0,
            "last_generated_at": str(row["last_generated_at"]) if row["last_generated_at"] else None,
            "batch_id": row["generation_batch_id"]
        }

    def verify_and_consume_code(self, user_id: str, raw_code: str) -> Tuple[bool, str]:
        """
        Verifies a user-provided recovery code and immediately invalidates it upon use.
        Returns (success, message).
        """
        if not raw_code or not raw_code.strip():
            return False, "Recovery code is required."

        normalized = self.normalize_code(raw_code)
        if len(normalized) < 8:
            return False, "Invalid recovery code format."

        conn = get_db_connection()
        cursor = conn.cursor()

        # Query all active (unconsumed) codes for the user
        cursor.execute(
            """
            SELECT id, code_hash, salt, generation_batch_id
            FROM account_recovery_codes
            WHERE user_id = ? AND is_consumed = 0
            """,
            (user_id,)
        )
        active_codes = cursor.fetchall()

        matched_id = None
        for record in active_codes:
            if self.verify_code_hash(raw_code, record["code_hash"], record["salt"]):
                matched_id = record["id"]
                break

        if matched_id is None:
            conn.close()
            logger.warning("Failed recovery code verification attempt for user %s", user_id)
            return False, "Invalid or already consumed recovery code."

        # Mark code as consumed immediately
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            UPDATE account_recovery_codes
            SET is_consumed = 1, consumed_at = ?
            WHERE id = ?
            """,
            (now_iso, matched_id)
        )
        conn.commit()

        # Check how many codes remain
        cursor.execute(
            """
            SELECT COUNT(*) as remaining
            FROM account_recovery_codes
            WHERE user_id = ? AND is_consumed = 0
            """,
            (user_id,)
        )
        rem_row = cursor.fetchone()
        remaining = rem_row["remaining"] if rem_row else 0
        conn.close()

        logger.info("Recovery code consumed successfully for user %s. Remaining: %d", user_id, remaining)
        return True, f"Recovery code accepted. You have {remaining} recovery code{'s' if remaining != 1 else ''} remaining."

    def invalidate_all_codes(self, user_id: str) -> int:
        """
        Permanently invalidates / clears all recovery codes for a user.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM account_recovery_codes WHERE user_id = ?",
            (user_id,)
        )
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        logger.info("Invalidated all recovery codes for user %s (count: %d)", user_id, deleted_count)
        return deleted_count

    def generate_download_text(self, user_email: str, recovery_codes: List[str]) -> str:
        """
        Generates standard formatted text file content for user download.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        border = "=" * 64
        lines = [
            border,
            "AI CAMPUS PLACEMENT AGENT - ONE-TIME ACCOUNT RECOVERY CODES",
            border,
            f"Account: {user_email}",
            f"Generated: {timestamp}",
            f"Total Codes: {len(recovery_codes)}",
            "",
            "CRITICAL SECURITY NOTICE:",
            "- Each recovery code can only be used ONCE to access your account.",
            "- If you generate a new set of codes, these codes become invalid.",
            "- Store this file in a secure password manager or encrypted folder.",
            "- These codes will NOT be displayed again.",
            "",
            "YOUR RECOVERY CODES:",
            border
        ]

        for idx, code in enumerate(recovery_codes, start=1):
            lines.append(f"  {idx:2d}.  {code}")

        lines.extend([
            border,
            "End of Recovery Codes Document.",
            border
        ])
        return "\n".join(lines)


# Global singleton instance
recovery_code_service = AccountRecoveryCodeService()
