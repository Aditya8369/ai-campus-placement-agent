"""
Pluggable Job Data Sources (#533)
=================================
Defines the JobDataSource interface and concrete implementations allowing the job
recommendation system to load listings from diverse sources (JSON files, in-memory lists,
remote APIs, RSS feeds) without changing the scoring or ranking algorithms.
"""

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any, Optional

import config

logger = logging.getLogger(__name__)

# Fallback seed jobs in case file is absent or corrupted
DEFAULT_FALLBACK_JOBS: List[Dict[str, Any]] = [
    {
        "id": "job-google-swe-univ-2026",
        "title": "Software Engineer - University Graduate (2025/2026)",
        "company": "Google",
        "logo_color": "#4285F4",
        "location": "Bengaluru",
        "role_type": "Full-time",
        "experience_level": "Fresher / 0-1 Years",
        "batch_eligibility": "2025 & 2026 Batch",
        "salary_range": "₹24 - ₹38 LPA",
        "required_skills": ["Python", "C++", "Java", "Data Structures", "Algorithms", "System Design", "Git"],
        "preferred_skills": ["Cloud Architecture", "Distributed Systems", "Machine Learning", "Linux"],
        "description": "Develop next-generation technologies that change how billions of users connect, explore, and interact.",
        "apply_url": "https://careers.google.com/jobs/results/?q=University%20Graduate",
        "posted_date": "1 day ago",
        "deadline": "Active Drive - Rolling Basis",
        "drive_mode": "National Campus Hiring",
        "work_mode": "On-site"
    },
    {
        "id": "job-msft-sde-grad-2026",
        "title": "Software Engineer - Early Career & University",
        "company": "Microsoft",
        "logo_color": "#00A4EF",
        "location": "Hyderabad",
        "role_type": "Full-time",
        "experience_level": "Fresher / 0-1 Years",
        "batch_eligibility": "2025 & 2026 Batch",
        "salary_range": "₹22 - ₹34 LPA",
        "required_skills": ["C#", "C++", "Java", "Data Structures", "Algorithms", "Object-Oriented Design", "SQL"],
        "preferred_skills": ["Azure", "Cloud Architecture", "REST APIs", "Microservices"],
        "description": "Design, build, and deploy large-scale cloud services, developer tools, and intelligent productivity suites.",
        "apply_url": "https://careers.microsoft.com/v2/global/en/home.html",
        "posted_date": "2 days ago",
        "deadline": "Closes Nov 28, 2026",
        "drive_mode": "Virtual Campus Drive",
        "work_mode": "Hybrid"
    },
    {
        "id": "job-amazon-intern-2026",
        "title": "Software Development Engineer Intern (Summer 2026)",
        "company": "Amazon",
        "logo_color": "#FF9900",
        "location": "Bengaluru",
        "role_type": "Internship",
        "experience_level": "Student / Pre-final Year",
        "batch_eligibility": "2027 Batch",
        "salary_range": "₹80,000 / month Stipend",
        "required_skills": ["Java", "Python", "Data Structures", "Algorithms", "Git"],
        "preferred_skills": ["AWS", "Linux", "REST APIs"],
        "description": "Build high-throughput, low-latency microservices powering global infrastructure during a 6-month internship.",
        "apply_url": "https://amazon.jobs/en/job_categories/software-development",
        "posted_date": "3 days ago",
        "deadline": "Active Internship Drive",
        "drive_mode": "Virtual Assessment",
        "work_mode": "Hybrid"
    }
]


class JobDataSource(ABC):
    """
    Abstract interface for pluggable job data sources.
    Enables swapping underlying storage or retrieval providers without altering ranking logic.
    """

    @abstractmethod
    def get_jobs(self) -> List[Dict[str, Any]]:
        """Retrieves and returns a list of standardized job dictionaries."""
        pass


class JsonFileJobDataSource(JobDataSource):
    """
    Loads curated campus drive and internship listings from a local JSON file.
    Default data source pointing to data/campus_jobs.json.
    """

    def __init__(self, file_path: Optional[Path] = None) -> None:
        if file_path is None:
            base_dir = getattr(config, "BASE_DIR", None) or Path.cwd()
            self.file_path = Path(base_dir) / "data" / "campus_jobs.json"
        else:
            self.file_path = Path(file_path)

    def get_jobs(self) -> List[Dict[str, Any]]:
        """Reads listings from the configured JSON file, falling back gracefully if unreadable."""
        try:
            if self.file_path.exists():
                with open(self.file_path, "r", encoding="utf-8") as f:
                    jobs = json.load(f)
                if isinstance(jobs, list) and jobs:
                    return jobs
            logger.warning(f"Campus jobs JSON file not found at {self.file_path}. Using fallback seed jobs.")
        except Exception as e:
            logger.error(f"Failed to load jobs from {self.file_path}: {e}")

        return [dict(j) for j in DEFAULT_FALLBACK_JOBS]


class InMemoryJobDataSource(JobDataSource):
    """
    In-memory data source for unit testing, mock fixtures, and dynamically injected listings.
    """

    def __init__(self, jobs: Optional[List[Dict[str, Any]]] = None) -> None:
        self._jobs: List[Dict[str, Any]] = list(jobs) if jobs is not None else []

    def set_jobs(self, jobs: List[Dict[str, Any]]) -> None:
        """Updates the in-memory jobs collection."""
        self._jobs = list(jobs)

    def get_jobs(self) -> List[Dict[str, Any]]:
        """Returns the in-memory jobs list."""
        return list(self._jobs)


class CompositeJobDataSource(JobDataSource):
    """
    Combines listings from multiple pluggable data sources, deduplicating records by unique id.
    """

    def __init__(self, sources: List[JobDataSource]) -> None:
        self.sources = sources

    def get_jobs(self) -> List[Dict[str, Any]]:
        combined: List[Dict[str, Any]] = []
        seen_ids = set()

        for source in self.sources:
            try:
                for job in source.get_jobs():
                    jid = job.get("id")
                    if jid and jid in seen_ids:
                        continue
                    if jid:
                        seen_ids.add(jid)
                    combined.append(job)
            except Exception as e:
                logger.warning(f"Error fetching from composite job source {source}: {e}")

        return combined
