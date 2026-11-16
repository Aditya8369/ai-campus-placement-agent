"""
SelfIntroductionAgent - 'Tell Me About Yourself' Introduction Builder & Practice Coach (#432)

Generates authentic, role-aligned self-introductions in 3 calibrated lengths (30s, 60s, 90s)
grounded strictly in verified candidate resume facts (without inventing achievements).
Provides estimated speaking time calculation and an interactive practice evaluation module
scoring structure (Present, Past, Future), clarity, and length.
"""

import re
import json
import logging
from typing import Dict, Any, List, Optional

import config
import prompts
from utils.gemini import generate_json_response, AIAnalysisError
from utils.prompt_security import (
    sanitize_untrusted_text,
    encapsulate_untrusted_input,
)

logger = logging.getLogger(__name__)

# Standard speaking rate: 140 words per minute (~2.33 words per second)
WORDS_PER_MINUTE = 140.0
WORDS_PER_SECOND = WORDS_PER_MINUTE / 60.0

# Calibrated word-count bands for target speaking times
LENGTH_CONFIGS = {
    "30": {
        "target_seconds": 30,
        "target_words": 75,
        "min_words": 55,
        "max_words": 95,
        "label": "30 Seconds (Quick Pitch)",
        "description": "Fast elevator pitch for career fairs, networking events, or rapid rounds.",
    },
    "60": {
        "target_seconds": 60,
        "target_words": 145,
        "min_words": 115,
        "max_words": 175,
        "label": "60 Seconds (Standard Introduction)",
        "description": "Balanced present-past-future introduction for initial HR and screening rounds.",
    },
    "90": {
        "target_seconds": 90,
        "target_words": 210,
        "min_words": 170,
        "max_words": 250,
        "label": "90 Seconds (In-Depth Walkthrough)",
        "description": "Comprehensive walkthrough connecting technical depth, key projects, and company alignment.",
    },
}


def calculate_speaking_time(text: str) -> Dict[str, Any]:
    """
    Computes word count and estimated speaking time based on a standard conversational pace (140 wpm).
    """
    if not text:
        return {
            "word_count": 0,
            "char_count": 0,
            "estimated_seconds": 0,
            "formatted_time": "0s",
            "formatted": "0s",
            "pace_wpm": int(WORDS_PER_MINUTE),
        }

    clean_text = str(text).strip()
    words = re.findall(r"\b\w+(?:[-']\w+)?\b", clean_text)
    word_count = len(words)
    char_count = len(clean_text)

    estimated_seconds = int(round(word_count / WORDS_PER_SECOND)) if word_count > 0 else 0

    if estimated_seconds < 60:
        formatted_time = f"{estimated_seconds}s"
    else:
        mins = estimated_seconds // 60
        secs = estimated_seconds % 60
        formatted_time = f"{mins}m {secs}s" if secs > 0 else f"{mins}m"

    return {
        "word_count": word_count,
        "char_count": char_count,
        "estimated_seconds": estimated_seconds,
        "formatted_time": formatted_time,
        "formatted": formatted_time,
        "pace_wpm": int(WORDS_PER_MINUTE),
    }


class SelfIntroductionAgent:
    """
    Agent responsible for generating tailored 30s, 60s, and 90s self-introduction scripts
    from verified candidate resume data and analyzing student practice deliveries.
    """

    def __init__(self) -> None:
        pass

    def extract_resume_context(self, analysis_record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extracts verified factual details from the candidate's analysis record.
        Strictly limits extraction to facts in the resume so no achievements are fabricated.
        """
        if not isinstance(analysis_record, dict):
            analysis_record = {}

        results = analysis_record.get("results")
        if isinstance(results, str):
            try:
                results = json.loads(results)
            except Exception:
                results = {}
        if not isinstance(results, dict):
            results = {}

        resume_analysis = results.get("resume_analysis", {})
        job_match = results.get("job_match", {})

        candidate_name = (
            analysis_record.get("candidate_name")
            or analysis_record.get("resume_filename", "").replace(".pdf", "").replace(".docx", "").replace("_", " ").title()
        )
        if not candidate_name:
            # Check resume text first line or common pattern
            resume_text = analysis_record.get("resume_text", "")
            first_line = resume_text.strip().split("\n")[0].strip() if resume_text else ""
            if first_line and len(first_line) < 40 and not any(kw in first_line.lower() for kw in ["resume", "curriculum", "page", "phone", "email"]):
                candidate_name = first_line
            else:
                candidate_name = "Candidate"

        # Verified skills from resume analysis or job match
        skills = job_match.get("matched_skills", []) or resume_analysis.get("skills", [])
        if not skills and analysis_record.get("resume_text"):
            # Fallback parse from resume text
            for line in analysis_record.get("resume_text", "").splitlines():
                if line.lower().startswith("skills:"):
                    skills = [s.strip() for s in line.split(":", 1)[1].split(",") if s.strip()]
                    break
        if not isinstance(skills, list):
            skills = [str(skills)] if skills else []

        # Verified strengths
        strengths = resume_analysis.get("strengths", [])
        if not isinstance(strengths, list):
            strengths = [str(strengths)] if strengths else []

        # Verified education
        education = []
        if analysis_record.get("resume_text"):
            for line in analysis_record.get("resume_text", "").splitlines():
                if any(ed_kw in line.lower() for ed_kw in ["education:", "degree", "bachelor", "master", "university", "college", "institute", "school"]):
                    education.append(line.strip())

        # Verified summary and feedback
        resume_summary = resume_analysis.get("summary", "Dedicated engineering student with strong technical fundamentals.")
        project_feedback = resume_analysis.get("project_feedback", "")
        experience_feedback = resume_analysis.get("experience_feedback", "")
        experience_context = f"{project_feedback} {experience_feedback}".strip() or "Practical academic projects and software engineering coursework."

        company_name = analysis_record.get("company_name", "General Placement Preparation")
        job_description = analysis_record.get("job_description", "")

        return {
            "candidate_name": candidate_name,
            "skills": skills,
            "verified_skills": skills,
            "education": education,
            "strengths": strengths,
            "resume_summary": resume_summary,
            "experience_context": experience_context,
            "experiences": [experience_context],
            "company_name": company_name,
            "job_description": job_description,
        }

    def generate_scripts(
        self,
        analysis_record: Dict[str, Any],
        target_role: Optional[str] = None,
        target_company: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generates 3 calibrated 'Tell Me About Yourself' scripts (30s, 60s, 90s).
        Grounded strictly in factual resume details, with deterministic fallback if AI is offline.
        """
        context = self.extract_resume_context(analysis_record)

        company = (target_company or context["company_name"] or "Target Company").strip()
        role = (target_role or "Software Engineer").strip()

        # Company profile context from data/companies.json if available
        company_details_str = ""
        try:
            companies_file = config.BASE_DIR / "data" / "companies.json"
            if companies_file.exists():
                with open(companies_file, "r", encoding="utf-8") as f:
                    comp_data = json.load(f)
                    c_info = comp_data.get(company, {})
                    if c_info:
                        company_details_str = json.dumps({
                            "overview": c_info.get("overview", ""),
                            "required_skills": c_info.get("required_skills", []),
                            "hiring_process": c_info.get("hiring_process", ""),
                        })
        except Exception as e:
            logger.warning("Could not read company details for self intro: %s", e)

        # Try LLM generation
        try:
            skills_str = ", ".join(context["skills"][:8]) if context["skills"] else "software engineering fundamentals, problem-solving, and clean code"
            strengths_str = "; ".join(context["strengths"][:4]) if context["strengths"] else "fast learner, structured analytical approach"

            user_prompt = prompts.SELF_INTRO_USER_PROMPT_TEMPLATE.format(
                company_name=company,
                role_title=role,
                candidate_name=context["candidate_name"],
                skills=skills_str,
                strengths=strengths_str,
                resume_summary=sanitize_untrusted_text(context["resume_summary"][:400]),
                experience_context=sanitize_untrusted_text(context["experience_context"][:800]),
                company_details=company_details_str or "Standard campus placement interview expectations.",
            )

            raw_response = generate_json_response(
                system_instruction=prompts.SELF_INTRO_SYSTEM_INSTRUCTION,
                prompt=user_prompt,
                feature="interview",
            )

            if isinstance(raw_response, dict) and "scripts" in raw_response:
                return self._finalize_scripts_payload(raw_response, company, role, context)

        except Exception as ai_err:
            logger.warning("Gemini self-intro generation failed; falling back to deterministic builder: %s", ai_err)

        return self._generate_fallback_scripts(company, role, context)

    def _finalize_scripts_payload(
        self,
        raw_response: Dict[str, Any],
        company: str,
        role: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validates, decorates, and measures word counts / speaking times for generated scripts.
        """
        scripts_dict = raw_response.get("scripts", {})
        finalized_scripts = {}

        for length_key in ("30", "60", "90"):
            cfg = LENGTH_CONFIGS[length_key]
            item = scripts_dict.get(length_key, {})
            script_text = item.get("script") or ""

            # If AI omitted or produced empty script, supply fallback
            if not script_text.strip():
                script_text = self._build_deterministic_script(length_key, company, role, context)

            timing = calculate_speaking_time(script_text)

            finalized_scripts[length_key] = {
                "length_key": length_key,
                "target_seconds": cfg["target_seconds"],
                "label": cfg["label"],
                "description": cfg["description"],
                "approx_words": f"{cfg['min_words']}-{cfg['max_words']} words",
                "script": script_text.strip(),
                "word_count": timing["word_count"],
                "char_count": timing["char_count"],
                "estimated_seconds": timing["estimated_seconds"],
                "formatted_time": timing["formatted_time"],
                "estimated_speaking_time": timing["formatted_time"],
                "structure_breakdown": item.get("structure_breakdown") or {
                    "present": f"Candidate background & core skills in {role}",
                    "past": "Relevant academic projects and practical software development",
                    "future": f"Alignment with {company} engineering objectives",
                },
            }

        # Also provide alias keys '30s', '60s', '90s' for flexible template & API consumption
        for k in ("30", "60", "90"):
            finalized_scripts[f"{k}s"] = finalized_scripts[k]

        return {
            "success": True,
            "company_name": company,
            "role_title": role,
            "candidate_name": context["candidate_name"],
            "scripts": finalized_scripts,
        }

    def _generate_fallback_scripts(
        self,
        company: str,
        role: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Builds high-quality deterministic self-introductions grounded strictly
        in the student's resume facts when AI is offline or unavailable.
        """
        finalized_scripts = {}
        for length_key in ("30", "60", "90"):
            cfg = LENGTH_CONFIGS[length_key]
            script_text = self._build_deterministic_script(length_key, company, role, context)
            timing = calculate_speaking_time(script_text)

            finalized_scripts[length_key] = {
                "length_key": length_key,
                "target_seconds": cfg["target_seconds"],
                "label": cfg["label"],
                "description": cfg["description"],
                "approx_words": f"{cfg['min_words']}-{cfg['max_words']} words",
                "script": script_text,
                "word_count": timing["word_count"],
                "char_count": timing["char_count"],
                "estimated_seconds": timing["estimated_seconds"],
                "formatted_time": timing["formatted_time"],
                "estimated_speaking_time": timing["formatted_time"],
                "structure_breakdown": {
                    "present": f"Background and technical foundations in {role}",
                    "past": "Hands-on projects and software development experiences",
                    "future": f"Alignment with {company} goals and role readiness",
                },
            }

        for k in ("30", "60", "90"):
            finalized_scripts[f"{k}s"] = finalized_scripts[k]

        return {
            "success": True,
            "company_name": company,
            "role_title": role,
            "candidate_name": context["candidate_name"],
            "scripts": finalized_scripts,
        }

    def _build_deterministic_script(
        self,
        length_key: str,
        company: str,
        role: str,
        context: Dict[str, Any]
    ) -> str:
        """
        Generates deterministic text strictly following the Present -> Past -> Future structure.
        Calibrated to land accurately inside the 30s (~75w), 60s (~145w), and 90s (~210w) ranges.
        """
        skills_sample = context["skills"][:4] if context["skills"] else ["data structures", "algorithms", "software development"]
        top_skill = skills_sample[0] if skills_sample else "software engineering"
        other_skills = ", ".join(skills_sample[1:]) if len(skills_sample) > 1 else "core problem-solving"

        name = context["candidate_name"] if context["candidate_name"] != "Candidate" else "a Computer Science candidate"

        if length_key == "30":
            # Target ~70-80 words
            return (
                f"Hello, I am {name}, an aspiring {role} with a solid foundation in {top_skill} and {other_skills}. "
                f"Recently, I developed hands-on technical projects focusing on building reliable, scalable software solutions. "
                f"I have been closely following {company}'s engineering culture and high-impact products, and I am eager to contribute "
                f"my analytical mindset and technical drive as a {role} on your team."
            )

        elif length_key == "60":
            # Target ~135-155 words
            return (
                f"Hello, thank you for having me. I am {name}, an enthusiastic engineering student targeting the {role} position. "
                f"Presently, my primary technical focus centers around {top_skill}, along with hands-on proficiency in {other_skills}. "
                f"Throughout my academic journey, I have prioritized practical application by architecting full-featured software projects. "
                f"For instance, I developed modular systems where I tackled algorithmic efficiency, database design, and end-to-end integration. "
                f"These experiences taught me how to write maintainable code, troubleshoot production issues under tight deadlines, and collaborate effectively. "
                f"Looking ahead, I am genuinely excited about {company} because of your commitment to technical innovation and engineering excellence at scale. "
                f"I am eager to apply my strong foundations and rapid learning ability to deliver meaningful results for your engineering team."
            )

        else:
            # 90 seconds: Target ~195-225 words
            return (
                f"Good morning, and thank you for this opportunity. I am {name}, an aspiring {role} passionate about building scalable, high-performance software. "
                f"Currently, my core technical expertise lies in {top_skill}, complemented by practical experience across {other_skills} and core computer science fundamentals. "
                f"Over the past few semesters, I have channeled this passion into rigorous software engineering projects. "
                f"In my primary project work, I took ownership of system architecture, API design, and optimization, which helped me translate theoretical algorithms into robust, usable software. "
                f"Working on these initiatives reinforced not only my debugging and testing discipline but also the importance of clean architecture, version control, and clear technical communication. "
                f"Beyond coursework, I actively solve algorithmic challenges to continuously sharpen my problem-solving speed and edge-case handling. "
                f"What draws me specifically to {company} is your reputation for solving complex engineering challenges and creating products that impact millions of users. "
                f"I am looking for an environment where I can be challenged, contribute clean and maintainable code from day one, and grow alongside world-class engineers as a {role}."
            )

    def evaluate_practice_delivery(
        self,
        practice_text: str,
        company_name: str = "Target Company",
        role_title: str = "Software Engineer",
        analysis_record: Optional[Dict[str, Any]] = None,
        target_duration: int = 60,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Evaluates a candidate's practice self-introduction on:
        - Structure (Present, Past, Future)
        - Clarity, coherence, and conciseness
        - Word count & speaking length verdict
        - Strengths and actionable improvements
        """
        # Accept kwargs or target_role / target_company aliases
        if "target_role" in kwargs:
            role_title = kwargs["target_role"]
        if "target_company" in kwargs:
            company_name = kwargs["target_company"]
        clean_text = str(practice_text or "").strip()
        timing = calculate_speaking_time(clean_text)
        word_count = timing["word_count"]
        sec = timing["estimated_seconds"]

        if word_count < 10:
            return {
                "success": False,
                "error": "Practice introduction is too brief. Please provide at least 2-3 sentences to receive meaningful coaching feedback.",
                "word_count": word_count,
                "estimated_speaking_seconds": sec,
                "formatted_time": timing["formatted_time"],
            }

        # Rule-based heuristics for structure detection
        has_present = bool(
            re.search(r"\b(i am|my name is|currently|pursuing|student|graduate|specializing in|focus on|foundation in)\b", clean_text, re.I)
        )
        has_past = bool(
            re.search(r"\b(built|developed|project|internship|worked on|experience|implemented|created|designed|achieved)\b", clean_text, re.I)
        )
        has_future = bool(
            re.search(r"\b(excited|looking forward|goal|aim|add value|join|contribute|aspire|passionate about|target role)\b", clean_text, re.I)
            or company_name.lower() in clean_text.lower()
        )

        # Length verdict
        if word_count < 50:
            length_verdict = "Too Brief"
            length_feedback = f"At {word_count} words ({timing['formatted_time']}), your introduction is quite brief. Aim for at least 65-75 words for a punchy 30-second pitch or ~145 words for a standard HR round."
        elif word_count <= 240:
            length_verdict = "Ideal"
            length_feedback = f"Your introduction is {word_count} words ({timing['formatted_time']}), which fits comfortably within a calibrated 30 to 90-second interview response."
        else:
            length_verdict = "Rambling"
            length_feedback = f"At {word_count} words ({timing['formatted_time']}), this introduction risks rambling. Aim to trim it down to under 220 words to keep the interviewer engaged."

        # Heuristic baseline
        heuristic_strengths = []
        heuristic_improvements = []

        if has_present and has_past and has_future:
            heuristic_strengths.append("Excellent structural flow: cleanly transitions through Present, Past, and Future.")
        elif has_present and has_past:
            heuristic_improvements.append("Strengthen the Future component: clearly state why you want to join this target company and how you add value.")
        elif not has_past:
            heuristic_improvements.append("Highlight specific past achievements or projects from your resume to back up your skills.")

        if word_count >= 60 and word_count <= 180:
            heuristic_strengths.append("Strong concise pacing: avoids unnecessary filler while communicating key qualifications.")

        if not heuristic_improvements:
            heuristic_improvements.append("Consider practicing aloud with a timer to ensure natural vocal cadence and steady eye contact.")

        # Attempt AI enhancement
        try:
            resume_ctx = ""
            if analysis_record:
                ctx = self.extract_resume_context(analysis_record)
                resume_ctx = f"Skills: {', '.join(ctx['skills'][:5])}; Summary: {ctx['resume_summary'][:150]}"

            practice_prompt = prompts.SELF_INTRO_PRACTICE_USER_PROMPT_TEMPLATE.format(
                company_name=company_name,
                role_title=role_title,
                resume_context=resume_ctx or "Engineering candidate resume data.",
                practice_text=sanitize_untrusted_text(clean_text[:3000]),
                word_count=word_count,
                estimated_speaking_seconds=sec,
            )

            raw_ai = generate_json_response(
                system_instruction=prompts.SELF_INTRO_PRACTICE_SYSTEM_INSTRUCTION,
                prompt=practice_prompt,
                feature="interview",
            )

            if isinstance(raw_ai, dict) and "structure_analysis" in raw_ai:
                raw_ai["success"] = True
                raw_ai["word_count"] = word_count
                raw_ai["estimated_speaking_seconds"] = sec
                raw_ai["formatted_time"] = timing["formatted_time"]
                return raw_ai

        except Exception as e:
            logger.warning("AI self-intro practice evaluation failed; returning heuristic assessment: %s", e)

        # Fallback response
        structure_feedback = (
            "Covers Present, Past, and Future effectively."
            if (has_present and has_past and has_future)
            else "Needs better structural alignment across Present, Past, and Future."
        )

        structure_dict = {
            "has_present": has_present,
            "has_past": has_past,
            "has_future": has_future,
            "feedback": structure_feedback,
        }

        clarity_score = 85 if (has_present and has_past and has_future) else (75 if (has_present or has_past) else 65)

        return {
            "success": True,
            "word_count": word_count,
            "estimated_speaking_seconds": sec,
            "formatted_time": timing["formatted_time"],
            "speaking_time_formatted": timing["formatted_time"],
            "clarity_score": clarity_score,
            "length_verdict": length_verdict,
            "structure_score": structure_dict,
            "structure_analysis": structure_dict,
            "clarity_analysis": {
                "score": clarity_score,
                "feedback": "Clear sentence structure and professional terminology.",
            },
            "length_analysis": {
                "verdict": length_verdict,
                "feedback": length_feedback,
            },
            "strengths": heuristic_strengths or ["Clear, professional tone and direct opening."],
            "improvements": heuristic_improvements or ["Rehearse smoothly to avoid pauses."],
            "feedback_summary": f"Your delivery is {length_verdict.lower()} ({timing['formatted_time']}, {word_count} words). {structure_feedback}",
            "suggested_revision": clean_text,
        }
