"""
seed.py - Convenience CLI wrapper for local development data seeding (#task-seed-command).

Usage:
    python seed.py                # Populate isolated dev database (placement_agent_dev.db)
    python seed.py --status       # Check current seed inventory
    python seed.py --reset        # Safely reset seed data
    python seed.py --app-db       # Seed primary placement_agent.db
"""

import sys
from utils.seed_data import main

if __name__ == "__main__":
    sys.exit(main())
