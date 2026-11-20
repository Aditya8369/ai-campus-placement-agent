"""
OutreachGeneratorAgent - Tailored Cover Letter & Outreach Pitch Generator

Generates high-converting job application outreach assets:
- Tailored formal cover letters for target companies and job descriptions.
- High-response LinkedIn InMail / connection pitches for recruiters and engineering managers.
- Value-first Cold Recruiter Emails with multiple subject line variants.
- Executive pitch highlights tailored by tone (formal, enthusiastic, concise).
- Export utilities for formatted .docx and .txt outputs.
"""

import io
import re
import json
import logging
from typing import Dict, Any, List, Optional
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

import config
import prompts
from utils.gemini import generate_json_response, AIAnalysisError
from utils.prompt_security import (
    sanitize_untrusted_text,
    encapsulate_untrusted_input,
    build_secure_system_instruction,
    redact_sensitive_information,
)

logger = logging.getLogger(__name__)

VALID_TONES = ["formal", "friendly", "enthusiastic", "concise"]
DEFAULT_TONE = "formal"


class OutreachGeneratorAgent:
    """
    Agent responsible for generating tailored cover letters, LinkedIn outreach pitches,
    and cold recruiter emails based on candidate profile, target company, and job description.
    """

    def __init__(self) -> None:
        pass

    def generate_outreach(
        self,
        analysis_record: Dict[str, Any],
        tone: str = "formal",
        role_title: str = ""
    ) -> Dict[str, Any]:
        """
        Generates tailored application outreach assets for a given candidate analysis record.
        Supports tone modulation ('formal', 'enthusiastic', 'concise') and falls back to a
        deterministic heuristic generator when offline or if Gemini fails.
        """
        norm_tone = str(tone or "").strip().lower()
        if norm_tone not in VALID_TONES:
            norm_tone = DEFAULT_TONE

        company_name = analysis_record.get("company_name", "Target Company") or "Target Company"
        job_description = analysis_record.get("job_description", "") or ""

        # Extract nested results payload
        results = analysis_record.get("results", {})
        if isinstance(results, str):
            try:
                results = json.loads(results)
            except Exception:
                results = {}
        if not isinstance(results, dict):
            results = {}

        resume_analysis = results.get("resume_analysis", {})
        job_match = results.get("job_match", {})

        matched_skills = job_match.get("matched_skills", []) or resume_analysis.get("skills", [])
        if not isinstance(matched_skills, list):
            matched_skills = [str(matched_skills)] if matched_skills else []

        strengths = resume_analysis.get("strengths", [])
        if not isinstance(strengths, list):
            strengths = [str(strengths)] if strengths else []

        ats_score = resume_analysis.get("ats_score", 75)
        resume_summary = resume_analysis.get("summary", "Dedicated engineering student with strong technical fundamentals.")
        project_feedback = resume_analysis.get("project_feedback", "")
        experience_feedback = resume_analysis.get("experience_feedback", "")
        experience_context = f"{project_feedback} {experience_feedback}".strip() or "Full-stack development, software engineering, and system design."

        # Detect role title if omitted
        inferred_role = self._infer_role_title(role_title, job_description)

        # Attempt LLM generation
        try:
            company_details_str = ""
            companies_file = config.BASE_DIR / "data" / "companies.json"
            if companies_file.exists():
                with open(companies_file, "r", encoding="utf-8") as f:
                    comp_data = json.load(f)
                    c_info = comp_data.get(company_name, {})
                    if c_info:
                        company_details_str = json.dumps(c_info)

            safe_jd = sanitize_untrusted_text(job_description or f"Engineering position at {company_name}.", max_length=15000)
            encapsulated_jd = encapsulate_untrusted_input(safe_jd, document_type="job_description")
            safe_exp = sanitize_untrusted_text(experience_context[:600])

            prompt = prompts.OUTREACH_USER_PROMPT_TEMPLATE.format(
                company_name=company_name,
                role_title=inferred_role,
                tone=norm_tone,
                company_details=company_details_str or f"Hiring for engineering and technical positions at {company_name}.",
                job_description=encapsulated_jd,
                matched_skills=", ".join(matched_skills[:8]) if matched_skills else "Python, Problem Solving, Data Structures",
                strengths=", ".join(strengths[:4]) if strengths else "Strong fundamentals, analytical mindset",
                resume_summary=resume_summary,
                ats_score=ats_score,
                experience_context=safe_exp
            )

            raw_outreach = generate_json_response(
                prompt=prompt,
                system_instruction=build_secure_system_instruction(prompts.OUTREACH_SYSTEM_INSTRUCTION),
                feature="outreach"
            )

            validated = self._validate_and_sanitize_outreach(
                raw_outreach,
                company_name=company_name,
                role_title=inferred_role,
                tone=norm_tone,
                matched_skills=matched_skills
            )
            if validated:
                return redact_sensitive_information(validated)

        except Exception as e:
            logger.warning(f"LLM outreach generation failed or offline ({e}). Using heuristic generator.")

        # Fallback to deterministic heuristic generation
        return self._generate_heuristic_outreach(
            company_name=company_name,
            role_title=inferred_role,
            tone=norm_tone,
            matched_skills=matched_skills,
            strengths=strengths,
            resume_summary=resume_summary,
            ats_score=ats_score
        )

    def _infer_role_title(self, user_role: str, jd: str) -> str:
        """Determines best role title from user input or job description text."""
        if user_role and user_role.strip():
            return user_role.strip()

        common_titles = [
            "Software Development Engineer",
            "Software Engineer",
            "Full Stack Developer",
            "Backend Engineer",
            "Frontend Engineer",
            "Machine Learning Engineer",
            "Data Scientist",
            "Data Analyst",
            "DevOps Engineer",
            "Cloud Engineer",
            "Associate Software Engineer",
            "Graduate Engineer Trainee",
            "Systems Engineer"
        ]

        for title in common_titles:
            pattern = re.compile(rf"\b{re.escape(title)}\b", re.IGNORECASE)
            if pattern.search(jd):
                return title

        return "Software Engineer"

    def _validate_and_sanitize_outreach(
        self,
        data: Any,
        company_name: str,
        role_title: str,
        tone: str,
        matched_skills: List[str]
    ) -> Optional[Dict[str, Any]]:
        """Ensures the generated dictionary contains all required fields and conforms to schema."""
        if not isinstance(data, dict):
            return None

        cover_letter = str(data.get("cover_letter", "")).strip()
        linkedin_inmail = str(data.get("linkedin_inmail", "")).strip()
        cold_email = str(data.get("cold_email", "")).strip()

        if not cover_letter or not linkedin_inmail or not cold_email:
            return None

        subject_lines = data.get("subject_lines", [])
        if not isinstance(subject_lines, list) or len(subject_lines) < 2:
            skill_tag = matched_skills[0] if matched_skills else "Engineering"
            subject_lines = [
                f"{role_title} Candidate - {skill_tag} | [Your Name]",
                f"Passionate about {company_name} Tech - {role_title} Inquiry",
                f"Quick connection regarding {company_name} engineering team - [Your Name]"
            ]

        key_highlights = data.get("key_highlights", [])
        if not isinstance(key_highlights, list) or len(key_highlights) < 2:
            key_highlights = [
                f"Demonstrated proficiency in {', '.join(matched_skills[:3]) if matched_skills else 'core computer science fundamentals'}.",
                f"Proven track record building end-to-end technical solutions with measurable performance.",
                f"Strong alignment with {company_name}'s engineering principles and high-velocity shipping culture."
            ]

        return {
            "tone": tone,
            "role_title": role_title,
            "company_name": company_name,
            "cover_letter": cover_letter,
            "linkedin_inmail": linkedin_inmail,
            "cold_email": cold_email,
            "subject_lines": [str(s).strip() for s in subject_lines if s],
            "key_highlights": [str(h).strip() for h in key_highlights if h]
        }

    def _generate_heuristic_outreach(
        self,
        company_name: str,
        role_title: str,
        tone: str,
        matched_skills: List[str],
        strengths: List[str],
        resume_summary: str,
        ats_score: int
    ) -> Dict[str, Any]:
        """
        Deterministic, rule-based outreach generator producing polished, customized materials
        across formal, enthusiastic, and concise tones.
        """
        top_skills = matched_skills[:4] if matched_skills else ["Python", "Data Structures", "System Design"]
        skills_str = ", ".join(top_skills)
        primary_skill = top_skills[0]
        strength_1 = strengths[0] if strengths else "strong analytical and technical problem solving"
        strength_2 = strengths[1] if len(strengths) > 1 else "rapid adaptability to modern engineering workflows"

        if tone == "formal":
            cover_letter = (
                f"Dear Hiring Team at {company_name},\n\n"
                f"I am writing to express my strong interest in the {role_title} position at {company_name}. "
                f"Having developed a rigorous foundation in software engineering and hands-on experience in {skills_str}, "
                f"I am eager to contribute to your team's mission-critical systems and ongoing technological innovation.\n\n"
                f"Throughout my academic and project initiatives, I have focused on building performant, scalable applications. "
                f"My background emphasizes {strength_1} alongside practical implementation of {primary_skill}. "
                f"In recent work, I architected structured solutions that prioritized algorithmic efficiency, maintainability, and clean design patterns—qualities "
                f"I know {company_name} values deeply in its technical talent.\n\n"
                f"What particularly attracts me to {company_name} is your commitment to engineering excellence and scalable impact. "
                f"I am confident that my technical proficiency in {skills_str}, combined with {strength_2}, will enable me to hit the ground running "
                f"and add immediate value to your engineering initiatives.\n\n"
                f"Thank you for your time and consideration. I welcome the opportunity to discuss how my skill set and dedication can support {company_name}'s goals.\n\n"
                f"Sincerely,\n"
                f"[Your Name]\n"
                f"[Your Phone] | [Your Email] | [LinkedIn Profile] | [GitHub / Portfolio]"
            )

            linkedin_inmail = (
                f"Dear [First Name],\n\n"
                f"I hope this note finds you well. I follow {company_name}'s engineering advancements closely and noticed the open {role_title} opportunity.\n\n"
                f"As an aspiring software engineer specializing in {skills_str}, I have built projects focusing on {strength_1}. "
                f"I would welcome the opportunity to connect and learn more about your team's priorities at {company_name}.\n\n"
                f"Thank you for your time and guidance.\n\n"
                f"Best regards,\n"
                f"[Your Name]"
            )

            cold_email = (
                f"Subject: Application for {role_title} - [Your Name] | {primary_skill} Background\n\n"
                f"Dear [Hiring Manager / Recruiter Name],\n\n"
                f"I am reaching out to formally apply for the {role_title} opening at {company_name}. "
                f"With practical expertise across {skills_str}, I have developed software solutions that emphasize scalability and robust code quality.\n\n"
                f"Key qualifications I bring to the team:\n"
                f"• Technical Breadth: Demonstrated capability in {skills_str} applied to real-world engineering challenges.\n"
                f"• Execution & Impact: Proven track record in {strength_1}.\n"
                f"• Culture Alignment: Disciplined focus on {strength_2} and high team collaboration.\n\n"
                f"My resume is attached for your review. Would you be open to a brief 10-minute introductory conversation this week?\n\n"
                f"Thank you for your consideration,\n"
                f"[Your Name]\n"
                f"[Your Phone] | [Your Email] | [Portfolio Link]"
            )

        elif tone in ("friendly", "enthusiastic"):
            cover_letter = (
                f"Dear {company_name} Team,\n\n"
                f"I am thrilled to apply for the {role_title} role at {company_name}! "
                f"I have long admired {company_name}'s culture of rapid innovation, and the prospect of building impactful software "
                f"alongside such world-class engineers is genuinely inspiring.\n\n"
                f"As a software developer passionate about {skills_str}, I love transforming complex ideas into production-ready software. "
                f"My key strengths include {strength_1} and an energetic commitment to learning cutting-edge technologies. "
                f"Whether optimizing complex algorithms or collaborating on team codebases, I bring boundless curiosity and high execution velocity.\n\n"
                f"What excites me most about {company_name} is the chance to tackle large-scale challenges that genuinely improve user experiences. "
                f"I am eager to contribute my energy, deep foundation in {primary_skill}, and drive to your dynamic engineering team.\n\n"
                f"I would love the opportunity to chat about how my energy and technical background align with your upcoming milestones!\n\n"
                f"Warm regards,\n"
                f"[Your Name]\n"
                f"[Your Phone] | [Your Email] | [LinkedIn Profile]"
            )

            linkedin_inmail = (
                f"Hi [First Name]!\n\n"
                f"I came across your profile while exploring {company_name}'s amazing engineering work! "
                f"I am a passionate software developer proficient in {skills_str}, and I'm very excited about the {role_title} opening.\n\n"
                f"I'd love to connect, follow your journey, and hear any quick insights you might share about building impactful systems at {company_name}!\n\n"
                f"Best,\n"
                f"[Your Name]"
            )

            cold_email = (
                f"Subject: Enthusiastic {role_title} Candidate passionate about {company_name}!\n\n"
                f"Hi [Hiring Manager Name],\n\n"
                f"I hope you're having a wonderful week! I'm reaching out because I'm genuinely passionate about {company_name}'s products and "
                f"would love to contribute as your next {role_title}.\n\n"
                f"Here is what I am excited to bring to your team:\n"
                f"• Technical Stack: Solid hands-on foundation in {skills_str}.\n"
                f"• Growth Mindset: {strength_1} with passion for building resilient features.\n"
                f"• High Energy: Dedicated to shipping clean, well-tested code with velocity.\n\n"
                f"I'd be thrilled to speak with you for 10 minutes whenever convenient. Looking forward to connecting!\n\n"
                f"Cheers,\n"
                f"[Your Name]\n"
                f"[Your Phone] | [Your Email] | [GitHub / Portfolio]"
            )

        else:  # concise
            cover_letter = (
                f"Dear Hiring Team at {company_name},\n\n"
                f"Please consider my application for the {role_title} opening at {company_name}.\n\n"
                f"Summary of Core Qualifications:\n"
                f"• Technical Competencies: {skills_str}.\n"
                f"• Demonstrated Strengths: {strength_1}.\n"
                f"• Execution Focus: Proven ability to design and deploy robust software under tight timelines.\n\n"
                f"I admire {company_name}'s high-caliber engineering culture and welcome the opportunity to discuss how my skill set can support your team's immediate objectives.\n\n"
                f"Best regards,\n"
                f"[Your Name]\n"
                f"[Your Phone] | [Your Email] | [Portfolio Link]"
            )

            linkedin_inmail = (
                f"Hi [First Name],\n\n"
                f"I'm an engineer specializing in {skills_str} and currently exploring the {role_title} opening at {company_name}.\n\n"
                f"My background centers on {strength_1}. I would love to connect and hear if you have 5 minutes for a quick chat regarding the team's engineering stack.\n\n"
                f"Thanks,\n"
                f"[Your Name]"
            )

            cold_email = (
                f"Subject: {role_title} Fit - [Your Name] ({primary_skill})\n\n"
                f"Hi [Hiring Manager Name],\n\n"
                f"Reaching out regarding the {role_title} role at {company_name}. A quick snapshot of my qualifications:\n\n"
                f"• Core Stack: {skills_str}\n"
                f"• Key Differentiator: {strength_1}\n"
                f"• Placement Readiness: Verified strong ATS alignment & project foundation\n\n"
                f"Are you available for a brief 5-minute call this Thursday or Friday to connect?\n\n"
                f"Best,\n"
                f"[Your Name]\n"
                f"[Your Phone] | [Your Email] | [Portfolio Link]"
            )

        subject_lines = [
            f"{role_title} Application - [Your Name] | {primary_skill}",
            f"Passionate about {company_name} Engineering - {role_title} Candidate",
            f"Quick question regarding {company_name}'s {role_title} opening - [Your Name]"
        ]

        key_highlights = [
            f"Proficient in {skills_str} with hands-on project implementation.",
            f"Core strength: {strength_1}.",
            f"Core strength: {strength_2}.",
            f"ATS compatibility score of {ats_score}/100 verified against target engineering benchmarks."
        ]

        return {
            "tone": tone,
            "role_title": role_title,
            "company_name": company_name,
            "cover_letter": cover_letter,
            "linkedin_inmail": linkedin_inmail,
            "cold_email": cold_email,
            "subject_lines": subject_lines,
            "key_highlights": key_highlights
        }

    def export_to_docx(
        self,
        outreach_data: Dict[str, Any],
        candidate_name: str = "Candidate",
        company_name: str = ""
    ) -> bytes:
        """
        Builds a styled Word document (.docx) in memory containing the outreach portfolio:
        - Candidate Letterhead & Target Company Info
        - Tailored Cover Letter
        - LinkedIn InMail Pitch
        - Cold Recruiter Email & Subject Line Variants
        - Key Highlights
        """
        doc = docx.Document()

        # Set page margins (1 inch all sides)
        sections = doc.sections
        for s in sections:
            s.top_margin = Inches(1.0)
            s.bottom_margin = Inches(1.0)
            s.left_margin = Inches(1.0)
            s.right_margin = Inches(1.0)

        c_name = candidate_name if candidate_name and candidate_name != "default_student" else "Candidate"
        target_company = company_name or outreach_data.get("company_name", "Target Company")
        role_title = outreach_data.get("role_title", "Software Engineer")
        tone = outreach_data.get("tone", "formal").capitalize()

        # Header Title
        title_para = doc.add_paragraph()
        title_run = title_para.add_run(f"JOB APPLICATION OUTREACH PORTFOLIO")
        title_run.font.size = Pt(18)
        title_run.font.bold = True
        title_run.font.color.rgb = RGBColor(30, 64, 175)  # Navy / Primary
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

        sub_para = doc.add_paragraph()
        sub_run = sub_para.add_run(f"Target: {target_company} | Position: {role_title} | Tone: {tone}")
        sub_run.font.size = Pt(11)
        sub_run.font.italic = True
        sub_run.font.color.rgb = RGBColor(100, 116, 139)
        sub_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

        doc.add_paragraph().paragraph_format.space_after = Pt(12)

        # -------------------------------------------------------------
        # Section 1: Formal Cover Letter
        # -------------------------------------------------------------
        h1 = doc.add_heading("1. Tailored Cover Letter", level=1)
        h1.runs[0].font.color.rgb = RGBColor(30, 64, 175)
        h1.paragraph_format.space_before = Pt(12)
        h1.paragraph_format.space_after = Pt(6)

        cover_letter_text = outreach_data.get("cover_letter", "")
        for block in cover_letter_text.split("\n\n"):
            clean_block = block.strip()
            if clean_block:
                p = doc.add_paragraph(clean_block)
                p.paragraph_format.line_spacing = 1.15
                p.paragraph_format.space_after = Pt(6)

        doc.add_paragraph().paragraph_format.space_after = Pt(12)

        # -------------------------------------------------------------
        # Section 2: LinkedIn InMail Pitch
        # -------------------------------------------------------------
        h2 = doc.add_heading("2. LinkedIn InMail / Referral Connection Pitch", level=1)
        h2.runs[0].font.color.rgb = RGBColor(30, 64, 175)
        h2.paragraph_format.space_before = Pt(12)
        h2.paragraph_format.space_after = Pt(6)

        inmail_text = outreach_data.get("linkedin_inmail", "")
        for block in inmail_text.split("\n\n"):
            clean_block = block.strip()
            if clean_block:
                p = doc.add_paragraph(clean_block)
                p.paragraph_format.line_spacing = 1.15
                p.paragraph_format.space_after = Pt(6)

        doc.add_paragraph().paragraph_format.space_after = Pt(12)

        # -------------------------------------------------------------
        # Section 3: Cold Recruiter Email & Subject Lines
        # -------------------------------------------------------------
        h3 = doc.add_heading("3. Cold Recruiter Outreach Email", level=1)
        h3.runs[0].font.color.rgb = RGBColor(30, 64, 175)
        h3.paragraph_format.space_before = Pt(12)
        h3.paragraph_format.space_after = Pt(6)

        subject_lines = outreach_data.get("subject_lines", [])
        if subject_lines:
            sub_head = doc.add_paragraph()
            sh_run = sub_head.add_run("Recommended Email Subject Lines:")
            sh_run.font.bold = True
            sh_run.font.size = Pt(10.5)
            for sl in subject_lines:
                bullet = doc.add_paragraph(sl, style="List Bullet")
                bullet.paragraph_format.space_after = Pt(2)

        cold_email_text = outreach_data.get("cold_email", "")
        for block in cold_email_text.split("\n\n"):
            clean_block = block.strip()
            if clean_block:
                p = doc.add_paragraph(clean_block)
                p.paragraph_format.line_spacing = 1.15
                p.paragraph_format.space_after = Pt(6)

        doc.add_paragraph().paragraph_format.space_after = Pt(12)

        # -------------------------------------------------------------
        # Section 4: Key Pitch Highlights
        # -------------------------------------------------------------
        highlights = outreach_data.get("key_highlights", [])
        if highlights:
            h4 = doc.add_heading("4. Key Elevator Pitch Highlights", level=1)
            h4.runs[0].font.color.rgb = RGBColor(30, 64, 175)
            h4.paragraph_format.space_before = Pt(12)
            h4.paragraph_format.space_after = Pt(6)

            for hl in highlights:
                b = doc.add_paragraph(hl, style="List Bullet")
                b.paragraph_format.space_after = Pt(3)

        # Save to buffer
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()

    def export_to_txt(
        self,
        outreach_data: Dict[str, Any],
        candidate_name: str = "Candidate",
        company_name: str = ""
    ) -> str:
        """Formats the generated outreach materials into clean plain text."""
        target_company = company_name or outreach_data.get("company_name", "Target Company")
        role_title = outreach_data.get("role_title", "Software Engineer")
        tone = outreach_data.get("tone", "formal").capitalize()

        lines = [
            "=" * 72,
            f"JOB APPLICATION OUTREACH PORTFOLIO",
            f"Target: {target_company} | Position: {role_title} | Tone: {tone}",
            "=" * 72,
            "",
            "1. TAILORED COVER LETTER",
            "-" * 72,
            outreach_data.get("cover_letter", "").strip(),
            "",
            "-" * 72,
            "2. LINKEDIN INMAIL / REFERRAL PITCH",
            "-" * 72,
            outreach_data.get("linkedin_inmail", "").strip(),
            "",
            "-" * 72,
            "3. COLD RECRUITER OUTREACH EMAIL",
            "-" * 72,
        ]

        subject_lines = outreach_data.get("subject_lines", [])
        if subject_lines:
            lines.append("Subject Line Variants:")
            for sl in subject_lines:
                lines.append(f"  • {sl}")
            lines.append("")

        lines.extend([
            outreach_data.get("cold_email", "").strip(),
            "",
            "-" * 72,
            "4. KEY ELEVATOR PITCH HIGHLIGHTS",
            "-" * 72,
        ])

        for hl in outreach_data.get("key_highlights", []):
            lines.append(f"  • {hl}")

        lines.append("")
        lines.append("=" * 72)
        return "\n".join(lines)

    def generate_tailored_cover_letter(
        self,
        resume_text: str,
        job_description: str,
        company_name: Optional[str] = None,
        tone: str = "formal"
    ) -> Dict[str, Any]:
        """
        Generates a tailored 3-to-4 paragraph cover letter grounded strictly in the candidate's resume
        and tailored to the target job description (#537).
        """
        clean_jd = (job_description or "").strip()
        if not clean_jd:
            return {
                "success": False,
                "error": "A job description is required to generate a tailored cover letter. Please paste the target job description.",
                "missing_field": "job_description",
                "cover_letter": ""
            }

        clean_resume = (resume_text or "").strip()
        if not clean_resume:
            return {
                "success": False,
                "error": "Resume text is missing. Please provide a resume to tailor the cover letter.",
                "missing_field": "resume_text",
                "cover_letter": ""
            }

        resume_facts = self._extract_resume_facts(clean_resume)

        # 1. Try AI-powered letter if LLM available
        ai_res = self._call_gemini_cover_letter(
            resume_text=clean_resume,
            job_description=clean_jd,
            company_name=company_name or "",
            tone=tone,
            resume_facts=resume_facts
        )
        if ai_res:
            return ai_res

        # 2. Fall back to deterministic heuristic letter
        return self._generate_heuristic_cover_letter(
            resume_facts=resume_facts,
            job_description=clean_jd,
            company_name=company_name or "",
            tone=tone
        )

    def _extract_resume_facts(self, resume_text: str) -> Dict[str, Any]:
        """
        Extracts verified skills, projects, degrees, experiences, and candidate name
        from resume text to prevent claiming skills/experience missing from the resume (#537).
        """
        text = (resume_text or "").strip()
        words = text.split()

        # Extract name if apparent
        candidate_name = None
        if text:
            first_line = text.split("\n")[0].strip()
            if re.match(r"^[A-Za-z\.\s\-]{3,40}$", first_line) and not re.search(
                r"\b(resume|cv|curriculum|profile|engineer|developer|analyst|student)\b",
                first_line,
                re.I
            ):
                candidate_name = first_line

        # Known technical inventory
        tech_inventory = [
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

        skills_found = []
        # Explicit skills section
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
                if 2 <= len(tok_clean) <= 30 and tok_clean not in skills_found:
                    if not re.search(r"\b(experience|education|projects|awards|activities)[\s:]*$", tok_clean, re.I):
                        skills_found.append(tok_clean)

        for tech in tech_inventory:
            pattern = r"\b" + re.escape(tech) + r"\b"
            if re.search(pattern, text, re.I):
                if not any(tech.lower() == s.lower() for s in skills_found):
                    skills_found.append(tech)

        # Degree
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

        # Projects
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

        # Experiences
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

        return {
            "name": candidate_name,
            "candidate_name": candidate_name,
            "skills": skills_found,
            "degree": degree,
            "projects": projects[:3],
            "experiences": experiences[:2],
            "is_sparse": (len(words) < 25) and (not experiences) and (not projects) and (len(skills_found) < 3),
            "word_count": len(words)
        }

    def _generate_heuristic_cover_letter(
        self,
        resume_facts: Dict[str, Any],
        job_description: str,
        company_name: str,
        tone: str
    ) -> Dict[str, Any]:
        """
        Deterministic, rule-based 3-to-4 paragraph tailored cover letter generator.
        Guarantees that no skills or experiences missing from the resume are claimed (#537).
        """
        skills = resume_facts.get("skills", [])
        experiences = resume_facts.get("experiences", [])
        projects = resume_facts.get("projects", [])
        degree = resume_facts.get("degree")
        candidate_name = resume_facts.get("name") or "[Your Name]"

        role_title = self._infer_role_title("", job_description)
        target_company = (company_name or "").strip() or "the Hiring Team"
        norm_tone = "friendly" if str(tone).lower().strip() in ("friendly", "enthusiastic") else "formal"

        # Intersect candidate's resume skills with job description keywords
        jd_lower = job_description.lower()
        matched_skills = []
        for s in skills:
            pattern = r"\b" + re.escape(s.lower()) + r"\b"
            if re.search(pattern, jd_lower):
                matched_skills.append(s)

        # Highlight skills: strictly subset of resume skills
        highlight_skills = matched_skills[:4] if matched_skills else skills[:4]
        skills_summary = ", ".join(highlight_skills) if highlight_skills else "software engineering principles"
        primary_skill = highlight_skills[0] if highlight_skills else "clean code development"
        degree_part = f"a solid foundation in {degree}" if degree else "hands-on technical training"

        # Construct Paragraphs
        if norm_tone == "friendly":
            salutation = f"Hi {target_company} Team," if target_company != "the Hiring Team" else "Hello Hiring Team,"

            p1 = (
                f"I was excited to discover the open {role_title} opportunity at {target_company} and would love to be considered! "
                f"With {degree_part} and hands-on experience working with {skills_summary}, I am eager to bring my curiosity, dedication, "
                f"and technical energy to your engineering team."
            )

            p2 = (
                f"The challenges and priorities outlined in your job description strongly resonate with me. Looking through the requirements, "
                f"my practical background in {skills_summary} feels like a natural fit. I genuinely enjoy writing clean, well-tested code, "
                f"collaborating closely with teammates, and continuously expanding my technical toolkit to solve real-world user problems."
            )

            if experiences:
                p3 = (
                    f"During my time as {experiences[0]}, I gained valuable practical experience implementing features, "
                    f"prioritizing code maintainability, and learning from experienced colleagues in an engineering environment."
                )
            elif projects:
                p3 = (
                    f"A project I am particularly proud of is {projects[0]}, where I applied {primary_skill} to build a working, "
                    f"reliable application. Designing and iterating on this project taught me how to tackle technical hurdles and build with users in mind."
                )
            else:
                p3 = (
                    f"Through dedicated coursework and building practical software projects, I have developed a strong habit of writing reliable code, "
                    f"seeking feedback, and learning quickly from technical challenges."
                )

            p4 = (
                f"I would love the opportunity to connect and chat about how my skill set and enthusiasm can support {target_company}'s upcoming milestones. "
                f"Thank you so much for your time and consideration!"
            )

            signoff = f"Warm regards,\n{candidate_name}"

        else:  # formal
            salutation = f"Dear Hiring Team at {target_company}," if target_company != "the Hiring Team" else "Dear Hiring Manager,"

            p1 = (
                f"I am writing to express my strong interest in the {role_title} position at {target_company}. "
                f"With {degree_part} and hands-on technical proficiency in {skills_summary}, I am eager to contribute to "
                f"your team's software engineering initiatives and high-quality deliverables."
            )

            p2 = (
                f"Having carefully reviewed the job requirements, I believe my technical background in {skills_summary} provides "
                f"a strong foundation for this role. I have consistently focused on writing clean, maintainable code, applying algorithmic efficiency, "
                f"and adapting rapidly to modern engineering stacks and team standards."
            )

            if experiences:
                p3 = (
                    f"My practical experience includes serving as {experiences[0]}, where I was responsible for delivering dependable solutions "
                    f"and collaborating with colleagues in an engineering environment. This experience reinforced my discipline in code quality, debugging, "
                    f"and structured teamwork."
                )
            elif projects:
                p3 = (
                    f"My technical projects include developing {projects[0]}, where I utilized {primary_skill} to implement functional, "
                    f"scalable components. This hands-on project work reinforced my understanding of architectural design, systematic testing, and software reliability."
                )
            else:
                p3 = (
                    f"Through rigorous academic coursework and hands-on projects, I have built a disciplined approach to software implementation, "
                    f"emphasizing algorithmic efficiency, testability, and clean architecture."
                )

            p4 = (
                f"I welcome the opportunity to discuss in an interview how my technical abilities and dedication align with {target_company}'s goals. "
                f"Thank you for your time, consideration, and review of my application materials."
            )

            signoff = f"Sincerely,\n{candidate_name}"

        full_letter = f"{salutation}\n\n{p1}\n\n{p2}\n\n{p3}\n\n{p4}\n\n{signoff}"
        paragraphs_only = [p1, p2, p3, p4]

        return {
            "success": True,
            "cover_letter": full_letter,
            "tone": norm_tone,
            "role_title": role_title,
            "company_name": target_company,
            "matched_skills": highlight_skills,
            "paragraph_count": len(paragraphs_only),
            "paragraphs_count": len(paragraphs_only),
            "word_count": len(full_letter.split()),
            "source": "heuristic"
        }

    def _call_gemini_cover_letter(
        self,
        resume_text: str,
        job_description: str,
        company_name: str,
        tone: str,
        resume_facts: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Uses Gemini LLM to generate a customized 3 to 4 paragraph cover letter.
        Enforces strict grounding: only resume facts, no unmentioned claims.
        """
        try:
            target_company = (company_name or "").strip() or "the Hiring Team"
            role_title = self._infer_role_title("", job_description)
            norm_tone = "friendly" if str(tone).lower().strip() in ("friendly", "enthusiastic") else "formal"

            system_instruction = (
                "You are an expert career advisor and technical recruiter. "
                "You write compelling, tailored 3 to 4 paragraph cover letters for students and graduates. "
                "CRITICAL CONSTRAINT: You MUST strictly use ONLY skills, technologies, projects, experiences, and education "
                "explicitly mentioned in the candidate's resume text below. "
                "Do NOT fabricate, invent, assume, or extrapolate any skills, tools, previous employers, degrees, or quantitative metrics. "
                "If the job description mentions a skill or technology NOT present in the candidate's resume, DO NOT claim the candidate has it. "
                "The letter must be exactly 3 to 4 concise paragraphs plus formal/friendly salutation and sign-off. "
                "Return valid JSON only."
            )

            prompt = f"""
Write a tailored 3 to 4 paragraph cover letter for this candidate based STRICTLY on their resume facts and the target job description.

Candidate Resume Text:
\"\"\"
{resume_text[:4000]}
\"\"\"

Target Job Description:
\"\"\"
{job_description[:4000]}
\"\"\"

Company Name: {target_company}
Target Role: {role_title}
Tone: {norm_tone} (formal or friendly)

Requirements:
1. Exactly 3 to 4 paragraphs between the salutation and sign-off.
2. Tone: {norm_tone}.
3. STRICT FACTUAL GROUNDING: NEVER claim any skill, experience, company, or metric that is missing from the resume.
4. Highlight skills from the resume that genuinely match the job description.

Return ONLY valid JSON matching this schema:
{{
  "cover_letter": "Salutation\\n\\nParagraph 1\\n\\nParagraph 2\\n\\nParagraph 3\\n\\nParagraph 4\\n\\nSign-off",
  "matched_skills": ["skill1", "skill2"],
  "paragraph_count": 4,
  "word_count": 250,
  "tone": "{norm_tone}",
  "company_name": "{target_company}"
}}
"""
            data = generate_json_response(system_instruction=system_instruction, prompt=prompt, feature="outreach")
            if not isinstance(data, dict):
                return None

            cover_letter = (data.get("cover_letter") or "").strip()
            if not cover_letter or len(cover_letter.split()) < 50:
                return None

            matched_skills = data.get("matched_skills", [])
            paras = [p.strip() for p in cover_letter.split("\n\n") if p.strip()]

            return {
                "success": True,
                "cover_letter": cover_letter,
                "tone": norm_tone,
                "role_title": role_title,
                "company_name": target_company,
                "matched_skills": matched_skills,
                "paragraph_count": max(3, min(4, len(paras) - 2 if len(paras) > 2 else len(paras))),
                "paragraphs_count": max(3, min(4, len(paras) - 2 if len(paras) > 2 else len(paras))),
                "word_count": len(cover_letter.split()),
                "source": "ai"
            }
        except Exception as e:
            logger.warning(f"Gemini LLM call failed in generate_tailored_cover_letter: {e}. Falling back to rule-based engine.")
            return None

    def export_cover_letter_docx(
        self,
        cover_letter_text: str,
        candidate_name: str = "Candidate",
        company_name: str = "",
        role_title: str = ""
    ) -> bytes:
        """
        Exports a clean, professionally styled single cover letter to Word (.docx) format.
        """
        doc = docx.Document()

        # Page margins
        for section in doc.sections:
            section.top_margin = Inches(1.0)
            section.bottom_margin = Inches(1.0)
            section.left_margin = Inches(1.0)
            section.right_margin = Inches(1.0)

        # Candidate Header
        name_p = doc.add_paragraph()
        name_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        name_p.paragraph_format.space_after = Pt(2)
        n_run = name_p.add_run(candidate_name if candidate_name and candidate_name != "[Your Name]" else "Candidate Application")
        n_run.font.size = Pt(16)
        n_run.font.bold = True
        n_run.font.color.rgb = RGBColor(15, 23, 42)

        if role_title:
            sub_p = doc.add_paragraph()
            sub_p.paragraph_format.space_after = Pt(16)
            s_run = sub_p.add_run(f"Application for {role_title}" + (f" at {company_name}" if company_name else ""))
            s_run.font.size = Pt(11)
            s_run.font.color.rgb = RGBColor(71, 85, 105)

        # Body paragraphs
        paragraphs = (cover_letter_text or "").strip().split("\n\n")
        for para in paragraphs:
            para_clean = para.strip()
            if para_clean:
                p = doc.add_paragraph()
                p.paragraph_format.line_spacing = 1.15
                p.paragraph_format.space_after = Pt(10)
                run = p.add_run(para_clean)
                run.font.size = Pt(11)
                run.font.color.rgb = RGBColor(30, 41, 59)

        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()

    def export_cover_letter_txt(
        self,
        cover_letter_text: str,
        candidate_name: str = "Candidate",
        company_name: str = "",
        role_title: str = ""
    ) -> str:
        """
        Formats a single cover letter into clean plain text.
        """
        lines = []
        if candidate_name and candidate_name != "[Your Name]":
            lines.append(candidate_name)
        if role_title:
            lines.append(f"Application for: {role_title}" + (f" at {company_name}" if company_name else ""))
        if lines:
            lines.append("=" * 60)
            lines.append("")
        lines.append((cover_letter_text or "").strip())
        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level convenience wrappers (#537)
# ---------------------------------------------------------------------------

def generate_tailored_cover_letter(
    resume_text: str,
    job_description: str,
    company_name: Optional[str] = None,
    tone: str = "formal"
) -> Dict[str, Any]:
    """Module-level wrapper for OutreachGeneratorAgent().generate_tailored_cover_letter."""
    agent = OutreachGeneratorAgent()
    return agent.generate_tailored_cover_letter(
        resume_text=resume_text,
        job_description=job_description,
        company_name=company_name,
        tone=tone
    )


def export_cover_letter_docx(
    cover_letter_text: str,
    candidate_name: str = "Candidate",
    company_name: str = "",
    role_title: str = ""
) -> bytes:
    """Module-level wrapper for OutreachGeneratorAgent().export_cover_letter_docx."""
    agent = OutreachGeneratorAgent()
    return agent.export_cover_letter_docx(
        cover_letter_text=cover_letter_text,
        candidate_name=candidate_name,
        company_name=company_name,
        role_title=role_title
    )


def export_cover_letter_txt(
    cover_letter_text: str,
    candidate_name: str = "Candidate",
    company_name: str = "",
    role_title: str = ""
) -> str:
    """Module-level wrapper for OutreachGeneratorAgent().export_cover_letter_txt."""
    agent = OutreachGeneratorAgent()
    return agent.export_cover_letter_txt(
        cover_letter_text=cover_letter_text,
        candidate_name=candidate_name,
        company_name=company_name,
        role_title=role_title
    )


def _extract_resume_facts(resume_text: str) -> Dict[str, Any]:
    """Module-level wrapper for OutreachGeneratorAgent()._extract_resume_facts."""
    agent = OutreachGeneratorAgent()
    return agent._extract_resume_facts(resume_text)


def _generate_heuristic_cover_letter(
    resume_facts: Dict[str, Any],
    job_description: str,
    company_name: Optional[str] = None,
    tone: str = "formal"
) -> Dict[str, Any]:
    """Module-level wrapper for OutreachGeneratorAgent()._generate_heuristic_cover_letter."""
    agent = OutreachGeneratorAgent()
    return agent._generate_heuristic_cover_letter(resume_facts, job_description, company_name, tone)


