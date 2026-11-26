import logging
from typing import Dict, Any, List, Optional
import prompts
from utils.gemini import generate_json_response, format_ai_error_for_user
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

    def process(self, data: Any, company_name: Optional[str] = None, **kwargs) -> Dict[str, List[str]]:
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
    def ensure_minimum_session_questions(
        questions_list: List[Dict[str, Any]],
        round_type: str = "All",
        target_role: str = "Software Engineer",
        target_company: str = "General",
        min_count: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Guarantees that a mock interview session contains at least min_count questions (#496).
        Supplements questions with role- and round-appropriate fallbacks if fewer than min_count are provided.
        Ensures consistent sequential zero-based indexing and behavioral metadata.
        """
        clean_questions: List[Dict[str, Any]] = []
        if isinstance(questions_list, list):
            for item in questions_list:
                if isinstance(item, dict) and item.get("question"):
                    clean_questions.append(dict(item))

        hr_defaults = [
            "Tell me about yourself and walk me through your resume.",
            f"Why are you interested in joining {target_company} as a {target_role} specifically?",
            "What are your greatest professional strengths, and what is one area you are actively improving?",
            "Where do you see yourself professionally five years from now?",
            "How do you prioritize competing deadlines and manage high-pressure project delivery?",
            "Describe a challenging interpersonal situation in a team and how you constructively resolved it.",
        ]

        tech_defaults = [
            "What are the primary differences between SQL and NoSQL databases, and when would you choose each?",
            "Explain the core principles of Object-Oriented Programming (OOP) and how polymorphism benefits software design.",
            "How do you analyze and optimize the algorithmic time and space complexity of a bottleneck in production code?",
            "What is the difference between TCP and UDP protocols, and in what real-world scenarios is UDP preferred?",
            "How does virtual memory, paging, and swapping work in modern operating systems?",
            "Explain database indexing mechanisms (e.g. B-Trees) and the trade-offs between read and write throughput.",
        ]

        behav_defaults = [
            "Tell me about a challenging team project where a conflict arose and how you handled it.",
            "Describe a time you had to master a complex new technology or framework in a very short timeframe.",
            "Share an example of a mistake or technical failure in a past project and what you learned from it.",
            "Describe a situation where you took initiative and went above and beyond to deliver on time.",
            "How do you handle receiving critical feedback on your work from team leads or peers?",
            "Describe a time when you had to balance technical debt with business deadlines.",
        ]

        # Existing question texts to avoid duplicate questions
        existing_texts = {str(q.get("question", "")).strip().lower() for q in clean_questions}

        normalized_round = str(round_type or "All").strip().capitalize()
        if normalized_round == "Hr":
            normalized_round = "HR"

        def _get_candidate_pools() -> List[tuple[str, List[str], bool]]:
            if normalized_round == "HR":
                return [("HR", hr_defaults, False)]
            elif normalized_round == "Technical":
                return [("Technical", tech_defaults, False)]
            elif normalized_round == "Behavioral":
                return [("Behavioral", behav_defaults, True)]
            else:
                return [
                    ("Technical", tech_defaults, False),
                    ("HR", hr_defaults, False),
                    ("Behavioral", behav_defaults, True),
                ]

        candidate_pools = _get_candidate_pools()
        pool_idx = 0

        while len(clean_questions) < min_count:
            category, pool, is_behav = candidate_pools[pool_idx % len(candidate_pools)]
            pool_idx += 1

            # Pick first question from this pool that isn't already present
            chosen_q = None
            for cand in pool:
                if cand.strip().lower() not in existing_texts:
                    chosen_q = cand
                    break

            if not chosen_q:
                # If all were somehow used, synthesize a numbered fallback
                chosen_q = f"Describe an applied problem you solved in {category} practice (Question {len(clean_questions) + 1})."

            existing_texts.add(chosen_q.strip().lower())
            clean_questions.append({
                "index": len(clean_questions),
                "type": category,
                "question": chosen_q,
                "difficulty": clean_questions[0].get("difficulty", "Intermediate") if clean_questions else "Intermediate",
                "is_behavioral": is_behav or ("behavioral" in chosen_q.lower()),
            })

        # Re-index all questions cleanly
        for idx, q in enumerate(clean_questions):
            q["index"] = idx
            if "type" not in q or not q["type"]:
                q["type"] = normalized_round if normalized_round in ["HR", "Technical", "Behavioral"] else "Technical"
            if "is_behavioral" not in q:
                q["is_behavioral"] = (str(q["type"]).lower() == "behavioral") or InterviewAgent.is_behavioral_question(q.get("question", ""), q["type"])

        return clean_questions

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

    @staticmethod
    def is_behavioral_question(question: str, question_type: str = "") -> bool:
        """
        Determines whether a question is behavioral based on its category or phrasing (#303).
        """
        if question_type and str(question_type).strip().lower() in ("behavioral", "behavioural"):
            return True
        q_lower = str(question or "").strip().lower()
        behavioral_phrases = [
            "tell me about a time",
            "describe a time",
            "describe a situation",
            "give an example",
            "share an example",
            "have you ever",
            "how do you handle",
            "how did you handle",
            "what would you do if",
            "conflict arose",
            "mistake or failure",
            "above and beyond",
            "walk me through",
        ]
        return any(phrase in q_lower for phrase in behavioral_phrases)

    @staticmethod
    def _normalize_star_part(value: Any) -> str:
        """
        Normalizes a STAR component status to 'present', 'weak', or 'missing' (#303).
        """
        if value is True:
            return "present"
        if value is False or value is None:
            return "missing"
        val = str(value).strip().lower()
        if val in ("present", "yes", "true", "complete", "strong", "good", "included", "covered"):
            return "present"
        if val in ("weak", "partial", "needs_improvement", "unclear", "moderate", "fair"):
            return "weak"
        if val in ("missing", "no", "false", "none", "not_present", "absent", "omitted"):
            return "missing"
        return "weak" if val else "missing"

    def _parse_star_block(self, res: Dict[str, Any], is_behavioral: bool) -> Any:
        """
        Safely extracts and sanitizes the STAR analysis block for behavioral questions (#303).
        Returns None for technical questions or if the model omits / malforms the STAR block.
        """
        if not is_behavioral:
            return None

        raw_star = res.get("star_analysis")
        if not isinstance(raw_star, dict):
            # Also check if it was nested under star_method_analysis
            raw_star_method = res.get("star_method_analysis")
            if isinstance(raw_star_method, dict) and any(
                k in raw_star_method for k in ("situation", "task", "action", "result")
            ):
                raw_star = raw_star_method
            else:
                return None

        situation = self._normalize_star_part(raw_star.get("situation"))
        task = self._normalize_star_part(raw_star.get("task"))
        action = self._normalize_star_part(raw_star.get("action"))
        result = self._normalize_star_part(raw_star.get("result"))

        tip = str(
            raw_star.get("tip")
            or raw_star.get("improvement_tip")
            or raw_star.get("feedback")
            or ""
        ).strip()

        if not tip:
            missing_parts = [
                name for name, status in [
                    ("Situation", situation),
                    ("Task", task),
                    ("Action", action),
                    ("Result", result),
                ] if status in ("missing", "weak")
            ]
            if missing_parts:
                tip = f"Strengthen your answer by detailing the {', '.join(missing_parts)} component{'s' if len(missing_parts) > 1 else ''}."
            else:
                tip = "Excellent narrative structure covering all Situation, Task, Action, and Result components."

        return {
            "situation": situation,
            "task": task,
            "action": action,
            "result": result,
            "tip": tip
        }

    def evaluate_answer(
        self,
        question_type: str,
        question: str,
        answer: str,
        is_behavioral: Any = None,
        interviewer_style: str = "friendly",
    ) -> Dict[str, Any]:
        """
        Performs a dynamic API evaluation call to score a single answer response,
        including verbal communication indicators (clarity, filler words, STAR approach).
        For behavioral questions, evaluates STAR method parts (Situation, Task, Action, Result)
        and returns which are present, missing or weak, plus one improvement tip (#303).
        Adapts tone and probing follow-up behavior according to interviewer_style persona (#686).
        """
        from utils.interviewer_style_service import get_style_config

        style_cfg = get_style_config(interviewer_style)

        if is_behavioral is None:
            is_behavioral = self.is_behavioral_question(question, question_type)

        logger.info(
            f"InterviewAgent: Dynamic response evaluation started for type: '{question_type}' "
            f"(is_behavioral={is_behavioral}, style={style_cfg['id']})"
        )

        if not answer or not answer.strip():
            star_analysis = None
            if is_behavioral:
                star_analysis = {
                    "situation": "missing",
                    "task": "missing",
                    "action": "missing",
                    "result": "missing",
                    "tip": "Provide a descriptive answer detailing the Situation, Task, Action, and Result."
                }
            probing_follow_up = None
            if style_cfg.get("probing_follow_up"):
                probing_follow_up = "Follow-up Challenge: What are the primary trade-offs, edge cases, and worst-case Big-O complexities of this approach?"
            return {
                "confidence_score": 0,
                "communication_score": 0,
                "technical_accuracy": 0,
                "verbal_clarity_score": 0,
                "filler_words_detected": [],
                "filler_word_count": 0,
                "clarity": "No response provided. Speech clarity and articulation could not be evaluated.",
                "structure": "No answer structure detected. Structure your answer using logical steps or the STAR framework.",
                "relevance": "No response provided to address the question prompt.",
                "tip": "Begin by directly addressing the question with a high-level summary, followed by a concrete example.",
                "star_method_analysis": {
                    "used_star": False,
                    "feedback": "No answer provided to analyze structure."
                },
                "star_analysis": star_analysis,
                "suggestions": [
                    "Answer field was submitted empty.",
                    "Please formulate a response of at least 2-3 sentences."
                ],
                "feedback": "The candidate did not provide an answer. Prompt evaluation requires written or spoken input.",
                "interviewer_style": style_cfg["id"],
                "interviewer_style_name": style_cfg["name"],
                "interviewer_style_badge": style_cfg["badge_class"],
                "interviewer_style_icon": style_cfg["icon"],
                "probing_follow_up": probing_follow_up,
            }

        safe_answer = sanitize_untrusted_text(answer.strip(), max_length=5000)
        encapsulated_answer = encapsulate_untrusted_input(safe_answer, document_type="candidate_interview_answer")

        prompt = prompts.INTERVIEW_EVAL_USER_PROMPT_TEMPLATE.format(
            question_type=question_type,
            question=question,
            candidate_answer=encapsulated_answer
        )
        if style_cfg.get("prompt_fragment"):
            prompt += f"\n\n{style_cfg['prompt_fragment']}"

        system_instruction = prompts.INTERVIEW_EVAL_SYSTEM_INSTRUCTION
        if style_cfg.get("system_instruction_addon"):
            system_instruction += f"\n\n{style_cfg['system_instruction_addon']}"

        try:
            # Query Gemini for the answer evaluation with hardened security instructions
            res = generate_json_response(
                system_instruction=build_secure_system_instruction(system_instruction),
                prompt=prompt,
                feature="interview"
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

            star_analysis = self._parse_star_block(res, is_behavioral)

            star_data = res.get("star_method_analysis")
            if not isinstance(star_data, dict):
                used_star_flag = bool(
                    star_analysis
                    and star_analysis["situation"] == "present"
                    and star_analysis["action"] == "present"
                )
                star_data = {
                    "used_star": used_star_flag,
                    "feedback": (
                        star_analysis["tip"]
                        if star_analysis
                        else "Consider structuring experiences using Situation, Task, Action, and Result."
                    )
                }
            else:
                star_data = {
                    "used_star": bool(star_data.get("used_star", False)),
                    "feedback": str(star_data.get("feedback", "Structured response reviewed."))
                }

            # Per-answer feedback on clarity, structure, relevance, and actionable tip (#496)
            clarity = str(res.get("clarity") or res.get("clarity_feedback") or "").strip()
            if not clarity:
                if verbal_clarity >= 75:
                    clarity = "Clear, articulate explanation with natural phrasing and smooth pacing."
                elif verbal_clarity >= 55:
                    clarity = "Generally understandable, though phrasing could be crisper and more concise."
                else:
                    clarity = "Response needs clearer articulation, reduced filler words, and smoother delivery."

            structure = str(res.get("structure") or res.get("structure_feedback") or "").strip()
            if not structure:
                if star_data.get("used_star"):
                    structure = "Well-structured response following a clear sequence (Situation, Task, Action, Result)."
                elif comm >= 70:
                    structure = "Logical progression with discernible beginning, main details, and conclusion."
                else:
                    structure = "Structure would benefit from signposting (e.g. 'First, Second, Finally') or the STAR framework."

            relevance = str(res.get("relevance") or res.get("relevance_feedback") or "").strip()
            if not relevance:
                if tech >= 70:
                    relevance = "Directly and accurately addresses the core intent and domain concepts of the prompt."
                else:
                    relevance = "Answer touches on relevant concepts, but needs closer alignment to the specific question asked."

            tip = str(res.get("tip") or (star_analysis.get("tip") if star_analysis else "") or "").strip()
            if not tip:
                sug_list = self._sanitize_list(res.get("suggestions"))
                if sug_list:
                    tip = sug_list[0]
                elif is_behavioral:
                    tip = "Use the STAR method: quantify your end result with measurable impact or key learnings."
                else:
                    tip = "Anchor your explanation with a concrete technical example or architectural tradeoff."

            probing_follow_up = None
            if style_cfg.get("probing_follow_up"):
                probing_follow_up = str(
                    res.get("probing_follow_up")
                    or res.get("probing_question")
                    or res.get("follow_up")
                    or ""
                ).strip()
                if not probing_follow_up:
                    probing_follow_up = "Follow-up Challenge: What are the primary trade-offs, edge cases, and worst-case Big-O complexities of this approach?"

            return {
                "confidence_score": conf,
                "communication_score": comm,
                "technical_accuracy": tech,
                "verbal_clarity_score": verbal_clarity,
                "filler_words_detected": filler_list,
                "filler_word_count": filler_count,
                "clarity": clarity,
                "structure": structure,
                "relevance": relevance,
                "tip": tip,
                "star_method_analysis": star_data,
                "star_analysis": star_analysis,
                "suggestions": self._sanitize_list(res.get("suggestions")) or ["Incorporate clear structured responses (STAR method)."],
                "feedback": str(res.get("feedback", "Feedback generation completed.")),
                "interviewer_style": style_cfg["id"],
                "interviewer_style_name": style_cfg["name"],
                "interviewer_style_badge": style_cfg["badge_class"],
                "interviewer_style_icon": style_cfg["icon"],
                "probing_follow_up": probing_follow_up,
            }

        except Exception as e:
            logger.error(f"InterviewAgent: Evaluation execution failed: {str(e)}")
            star_analysis = None
            if is_behavioral:
                star_analysis = {
                    "situation": "weak",
                    "task": "weak",
                    "action": "weak",
                    "result": "weak",
                    "tip": "Structure your response with clear Situation, Task, Action, and Result stages."
                }
            clarity = "Response articulation could not be fully evaluated due to transient service limitation."
            structure = "Response structure could not be fully analyzed."
            relevance = "Relevance could not be fully verified."
            tip = "Structure your answer logically with an opening summary, supporting details, and concrete results."
            probing_follow_up = None
            if style_cfg.get("probing_follow_up"):
                probing_follow_up = "Follow-up Challenge: What are the primary trade-offs, edge cases, and worst-case Big-O complexities of this approach?"
            return {
                "confidence_score": 50,
                "communication_score": 50,
                "technical_accuracy": 50,
                "verbal_clarity_score": 50,
                "filler_words_detected": [],
                "filler_word_count": 0,
                "clarity": clarity,
                "structure": structure,
                "relevance": relevance,
                "tip": tip,
                "star_method_analysis": {
                    "used_star": False,
                    "feedback": "Evaluation system was unable to evaluate STAR structure."
                },
                "star_analysis": star_analysis,
                "suggestions": [
                    "Use quantitative metrics where possible.",
                    "Break down explanations into clear steps."
                ],
                "feedback": f"Evaluation system was unable to analyze this response due to a temporary AI service limitation. ({format_ai_error_for_user(e)})",
                "interviewer_style": style_cfg["id"],
                "interviewer_style_name": style_cfg["name"],
                "interviewer_style_badge": style_cfg["badge_class"],
                "interviewer_style_icon": style_cfg["icon"],
                "probing_follow_up": probing_follow_up,
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
                "summary_feedback": "No answers have been evaluated for this session yet.",
                "strengths": [],
                "weak_areas": ["No answers submitted yet for evaluation."],
                "improvements": ["No answers submitted yet for evaluation."],
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

        # Competency Breakdown across Technical Knowledge, Communication, Problem-Solving, Relevance (#267)
        try:
            from utils.interview_performance_breakdown import calculate_competency_breakdown
            competency_analysis = calculate_competency_breakdown(answers_list)
        except Exception as e_comp:
            logger.warning(f"Could not calculate competency breakdown: {e_comp}")
            competency_analysis = {}

        # Timed Answer Mode Performance Metrics (#431)
        timed_answers = [
            a for a in answers_list
            if isinstance(a, dict) and (
                a.get("is_timed")
                or a.get("time_taken_seconds") is not None
                or (isinstance(a.get("evaluation"), dict) and a["evaluation"].get("time_taken_seconds") is not None)
            )
        ]
        timing_summary = None
        if timed_answers:
            durations = []
            within_limit = 0
            for a in timed_answers:
                t_taken = a.get("time_taken_seconds")
                if t_taken is None and isinstance(a.get("evaluation"), dict):
                    t_taken = a["evaluation"].get("time_taken_seconds")
                t_limit = a.get("time_limit_seconds")
                if t_limit is None and isinstance(a.get("evaluation"), dict):
                    t_limit = a["evaluation"].get("time_limit_seconds")
                if t_taken is not None:
                    try:
                        t_val = int(round(float(t_taken)))
                        durations.append(t_val)
                        if t_limit is None or t_val <= int(round(float(t_limit))):
                            within_limit += 1
                    except (ValueError, TypeError):
                        pass

            if durations:
                avg_sec = int(round(sum(durations) / len(durations)))
                m_avg = avg_sec // 60
                s_avg = avg_sec % 60
                timing_summary = {
                    "total_timed_questions": len(durations),
                    "total_time_seconds": sum(durations),
                    "average_time_seconds": avg_sec,
                    "average_time_per_answer_seconds": avg_sec,
                    "average_time_formatted": f"{m_avg}:{s_avg:02d}",
                    "formatted_avg_time": f"{m_avg}:{s_avg:02d}",
                    "within_limit_count": within_limit,
                    "answers_within_limit": within_limit,
                    "within_limit_percentage": int(round((within_limit / len(durations)) * 100)),
                }

        # Derive top-level strengths and weak areas (#496)
        summary_strengths = []
        summary_weak_areas = []
        if isinstance(competency_analysis, dict):
            summary_strengths = competency_analysis.get("strengths") or []
            summary_weak_areas = competency_analysis.get("improvements") or []

        if not summary_strengths:
            if overall_avg >= 70:
                summary_strengths.append("Demonstrated consistent technical command and responsive communication delivery.")
            else:
                summary_strengths.append("Successfully attempted all assigned interview questions.")

        if not summary_weak_areas:
            if overall_avg < 70:
                summary_weak_areas.append("Deepen core technical fundamentals and structure answers with the STAR method.")
            else:
                summary_weak_areas.append("Maintain consistent practice with timed answers to further elevate interview polish.")

        return {
            "total_answered": total_ans,
            "overall_score": overall_avg,
            "category_scores": category_breakdown,
            "readiness_verdict": verdict,
            "summary_feedback": summary_feedback,
            "strengths": summary_strengths,
            "weak_areas": summary_weak_areas,
            "improvements": summary_weak_areas,
            "competency_breakdown": competency_analysis,
            "verbal_metrics": {
                "average_verbal_clarity": avg_verbal,
                "total_filler_words": total_filler_words,
                "star_adherence_rate": f"{int(round((star_used_count / total_ans) * 100))}%" if total_ans else "0%"
            },
            "timing_summary": timing_summary,
        }
