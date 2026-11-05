
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
    raise RuntimeError("FLASK_SECRET_KEY is missing. Add it to your .env file.")

# Centralized model setting
GEMINI_MODEL = "gemini-2.5-flash"

# Upload file size limit (16MB)
MAX_CONTENT_LENGTH = 16 * 1024 * 1024
