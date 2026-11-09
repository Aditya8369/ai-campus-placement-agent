"""
Bullet Optimizer Agent - Line-by-Line Resume AI Rewrite Sandbox.
Generates 3 specialized rewrite flavors: Metric-Driven (Quantified), Technical Depth, and Leadership Impact.
"""

import re
import json
import logging
from typing import Dict, Any, List, Optional

import config
import prompts
from utils.gemini import generate_json_response
from utils.prompt_security import (
    sanitize_untrusted_text,
    encapsulate_untrusted_input,
    build_secure_system_instruction,
    redact_sensitive_information,
)

logger = logging.getLogger(__name__)

# Action verb replacements for weak or passive openings
WEAK_VERB_PATTERNS = [
    (r"^(?:worked on|worked in|was responsible for|helped with|helped in|assisted with|assisted in|involved in|part of a team that|contributed to)\s+", ""),
    (r"^(?:made|did|built|created|developed|coded|wrote)\s+", ""),
    (r"^(?:responsible for|tasked with|handled|managed)\s+", "")
]

STRONG_POWER_VERBS = {
    "metric": ["Architected", "Optimized", "Scaled", "Engineered", "Accelerated", "Streamlined"],
    "technical": ["Architected", "Engineered", "Implemented", "Containerized", "Refactored", "Deployed"],
    "leadership": ["Spearheaded", "Orchestrated", "Championed", "Led", "Formulated", "Pioneered"]
}


class BulletOptimizerAgent:
    """
    Agent responsible for analyzing individual resume bullet points and offering
    targeted line-by-line rewrites across 3 distinct recruiter-preferred flavors.
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def calculate_bullet_score(bullet: str) -> int:
        """
        Calculates a baseline ATS & recruiter impact score (0-100) based on
        action verb strength, quantifiable metrics, technical density, and length.
        """
        if not bullet or not bullet.strip():
            return 20

        score = 45
        text = bullet.strip().lower()

        # Check for weak passive starters
        if any(re.search(pat[0], text) for pat in WEAK_VERB_PATTERNS):
            score -= 10

        # Check for numbers / percentages / metrics
        if re.search(r"\b\d+%\b|\b\d+x\b|\$\d+|\b\d{2,}\b|\b\d+\+\b", text):
            score += 18
        else:
            score -= 5

        # Check for strong action verbs at the start
        if re.search(r"^(?:architected|engineered|spearheaded|orchestrated|optimized|streamlined|formulated|accelerated|implemented|scaled)", text):
            score += 15

        # Check length (ideal bullet is 80 - 220 chars)
        length = len(text)
        if 80 <= length <= 220:
            score += 12
        elif length < 50:
            score -= 10

        # Technical keyword presence
        tech_indicators = ["api", "sql", "db", "cloud", "docker", "pipeline", "service", "system", "react", "python", "java", "async", "latency", "throughput"]
        found_tech = sum(1 for kw in tech_indicators if kw in text)
        score += min(15, found_tech * 5)

        return max(25, min(95, score))

    def _generate_rule_based_rewrites(
        self,
        original_bullet: str,
        company_name: str = "General",
        role_target: str = "Software Engineer",
        original_score: int = 50
    ) -> List[Dict[str, Any]]:
        """
        High-fidelity algorithmic fallback that transforms bullet points into
        3 structured flavors with power verbs and realistic metrics.
        """
        clean_text = original_bullet.strip().rstrip(".")
        # Strip common bullet prefixes like -, *, •
        clean_text = re.sub(r"^[\*\-\•\>\s]+", "", clean_text).strip()

        core_task = clean_text
        for pattern, replacement in WEAK_VERB_PATTERNS:
            core_task = re.sub(pattern, replacement, core_task, flags=re.IGNORECASE).strip()

        if not core_task:
            core_task = "high-performance full-stack web application modules"

        # Make sure first character is lowercase for smooth joining
        first_word = core_task.split()[0] if core_task.split() else "feature"
        rest_of_task = core_task

        # Identify existing technologies mentioned
        has_python = bool(re.search(r"\bpython\b", clean_text, re.I))
        has_java = bool(re.search(r"\bjava\b", clean_text, re.I))
        has_react = bool(re.search(r"\breact\b|\bfrontend\b", clean_text, re.I))
        has_sql = bool(re.search(r"\bsql\b|\bdatabase\b|\bmysql\b|\bpostgres\b", clean_text, re.I))

        tech_snippet = "REST APIs and modular microservices"
        if has_python:
            tech_snippet = "Python, FastAPI, and asynchronous workers"
        elif has_java:
            tech_snippet = "Java, Spring Boot microservices, and PostgreSQL"
        elif has_react:
            tech_snippet = "React, TypeScript, and state-managed frontend components"
        elif has_sql:
            tech_snippet = "relational PostgreSQL schemas with indexed query optimization"

        # 1. Metric-Driven (Quantified)
        metric_score_boost = 28
        metric_bullet = (
            f"Engineered and scaled {rest_of_task} using {tech_snippet}, "
            f"reducing API response latency by 38% and successfully handling 15,000+ daily transactions."
        )

        # 2. Technical Depth
        tech_score_boost = 24
        tech_bullet = (
            f"Architected modular {rest_of_task} leveraging {tech_snippet} with Docker containerization, "
            f"automated CI/CD pipelines, and 95%+ unit test coverage adhering to enterprise standards."
        )

        # 3. Leadership Impact
        lead_score_boost = 22
        lead_bullet = (
            f"Spearheaded end-to-end delivery of {rest_of_task}, orchestrating 2-week agile sprints, "
            f"conducting peer code reviews, and accelerating product milestone release by 3 weeks."
        )

        return [
            {
                "flavor": "Metric-Driven (Quantified)",
                "flavor_id": "metric",
                "tag": "Google XYZ Formula",
                "icon": "fa-chart-line",
                "badge_class": "success",
                "rewritten_bullet": metric_bullet,
                "impact_score_boost": metric_score_boost,
                "new_score": min(98, original_score + metric_score_boost),
                "action_verbs": ["Engineered", "Scaled", "Reduced"],
                "key_enhancement": "Quantifies performance gains with a 38% latency drop and 15k+ daily volume.",
                "diff_added": ["reduced API response latency by 38%", "scaled to 15,000+ transactions"]
            },
            {
                "flavor": "Technical Depth",
                "flavor_id": "technical",
                "tag": "System Architecture",
                "icon": "fa-microchip",
                "badge_class": "primary",
                "rewritten_bullet": tech_bullet,
                "impact_score_boost": tech_score_boost,
                "new_score": min(95, original_score + tech_score_boost),
                "action_verbs": ["Architected", "Containerized", "Deployed"],
                "key_enhancement": "Emphasizes containerized architecture, CI/CD automation, and test coverage.",
                "diff_added": ["Docker containerization", "automated CI/CD pipelines", "95%+ test coverage"]
            },
            {
                "flavor": "Leadership Impact",
                "flavor_id": "leadership",
                "tag": "Ownership & Delivery",
                "icon": "fa-people-group",
                "badge_class": "warning",
                "rewritten_bullet": lead_bullet,
                "impact_score_boost": lead_score_boost,
                "new_score": min(92, original_score + lead_score_boost),
                "action_verbs": ["Spearheaded", "Orchestrated", "Accelerated"],
                "key_enhancement": "Highlights proactive engineering ownership, code reviews, and rapid sprint delivery.",
                "diff_added": ["spearheaded end-to-end delivery", "conducted peer code reviews", "accelerated by 3 weeks"]
            }
        ]

    def optimize_bullet(
        self,
        original_bullet: str,
        company_name: str = "General",
        role_target: str = "Software Engineer",
        context: str = ""
    ) -> Dict[str, Any]:
        """
        Rewrites a resume bullet point into 3 distinct recruiter-grade flavors.
        Attempts Gemini AI transformation first, falling back gracefully to the rule-based optimizer.
        """
        clean_bullet = (original_bullet or "").strip()
        if not clean_bullet:
            return {
                "success": False,
                "error": "Input bullet point cannot be empty."
            }

        original_score = self.calculate_bullet_score(clean_bullet)

        # Attempt Gemini call if API key configured
        if config.GEMINI_API_KEY:
            try:
                safe_bullet = sanitize_untrusted_text(clean_bullet, max_length=1000)
                encapsulated_bullet = encapsulate_untrusted_input(safe_bullet, document_type="resume_bullet")
                user_prompt = prompts.BULLET_OPTIMIZER_PROMPT_TEMPLATE.format(
                    original_bullet=encapsulated_bullet,
                    company_name=company_name or "General",
                    role_target=role_target or "Software Engineer",
                    context=context or "Technical college project or internship experience."
                )

                response_json = generate_json_response(
                    system_instruction=build_secure_system_instruction(prompts.BULLET_OPTIMIZER_SYSTEM_INSTRUCTION),
                    prompt=user_prompt
                )
                response_json = redact_sensitive_information(response_json)

                if isinstance(response_json, dict) and "rewrites" in response_json and isinstance(response_json["rewrites"], list) and len(response_json["rewrites"]) >= 3:
                    # Enrich response with UI icons and badge classes
                    enriched_rewrites = []
                    flavor_metadata = {
                        "metric": {"icon": "fa-chart-line", "badge_class": "success", "tag": "Google XYZ Formula"},
                        "technical": {"icon": "fa-microchip", "badge_class": "primary", "tag": "System Architecture"},
                        "leadership": {"icon": "fa-people-group", "badge_class": "warning", "tag": "Ownership & Delivery"}
                    }

                    for idx, rw in enumerate(response_json["rewrites"]):
                        fid = rw.get("flavor_id", ["metric", "technical", "leadership"][idx % 3])
                        meta = flavor_metadata.get(fid, {"icon": "fa-wand-magic-sparkles", "badge_class": "info", "tag": "Optimized"})
                        boost = int(rw.get("impact_score_boost", 20))
                        enriched_rewrites.append({
                            **rw,
                            "flavor_id": fid,
                            "icon": meta["icon"],
                            "badge_class": meta["badge_class"],
                            "tag": meta["tag"],
                            "new_score": min(98, original_score + boost)
                        })

                    return {
                        "success": True,
                        "original_bullet": clean_bullet,
                        "original_score": original_score,
                        "company_name": company_name,
                        "role_target": role_target,
                        "rewrites": enriched_rewrites
                    }
            except Exception as e:
                logger.warning(f"BulletOptimizerAgent: Gemini call failed ({e}). Using algorithmic fallback.")

        # Fallback to rule-based engine
        fallback_rewrites = self._generate_rule_based_rewrites(
            original_bullet=clean_bullet,
            company_name=company_name,
            role_target=role_target,
            original_score=original_score
        )

        return {
            "success": True,
            "original_bullet": clean_bullet,
            "original_score": original_score,
            "company_name": company_name,
            "role_target": role_target,
            "rewrites": fallback_rewrites
        }

