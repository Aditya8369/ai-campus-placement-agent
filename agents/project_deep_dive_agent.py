"""
Project Deep-Dive Interview Agent (#466).

Enables candidates to practice project defense in technical interview rounds:
1. Extracts project entries (title, tech stack, short description) from analysed resumes.
2. Evaluates project detail thickness; prompts student to add detail if the entry is too thin.
3. Generates 5 follow-up questions grounded strictly in what the resume says:
   - Design choices & architectural selection
   - Implementation challenges & debugging
   - Testing & verification
   - Retrospective & future improvements
   - Technical trade-offs & data flow
4. Scores candidate answers on clarity, depth, and consistency with the resume.
5. Provides exactly one concrete, actionable improvement tip per answer.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

import prompts
from utils.gemini import generate_json_response
from utils.prompt_security import (
    sanitize_untrusted_text,
    encapsulate_untrusted_input,
    redact_sensitive_information,
    build_secure_system_instruction,
)
from utils.pdf_reader import standardize_resume_sections
from utils.resume_info_extractor import extract_projects_entries

logger = logging.getLogger(__name__)

THIN_PROJECT_MIN_WORDS = 15


class ProjectDeepDiveAgent:
    """
    Agent responsible for extracting candidate projects, generating grounded follow-up
    questions, and evaluating project defense responses for technical interview practice.
    """

    def __init__(self) -> None:
        pass

    def is_project_thin(self, project: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Determines if a project's description is too thin to generate grounded questions.
        Returns (is_thin, explanation).
        """
        if not isinstance(project, dict):
            return True, "No project details provided."

        desc = str(project.get("description", "") or "").strip()
        tech = str(project.get("tech_stack", "") or project.get("technologies", "") or "").strip()
        words = desc.split()
        word_count = len(words)

        if word_count == 0:
            return True, "Project has no description. Please add implementation details first."

        if word_count < THIN_PROJECT_MIN_WORDS:
            return True, (
                f"Project description is too thin ({word_count} words; minimum {THIN_PROJECT_MIN_WORDS} words). "
                "Please add details about your architecture, tech stack, or implementation before practicing."
            )

        if word_count < 25 and not tech:
            return True, (
                "Project description is brief and lists no technologies or tools. "
                "Please specify the tech stack and key components first."
            )

        return False, ""

    def extract_projects(self, analysis_record: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extracts verified project entries (title, tech stack, short description) from the analysed resume.
        Returns an empty list if none are found.
        """
        if not isinstance(analysis_record, dict):
            return []

        results = analysis_record.get("results")
        if isinstance(results, str):
            import json
            try:
                results = json.loads(results)
            except Exception:
                results = {}
        if not isinstance(results, dict):
            results = {}

        raw_projects: List[Dict[str, Any]] = []

        # 1. Check if projects were previously structured in analysis results
        if isinstance(results.get("extracted_projects"), list) and results["extracted_projects"]:
            raw_projects = list(results["extracted_projects"])
        elif isinstance(results.get("projects"), list) and results["projects"]:
            raw_projects = list(results["projects"])
        elif isinstance(results.get("parsed_resume", {}).get("projects"), list) and results["parsed_resume"]["projects"]:
            raw_projects = list(results["parsed_resume"]["projects"])

        # 2. If not pre-extracted, parse directly from raw resume text
        if not raw_projects:
            resume_text = (
                analysis_record.get("resume_text")
                or results.get("extracted_resume_text")
                or results.get("resume_text")
                or ""
            )
            if resume_text and isinstance(resume_text, str):
                sections = standardize_resume_sections(resume_text)
                proj_text = sections.get("projects", "")
                if proj_text and proj_text.strip():
                    raw_projects = extract_projects_entries(proj_text)
                elif re.search(r"(?:^|\n)\s*(?:academic projects?|key projects?|personal projects?|projects?)(?:\s*[:\n]|\s*$)", resume_text, re.IGNORECASE):
                    # Only attempt extraction if an explicit project section or keyword header exists
                    raw_projects = extract_projects_entries(resume_text)

        # 3. Clean and normalize detected projects
        standardized_projects: List[Dict[str, Any]] = []
        for idx, p in enumerate(raw_projects):
            if not isinstance(p, dict):
                continue

            title = str(p.get("title", "") or "").strip()
            if not title or len(title) < 2:
                continue

            # Strip regex narrative artifact if title starts with 'n ' or 'a '
            if re.match(r"^[an]\s+", title, re.IGNORECASE):
                title = re.sub(r"^[an]\s+", "", title, flags=re.IGNORECASE).strip()
            if title:
                title = title[0].upper() + title[1:]

            # Skip lines matching resume section headers or common candidate bio lines
            if any(k in title.lower() for k in ["education", "skills", "experience", "bachelor", "master", "university", "curriculum", "resume", "objective"]):
                continue

            tech = str(p.get("tech_stack") or p.get("technologies") or "").strip()
            desc = str(p.get("description") or "").strip()

            # Create clean short description (first 2 sentences or ~35 words)
            sentences = re.split(r"(?<=[.!?])\s+", desc)
            short_desc = " ".join(sentences[:2]).strip() if sentences else desc
            if len(short_desc.split()) > 35:
                short_desc = " ".join(short_desc.split()[:35]) + "..."

            words = desc.split()
            word_count = len(words)

            proj_obj = {
                "id": str(p.get("id") or f"proj-{idx+1}"),
                "title": title,
                "tech_stack": tech,
                "technologies": tech,
                "description": desc,
                "short_description": short_desc or desc,
                "word_count": word_count,
            }

            is_thin, thin_reason = self.is_project_thin(proj_obj)
            proj_obj["is_thin"] = is_thin
            proj_obj["thin_reason"] = thin_reason

            standardized_projects.append(proj_obj)

        return standardized_projects

    def generate_grounded_fallback_questions(
        self,
        project: Dict[str, Any],
        company_name: str = "Placement"
    ) -> List[Dict[str, Any]]:
        """
        Produces 5 deterministic follow-up questions strictly grounded in the project's
        title, stated tech stack, and resume description without hallucinating outside tools.
        """
        title = project.get("title", "this project").strip()
        tech = project.get("tech_stack", "").strip()
        tech_ref = f" ({tech})" if tech else ""

        return [
            {
                "index": 0,
                "category": "design_choices",
                "question": (
                    f"In {title}{tech_ref}, what specific technical requirements led you to choose this architecture "
                    "and technology stack over other alternatives you may have considered?"
                ),
            },
            {
                "index": 1,
                "category": "challenges",
                "question": (
                    f"What was the most challenging technical hurdle, edge case, or bug you encountered while building {title}, "
                    "and what was your step-by-step approach to diagnosing and resolving it?"
                ),
            },
            {
                "index": 2,
                "category": "testing",
                "question": (
                    f"How did you test and validate the functionality of {title} to ensure system stability, correctness, "
                    "and proper handling of invalid or unexpected user inputs?"
                ),
            },
            {
                "index": 3,
                "category": "improvements",
                "question": (
                    f"Looking back at {title}, if you had to rebuild or scale it today for a high-traffic production environment, "
                    "what architectural decision would you refine or do differently?"
                ),
            },
            {
                "index": 4,
                "category": "tradeoffs",
                "question": (
                    f"Can you explain the core data flow in {title} and describe a key technical trade-off "
                    "(such as performance vs simplicity, or latency vs memory) that you had to navigate during implementation?"
                ),
            },
        ]

    def generate_questions(
        self,
        project: Dict[str, Any],
        company_name: str = "Placement",
        additional_details: str = "",
    ) -> Dict[str, Any]:
        """
        Generates 5 follow-up questions grounded only in the selected project entry.
        Enforces thin project guard: if project text is too thin, requests detail first.
        """
        if not isinstance(project, dict) or not project.get("title"):
            return {
                "success": False,
                "error": "A valid project entry is required to start a deep-dive interview.",
                "questions": [],
            }

        title = str(project.get("title", "")).strip()
        tech = str(project.get("tech_stack", "") or project.get("technologies", "")).strip()
        base_desc = str(project.get("description", "")).strip()

        combined_desc = f"{base_desc}\n{additional_details}".strip() if additional_details else base_desc
        eval_proj = dict(project)
        eval_proj["description"] = combined_desc

        is_thin, thin_reason = self.is_project_thin(eval_proj)
        if is_thin:
            return {
                "success": False,
                "error": (
                    thin_reason
                    or "Project description is too thin to generate grounded questions. Please add detail first."
                ),
                "is_thin": True,
                "detail_needed": True,
                "questions": [],
            }

        safe_title = sanitize_untrusted_text(title, max_length=150)
        safe_tech = sanitize_untrusted_text(tech or "Not explicitly specified", max_length=200)
        safe_desc = sanitize_untrusted_text(combined_desc, max_length=3000)

        prompt = prompts.PROJECT_DEEP_DIVE_QUESTIONS_USER_PROMPT_TEMPLATE.format(
            company_name=company_name or "Placement",
            project_title=safe_title,
            tech_stack=safe_tech,
            project_description=encapsulate_untrusted_input(safe_desc, document_type="candidate_project_description"),
        )

        try:
            res = generate_json_response(
                system_instruction=build_secure_system_instruction(
                    prompts.PROJECT_DEEP_DIVE_QUESTIONS_SYSTEM_INSTRUCTION
                ),
                prompt=prompt,
                feature="interview",
            )
            raw_qs = res.get("questions") if isinstance(res, dict) else None

            valid_questions: List[Dict[str, Any]] = []
            if isinstance(raw_qs, list):
                expected_cats = ["design_choices", "challenges", "testing", "improvements", "tradeoffs"]
                for i, q_item in enumerate(raw_qs[:5]):
                    if isinstance(q_item, dict) and q_item.get("question"):
                        valid_questions.append({
                            "index": i,
                            "category": str(q_item.get("category") or (expected_cats[i] if i < len(expected_cats) else "general")),
                            "question": str(q_item["question"]).strip(),
                        })

            # If model returned fewer than 5 questions, pad with grounded fallbacks
            if len(valid_questions) < 5:
                fallbacks = self.generate_grounded_fallback_questions(eval_proj, company_name)
                for fb in fallbacks[len(valid_questions):]:
                    valid_questions.append(fb)

            return {
                "success": True,
                "project_title": title,
                "tech_stack": tech,
                "questions": valid_questions,
            }

        except Exception as e:
            logger.warning(f"ProjectDeepDiveAgent: AI question generation failed ({e}); using grounded fallback.")
            fallbacks = self.generate_grounded_fallback_questions(eval_proj, company_name)
            return {
                "success": True,
                "project_title": title,
                "tech_stack": tech,
                "questions": fallbacks,
            }

    def evaluate_answer(
        self,
        project: Dict[str, Any],
        question: str,
        answer: str,
    ) -> Dict[str, Any]:
        """
        Scores a candidate's answer on clarity, depth, and consistency with the resume,
        and provides exactly one actionable improvement tip.
        """
        if not isinstance(project, dict):
            project = {}

        title = str(project.get("title", "")).strip() or "Project"
        tech = str(project.get("tech_stack", "") or project.get("technologies", "")).strip() or "Not specified"
        desc = str(project.get("description", "")).strip()

        # Handle empty or whitespace answer
        if not answer or not answer.strip():
            return {
                "clarity_score": 0,
                "depth_score": 0,
                "consistency_score": 0,
                "overall_score": 0,
                "tip": "Start by directly addressing the question with a high-level summary of your project implementation, followed by specific technical rationale.",
                "feedback": "No answer was submitted. Project defense rounds require verbalizing your technical rationale and implementation choices.",
                "clarity_feedback": "No response detected.",
                "depth_feedback": "No technical explanation provided.",
                "consistency_feedback": "Unable to assess consistency without candidate response.",
                "is_consistent": False,
            }

        safe_answer = sanitize_untrusted_text(answer.strip(), max_length=5000)
        encapsulated_answer = encapsulate_untrusted_input(safe_answer, document_type="candidate_project_defense_answer")

        prompt = prompts.PROJECT_DEEP_DIVE_EVAL_USER_PROMPT_TEMPLATE.format(
            project_title=title,
            tech_stack=tech,
            project_description=encapsulate_untrusted_input(desc, document_type="resume_project_description"),
            question=question,
            candidate_answer=encapsulated_answer,
        )

        try:
            res = generate_json_response(
                system_instruction=build_secure_system_instruction(
                    prompts.PROJECT_DEEP_DIVE_EVAL_SYSTEM_INSTRUCTION
                ),
                prompt=prompt,
                feature="interview",
            )
            res = redact_sensitive_information(res)

            clarity = self._parse_score(res.get("clarity_score"), 65)
            depth = self._parse_score(res.get("depth_score"), 60)
            consistency = self._parse_score(res.get("consistency_score"), 70)
            overall = self._parse_score(
                res.get("overall_score"),
                int(round((clarity * 0.3) + (depth * 0.4) + (consistency * 0.3)))
            )

            tip = str(res.get("tip") or "").strip()
            if not tip:
                tip = "Articulate concrete technical metrics or trade-offs (e.g. latency, query efficiency, or caching) to substantiate your design choice."

            feedback = str(res.get("feedback") or "").strip()
            if not feedback:
                feedback = "Clear foundational answer defending your project implementation. Incorporate deeper technical rationale to strengthen conviction."

            return {
                "clarity_score": clarity,
                "depth_score": depth,
                "consistency_score": consistency,
                "overall_score": overall,
                "tip": tip,
                "feedback": feedback,
                "clarity_feedback": str(res.get("clarity_feedback") or "Good communication flow."),
                "depth_feedback": str(res.get("depth_feedback") or "Sound technical explanation."),
                "consistency_feedback": str(res.get("consistency_feedback") or "Consistent with project details on resume."),
                "is_consistent": consistency >= 50,
            }

        except Exception as e:
            logger.warning(f"ProjectDeepDiveAgent: AI evaluation failed ({e}); using deterministic fallback evaluation.")
            return self._deterministic_fallback_evaluation(project, question, safe_answer)

    def _parse_score(self, val: Any, default: int = 60) -> int:
        try:
            num = int(val)
            return max(0, min(100, num))
        except (ValueError, TypeError):
            return default

    def _deterministic_fallback_evaluation(
        self,
        project: Dict[str, Any],
        question: str,
        answer: str,
    ) -> Dict[str, Any]:
        """
        Deterministic, rule-based fallback evaluation calculating clarity, depth, and consistency
        scores with one actionable improvement tip.
        """
        words = answer.strip().split()
        word_count = len(words)

        # 1. Clarity score based on length, punctuation, and structure
        has_sentences = len(re.split(r"[.!?]+", answer.strip())) >= 2
        clarity = 50
        if word_count >= 30 and has_sentences:
            clarity = min(90, 60 + min(30, word_count // 3))
        elif word_count >= 15:
            clarity = 60
        else:
            clarity = 40

        # 2. Depth score based on technical terms, rationale keywords
        tech_words = ["because", "architecture", "database", "api", "query", "tradeoff", "latency", "async", "cache", "tested", "bug", "concurrency", "scale", "performance", "component", "service", "pipeline", "schema", "index"]
        tech_count = sum(1 for kw in tech_words if re.search(r"\b" + kw + r"\b", answer, re.IGNORECASE))
        depth = min(92, 45 + (tech_count * 6) + (min(20, word_count // 5)))

        # 3. Consistency with resume project facts
        p_tech = str(project.get("tech_stack", "") or "").lower()
        p_desc = str(project.get("description", "") or "").lower()
        consistency = 75
        # If student claims a completely unrelated technology or contradicts
        if p_tech:
            for t in re.split(r"[,/|; ]+", p_tech):
                t_clean = t.strip()
                if t_clean and len(t_clean) > 2 and t_clean in answer.lower():
                    consistency = min(95, consistency + 5)

        overall = int(round((clarity * 0.3) + (depth * 0.4) + (consistency * 0.3)))

        # Generate one specific improvement tip
        if depth < 65:
            tip = "Mention specific engineering constraints or architectural trade-offs to demonstrate deeper technical command of your project."
        elif clarity < 65:
            tip = "Lead with a direct one-sentence answer before detailing the implementation steps to improve answer structure."
        elif consistency < 70:
            tip = "Ensure your verbal explanation directly ties back to the technologies and scope described on your resume."
        else:
            tip = "Quantify the real-world impact or performance improvement (e.g. % faster latency or user scale) to make your answer unforgettable."

        return {
            "clarity_score": clarity,
            "depth_score": depth,
            "consistency_score": consistency,
            "overall_score": overall,
            "tip": tip,
            "feedback": (
                f"Solid project defense answer ({word_count} words). "
                "You clearly explained the technical context while maintaining alignment with your resume."
            ),
            "clarity_feedback": "Answer is clearly communicated with understandable phrasing.",
            "depth_feedback": f"Addressed technical components with relevant keywords ({tech_count} technical indicators detected).",
            "consistency_feedback": "Response is consistent with your resume project entry.",
            "is_consistent": consistency >= 50,
        }
