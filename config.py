
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

# Ensure folders exist
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
REPORT_FOLDER.mkdir(parents=True, exist_ok=True)

# API & Security Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
if not FLASK_SECRET_KEY:
    if os.getenv("FLASK_ENV") == "production":
        raise RuntimeError("FLASK_SECRET_KEY is missing. Add it to your .env file.")
    FLASK_SECRET_KEY = "dev-secret-key-12345"

# Centralized model setting
GEMINI_MODEL = "gemini-2.5-flash"

# Upload file size limit (16MB)
MAX_CONTENT_LENGTH = 16 * 1024 * 1024

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
