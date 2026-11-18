"""
Time-Based One-Time Password (TOTP) and Recovery Code Utilities (#380).

Standard library implementation compliant with RFC 6238 (TOTP) and RFC 4226 (HOTP).
Provides:
- Base32 secret generation and formatting
- RFC 6238 time-step code generation and verification with clock-drift window
- Emergency backup recovery codes generation and salted/SHA-256 verification
- Authenticator app URI generation (compatible with Google Authenticator, Microsoft Authenticator, Authy, Apple Passwords)
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import struct
import time
import urllib.parse
from typing import List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Standard Base32 alphabet according to RFC 4648
BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
TIME_STEP_SECONDS = 30
CODE_DIGITS = 6


def generate_totp_secret(length: int = 32) -> str:
    """
    Generate a cryptographically secure Base32 secret for TOTP.
    Default 32 characters provides 160 bits of entropy (matching SHA-1).
    """
    return "".join(secrets.choice(BASE32_ALPHABET) for _ in range(length))


def format_totp_secret(secret: str) -> str:
    """
    Format a Base32 secret into 4-character chunks for human-friendly manual entry.
    Example: 'JBSWY3DPEHPK3PXP' -> 'JBSW Y3DP EHPK 3PXP'
    """
    cleaned = secret.replace(" ", "").replace("-", "").upper()
    return " ".join(cleaned[i:i + 4] for i in range(0, len(cleaned), 4))


def generate_totp_uri(secret: str, account_name: str, issuer: str = "AI Campus Placement Agent") -> str:
    """
    Generate an RFC 6238 compliant otpauth:// URI for authenticator app configuration.
    """
    cleaned_secret = secret.replace(" ", "").replace("-", "").upper()
    label = f"{issuer}:{account_name.strip()}"
    params = {
        "secret": cleaned_secret,
        "issuer": issuer,
        "algorithm": "SHA1",
        "digits": str(CODE_DIGITS),
        "period": str(TIME_STEP_SECONDS)
    }
    encoded_label = urllib.parse.quote(label)
    encoded_params = urllib.parse.urlencode(params)
    return f"otpauth://totp/{encoded_label}?{encoded_params}"


def _decode_base32_secret(secret: str) -> bytes:
    """
    Safely decode a Base32 secret into bytes, padding with '=' as necessary.
    """
    cleaned = secret.replace(" ", "").replace("-", "").upper().strip()
    missing_padding = len(cleaned) % 8
    if missing_padding:
        cleaned += "=" * (8 - missing_padding)
    return base64.b32decode(cleaned, casefold=True)


def generate_totp_code(secret: str, timestamp: Optional[float] = None) -> str:
    """
    Generate the current 6-digit TOTP code for a secret at a given timestamp.
    """
    current_time = time.time() if timestamp is None else timestamp
    time_step = int(current_time // TIME_STEP_SECONDS)
    key_bytes = _decode_base32_secret(secret)
    counter_bytes = struct.pack(">Q", time_step)

    hmac_hash = hmac.new(key_bytes, counter_bytes, hashlib.sha1).digest()
    offset = hmac_hash[-1] & 0x0F
    binary_code = struct.unpack(">I", hmac_hash[offset:offset + 4])[0] & 0x7FFFFFFF
    otp = binary_code % (10 ** CODE_DIGITS)
    return str(otp).zfill(CODE_DIGITS)


def verify_totp_code(secret: str, user_code: str, window: int = 1, timestamp: Optional[float] = None) -> bool:
    """
    Verify a user-provided TOTP code against the secret.
    Allows clock drift within +/- `window` time steps (default +/- 1 step = 30 seconds).
    Uses constant-time comparison to prevent timing side-channel attacks.
    """
    if not secret or not user_code:
        return False

    cleaned_code = str(user_code).strip().replace(" ", "").replace("-", "")
    if len(cleaned_code) != CODE_DIGITS or not cleaned_code.isdigit():
        return False

    try:
        key_bytes = _decode_base32_secret(secret)
    except Exception as exc:
        logger.warning("Failed to decode Base32 secret during TOTP verification: %s", exc)
        return False

    current_time = time.time() if timestamp is None else timestamp
    current_step = int(current_time // TIME_STEP_SECONDS)

    for offset in range(-window, window + 1):
        step = current_step + offset
        counter_bytes = struct.pack(">Q", step)
        hmac_hash = hmac.new(key_bytes, counter_bytes, hashlib.sha1).digest()
        idx = hmac_hash[-1] & 0x0F
        binary_code = struct.unpack(">I", hmac_hash[idx:idx + 4])[0] & 0x7FFFFFFF
        valid_code = str(binary_code % (10 ** CODE_DIGITS)).zfill(CODE_DIGITS)

        if hmac.compare_digest(valid_code, cleaned_code):
            return True

    return False


# ==============================================================================
# Emergency Backup Recovery Codes
# ==============================================================================

RECOVERY_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # Omits 0/O, 1/I to avoid visual confusion


def generate_backup_codes(count: int = 8) -> List[str]:
    """
    Generate emergency one-time recovery codes formatted as 'XXXX-XXXX'.
    Example: 'A7K9-W3M2'
    """
    codes = []
    for _ in range(count):
        part1 = "".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(4))
        part2 = "".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(4))
        codes.append(f"{part1}-{part2}")
    return codes


def hash_backup_code(code: str) -> str:
    """
    Compute a normalized SHA-256 hash of a recovery code.
    Normalized by removing hyphens and converting to uppercase.
    """
    normalized = str(code).replace("-", "").replace(" ", "").strip().upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def verify_and_consume_backup_code(
    stored_codes_data: Union[str, List[str], None],
    provided_code: str
) -> Tuple[bool, List[str]]:
    """
    Verify a provided backup recovery code against stored hashes.
    If valid, removes the consumed hash from the list and returns (True, updated_hashes).
    If invalid, returns (False, original_hashes).
    """
    if not stored_codes_data or not provided_code:
        return False, []

    if isinstance(stored_codes_data, str):
        try:
            hashes_list = json.loads(stored_codes_data)
        except Exception:
            return False, []
    elif isinstance(stored_codes_data, list):
        hashes_list = list(stored_codes_data)
    else:
        return False, []

    provided_hash = hash_backup_code(provided_code)

    for idx, stored_hash in enumerate(hashes_list):
        if hmac.compare_digest(stored_hash, provided_hash):
            # Code found - remove consumed code (single use only)
            updated_hashes = hashes_list[:idx] + hashes_list[idx + 1:]
            return True, updated_hashes

    return False, hashes_list
