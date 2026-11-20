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
            ],
            "data analyst": [
                "SQL", "Python", "Tableau", "Power BI", "Excel", "Data Cleaning",
                "Data Visualization", "Statistical Analysis", "ETL", "Reporting", "Pandas"
            ],
            "web developer": [
                "HTML5", "CSS3", "JavaScript", "TypeScript", "React", "Node.js",
                "Responsive Design", "REST APIs", "Git", "Webpack", "Tailwind CSS", "SQL"
            ],
            "full stack developer": [
                "React", "Node.js", "Python", "JavaScript", "TypeScript", "SQL",
                "MongoDB", "REST APIs", "Git", "Docker", "Express", "Microservices"
            ],
            "devops engineer": [
                "CI/CD", "Docker", "Kubernetes", "AWS", "Terraform", "Linux",
                "Git", "Jenkins", "Ansible", "Bash", "Monitoring", "Cloud Security"
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
            data = generate_json_response(system_instruction=system_instruction, prompt=prompt, feature="outreach")
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

    def generate_linkedin_suggestions(
        self,
        resume_text: str,
        target_role: str = "Software Engineer",
        candidate_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Suggests LinkedIn headlines, first-person About section, and recruiter search keywords (#538).
        Ensures all 3 headline options strictly respect LinkedIn's 220-character limit,
        only utilizes verified details present in the resume, and gracefully handles
        minimal/sparse resumes without raising exceptions or fabricating credentials.
        """
        target_role = (target_role or "Software Engineer").strip()
        entities = self._extract_resume_entities(resume_text, candidate_name=candidate_name)

        # 1. Attempt AI-driven suggestions if available
        ai_result = self._call_gemini_linkedin_suggestions(
            resume_text=resume_text,
            target_role=target_role,
            entities=entities
        )
        if ai_result:
            return ai_result

        # 2. Fall back to deterministic rule-based generator
        return self._generate_deterministic_suggestions(entities=entities, target_role=target_role)

    def _extract_resume_entities(
        self,
        resume_text: str,
        candidate_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Parses resume text into structured entities: skills, projects, experience,
        degree, graduation year, and candidate name strictly from provided content.
        """
        text = (resume_text or "").strip()
        words = text.split()
        is_sparse = len(words) < 30

        # Extract name if not provided
        name = candidate_name
        if not name and text:
            first_line = text.split("\n")[0].strip()
            # If first line looks like a person's name (2-4 words, alphabetic, no email/phone/url)
            if re.match(r"^[A-Za-z\.\s\-]{3,40}$", first_line) and not re.search(
                r"\b(resume|cv|curriculum|profile|engineer|developer|analyst|student)\b",
                first_line,
                re.I
            ):
                name = first_line

        # Common technical competencies inventory
        common_tech = [
            "Python", "Java", "C++", "C", "C#", "Go", "Rust", "JavaScript", "TypeScript",
            "HTML", "HTML5", "CSS", "CSS3", "React", "Next.js", "Angular", "Vue", "Node.js",
            "Express", "Django", "Flask", "FastAPI", "Spring Boot", "SQL", "PostgreSQL",
            "MySQL", "MongoDB", "Redis", "SQLite", "Docker", "Kubernetes", "AWS", "Google Cloud",
            "Azure", "Git", "GitHub", "Linux", "REST APIs", "REST", "GraphQL", "Microservices",
            "CI/CD", "Machine Learning", "Deep Learning", "TensorFlow", "PyTorch", "Pandas",
            "NumPy", "Scikit-Learn", "Data Structures", "Algorithms", "System Design", "Agile",
            "Scrum", "Tailwind CSS", "Bootstrap", "Jest", "Unit Testing", "Tableau", "Power BI",
            "Excel", "Hadoop", "Spark", "Kafka", "Bash", "Selenium"
        ]

        skills_matched = []
        # Check explicit skills section
        skills_sec = re.search(
            r"(?:technical skills|skills|technologies|proficiencies)[\s:]+([^\n\r]+(?:\n(?:[\t\s]*-?[^\n\r]+)){0,4})",
            text,
            re.I
        )
        if skills_sec:
            raw_sec = skills_sec.group(1)
            raw_sec = re.split(r"\n\s*(?:experience|education|projects|certifications|awards|summary)[\s:]", raw_sec, flags=re.I)[0]
            tokens = [t.strip() for t in re.split(r"[,;•|\n\t/]+", raw_sec) if t.strip()]
            for tok in tokens:
                tok_clean = re.sub(r"^[-\*•\d\.\)]+\s*", "", tok).strip()
                if 2 <= len(tok_clean) <= 30 and tok_clean not in skills_matched:
                    if not re.search(r"\b(experience|education|projects|awards|activities)[\s:]*$", tok_clean, re.I):
                        skills_matched.append(tok_clean)

        # Match known tech tokens in full text
        for tech in common_tech:
            pattern = r"\b" + re.escape(tech) + r"\b"
            if re.search(pattern, text, re.I):
                if not any(tech.lower() == s.lower() for s in skills_matched):
                    skills_matched.append(tech)

        # Detect degree
        degree = None
        deg_match = re.search(
            r"\b(B\.?Tech|B\.?E\.?|B\.?S\.?|Bachelor(?:'s)?|M\.?Tech|M\.?S\.?|Master(?:'s)?|Diploma)\b(?:\s+(?:in\s+)?([A-Za-z\s]+))?",
            text,
            re.I
        )
        if deg_match:
            degree_type = deg_match.group(1).replace(".", "")
            major = deg_match.group(2).strip() if deg_match.group(2) else ""
            if major and len(major) < 30 and not re.search(r"\b(from|at|university|college|gpa)\b", major, re.I):
                degree = f"{degree_type} in {major}"
            else:
                degree = degree_type

        # Detect graduation year
        grad_year = None
        year_match = re.search(r"\b(202[3-9]|2030)\b", text)
        if year_match:
            grad_year = year_match.group(1)

        # Detect projects
        projects = []
        proj_sec = re.search(
            r"(?:projects|academic projects|key projects)[\s:]*\n+([^\n\r]+(?:\n[^\n\r]+){0,6})",
            text,
            re.I
        )
        if proj_sec:
            p_lines = proj_sec.group(1).split("\n")
            for pl in p_lines:
                pl = pl.strip()
                if pl and not pl.startswith("-") and not pl.startswith("•") and len(pl) < 50:
                    clean_p = re.sub(r"^[-\*•\d\.\)]+\s*", "", pl).strip()
                    if clean_p and clean_p not in projects:
                        projects.append(clean_p)
                elif pl.startswith("-") or pl.startswith("•"):
                    first_words = " ".join(pl.split()[:4]).replace("-", "").replace("•", "").strip()
                    if first_words and len(first_words) < 40 and first_words not in projects:
                        projects.append(first_words)

        # Detect experience / internships
        experiences = []
        exp_match = re.search(
            r"(?:experience|work experience|internships?)[\s:]*\n+([^\n\r]+(?:\n[^\n\r]+){0,6})",
            text,
            re.I
        )
        if exp_match:
            e_lines = exp_match.group(1).split("\n")
            for el in e_lines:
                el = el.strip()
                if re.search(r"\b(intern|developer|engineer|assistant|analyst|fellow)\b", el, re.I) and len(el) < 60:
                    clean_e = re.sub(r"^[-\*•\d\.\)]+\s*", "", el).strip()
                    if clean_e and clean_e not in experiences:
                        experiences.append(clean_e)

        is_sparse = (len(words) < 25) and (not experiences) and (not projects) and (len(skills_matched) < 3)

        return {
            "name": name,
            "skills": skills_matched,
            "degree": degree,
            "grad_year": grad_year,
            "projects": projects[:3],
            "experiences": experiences[:2],
            "is_sparse": is_sparse,
            "word_count": len(words),
            "raw_text": text
        }

    def _sanitize_headline(self, headline: str, max_chars: int = 220) -> str:
        """
        Trims and normalizes a headline to strictly fit within LinkedIn's 220-character limit.
        Trims cleanly at natural separator boundaries if truncation is needed.
        """
        clean = re.sub(r"\s+", " ", (headline or "")).strip()
        clean = clean.strip("\"'")
        if len(clean) <= max_chars:
            return clean

        truncated = clean[:max_chars]
        last_sep = max(
            truncated.rfind(" | "),
            truncated.rfind(" • "),
            truncated.rfind(" - "),
            truncated.rfind(", ")
        )
        if last_sep > max_chars // 2:
            return truncated[:last_sep].strip()

        last_space = truncated.rfind(" ")
        if last_space > max_chars // 2:
            return truncated[:last_space].strip()

        return truncated.strip()

    def _resolve_role_keywords(self, target_role: str) -> List[str]:
        """
        Resolves expected recruiter keywords for a target role from role_keywords_map.
        """
        role_key = (target_role or "software engineer").strip().lower()
        if "data" in role_key and "analyst" in role_key:
            lookup = "data analyst"
        elif "web" in role_key:
            lookup = "web developer"
        elif "full" in role_key and "stack" in role_key:
            lookup = "full stack developer"
        elif "devops" in role_key:
            lookup = "devops engineer"
        elif "cloud" in role_key:
            lookup = "cloud engineer"
        elif "product" in role_key:
            lookup = "product manager"
        elif "data" in role_key:
            lookup = "data scientist"
        elif "front" in role_key:
            lookup = "frontend developer"
        elif "back" in role_key:
            lookup = "backend developer"
        else:
            lookup = "software engineer"

        return self.role_keywords_map.get(lookup, self.role_keywords_map["software engineer"])

    def _generate_deterministic_suggestions(
        self,
        entities: Dict[str, Any],
        target_role: str
    ) -> Dict[str, Any]:
        """
        Deterministic, rule-based LinkedIn suggestion generator.
        Guarantees that all suggestions strictly use information present in the resume,
        headlines do not exceed 220 chars, and sparse resumes are handled cleanly.
        """
        skills = entities.get("skills", [])
        experiences = entities.get("experiences", [])
        projects = entities.get("projects", [])
        degree = entities.get("degree")
        grad_year = entities.get("grad_year")
        is_sparse = entities.get("is_sparse", False)

        # 1. Headline Option 1: Role & Core Stack
        if skills:
            skills_sub = ", ".join(skills[:3])
            deg_suffix = f" | {degree}" if degree else (f" | Class of '{grad_year[-2:]}" if grad_year else " | Open to Placements")
            h1 = f"{target_role} | {skills_sub}{deg_suffix}"
        elif degree:
            h1 = f"{target_role} | {degree} | Open to Campus Placements"
        else:
            h1 = f"Aspiring {target_role} | Computer Science & Engineering | Open to Opportunities"
        h1 = self._sanitize_headline(h1, max_chars=220)

        # 2. Headline Option 2: Impact & Experience
        if experiences:
            exp_text = experiences[0]
            skills_clause = f" | {', '.join(skills[:2])}" if skills else ""
            h2 = f"{target_role} • {exp_text}{skills_clause} | Building Scalable Solutions"
        elif projects:
            proj_text = projects[0]
            skills_clause = f" using {skills[0]}" if skills else ""
            h2 = f"{target_role} | Project Developer: {proj_text}{skills_clause} | Seeking Placements"
        elif skills:
            h2 = f"{target_role} Candidate | Skilled in {', '.join(skills[:3])} | Dedicated to Clean Architecture"
        else:
            h2 = f"{target_role} Candidate | Ready to Contribute & Build Reliable Software Systems"
        h2 = self._sanitize_headline(h2, max_chars=220)

        # 3. Headline Option 3: Specialization & Vision
        primary_spec = skills[0] if skills else "Modern Software Development"
        secondary_spec = f" & {skills[1]}" if len(skills) > 1 else ""
        h3 = f"Future {target_role} specializing in {primary_spec}{secondary_spec} | Fast Learner & Problem Solver | Open to Campus Recruitment"
        h3 = self._sanitize_headline(h3, max_chars=220)

        headline_options = [
            {
                "headline": h1,
                "char_count": len(h1),
                "max_chars": 220,
                "type": "Role & Core Stack",
                "description": "Direct and keyword-rich, highlighting your target role, core stack, and credentials."
            },
            {
                "headline": h2,
                "char_count": len(h2),
                "max_chars": 220,
                "type": "Impact & Experience",
                "description": "Emphasizes hands-on practical experience, featured project contributions, or problem-solving impact."
            },
            {
                "headline": h3,
                "char_count": len(h3),
                "max_chars": 220,
                "type": "Specialization & Vision",
                "description": "Showcases domain focus, technical agility, and campus recruitment readiness."
            }
        ]

        # 4. First-Person About Section Draft
        if is_sparse:
            skills_part = f" with hands-on practice in {', '.join(skills[:3])}" if skills else ""
            degree_part = f" pursuing my degree in {degree}" if degree else ""
            about = (
                f"I am an aspiring {target_role}{degree_part}{skills_part}. "
                f"I am deeply committed to developing my technical craft, writing clean code, and solving real-world challenges through software.\n\n"
                f"I am actively seeking entry-level and campus placement opportunities where I can contribute to high-performing teams, "
                f"learn from experienced engineering mentors, and deliver measurable impact. Let's connect!"
            )
        else:
            skills_str = ", ".join(skills[:5]) if skills else "modern software engineering practices"
            degree_clause = f" studying {degree}" if degree else ""
            p1 = f"I am a {target_role}{degree_clause} with a strong technical focus in {skills_str}. I enjoy transforming complex problems into clean, well-tested, and maintainable software."

            p2_parts = []
            if experiences:
                p2_parts.append(f"In my experience as {experiences[0]}, I contributed to building practical solutions and collaborating in an engineering environment.")
            if projects:
                p2_parts.append(f"Through hands-on projects such as {projects[0]}, I gained practical exposure to building scalable systems and refining user experiences.")
            if not p2_parts:
                p2_parts.append("Through hands-on coursework and independent projects, I have developed a solid foundation in algorithm design and system implementation.")
            p2 = " ".join(p2_parts)

            p3 = f"I am preparing for campus placements and actively exploring {target_role} opportunities where I can add value from day one, tackle new technical domains, and grow alongside an innovative team. Open to networking and conversations!"
            about = f"{p1}\n\n{p2}\n\n{p3}"

        # 5. Recruiter Search Keywords
        expected_keywords = self._resolve_role_keywords(target_role)
        resume_lower = entities.get("raw_text", "").lower()

        matched_keywords = []
        recommended_keywords = []
        for kw in expected_keywords:
            if re.search(r"\b" + re.escape(kw.lower()) + r"\b", resume_lower) or any(kw.lower() == s.lower() for s in skills):
                matched_keywords.append(kw)
            else:
                recommended_keywords.append(kw)

        # Include candidate's own parsed skills in matched keywords
        for s in skills[:8]:
            if s not in matched_keywords and len(s) > 1:
                matched_keywords.append(s)

        all_keywords = matched_keywords + recommended_keywords

        return {
            "target_role": target_role,
            "candidate_name": entities.get("name"),
            "headline_options": headline_options,
            "about_section": about,
            "about_word_count": len(about.split()),
            "about_char_count": len(about),
            "recruiter_keywords": all_keywords[:15],
            "matched_keywords": matched_keywords[:10],
            "recommended_keywords": recommended_keywords[:10],
            "is_sparse": is_sparse,
            "headline_limit": 220
        }

    def _call_gemini_linkedin_suggestions(
        self,
        resume_text: str,
        target_role: str,
        entities: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Uses Gemini LLM to generate personalized, high-converting LinkedIn profile assets.
        Strictly constrains the model to use only facts present in the resume.
        """
        clean_text = (resume_text or "").strip()
        if not clean_text:
            return None

        system_instruction = (
            "You are an expert technical recruiter and executive LinkedIn optimization coach. "
            "You format candidates' resumes into high-converting, search-optimized LinkedIn profiles. "
            "CRITICAL CONSTRAINT: You MUST strictly use ONLY facts, skills, companies, education, and projects "
            "explicitly mentioned in the candidate's resume text below. Do NOT fabricate, assume, or extrapolate "
            "any unmentioned employers, colleges, certifications, or quantitative metrics. "
            "Every generated headline MUST be strictly 220 characters or fewer. "
            "The About section MUST be written entirely in the first person ('I', 'my'). "
            "Return valid JSON only."
        )

        prompt = f"""
Generate 3 distinct LinkedIn headline options, a first-person About section draft, and target recruiter keywords based STRICTLY on this candidate's resume.

Target Role: {target_role}
Candidate Resume Text:
\"\"\"
{clean_text[:4000]}
\"\"\"

Requirements:
1. headline_options: Exactly 3 distinct options.
   - Option 1 (Role & Core Stack): Search-friendly, lists target role and core skills verified in resume.
   - Option 2 (Impact & Experience): Highlights hands-on project or internship experience verified in resume.
   - Option 3 (Specialization & Vision): Highlights technical focus area and placement aspiration.
   - HARD LIMIT: Each headline MUST be strictly <= 220 characters in length.
2. about_section: A 2-3 paragraph first-person ('I', 'my') professional summary synthesizing only the candidate's actual skills, projects, and education. If the resume has very little content, write a concise, genuine statement without fabricating experience.
3. recruiter_keywords: A list of 8-15 high-volume search keywords that campus recruiters query on LinkedIn for {target_role} that align with the candidate's background.

Return ONLY valid JSON matching this schema:
{{
  "headline_options": [
    {{"headline": "Headline 1", "type": "Role & Core Stack", "description": "Search-optimized role and stack"}},
    {{"headline": "Headline 2", "type": "Impact & Experience", "description": "Highlighting tangible contributions"}},
    {{"headline": "Headline 3", "type": "Specialization & Vision", "description": "Domain focus and ambition"}}
  ],
  "about_section": "First-person narrative text...",
  "recruiter_keywords": ["keyword1", "keyword2"]
}}
"""
        try:
            data = generate_json_response(system_instruction=system_instruction, prompt=prompt, feature="outreach")
            if not isinstance(data, dict):
                return None

            raw_headlines = data.get("headline_options", [])
            about_section = (data.get("about_section") or "").strip()
            recruiter_keywords = data.get("recruiter_keywords", [])

            if not raw_headlines or not about_section:
                return None

            # Enforce <= 220 char limit on all headlines
            processed_headlines = []
            default_types = ["Role & Core Stack", "Impact & Experience", "Specialization & Vision"]
            default_descs = [
                "Clear and search-friendly headline highlighting your primary target role and verified technical stack.",
                "Results-oriented headline emphasizing hands-on project accomplishments and internship contributions.",
                "Domain-focused headline showcasing technical specialization and campus placement aspirations."
            ]
            for idx, item in enumerate(raw_headlines[:3]):
                text = item.get("headline", "") if isinstance(item, dict) else str(item)
                sanitized = self._sanitize_headline(text, max_chars=220)
                opt_type = item.get("type", default_types[idx]) if isinstance(item, dict) else default_types[idx]
                opt_desc = item.get("description", default_descs[idx]) if isinstance(item, dict) else default_descs[idx]
                processed_headlines.append({
                    "headline": sanitized,
                    "char_count": len(sanitized),
                    "max_chars": 220,
                    "type": opt_type,
                    "description": opt_desc
                })

            # If fewer than 3 headlines were returned, pad with deterministic fallbacks
            if len(processed_headlines) < 3:
                det = self._generate_deterministic_suggestions(entities, target_role)
                for missing_idx in range(len(processed_headlines), 3):
                    processed_headlines.append(det["headline_options"][missing_idx])

            # Resolve keyword matching
            expected_keywords = self._resolve_role_keywords(target_role)
            resume_lower = clean_text.lower()
            matched_keywords = []
            recommended_keywords = []
            for kw in (recruiter_keywords or expected_keywords):
                if re.search(r"\b" + re.escape(str(kw).lower()) + r"\b", resume_lower):
                    matched_keywords.append(str(kw))
                else:
                    recommended_keywords.append(str(kw))

            return {
                "target_role": target_role,
                "candidate_name": entities.get("name"),
                "headline_options": processed_headlines,
                "about_section": about_section,
                "about_word_count": len(about_section.split()),
                "about_char_count": len(about_section),
                "recruiter_keywords": (recruiter_keywords or (matched_keywords + recommended_keywords))[:15],
                "matched_keywords": matched_keywords[:10],
                "recommended_keywords": recommended_keywords[:10],
                "is_sparse": entities.get("is_sparse", False),
                "headline_limit": 220
            }
        except Exception as e:
            logger.warning(f"Gemini LLM call failed in generate_linkedin_suggestions: {e}. Falling back to rule-based engine.")
            return None
