
import os
from pathlib import Path
from dotenv import load_dotenv

# Project version
__version__ = "1.0.0"

# Load environment variables from .env
load_dotenv()

# Base project directory
BASE_DIR = Path(__file__).resolve().parent

# Detect Vercel environment
IS_VERCEL = os.getenv("VERCEL") == "1"

# Directory configurations
if IS_VERCEL:
    STORAGE_DIR = Path("/tmp")
else:
    STORAGE_DIR = BASE_DIR

UPLOAD_FOLDER = STORAGE_DIR / "uploads"
REPORT_FOLDER = STORAGE_DIR / "reports"
DATABASE_PATH = STORAGE_DIR / "placement_agent.db"
BACKUP_DIR = STORAGE_DIR / "backups"
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "admin-secret-key")

# Ensure folders exist
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
REPORT_FOLDER.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# API & Security Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
if not FLASK_SECRET_KEY:
    if os.getenv("FLASK_ENV") == "production":
        raise RuntimeError("FLASK_SECRET_KEY is missing. Add it to your .env file.")
    FLASK_SECRET_KEY = "dev-secret-key-12345"

ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "admin-default-secret-key-2026")

# Centralized model setting
GEMINI_MODEL = "gemini-2.5-flash"

# Upload file size limit (default: 5MB, configurable via MAX_UPLOAD_SIZE_MB or MAX_RESUME_SIZE_MB) (Issue #153)
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", os.getenv("MAX_RESUME_SIZE_MB", "5")))
MAX_RESUME_FILE_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
MAX_FILE_SIZE_BYTES = MAX_RESUME_FILE_SIZE_BYTES
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(MAX_RESUME_FILE_SIZE_BYTES)))
MAX_FEEDBACK_COMMENT_LENGTH = int(os.getenv("MAX_FEEDBACK_COMMENT_LENGTH", "500"))

# Structured Logging & Request Tracing Configurations (#301)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv("LOG_FORMAT", "key_value").lower()

# Rate Limiting & Abuse Prevention Configurations (Issue #160)
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")

# Configurable rate limit definitions (format: "<count>/<unit>" e.g. "5/hour", "30/hour", "100/minute")
# Stricter quotas apply to computationally expensive AI-backed endpoints to prevent API exhaustion:
RATE_LIMIT_ANALYZE = os.getenv("RATE_LIMIT_ANALYZE", "5/hour")
RATE_LIMIT_INTERVIEW = os.getenv("RATE_LIMIT_INTERVIEW", "30/hour")
RATE_LIMIT_BATCH = os.getenv("RATE_LIMIT_BATCH", "10/hour")
RATE_LIMIT_OUTREACH = os.getenv("RATE_LIMIT_OUTREACH", "20/hour")
RATE_LIMIT_STAR = os.getenv("RATE_LIMIT_STAR", "30/hour")
RATE_LIMIT_DEFAULT = os.getenv("RATE_LIMIT_DEFAULT", "100/minute")

RATE_LIMITS = {
    "analyze": RATE_LIMIT_ANALYZE,
    "analyze_submission": RATE_LIMIT_ANALYZE,
    "interview_eval": RATE_LIMIT_INTERVIEW,
    "interview": RATE_LIMIT_INTERVIEW,
    "batch_compare": RATE_LIMIT_BATCH,
    "generate_outreach": RATE_LIMIT_OUTREACH,
    "outreach": RATE_LIMIT_OUTREACH,
    "star_eval": RATE_LIMIT_STAR,
    "default": RATE_LIMIT_DEFAULT,
}

# Scanned / Image-Only PDF Detection & OCR Fallback (Issue #154)
# Detects image-only / scanned PDFs where PyPDF2 extracts fewer than MIN_PDF_TEXT_CHARS.
# Prevents meaningless analyses and wasted AI quota.
MIN_PDF_TEXT_CHARS = int(os.getenv("MIN_PDF_TEXT_CHARS", "100"))
MIN_PDF_EXTRACTED_CHARS = MIN_PDF_TEXT_CHARS
ENABLE_OCR_FALLBACK = os.getenv("ENABLE_OCR_FALLBACK", "false").lower() in ("true", "1", "yes")

# Gemini API Transient Error Retry & Exponential Backoff Configurations (Issue #155)
# Transient errors (429 rate limit, 500/503 server errors, network timeouts) are retried automatically.
# Permanent errors (400 bad request, 401/403 invalid credentials) fail fast without retry.
GEMINI_RETRY_ATTEMPTS = int(os.getenv("GEMINI_RETRY_ATTEMPTS", os.getenv("GEMINI_MAX_RETRIES", "3")))
GEMINI_MAX_RETRIES = GEMINI_RETRY_ATTEMPTS
GEMINI_RETRY_INITIAL_DELAY = float(os.getenv("GEMINI_RETRY_INITIAL_DELAY", "1.0"))  # in seconds (e.g. 1s, 2s, 4s)
GEMINI_RETRY_BACKOFF_FACTOR = float(os.getenv("GEMINI_RETRY_BACKOFF_FACTOR", "2.0"))
GEMINI_RETRY_MAX_DELAY = float(os.getenv("GEMINI_RETRY_MAX_DELAY", "10.0"))  # in seconds
GEMINI_RETRY_JITTER = os.getenv("GEMINI_RETRY_JITTER", "true").lower() in ("true", "1", "yes")

# Session Expiration & Inactivity Tracking Configurations
SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "30"))
SESSION_TIMEOUT_SECONDS = int(os.getenv("SESSION_TIMEOUT_SECONDS", str(SESSION_TIMEOUT_MINUTES * 60)))
SESSION_WARNING_SECONDS = int(os.getenv("SESSION_WARNING_SECONDS", "120"))

