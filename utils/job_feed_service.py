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
        search_query: Optional[str] = None,
        work_mode: Optional[str] = None,
        stipend_type: Optional[str] = None,
        duration: Optional[str] = None,
        technology: Optional[str] = None,
        deadline_status: Optional[str] = None,
        include_unspecified: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Filters a list of jobs by comprehensive search and filter panel criteria (#356):
        location, role type, search query, work mode (remote/on-site/hybrid),
        stipend availability, duration, technology/skills, and application deadline status.
        Gracefully handles listings with missing or unspecified attributes via include_unspecified.
        """
        filtered = []

        for j in jobs:
            meta = extract_job_filter_metadata(j)

            # 1. Location filter
            if location and location.strip() and location.strip().lower() not in ("all", "any"):
                loc_clean = location.strip().lower()
                if loc_clean not in (j.get("location") or "").lower():
                    continue

            # 2. Role filter
            if role_type and role_type.strip() and role_type.strip().lower() not in ("all", "any"):
                rt_clean = role_type.strip().lower()
                j_title = (j.get("title") or "").lower()
                j_role = (j.get("role_type") or "").lower()
                matched_role = False
                if rt_clean in j_title or rt_clean in j_role:
                    matched_role = True
                elif any(k in rt_clean for k in ["sde", "software"]):
                    matched_role = any(k in j_title for k in ["software", "sde", "developer", "engineer"])
                elif "backend" in rt_clean:
                    matched_role = any(k in j_title for k in ["backend", "api", "systems", "server"])
                elif "frontend" in rt_clean:
                    matched_role = any(k in j_title for k in ["frontend", "ui", "react", "web"])
                elif any(k in rt_clean for k in ["data", "ai", "analytics"]):
                    matched_role = any(k in j_title for k in ["data", "analytics", "ai", "machine learning", "ml", "research"])
                elif any(k in rt_clean for k in ["cloud", "devops"]):
                    matched_role = any(k in j_title for k in ["cloud", "devops", "sre", "infrastructure", "platform"])
                if not matched_role:
                    continue

            # 3. Work Mode filter (Remote / On-site / Hybrid)
            if work_mode and work_mode.strip() and work_mode.strip().lower() not in ("all", "any"):
                wm_clean = work_mode.strip().lower()
                meta_wm = meta["work_mode"].lower()
                if wm_clean in meta_wm:
                    pass
                elif include_unspecified and not meta["work_mode_specified"]:
                    pass
                else:
                    continue

            # 4. Stipend Availability filter
            if stipend_type and stipend_type.strip() and stipend_type.strip().lower() not in ("all", "any"):
                st_clean = stipend_type.strip().lower()
                if "paid" in st_clean:
                    if meta["has_stipend"] is True:
                        pass
                    elif include_unspecified and not meta["stipend_specified"]:
                        pass
                    else:
                        continue
                elif "unpaid" in st_clean:
                    if meta["has_stipend"] is False:
                        pass
                    elif include_unspecified and not meta["stipend_specified"]:
                        pass
                    else:
                        continue

            # 5. Duration filter (1-2 Months / 3 Months / 6 Months)
            if duration and duration.strip() and duration.strip().lower() not in ("all", "any"):
                dur_clean = duration.strip().lower()
                dur_meta = meta["duration"].lower()
                if ("1" in dur_clean or "2" in dur_clean) and ("1" in dur_meta or "2" in dur_meta):
                    pass
                elif "3" in dur_clean and "3" in dur_meta:
                    pass
                elif "6" in dur_clean and "6" in dur_meta:
                    pass
                elif dur_clean in dur_meta:
                    pass
                elif include_unspecified and not meta["duration_specified"]:
                    pass
                else:
                    continue

            # 6. Technology filter
            if technology and technology.strip() and technology.strip().lower() not in ("all", "any"):
                tech_clean = technology.strip().lower()
                matched_tech = (
                    any(tech_clean in t.lower() for t in meta["technologies"])
                    or tech_clean in (j.get("title") or "").lower()
                    or tech_clean in (j.get("description") or "").lower()
                )
                if not matched_tech:
                    continue

            # 7. Deadline status filter
            if deadline_status and deadline_status.strip() and deadline_status.strip().lower() not in ("all", "any"):
                dl_clean = deadline_status.strip().lower()
                if "closing" in dl_clean or "soon" in dl_clean:
                    if meta["deadline_status"] == "Closing Soon":
                        pass
                    elif include_unspecified and not meta["deadline_specified"]:
                        pass
                    else:
                        continue
                elif "active" in dl_clean or "open" in dl_clean or "rolling" in dl_clean:
                    if meta["deadline_status"] == "Active Drives":
                        pass
                    elif include_unspecified and not meta["deadline_specified"]:
                        pass
                    else:
                        continue

            # 8. Search query filter (matches title, company, description, or skills)
            if search_query and search_query.strip():
                q = search_query.strip().lower()
                def matches_q(job: Dict[str, Any]) -> bool:
                    if q in (job.get("title") or "").lower():
                        return True
                    if q in (job.get("company") or "").lower():
                        return True
                    if q in (job.get("description") or "").lower():
                        return True
                    skills = [s.lower() for s in (job.get("required_skills") or []) + (job.get("preferred_skills") or [])]
                    return any(q in s for s in skills)

                if not matches_q(j):
                    continue

            # Retain normalized metadata on job object for presentation
            enriched_job = dict(j)
            enriched_job.update(meta)
            filtered.append(enriched_job)

        return filtered


def extract_job_filter_metadata(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts and normalizes searchable filter dimensions for a job or internship listing (#356):
    work_mode, stipend_type, duration, technologies, and deadline_status.
    Tracks whether each dimension was explicitly specified or inferred/unspecified.
    """
    loc = (job.get("location") or "").strip()
    loc_lower = loc.lower()
    drive_mode = (job.get("drive_mode") or "").strip().lower()
    desc = (job.get("description") or "").strip().lower()
    title = (job.get("title") or "").strip().lower()
    combined_text = f"{title} {desc} {loc_lower} {drive_mode}"

    # 1. Work Mode (Remote / On-site / Hybrid)
    raw_wm = (job.get("work_mode") or "").strip().lower()
    if raw_wm in ("remote", "on-site", "onsite", "hybrid"):
        work_mode = "Remote" if raw_wm == "remote" else ("Hybrid" if raw_wm == "hybrid" else "On-site")
        work_mode_specified = True
    elif "remote / hybrid" in loc_lower or "hybrid / remote" in loc_lower or loc_lower == "remote / hybrid":
        work_mode = "Remote / Hybrid"
        work_mode_specified = False
    elif loc_lower == "remote" or ("remote" in loc_lower and "hybrid" not in loc_lower) or ("remote" in drive_mode and "hybrid" not in drive_mode) or "virtual" in drive_mode:
        work_mode = "Remote"
        work_mode_specified = True
    elif loc_lower == "hybrid" or ("hybrid" in loc_lower and "remote" not in loc_lower) or ("hybrid" in drive_mode and "remote" not in drive_mode):
        work_mode = "Hybrid"
        work_mode_specified = True
    elif loc and loc_lower not in ("remote / hybrid", "all", "flexible", "not specified"):
        work_mode = "On-site"
        work_mode_specified = True
    else:
        work_mode = "Not Specified"
        work_mode_specified = False

    # 2. Stipend Availability (Paid Stipend / Unpaid / Not Specified)
    sal = (job.get("salary_range") or job.get("stipend") or "").strip()
    sal_lower = sal.lower()
    if any(k in sal_lower for k in ["stipend", "/mo", "lpa", "₹", "$", "eur", "usd", "rs", "inr"]) and "unpaid" not in sal_lower:
        has_stipend = True
        stipend_type = "Paid Stipend"
        stipend_specified = True
    elif "unpaid" in sal_lower or "unpaid" in desc or "academic credit" in sal_lower or "certificate" in sal_lower:
        has_stipend = False
        stipend_type = "Unpaid / Any"
        stipend_specified = True
    elif sal:
        has_stipend = True
        stipend_type = "Paid Stipend"
        stipend_specified = True
    else:
        has_stipend = None
        stipend_type = "Not Specified"
        stipend_specified = False

    # 3. Duration (1-2 Months / 3 Months / 6 Months / Not Specified)
    raw_dur = (job.get("duration") or "").strip()
    dur_lower = raw_dur.lower()
    if ("6" in dur_lower and ("month" in dur_lower or "mo" in dur_lower)) or "6-month" in combined_text or "6 month" in combined_text or "semester" in combined_text:
        duration = "6 Months"
        duration_specified = True
    elif "3" in dur_lower or "summer" in dur_lower or "3-month" in combined_text or "3 month" in combined_text or "summer" in combined_text or "12-week" in combined_text:
        duration = "3 Months"
        duration_specified = True
    elif "2" in dur_lower or "1-2" in dur_lower or "2-month" in combined_text or "2 month" in combined_text or "8 week" in combined_text:
        duration = "1-2 Months"
        duration_specified = True
    elif raw_dur:
        duration = raw_dur
        duration_specified = True
    else:
        duration = "Not Specified"
        duration_specified = False

    # 4. Technologies
    req = job.get("required_skills") or []
    pref = job.get("preferred_skills") or []
    techs = {s.strip() for s in req + pref if s and s.strip()}
    common_tech_catalog = [
        "Python", "Java", "C++", "C#", "React", "JavaScript", "TypeScript",
        "Node.js", "SQL", "Go", "Docker", "Kubernetes", "AWS", "Git",
        "Machine Learning", "NLP", "FastAPI", "Spring Boot", "PostgreSQL"
    ]
    for ct in common_tech_catalog:
        if ct.lower() in combined_text:
            techs.add(ct)

    # 5. Deadline Status (Active Drives / Closing Soon / Not Specified)
    deadline_raw = (job.get("deadline") or "").strip()
    dl_lower = deadline_raw.lower()
    if any(k in dl_lower for k in ["closes", "closing", "deadline", "nov", "dec", "last date", "expires"]):
        deadline_status = "Closing Soon"
        deadline_specified = True
    elif any(k in dl_lower for k in ["active", "open", "rolling"]):
        deadline_status = "Active Drives"
        deadline_specified = True
    elif deadline_raw:
        deadline_status = "Active Drives"
        deadline_specified = True
    else:
        deadline_status = "Not Specified"
        deadline_specified = False

    # Track unspecified fields for user awareness
    unspecified_fields = []
    if not work_mode_specified:
        unspecified_fields.append("work_mode")
    if not stipend_specified:
        unspecified_fields.append("stipend")
    if not duration_specified:
        unspecified_fields.append("duration")
    if not deadline_specified:
        unspecified_fields.append("deadline")

    return {
        "work_mode": work_mode,
        "work_mode_specified": work_mode_specified,
        "has_stipend": has_stipend,
        "stipend_type": stipend_type,
        "stipend_specified": stipend_specified,
        "duration": duration,
        "duration_specified": duration_specified,
        "technologies": sorted(list(techs)),
        "deadline_status": deadline_status,
        "deadline_specified": deadline_specified,
        "unspecified_fields": unspecified_fields
    }

