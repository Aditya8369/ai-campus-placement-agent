#!/usr/bin/env python3
"""
Contributor Company Data Validation CLI Script (#785).
======================================================
Validates contributor company JSON files against required schemas, checks for
duplicate company names, detects broken links / invalid URLs, and highlights
field-specific errors with clear file and field names.

Usage:
    python scripts/validate_company_data.py [paths...]
    python scripts/validate_company_data.py --help
    python scripts/validate_company_data.py data/companies.json --strict
    python scripts/validate_company_data.py --json
"""

import sys
from pathlib import Path

# Ensure project root is available in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.company_data_validator import main

if __name__ == "__main__":
    sys.exit(main())
