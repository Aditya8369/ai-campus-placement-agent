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

logger = logging.getLogger(__name__)

VALID_TONES = ["formal", "enthusiastic", "concise"]
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

            prompt = prompts.OUTREACH_USER_PROMPT_TEMPLATE.format(
                company_name=company_name,
                role_title=inferred_role,
                tone=norm_tone,
                company_details=company_details_str or f"Hiring for engineering and technical positions at {company_name}.",
                job_description=job_description or f"Engineering position at {company_name}.",
                matched_skills=", ".join(matched_skills[:8]) if matched_skills else "Python, Problem Solving, Data Structures",
                strengths=", ".join(strengths[:4]) if strengths else "Strong fundamentals, analytical mindset",
                resume_summary=resume_summary,
                ats_score=ats_score,
                experience_context=experience_context[:600]
            )

            raw_outreach = generate_json_response(
                prompt=prompt,
                system_instruction=prompts.OUTREACH_SYSTEM_INSTRUCTION
            )

            validated = self._validate_and_sanitize_outreach(
                raw_outreach,
                company_name=company_name,
                role_title=inferred_role,
                tone=norm_tone,
                matched_skills=matched_skills
            )
            if validated:
                return validated

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

        elif tone == "enthusiastic":
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

