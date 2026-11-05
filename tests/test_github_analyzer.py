"""
Unit tests for GitHub Profile Analyzer Agent (#141).
"""

from agents.github_agent import GitHubAnalyzerAgent
from app import app


def test_github_username_normalization():
    """Verify URL and handle parsing into canonical GitHub usernames."""
    agent = GitHubAnalyzerAgent()
    assert agent.extract_username("https://github.com/torvalds") == "torvalds"
    assert agent.extract_username("github.com/torvalds/") == "torvalds"
    assert agent.extract_username("@octocat") == "octocat"
    assert agent.extract_username("  octocat  ") == "octocat"
    assert agent.extract_username("") == ""


def test_github_analyzer_mock_analysis():
    """Verify analysis payload structure with mocked API response."""
    agent = GitHubAnalyzerAgent()

    # Monkeypatch fetch calls
    agent.fetch_user_profile = lambda u: {
        "login": "octocat",
        "name": "The Octocat",
        "avatar_url": "https://avatars.githubusercontent.com/u/583231",
        "html_url": "https://github.com/octocat",
        "bio": "Open source enthusiast and developer at GitHub.",
        "location": "San Francisco",
        "blog": "https://github.blog",
        "public_repos": 8,
        "followers": 5000,
        "following": 9,
    }

    agent.fetch_user_repos = lambda u, max_repos=30: [
        {
            "name": "Hello-World",
            "description": "My first repository on GitHub!",
            "language": "Python",
            "stargazers_count": 42,
            "forks_count": 10,
            "html_url": "https://github.com/octocat/Hello-World",
            "fork": False,
            "updated_at": "2026-11-04T00:00:00Z"
        },
        {
            "name": "Spoon-Knife",
            "description": "This repo is for practice.",
            "language": "JavaScript",
            "stargazers_count": 120,
            "forks_count": 50,
            "html_url": "https://github.com/octocat/Spoon-Knife",
            "fork": False,
            "updated_at": "2026-11-04T00:00:00Z"
        }
    ]

    res = agent.analyze_profile("octocat")
    assert res["success"] is True
    assert res["username"] == "octocat"
    assert res["total_stars"] == 162
    assert res["developer_score"] >= 70
    assert len(res["top_languages"]) == 2
    assert len(res["strengths"]) > 0


def test_github_analyzer_web_route():
    """Verify GET and POST routes for /github-analyzer."""
    with app.test_client() as client:
        res = client.get("/github-analyzer")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "GitHub Profile Analyzer" in html
        assert "btnAnalyzeGithub" in html
