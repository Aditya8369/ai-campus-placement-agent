import logging
from typing import Dict, Any, List
import prompts
from utils.gemini import generate_json_response
from utils.prompt_security import (
    sanitize_untrusted_text,
    encapsulate_untrusted_input,
    build_secure_system_instruction,
    redact_sensitive_information,
)

logger = logging.getLogger(__name__)

class InterviewAgent:
    """
    Agent responsible for structuring, validating the initial 15 mock interview questions,
    and dynamically evaluating user answers using Gemini during the live interview session.
    """
    def __init__(self) -> None:
        pass

    def process(self, data: Any) -> Dict[str, List[str]]:
        """
        Validates the generated question sets from the coordinator.
        Ensures exactly 5 questions per section (HR, Technical, Behavioral).
        """
        logger.info("InterviewAgent: Verifying mock interview questions array.")

        if not isinstance(data, dict):
            logger.warning("InterviewAgent received invalid question payload. Loading system defaults.")
            data = {}

        hr_qs = self._sanitize_list(data.get("hr"))
        tech_qs = self._sanitize_list(data.get("technical"))
        behavioral_qs = self._sanitize_list(data.get("behavioral"))

        # Enforce exactly 5 questions for each list with standard fallbacks if short
        hr_qs = self._enforce_five_items(hr_qs, "HR", [
            "Tell me about yourself and walk me through your resume.",
            "Why are you interested in joining our company specifically?",
            "What are your core strengths and areas of improvement?",
            "Where do you see yourself five years from now?",
            "How do you prioritize tasks when working under tight deadlines?"
        ])

        tech_qs = self._enforce_five_items(tech_qs, "Technical", [
            "What are the differences between SQL and NoSQL databases?",
            "Explain the concept and practical benefits of polymorphism in OOP.",
            "How do you analyze and optimize the complexity of a slow algorithm?",
            "What is the difference between TCP and UDP protocols?",
            "How does virtual memory work in modern operating systems?"
        ])

        behavioral_qs = self._enforce_five_items(behavioral_qs, "Behavioral", [
            "Tell me about a challenging team project where a conflict arose and how you handled it.",
            "Describe a time you had to learn a complex new skill or framework in a very short time.",
            "Share an example of a mistake or failure in your academic/professional life and what you learned.",
            "Describe a situation where you went above and beyond to deliver a project on time.",
            "How do you handle receiving critical feedback from team members or mentors?"
        ])

        return {
            "hr": hr_qs,
            "technical": tech_qs,
            "behavioral": behavioral_qs
        }

    def _sanitize_list(self, raw_list: Any) -> List[str]:
        if isinstance(raw_list, list):
            return [str(q).strip() for q in raw_list if q and str(q).strip()]
        return []

    def _enforce_five_items(self, questions: List[str], label: str, defaults: List[str]) -> List[str]:
        if len(questions) >= 5:
            return questions[:5]
        else:
            diff = 5 - len(questions)
            logger.info(f"InterviewAgent: Injecting {diff} fallback questions for '{label}' list.")
            return questions + defaults[:diff]

    @staticmethod
    def parse_score(value: Any, default: int = 50) -> int:
        """
        Parses score into an integer clamped between 0 and 100.
        Handles floats (e.g. 85.5), strings with percentage (e.g. "85%"), and fraction formats.
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

    def evaluate_answer(self, question_type: str, question: str, answer: str) -> Dict[str, Any]:
        """
        Performs a dynamic API evaluation call to score a single answer response,
        including verbal communication indicators (clarity, filler words, STAR approach).
        """
        logger.info(f"InterviewAgent: Dynamic response evaluation started for type: '{question_type}'")

        if not answer or not answer.strip():
            return {
                "confidence_score": 0,
                "communication_score": 0,
                "technical_accuracy": 0,
                "verbal_clarity_score": 0,
                "filler_words_detected": [],
                "filler_word_count": 0,
                "star_method_analysis": {
                    "used_star": False,
                    "feedback": "No answer provided to analyze structure."
                },
                "suggestions": [
                    "Answer field was submitted empty.",
                    "Please formulate a response of at least 2-3 sentences."
                ],
                "feedback": "The candidate did not provide an answer. Prompt evaluation requires written or spoken input."
            }

        safe_answer = sanitize_untrusted_text(answer.strip(), max_length=5000)
        encapsulated_answer = encapsulate_untrusted_input(safe_answer, document_type="candidate_interview_answer")

        prompt = prompts.INTERVIEW_EVAL_USER_PROMPT_TEMPLATE.format(
            question_type=question_type,
            question=question,
            candidate_answer=encapsulated_answer
        )

        try:
            # Query Gemini for the answer evaluation with hardened security instructions
            res = generate_json_response(
                system_instruction=build_secure_system_instruction(prompts.INTERVIEW_EVAL_SYSTEM_INSTRUCTION),
                prompt=prompt
            )
            res = redact_sensitive_information(res)

            # Robust score sanitization
            conf = self.parse_score(res.get("confidence_score"), 50)
            comm = self.parse_score(res.get("communication_score"), 50)
            tech = self.parse_score(res.get("technical_accuracy"), 50)
            verbal_clarity = self.parse_score(res.get("verbal_clarity_score"), default=comm)

            # Verbal indicator extraction
            filler_list = self._sanitize_list(res.get("filler_words_detected"))
            filler_count = res.get("filler_word_count")
            if not isinstance(filler_count, int):
                filler_count = len(filler_list)

            star_data = res.get("star_method_analysis")
            if not isinstance(star_data, dict):
                star_data = {
                    "used_star": False,
                    "feedback": "Consider structuring experiences using Situation, Task, Action, and Result."
                }
            else:
                star_data = {
                    "used_star": bool(star_data.get("used_star", False)),
                    "feedback": str(star_data.get("feedback", "Structured response reviewed."))
                }

            return {
                "confidence_score": conf,
                "communication_score": comm,
                "technical_accuracy": tech,
                "verbal_clarity_score": verbal_clarity,
                "filler_words_detected": filler_list,
                "filler_word_count": filler_count,
                "star_method_analysis": star_data,
                "suggestions": self._sanitize_list(res.get("suggestions")) or ["Incorporate clear structured responses (STAR method)."],
                "feedback": str(res.get("feedback", "Feedback generation completed."))
            }

        except Exception as e:
            logger.error(f"InterviewAgent: Evaluation execution failed: {str(e)}")
            return {
                "confidence_score": 50,
                "communication_score": 50,
                "technical_accuracy": 50,
                "verbal_clarity_score": 50,
                "filler_words_detected": [],
                "filler_word_count": 0,
                "star_method_analysis": {
                    "used_star": False,
                    "feedback": "Evaluation system was unable to evaluate STAR structure."
                },
                "suggestions": [
                    "Use quantitative metrics where possible.",
                    "Break down explanations into clear steps."
                ],
                "feedback": f"Evaluation system was unable to analyze this response. Context: {str(e)}"
            }

    def calculate_session_summary(self, answers_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Aggregates mock interview responses across all answered questions.
        Computes overall performance, category-level breakdowns (HR, Technical, Behavioral),
        and issues an overall readiness verdict with actionable feedback.
        """
        if not answers_list:
            return {
                "total_answered": 0,
                "overall_score": 0,
                "category_scores": {},
                "readiness_verdict": "No answers recorded",
                "summary_feedback": "No answers have been evaluated for this session yet."
            }

        categories: Dict[str, List[Dict[str, int]]] = {"HR": [], "Technical": [], "Behavioral": []}
        all_tech = []
        all_comm = []
        all_conf = []
        all_verbal = []
        total_filler_words = 0
        star_used_count = 0

        for item in answers_list:
            q_type = str(item.get("type", "Technical")).capitalize()
            target_key = "HR" if q_type.upper() == "HR" else q_type
            if target_key not in categories:
                categories[target_key] = []

            eval_data = item.get("evaluation", {})
            tech = self.parse_score(eval_data.get("technical_accuracy"), 50)
            comm = self.parse_score(eval_data.get("communication_score"), 50)
            conf = self.parse_score(eval_data.get("confidence_score"), 50)
            verbal = self.parse_score(eval_data.get("verbal_clarity_score"), comm)

            all_tech.append(tech)
            all_comm.append(comm)
            all_conf.append(conf)
            all_verbal.append(verbal)

            filler_cnt = eval_data.get("filler_word_count", 0)
            if isinstance(filler_cnt, (int, float)):
                total_filler_words += int(filler_cnt)

            star_data = eval_data.get("star_method_analysis")
            if isinstance(star_data, dict) and star_data.get("used_star"):
                star_used_count += 1

            composite = int(round((tech + comm + conf) / 3))
            categories[target_key].append({
                "tech": tech,
                "comm": comm,
                "conf": conf,
                "verbal": verbal,
                "composite": composite
            })

        # Calculate category averages
        category_breakdown = {}
        for cat_name, scores in categories.items():
            if scores:
                avg_tech = int(round(sum(s["tech"] for s in scores) / len(scores)))
                avg_comm = int(round(sum(s["comm"] for s in scores) / len(scores)))
                avg_conf = int(round(sum(s["conf"] for s in scores) / len(scores)))
                avg_comp = int(round(sum(s["composite"] for s in scores) / len(scores)))
                category_breakdown[cat_name] = {
                    "count": len(scores),
                    "technical_accuracy": avg_tech,
                    "communication_score": avg_comm,
                    "confidence_score": avg_conf,
                    "average_score": avg_comp
                }

        total_ans = len(answers_list)
        overall_avg = int(round((sum(all_tech) + sum(all_comm) + sum(all_conf)) / (total_ans * 3))) if total_ans else 0
        avg_verbal = int(round(sum(all_verbal) / len(all_verbal))) if all_verbal else 0

        # Determine verdict
        if overall_avg >= 80:
            verdict = "Placement Ready"
            summary_feedback = "Exceptional performance across technical depth and structured communication. Candidate exhibits high readiness for placement rounds."
        elif overall_avg >= 65:
            verdict = "Competent (Needs Targeted Polish)"
            summary_feedback = "Solid foundational answers. Focus on incorporating quantitative impact metrics and practicing the STAR framework on behavioral questions."
        else:
            verdict = "Requires Active Preparation"
            summary_feedback = "Further practice needed on technical fundamentals and concise response structuring. Review the 6-week roadmap topics."

        return {
            "total_answered": total_ans,
            "overall_score": overall_avg,
            "category_scores": category_breakdown,
            "readiness_verdict": verdict,
            "summary_feedback": summary_feedback,
            "verbal_metrics": {
                "average_verbal_clarity": avg_verbal,
                "total_filler_words": total_filler_words,
                "star_adherence_rate": f"{int(round((star_used_count / total_ans) * 100))}%" if total_ans else "0%"
            }
        }
