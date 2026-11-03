"""
Job Feed Service - Aggregates, parses, and normalizes live curated campus placement drives,
graduate openings, and internship opportunities from curated datasets and public feeds.
"""

import json
import logging
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any, Optional

import config

logger = logging.getLogger(__name__)

# Fallback seed jobs if data file cannot be accessed
FALLBACK_SEED_JOBS: List[Dict[str, Any]] = [
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
        "drive_mode": "National Campus Hiring"
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
        "drive_mode": "Virtual Campus Drive"
    },
    {
        "id": "job-amazon-sde1-2026",
        "title": "Software Development Engineer (SDE I) - Campus 2026",
        "company": "Amazon",
        "logo_color": "#FF9900",
        "location": "Bengaluru",
        "role_type": "Full-time",
        "experience_level": "Fresher / 0-1 Years",
        "batch_eligibility": "2025 & 2026 Batch",
        "salary_range": "₹20 - ₹32 LPA",
        "required_skills": ["Java", "Python", "Data Structures", "Algorithms", "Object Oriented Design", "DBMS"],
        "preferred_skills": ["AWS", "NoSQL", "Distributed Systems", "Spring Boot"],
        "description": "Build high-throughput, low-latency microservices powering Amazon e-commerce, Prime, and AWS global infrastructure.",
        "apply_url": "https://amazon.jobs/en/job_categories/software-development",
        "posted_date": "3 days ago",
        "deadline": "Active Drive",
        "drive_mode": "National Qualifier Drive"
    }
]


class JobFeedService:
    """
    Service responsible for aggregating, caching, and serving campus hiring
    drives, fresher openings, and internships.
    """

    CACHE_TTL_SECONDS = 3600  # 1 hour cache TTL

    def __init__(self, data_file_path: Optional[Path] = None) -> None:
        if data_file_path is None:
            self.data_file_path = Path(config.BASE_DIR) / "data" / "campus_jobs.json"
        else:
            self.data_file_path = data_file_path

        self._cached_jobs: List[Dict[str, Any]] = []
        self._last_fetch_timestamp: float = 0.0

    def load_seed_jobs(self) -> List[Dict[str, Any]]:
        """
        Loads the curated campus job listings from data/campus_jobs.json.
        Falls back to built-in seed records if file read fails.
        """
        try:
            if self.data_file_path.exists():
                with open(self.data_file_path, "r", encoding="utf-8") as f:
                    jobs = json.load(f)
                if isinstance(jobs, list) and jobs:
                    logger.info(f"Loaded {len(jobs)} curated campus jobs from {self.data_file_path}")
                    return jobs
            logger.warning(f"Campus jobs file not found at {self.data_file_path}. Using fallback seed data.")
        except Exception as e:
            logger.error(f"Failed to read campus jobs from {self.data_file_path}: {e}")

        return [dict(j) for j in FALLBACK_SEED_JOBS]

    def fetch_public_rss_jobs(self, feed_url: str = "https://remoteok.com/remote-engineer-jobs.rss", timeout: float = 2.5) -> List[Dict[str, Any]]:
        """
        Optionally polls public fresher/graduate RSS feeds with safe timeout
        and graceful error suppression. Returns normalized job objects.
        """
        jobs: List[Dict[str, Any]] = []
        try:
            req = urllib.request.Request(
                feed_url,
                headers={"User-Agent": "AICampusPlacementAgent/1.0 (Student Placement Assistant)"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                content = response.read()
                root = ET.fromstring(content)
                channel = root.find("channel")
                if channel is not None:
                    for item in channel.findall("item")[:5]:  # limit to top 5
                        title_el = item.find("title")
                        link_el = item.find("link")
                        desc_el = item.find("description")
                        pub_date_el = item.find("pubDate")

                        title = title_el.text if title_el is not None and title_el.text else "Software Engineer"
                        link = link_el.text if link_el is not None and link_el.text else "https://remoteok.com"
                        desc = desc_el.text if desc_el is not None and desc_el.text else ""
                        pub_date = pub_date_el.text if pub_date_el is not None and pub_date_el.text else "Recently"

                        jobs.append({
                            "id": f"rss-{abs(hash(link)) % 1000000}",
                            "title": title,
                            "company": "Remote Tech Partner",
                            "logo_color": "#2D3748",
                            "location": "Remote",
                            "role_type": "Full-time",
                            "experience_level": "Early Career / Graduate",
                            "batch_eligibility": "2025 & 2026 Batch",
                            "salary_range": "Competitive Market CTC",
                            "required_skills": ["Python", "JavaScript", "Git", "REST APIs"],
                            "preferred_skills": ["Docker", "Cloud", "React"],
                            "description": (desc[:160] + "...") if len(desc) > 160 else desc,
                            "apply_url": link,
                            "posted_date": pub_date[:16] if len(pub_date) > 16 else pub_date,
                            "deadline": "Active Public Listing",
                            "drive_mode": "Public Remote Listing"
                        })
        except Exception as e:
            # Network restricted or feed unavailable - silently log and continue
            logger.debug(f"Optional public RSS job fetch skipped or timed out ({feed_url}): {e}")

        return jobs

    def get_all_jobs(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Retrieves active campus jobs, leveraging in-memory caching to avoid
        repeated disk or network operations.
        """
        now = time.time()
        if not force_refresh and self._cached_jobs and (now - self._last_fetch_timestamp < self.CACHE_TTL_SECONDS):
            return self._cached_jobs

        # Load seed curated jobs
        seed_jobs = self.load_seed_jobs()

        # Combine with optional public RSS listings
        rss_jobs = self.fetch_public_rss_jobs()
        combined = list(seed_jobs)

        # Merge rss jobs avoiding duplicate titles/companies
        existing_ids = {j.get("id") for j in seed_jobs}
        for rj in rss_jobs:
            if rj.get("id") not in existing_ids:
                combined.append(rj)

        self._cached_jobs = combined
        self._last_fetch_timestamp = now
        return self._cached_jobs

    def filter_jobs(
        self,
        jobs: List[Dict[str, Any]],
        location: Optional[str] = None,
        role_type: Optional[str] = None,
        search_query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Filters a list of jobs by location, role type, and search keyword.
        """
        filtered = jobs

        # Location filter
        if location and location.strip() and location.strip().lower() not in ("all", "any"):
            loc_clean = location.strip().lower()
            filtered = [
                j for j in filtered
                if loc_clean in (j.get("location") or "").lower()
            ]

        # Role type filter
        if role_type and role_type.strip() and role_type.strip().lower() not in ("all", "any"):
            rt_clean = role_type.strip().lower()
            filtered = [
                j for j in filtered
                if rt_clean in (j.get("role_type") or "").lower()
            ]

        # Search query filter (matches title, company, or skills)
        if search_query and search_query.strip():
            q = search_query.strip().lower()
            def matches(job: Dict[str, Any]) -> bool:
                if q in (job.get("title") or "").lower():
                    return True
                if q in (job.get("company") or "").lower():
                    return True
                if q in (job.get("description") or "").lower():
                    return True
                skills = [s.lower() for s in job.get("required_skills", []) + job.get("preferred_skills", [])]
                return any(q in s for s in skills)

            filtered = [j for j in filtered if matches(j)]

        return filtered

