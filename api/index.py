"""
Vercel Serverless Function WSGI Entrypoint for AI Campus Placement Agent.
Exports the Flask WSGI callable `app` for Vercel Python runtime execution.
"""

import os
import sys
from pathlib import Path

# Ensure root directory is on the Python module search path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure VERCEL environment variable is set
os.environ.setdefault("VERCEL", "1")

# Import the Flask application instance
from app import app

