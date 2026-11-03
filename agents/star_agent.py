"""
AI Behavioral STAR Story Coach & Non-Verbal Composure Analyzer

Dissects candidate interview responses into the STAR framework (Situation, Task, Action, Result),
evaluates verbal speech indicators (clarity, conciseness, filler words, cadence),
and assesses non-verbal composure (eye contact ratio, head steadiness, confidence).
"""

import re
import json
import logging
from typing import Dict, Any, List, Optional

import prompts
from utils.gemini import generate_json_response

logger = logging.getLogger(__name__)

# Common filler words and verbal pauses to identify
FILLER_PATTERNS = [
    re.compile(r"\b(um+)\b", re.IGNORECASE),
    re.compile(r"\b(uh+)\b", re.IGNORECASE),
    re.compile(r"\b(like)\b", re.IGNORECASE),
    re.compile(r"\b(you know)\b", re.IGNORECASE),
    re.compile(r"\b(actually)\b", re.IGNORECASE),
    re.compile(r"\b(basically)\b", re.IGNORECASE),
    re.compile(r"\b(literally)\b", re.IGNORECASE),
    re.compile(r"\b(sort of|kind of)\b", re.IGNORECASE),
    re.compile(r"\b(i mean)\b", re.IGNORECASE),
    re.compile(r"\b(so yeah)\b", re.IGNORECASE),
]

# Indicator keywords for STAR component segmentation
SITUATION_REGEX = re.compile(
    r"\b(when I was|at my|during my|in my|the context was|our team was|we were facing|at university|in college|while working on)\b",
    re.IGNORECASE,
)
TASK_REGEX = re.compile(
    r"\b(my task was|my responsibility was|I was tasked with|the goal was|I needed to|we had to|the challenge was|my role was|the objective was)\b",
    re.IGNORECASE,
)
ACTION_REGEX = re.compile(
    r"\b(I implemented|I resolved|I designed|I built|I took the initiative|I stepped in|I organized|I refactored|I analyzed|I decided to|I investigated|I collaborated|I initiated|I developed)\b",
    re.IGNORECASE,
)
RESULT_REGEX = re.compile(
    r"\b(as a result|we achieved|improved by|reduced by|successfully delivered|the outcome was|the project won|increased by|ultimately|in the end|which resulted in|learned that|saved)\b",
    re.IGNORECASE,
)


class StarEvaluationAgent:
    """
    Evaluates behavioral and HR interview responses using the STAR method,
    combining structured LLM extraction with client-side speech and composure telemetry.
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def parse_score(value: Any, default: int = 50) -> int:
        """
        Parses score into an integer clamped between 0 and 100.
        """
        if value is None:
            return default
        if isinstance(value, (int, float)):
            try:
                return max(0, min(100, int(round(value))))
            except (ValueError, OverflowError):
                return default
        try:
            val_str = str(value).strip().rstrip("%").strip()
            if "/" in val_str:
                num, denom = val_str.split("/", 1)
                return max(0, min(100, int(round((float(num) / float(denom)) * 100))))
            return max(0, min(100, int(round(float(val_str)))))
        except (ValueError, TypeError, ZeroDivisionError):
            return default

    def detect_fillers(self, text: str) -> Dict[str, Any]:
        """
        Detects filler words and counts occurrences in text.
        """
        detected: List[str] = []
        total_count = 0
        for pattern in FILLER_PATTERNS:
            matches = pattern.findall(text)
            if matches:
                detected.extend([m.lower() for m in matches])
                total_count += len(matches)

        return {
            "filler_words_detected": sorted(list(set(detected))),
            "filler_word_count": total_count,
        }

    def evaluate_star(
        self,
        question: str,
        answer: str,
        question_type: str = "Behavioral",
        speech_metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Performs a full STAR evaluation of candidate answer with verbal and non-verbal telemetry.
        """
        clean_answer = (answer or "").strip()
        speech_metrics = speech_metrics or {}

        # If answer is empty or too brief to evaluate
        words = clean_answer.split()
        word_count = len(words)
        if word_count < 10:
            return self._build_insufficient_answer_response(clean_answer, word_count, speech_metrics)

        # Attempt LLM evaluation first
        try:
            speech_metrics_str = json.dumps(speech_metrics, indent=2) if speech_metrics else "None recorded."
            user_prompt = prompts.STAR_USER_PROMPT_TEMPLATE.format(
                question_type=question_type,
                question=question,
                answer=clean_answer,
                speech_metrics_str=speech_metrics_str,
            )

            raw_json = generate_json_response(
                system_instruction=prompts.STAR_SYSTEM_INSTRUCTION,
                prompt=user_prompt,
            )

            if isinstance(raw_json, dict) and "situation" in raw_json and "action" in raw_json:
                return self._sanitize_evaluation_payload(raw_json, clean_answer, speech_metrics)
            else:
                logger.warning("StarEvaluationAgent: LLM returned non-standard schema. Falling back to heuristic engine.")
        except Exception as err:
            logger.warning(f"StarEvaluationAgent: AI call failed or disabled ({err}). Using heuristic analyzer.")

        # Fallback to local heuristic engine
        return self._heuristic_star_evaluation(question, clean_answer, question_type, speech_metrics)

    def _sanitize_evaluation_payload(
        self,
        raw: Dict[str, Any],
        answer: str,
        client_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Sanitizes and normalizes the LLM evaluation response into standard typed bounds.
        """
        s_block = raw.get("situation", {})
        t_block = raw.get("task", {})
        a_block = raw.get("action", {})
        r_block = raw.get("result", {})

        s_score = self.parse_score(s_block.get("score"), 70)
        t_score = self.parse_score(t_block.get("score"), 70)
        a_score = self.parse_score(a_block.get("score"), 75)
        r_score = self.parse_score(r_block.get("score"), 70)

        # Calculate overall weighted STAR score: S: 20%, T: 20%, A: 35%, R: 25%
        weighted_score = round(0.20 * s_score + 0.20 * t_score + 0.35 * a_score + 0.25 * r_score)
        star_score = self.parse_score(raw.get("star_score"), weighted_score)

        # Verbal metrics
        verbal = raw.get("verbal_metrics", {})
        fillers = self.detect_fillers(answer)
        filler_count = verbal.get("filler_word_count", fillers["filler_word_count"])
        detected_fillers = verbal.get("filler_words_detected", fillers["filler_words_detected"])

        # Pacing
        duration_s = float(client_metrics.get("duration_seconds", 0))
        word_count = len(answer.split())
        explicit_wpm = client_metrics.get("words_per_minute")
        if explicit_wpm:
            calculated_wpm = float(explicit_wpm)
        elif duration_s > 5:
            calculated_wpm = round((word_count / duration_s) * 60, 1)
        else:
            calculated_wpm = 130.0
        
        pacing_eval = "Optimal"
        if calculated_wpm < 85:
            pacing_eval = "Too Slow"
        elif calculated_wpm > 175:
            pacing_eval = "Too Fast"

        # Non-verbal composure synthesis
        non_verbal = raw.get("non_verbal_composure", {})
        eye_ratio = float(client_metrics.get("eye_contact_ratio", 0.85))
        eye_score = self.parse_score(non_verbal.get("eye_contact_score", int(eye_ratio * 100)))
        
        eye_status = "Good Center Focus" if eye_score >= 75 else ("Intermittent Eye Contact" if eye_score >= 50 else "Looking Away Frequently")
        composure_score = self.parse_score(client_metrics.get("composure_score", non_verbal.get("composure_score", 85)))
        composure_rating = "Confident & Composed" if composure_score >= 75 else ("Moderate Nervousness" if composure_score >= 50 else "High Anxiety / Restless")

        coaching = raw.get("coaching", {})
        strengths = [str(s).strip() for s in coaching.get("strengths", []) if str(s).strip()]
        improvements = [str(i).strip() for i in coaching.get("improvements", []) if str(i).strip()]
        rewrite = str(coaching.get("suggested_star_rewrite", "")).strip()

        if not strengths:
            strengths = ["Structured explanation of candidate experience."]
        if not improvements:
            improvements = ["Quantify results with concrete business or performance metrics."]

        return {
            "star_score": star_score,
            "situation": {
                "present": bool(s_block.get("present", True)),
                "score": s_score,
                "feedback": str(s_block.get("feedback", "Context provided adequately.")),
                "excerpt": str(s_block.get("excerpt", "")),
            },
            "task": {
                "present": bool(t_block.get("present", True)),
                "score": t_score,
                "feedback": str(t_block.get("feedback", "Objective clearly framed.")),
                "excerpt": str(t_block.get("excerpt", "")),
            },
            "action": {
                "present": bool(a_block.get("present", True)),
                "score": a_score,
                "feedback": str(a_block.get("feedback", "Key initiative and execution demonstrated.")),
                "excerpt": str(a_block.get("excerpt", "")),
            },
            "result": {
                "present": bool(r_block.get("present", True)),
                "score": r_score,
                "feedback": str(r_block.get("feedback", "Outcome and learning articulated.")),
                "excerpt": str(r_block.get("excerpt", "")),
            },
            "verbal_metrics": {
                "filler_words_detected": detected_fillers,
                "filler_word_count": filler_count,
                "clarity_score": self.parse_score(verbal.get("clarity_score", 85)),
                "conciseness_score": self.parse_score(verbal.get("conciseness_score", 80)),
                "speech_pace_wpm": calculated_wpm,
                "pacing_evaluation": pacing_eval,
            },
            "non_verbal_composure": {
                "eye_contact_score": eye_score,
                "eye_contact_status": eye_status,
                "composure_score": composure_score,
                "composure_rating": composure_rating,
                "feedback": str(non_verbal.get("feedback", "Candidate maintained steady focus and calm posture.")),
            },
            "coaching": {
                "strengths": strengths,
                "improvements": improvements,
                "suggested_star_rewrite": rewrite,
            },
        }

    def _heuristic_star_evaluation(
        self,
        question: str,
        answer: str,
        question_type: str,
        client_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Deterministic rule-based STAR analysis for test and offline environments.
        """
        sentences = [s.strip() for s in re.split(r"[.!?]+", answer) if s.strip()]
        
        # Check presence of each STAR dimension
        has_s = bool(SITUATION_REGEX.search(answer)) or len(sentences) >= 1
        has_t = bool(TASK_REGEX.search(answer)) or any("task" in s.lower() or "goal" in s.lower() or "need" in s.lower() for s in sentences)
        has_a = bool(ACTION_REGEX.search(answer)) or any("i " in s.lower() for s in sentences)
        has_r = bool(RESULT_REGEX.search(answer)) or any("result" in s.lower() or "%" in s or "outcome" in s.lower() for s in sentences)

        # Calculate scores
        s_score = 85 if has_s else 40
        t_score = 85 if has_t else 45
        a_score = 90 if has_a else 50
        r_score = 85 if has_r else 35

        weighted_score = round(0.20 * s_score + 0.20 * t_score + 0.35 * a_score + 0.25 * r_score)

        # Excerpt finders
        s_excerpt = next((s for s in sentences if SITUATION_REGEX.search(s)), sentences[0] if sentences else "")
        t_excerpt = next((s for s in sentences if TASK_REGEX.search(s)), "")
        a_excerpt = next((s for s in sentences if ACTION_REGEX.search(s)), "")
        r_excerpt = next((s for s in sentences if RESULT_REGEX.search(s)), "")

        # Verbal metrics
        fillers = self.detect_fillers(answer)
        clarity = max(40, 100 - (fillers["filler_word_count"] * 5))
        conciseness = 85 if len(answer.split()) < 180 else 65

        # Pacing
        duration_s = float(client_metrics.get("duration_seconds", 0))
        explicit_wpm = client_metrics.get("words_per_minute")
        if explicit_wpm:
            calculated_wpm = float(explicit_wpm)
        elif duration_s > 5:
            calculated_wpm = round((len(answer.split()) / duration_s) * 60, 1)
        else:
            calculated_wpm = 135.0

        pacing_eval = "Optimal" if 85 <= calculated_wpm <= 175 else ("Too Fast" if calculated_wpm > 175 else "Too Slow")

        # Non-verbal composure
        eye_ratio = float(client_metrics.get("eye_contact_ratio", 0.85))
        eye_score = self.parse_score(int(eye_ratio * 100))
        eye_status = "Good Center Focus" if eye_score >= 75 else ("Intermittent Eye Contact" if eye_score >= 50 else "Looking Away Frequently")
        composure_score = self.parse_score(client_metrics.get("composure_score", 85))
        composure_rating = "Confident & Composed" if composure_score >= 75 else "Moderate Nervousness"

        strengths = []
        if has_a:
            strengths.append("Strong personal accountability and active verbs demonstrated in the Action phase.")
        if has_s:
            strengths.append("Clear context established early in the response.")
        if not strengths:
            strengths.append("Communicated thoughts in a coherent conversational flow.")

        improvements = []
        if not has_r:
            improvements.append("Strengthen your Result: quantify specific outcomes, percent improvements, or team feedback.")
        if not has_t:
            improvements.append("Clearly separate the overarching Situation from your specific assigned Task.")
        if fillers["filler_word_count"] > 2:
            improvements.append(f"Minimize filler words ({', '.join(fillers['filler_words_detected'])}) with strategic pauses.")
        if not improvements:
            improvements.append("Maintain this strong structure and continue weaving in measurable KPIs.")

        model_rewrite = (
            f"During a critical project milestone, our team experienced an unexpected bottleneck (Situation). "
            f"My specific task was to diagnose the root cause and ensure on-time delivery (Task). "
            f"I proactively restructured the workflow, implemented automated checks, and aligned stakeholders (Action). "
            f"As a result, we delivered the milestone 3 days ahead of schedule with zero defect regressions (Result)."
        )

        return {
            "star_score": weighted_score,
            "situation": {
                "present": has_s,
                "score": s_score,
                "feedback": "Context established effectively." if has_s else "Missing explicit initial context or team background.",
                "excerpt": s_excerpt,
            },
            "task": {
                "present": has_t,
                "score": t_score,
                "feedback": "Clear personal assignment described." if has_t else "Task was vague; specify the exact problem or responsibility.",
                "excerpt": t_excerpt,
            },
            "action": {
                "present": has_a,
                "score": a_score,
                "feedback": "Decisive, detailed individual actions highlighted." if has_a else "Elaborate on specific technical or interpersonal actions you took.",
                "excerpt": a_excerpt,
            },
            "result": {
                "present": has_r,
                "score": r_score,
                "feedback": "Measurable outcome and positive takeaway stated." if has_r else "Include quantified metrics, lessons learned, or project impact.",
                "excerpt": r_excerpt,
            },
            "verbal_metrics": {
                "filler_words_detected": fillers["filler_words_detected"],
                "filler_word_count": fillers["filler_word_count"],
                "clarity_score": clarity,
                "conciseness_score": conciseness,
                "speech_pace_wpm": calculated_wpm,
                "pacing_evaluation": pacing_eval,
            },
            "non_verbal_composure": {
                "eye_contact_score": eye_score,
                "eye_contact_status": eye_status,
                "composure_score": composure_score,
                "composure_rating": composure_rating,
                "feedback": "Good eye contact and steady delivery during response.",
            },
            "coaching": {
                "strengths": strengths,
                "improvements": improvements,
                "suggested_star_rewrite": model_rewrite,
            },
        }

    def _build_insufficient_answer_response(
        self,
        answer: str,
        word_count: int,
        client_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Builds a helpful guidance response when candidate's answer is too short for a full STAR story.
        """
        return {
            "star_score": 30,
            "situation": {
                "present": False,
                "score": 30,
                "feedback": "Answer is too brief to extract the background Situation.",
                "excerpt": answer,
            },
            "task": {
                "present": False,
                "score": 30,
                "feedback": "No specific task or challenge was described.",
                "excerpt": "",
            },
            "action": {
                "present": False,
                "score": 30,
                "feedback": "Explain the step-by-step actions you took to resolve the situation.",
                "excerpt": "",
            },
            "result": {
                "present": False,
                "score": 30,
                "feedback": "Provide tangible results and achievements.",
                "excerpt": "",
            },
            "verbal_metrics": {
                "filler_words_detected": [],
                "filler_word_count": 0,
                "clarity_score": 40,
                "conciseness_score": 50,
                "speech_pace_wpm": float(client_metrics.get("words_per_minute", 100)),
                "pacing_evaluation": "Too Short",
            },
            "non_verbal_composure": {
                "eye_contact_score": 50,
                "eye_contact_status": "Insufficient Sample Duration",
                "composure_score": 50,
                "composure_rating": "Incomplete",
                "feedback": "Speak for at least 30-45 seconds to generate an accurate composure rating.",
            },
            "coaching": {
                "strengths": ["Started an answer attempt."],
                "improvements": [
                    "Aim for at least 40-70 words to build a complete STAR narrative.",
                    "Include Situation, Task, Action, and Result for behavioral interview questions.",
                ],
                "suggested_star_rewrite": (
                    "When working on our semester capstone project (Situation), our server crashed during high load (Task). "
                    "I implemented database connection pooling and optimized SQL queries (Action). "
                    "This improved latency by 60% and supported 500 concurrent users (Result)."
                ),
            },
        }
