"""
GitHub Profile Analyzer Agent (#141)

Reviews public GitHub developer profiles using public GitHub REST API endpoints.
Analyzes repositories, star counts, programming languages, commit recency, README coverage,
and generates structured recommendations to elevate candidate portfolios for technical recruiters.
"""

import logging
import re
import urllib.parse
from typing import Dict, Any, List, Optional
import requests

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubAnalyzerAgent:
    """
    Evaluates public candidate GitHub profiles, language distributions, and repository hygiene.
    """

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    @staticmethod
    def extract_username(input_str: str) -> str:
        """
        Normalizes a raw GitHub URL or handle into a clean username string.
        Examples:
          - 'https://github.com/octocat' -> 'octocat'
          - 'github.com/octocat/' -> 'octocat'
          - '@octocat' -> 'octocat'
        """
        clean = input_str.strip()
        if not clean:
            return ""

        # Remove trailing slash
        clean = clean.rstrip("/")

        # Check for URL
        if "github.com/" in clean:
            parts = clean.split("github.com/")
            clean = parts[-1].split("/")[0]

        # Strip leading @
        clean = clean.lstrip("@").strip()
        # Keep only valid GitHub username characters (alphanumeric, hyphens)
        clean = re.sub(r"[^a-zA-Z0-9\-]", "", clean)
        return clean

    def fetch_user_profile(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves user public metadata from GitHub API.
        """
        url = f"{GITHUB_API_BASE}/users/{urllib.parse.quote(username)}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AI-Campus-Placement-Agent-v1.0"
        }
        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404:
                logger.warning(f"GitHub user '{username}' not found.")
                return None
            elif resp.status_code == 403:
                logger.warning(f"GitHub API rate limit exceeded when fetching user '{username}'.")
                return {"rate_limited": True}
            else:
                logger.error(f"GitHub API returned HTTP {resp.status_code} for user '{username}'")
                return None
        except Exception as exc:
            logger.error(f"Failed to connect to GitHub API: {exc}")
            return None

    def fetch_user_repos(self, username: str, max_repos: int = 30) -> List[Dict[str, Any]]:
        """
        Retrieves up to max_repos public repositories for the user.
        """
        url = f"{GITHUB_API_BASE}/users/{urllib.parse.quote(username)}/repos"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AI-Campus-Placement-Agent-v1.0"
        }
        params = {
            "sort": "updated",
            "direction": "desc",
            "per_page": min(max_repos, 100),
            "type": "public"
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
            return []
        except Exception as exc:
            logger.error(f"Failed to fetch repositories for '{username}': {exc}")
            return []

    def analyze_profile(self, raw_input: str) -> Dict[str, Any]:
        """
        Performs full multi-dimensional evaluation of a GitHub developer profile.
        """
        username = self.extract_username(raw_input)
        if not username:
            return {
                "success": False,
                "error": "Please enter a valid GitHub username or profile URL."
            }

        profile_data = self.fetch_user_profile(username)
        if not profile_data:
            return {
                "success": False,
                "error": f"GitHub user '@{username}' could not be found. Please check the spelling."
            }

        if profile_data.get("rate_limited"):
            return {
                "success": False,
                "error": "GitHub API rate limit temporarily exceeded. Please try again shortly."
            }

        repos = self.fetch_user_repos(username)

        # Metrics aggregation
        languages_count: Dict[str, int] = {}
        total_stars = 0
        total_forks = 0
        repos_without_desc = []
        highlighted_projects = []

        for r in repos:
            # Forked repos are filtered or tagged
            is_fork = r.get("fork", False)
            lang = r.get("language")
            if lang and not is_fork:
                languages_count[lang] = languages_count.get(lang, 0) + 1

            stars = r.get("stargazers_count", 0)
            forks = r.get("forks_count", 0)
            total_stars += stars
            total_forks += forks

            desc = r.get("description")
            if not desc and not is_fork:
                repos_without_desc.append(r.get("name"))

            # Highlight significant or high-star repositories
            if not is_fork:
                highlighted_projects.append({
                    "name": r.get("name"),
                    "description": desc or "No description provided",
                    "language": lang or "General",
                    "stars": stars,
                    "forks": forks,
                    "url": r.get("html_url"),
                    "has_description": bool(desc),
                    "updated_at": r.get("updated_at", "")[:10]
                })

        # Top programming languages sorted by repository usage
        sorted_languages = sorted(languages_count.items(), key=lambda x: x[1], reverse=True)
        top_languages = [{"language": lang, "count": count} for lang, count in sorted_languages[:6]]

        # Strengths & Suggestions Generation
        suggestions: List[str] = []
        strengths: List[str] = []

        bio = profile_data.get("bio")
        if bio and len(bio.strip()) > 15:
            strengths.append("Clear developer bio summarizing professional focus and aspirations.")
        else:
            suggestions.append("Add a detailed professional bio highlighting your target tech stack, university, and career goals.")

        if profile_data.get("blog") or profile_data.get("twitter_username"):
            strengths.append("External links (portfolio/LinkedIn) present in profile metadata.")
        else:
            suggestions.append("Link your portfolio website or LinkedIn in your profile settings for recruiters.")

        if repos_without_desc:
            count_no_desc = len(repos_without_desc)
            suggestions.append(f"Add concise descriptions and relevant topic tags to {count_no_desc} repositories lacking summaries.")

        if total_stars >= 5:
            strengths.append(f"Demonstrated open-source traction with {total_stars} repository stars across public works.")

        if len(top_languages) >= 2:
            strengths.append(f"Multi-language proficiency demonstrated across {', '.join([l['language'] for l in top_languages[:3]])}.")

        if not suggestions:
            suggestions.append("Pin your top 4-6 most impressive full-stack or systems projects to your GitHub overview.")

        # Compute developer presence score out of 100
        score = 40  # Baseline
        if bio: score += 10
        if profile_data.get("location"): score += 5
        if profile_data.get("blog"): score += 10
        if len(repos) >= 5: score += 15
        if total_stars >= 3: score += 10
        if len(repos_without_desc) == 0 and len(repos) > 0: score += 10
        score = min(score, 100)

        return {
            "success": True,
            "username": username,
            "name": profile_data.get("name") or username,
            "avatar_url": profile_data.get("avatar_url"),
            "html_url": profile_data.get("html_url"),
            "bio": bio or "No bio provided",
            "location": profile_data.get("location") or "Not specified",
            "public_repos_count": profile_data.get("public_repos", 0),
            "followers": profile_data.get("followers", 0),
            "following": profile_data.get("following", 0),
            "total_stars": total_stars,
            "total_forks": total_forks,
            "developer_score": score,
            "top_languages": top_languages,
            "strengths": strengths,
            "suggestions": suggestions,
            "highlighted_projects": highlighted_projects[:8]
        }
