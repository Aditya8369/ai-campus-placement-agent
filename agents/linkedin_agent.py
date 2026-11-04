import logging
import json
import re
from typing import Dict, Any, List, Optional
from utils.gemini import generate_json_response

logger = logging.getLogger(__name__)

class LinkedInAgent:
    """
    LinkedIn Profile Analyzer Agent (#146).
    Analyzes public LinkedIn profile components (Headline, About/Summary, Experience, Skills),
    computes ATS-style profile strength scores, detects missing industry keywords, and produces
    actionable AI rewrites tailored to campus placements and target job roles.
    """

    def __init__(self):
        self.role_keywords_map = {
            "software engineer": [
                "Algorithms", "Data Structures", "System Design", "Python", "Java", "C++",
                "REST", "REST APIs", "RESTful APIs", "Microservices", "Git", "Docker", "CI/CD", "Unit Testing", "SQL"
            ],
            "data scientist": [
                "Machine Learning", "Python", "SQL", "Pandas", "Scikit-Learn", "TensorFlow",
                "PyTorch", "Data Visualization", "Statistical Analysis", "A/B Testing", "NLP", "BigQuery"
            ],
            "frontend developer": [
                "React", "JavaScript", "TypeScript", "HTML5", "CSS3", "Redux", "Next.js",
                "Responsive Design", "Web Performance", "REST APIs", "Tailwind CSS", "Jest"
            ],
            "backend developer": [
                "Node.js", "Python", "Django", "FastAPI", "Go", "PostgreSQL", "MongoDB",
                "Redis", "Microservices", "API Design", "Docker", "Kubernetes", "AWS"
            ],
            "cloud engineer": [
                "AWS", "Google Cloud", "Azure", "Terraform", "Kubernetes", "Docker",
                "CI/CD", "Linux", "Networking", "Infrastructure as Code", "Security", "Bash"
            ],
            "product manager": [
                "Agile", "Scrum", "Product Roadmap", "User Research", "Wireframing",
                "Data Analytics", "KPIs", "Cross-Functional Leadership", "Go-To-Market", "SQL"
            ]
        }

    def analyze_profile(
        self,
        headline: str,
        about: str,
        experience: str,
        skills: str,
        target_role: str = "Software Engineer"
    ) -> Dict[str, Any]:
        """
        Analyzes LinkedIn profile text, calculates section-by-section health scores,
        finds keyword alignment with target_role, and generates AI improvements.
        """
        headline = (headline or "").strip()
        about = (about or "").strip()
        experience = (experience or "").strip()
        skills_raw = (skills or "").strip()
        target_role = (target_role or "Software Engineer").strip()

        # Parse skills
        user_skills = [
            s.strip() for s in re.split(r"[,;\n]+", skills_raw) if s.strip()
        ]

        # 1. Headline scoring & analysis
        headline_score, headline_feedback = self._evaluate_headline(headline, target_role)

        # 2. About/Summary scoring & analysis
        about_score, about_feedback = self._evaluate_about(about)

        # 3. Experience section analysis
        exp_score, exp_feedback = self._evaluate_experience(experience)

        # 4. Skills & keyword matching
        matched_keywords, missing_keywords, skills_score = self._evaluate_skills(
            user_skills, target_role, f"{headline} {about} {experience}"
        )

        # Overall composite score (Headline: 25%, About: 25%, Experience: 25%, Skills: 25%)
        overall_score = round(
            (headline_score * 0.25) +
            (about_score * 0.25) +
            (exp_score * 0.25) +
            (skills_score * 0.25)
        )

        # AI-driven recommendations & rewrites
        headline_rewrites, ai_suggestions = self._generate_ai_recommendations(
            headline=headline,
            about=about,
            experience=experience,
            user_skills=user_skills,
            target_role=target_role,
            overall_score=overall_score
        )

        return {
            "overall_score": overall_score,
            "headline_score": headline_score,
            "about_score": about_score,
            "experience_score": exp_score,
            "skills_score": skills_score,
            "headline_feedback": headline_feedback,
            "about_feedback": about_feedback,
            "experience_feedback": exp_feedback,
            "matched_keywords": matched_keywords,
            "missing_keywords": missing_keywords,
            "headline_rewrites": headline_rewrites,
            "ai_suggestions": ai_suggestions,
            "target_role": target_role
        }

    def _evaluate_headline(self, headline: str, target_role: str) -> tuple[int, List[str]]:
        feedback = []
        score = 40  # base score

        if not headline:
            return 10, ["Headline is missing. Add a role-focused headline with your target specializations."]

        char_len = len(headline)
        if char_len < 30:
            feedback.append("Headline is too brief. Expand with skills, accomplishments, or domain specializations.")
            score += 10
        elif char_len > 120:
            score += 30
        else:
            score += 45

        # Check for pipe or bullet separator formatting (standard high-impact LinkedIn style)
        if "|" in headline or "•" in headline or "/" in headline:
            score += 15
        else:
            feedback.append("Use separators (e.g. '|' or '•') to clearly delineate role, core stack, and college/internship.")

        # Check if target role or keywords are present
        if target_role.lower() in headline.lower():
            score += 15
        else:
            feedback.append(f"Consider explicitly mentioning your aspiration or current role '{target_role}'.")

        # Check buzzwords to avoid
        fluff = ["passionate", "aspiring", "hardworking", "motivated", "enthusiastic", "detail-oriented"]
        found_fluff = [f for f in fluff if re.search(r"\b" + f + r"\b", headline, re.I)]
        if found_fluff:
            feedback.append(f"Replace generic descriptors like '{', '.join(found_fluff)}' with concrete technical skills and achievements.")
            score = max(20, score - 10)

        final_score = min(100, max(10, score))
        return final_score, feedback

    def _evaluate_about(self, about: str) -> tuple[int, List[str]]:
        feedback = []
        score = 30

        if not about:
            return 15, ["About/Summary section is empty. A compelling summary increases profile views and recruiter response rates."]

        word_count = len(about.split())
        if word_count < 40:
            feedback.append("Summary is too short. Elaborate on your technical background, projects, and career goals.")
            score += 20
        elif word_count < 120:
            score += 45
        else:
            score += 55

        # Check for first-person narrative or personal pitch
        if re.search(r"\b(I am|I've|my passion|I build|I enjoy)\b", about, re.I):
            score += 15

        # Check for technical keywords / achievements
        if re.search(r"\b(developed|engineered|built|implemented|launched|architected)\b", about, re.I):
            score += 15
        else:
            feedback.append("Include action verbs demonstrating hands-on technical contributions (e.g., built, deployed, engineered).")

        final_score = min(100, max(15, score))
        return final_score, feedback

    def _evaluate_experience(self, experience: str) -> tuple[int, List[str]]:
        feedback = []
        score = 35

        if not experience:
            return 20, ["No experience or projects listed. Even academic capstones, hackathons, or open-source work should be highlighted."]

        # Check for quantifiable metrics (e.g. 20%, 500+ users, 3x faster)
        has_metrics = bool(re.search(r"(\d+%\b|\d+x\b|\d+\+?\s*(users|requests|qps|ms|seconds|stars|downloads))", experience, re.I))
        if has_metrics:
            score += 35
        else:
            feedback.append("Incorporate quantifiable impact in your bullet points (e.g., 'Reduced query latency by 35%', 'Scaled to 2k users').")

        # Check for action verbs
        has_action_verbs = bool(re.search(r"\b(Led|Designed|Created|Optimized|Refactored|Authored|Integrated|Built|Engineered|Developed)\b", experience, re.I))
        if has_action_verbs:
            score += 35
        else:
            feedback.append("Begin descriptions with decisive past-tense action verbs to show direct ownership.")

        final_score = min(100, max(20, score))
        return final_score, feedback

    def _evaluate_skills(
        self,
        skills: List[str],
        target_role: str,
        full_text: str
    ) -> tuple[List[str], List[str], int]:
        role_key = target_role.strip().lower()
        expected = self.role_keywords_map.get(role_key, self.role_keywords_map["software engineer"])

        text_to_search = (full_text + " " + " ".join(skills)).lower()
        matched = []
        missing = []

        for kw in expected:
            if re.search(r"\b" + re.escape(kw.lower()) + r"\b", text_to_search):
                matched.append(kw)
            else:
                missing.append(kw)

        if not expected:
            return matched, missing, 70

        match_ratio = len(matched) / len(expected)
        score = min(100, max(20, int(match_ratio * 100)))
        return matched, missing, score

    def _generate_ai_recommendations(
        self,
        headline: str,
        about: str,
        experience: str,
        user_skills: List[str],
        target_role: str,
        overall_score: int
    ) -> tuple[List[str], List[str]]:
        """
        Uses Gemini if available, with robust deterministic fallback for offline/instant scenarios.
        """
        system_instruction = "You are an expert technical recruiter and executive career coach. Return structured JSON."
        prompt = f"""
Analyze this student's LinkedIn profile components and generate 3 compelling headline rewrites and 4 concise profile suggestions.

Target Role: {target_role}
Current Headline: {headline}
Summary/About: {about}
Experience/Projects: {experience}
Skills: {", ".join(user_skills)}

Return ONLY valid JSON matching this schema:
{{
  "headline_rewrites": ["Rewrite 1", "Rewrite 2", "Rewrite 3"],
  "suggestions": ["Suggestion 1", "Suggestion 2", "Suggestion 3", "Suggestion 4"]
}}
"""
        try:
            data = generate_json_response(system_instruction=system_instruction, prompt=prompt)
            if isinstance(data, dict):
                rewrites = data.get("headline_rewrites", [])
                suggestions = data.get("suggestions", [])
                if rewrites and suggestions:
                    return rewrites[:3], suggestions[:5]
        except Exception as e:
            logger.warning(f"Gemini LLM call failed in LinkedInAgent: {e}. Falling back to rule-based engine.")

        # Fallback high-impact rewrites
        skill_sample = ", ".join(user_skills[:3]) if user_skills else "Python, System Design, Cloud"
        rewrites = [
            f"{target_role} | {skill_sample} | Open to Campus Placements",
            f"Aspiring {target_role} • Ex-Intern • Building Scalable Web & Distributed Systems",
            f"{target_role} | Full-Stack Developer | CS Graduate '26 | Passionate about Clean Code & Cloud"
        ]

        suggestions = [
            f"Feature your top 3 GitHub repositories or deployed live demos in the 'Featured' section.",
            f"Add relevant industry keywords ({', '.join(user_skills[:3]) if user_skills else target_role}) to your Experience bullets for recruiter searchability.",
            f"Request recommendations from professors, hackathon teammates, or internship mentors to add social proof.",
            f"Include quantifiable metrics (percentage gains, latency reductions, user counts) in your project bullet points."
        ]

        return rewrites, suggestions
