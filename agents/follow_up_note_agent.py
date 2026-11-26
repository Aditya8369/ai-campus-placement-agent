"""
FollowUpNoteAgent - Interview Follow-Up Note & Outreach Helper (#847)

Generates concise, polite post-interview notes for students on tracked applications:
1. Thank-you within 24 hours of interview
2. Follow-up after one week without update
3. Offer acknowledgement upon receiving an offer

Strict Constraints:
- Under 150 words per draft.
- Grounded strictly in company name from the tracker and single detail provided by student.
- Handles empty detail with a polite generic draft.
- Never sends automatically (draft only, for user review and copy).
- Provides deterministic heuristic fallback when offline or LLM fails.
"""

import re
import logging
from typing import Dict, Any, Optional

import prompts
from utils.gemini import generate_json_response
from utils.prompt_security import sanitize_untrusted_text

logger = logging.getLogger(__name__)

NOTE_TYPES = {
    "thank_you": "Thank-you (within 24 hours)",
    "follow_up": "Follow-up (after one week)",
    "offer_acknowledgement": "Offer acknowledgement",
}

MAX_WORD_COUNT = 150


class FollowUpNoteAgent:
    """
    Agent responsible for generating post-interview follow-up notes,
    thank-you notes, and offer acknowledgements.
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def normalize_note_type(raw_type: Optional[str]) -> str:
        """Normalizes user input string to one of the 3 supported note types."""
        if not raw_type:
            return "thank_you"
        cleaned = str(raw_type).strip().lower().replace("-", "_").replace(" ", "_")
        if "thank" in cleaned:
            return "thank_you"
        if "follow" in cleaned:
            return "follow_up"
        if "offer" in cleaned or "acknowledge" in cleaned:
            return "offer_acknowledgement"
        return "thank_you"

    @staticmethod
    def count_words(text: str) -> int:
        """Returns the word count of the given text."""
        if not text:
            return 0
        return len(text.strip().split())

    def _ensure_under_word_limit(self, body: str, max_words: int = MAX_WORD_COUNT) -> str:
        """Ensures the body text is strictly under max_words while preserving sign-off."""
        words = body.strip().split()
        if len(words) < max_words:
            return body

        # If over limit, truncate words before sign-off
        sign_off_match = re.search(r"(Best regards,|Sincerely,|Thank you,|Warm regards,)", body)
        if sign_off_match:
            prefix = body[:sign_off_match.start()].strip().split()
            target_len = max_words - 10
            truncated_prefix = " ".join(prefix[:target_len])
            suffix = body[sign_off_match.start():].strip()
            return f"{truncated_prefix}...\n\n{suffix}"
        else:
            return " ".join(words[:max_words - 5]) + "..."

    def generate_note(
        self,
        company_name: str,
        note_type: str = "thank_you",
        interview_detail: str = "",
        role_title: str = "",
    ) -> Dict[str, Any]:
        """
        Generates a post-interview note draft.
        Uses Gemini LLM when available and falls back to deterministic heuristic templates.
        Guarantees word count under 150 words and incorporates student's interview detail.
        """
        norm_type = self.normalize_note_type(note_type)
        type_label = NOTE_TYPES.get(norm_type, "Thank-you (within 24 hours)")
        company = (company_name or "Target Company").strip()
        role = (role_title or "the position").strip()
        safe_detail = sanitize_untrusted_text(interview_detail or "", max_length=300).strip()

        # Attempt LLM generation
        try:
            if safe_detail:
                detail_instruction = (
                    f"Specifically incorporate this interview detail into the message: '{safe_detail}'."
                )
            else:
                detail_instruction = (
                    "No specific detail was provided. Generate a polite, professional generic message "
                    "without inventing any fictional details or claims."
                )

            prompt = prompts.FOLLOW_UP_NOTE_USER_PROMPT_TEMPLATE.format(
                company_name=company,
                role_title=role,
                note_type=norm_type,
                note_type_label=type_label,
                interview_detail=safe_detail or "[None provided - generate generic draft]",
                detail_instruction=detail_instruction,
            )

            raw_response = generate_json_response(
                prompt=prompt,
                system_instruction=prompts.FOLLOW_UP_NOTE_SYSTEM_INSTRUCTION,
                feature="outreach",
            )

            if isinstance(raw_response, dict) and "body" in raw_response:
                subject = str(raw_response.get("subject", "")).strip() or self._default_subject(norm_type, company, role)
                body = str(raw_response.get("body", "")).strip()

                # Ensure student's detail is present if provided
                if safe_detail and not self._detail_in_body(safe_detail, body):
                    body = self._weave_detail_into_body(body, safe_detail, norm_type)

                body = self._ensure_under_word_limit(body, MAX_WORD_COUNT)
                word_count = self.count_words(body)

                return {
                    "success": True,
                    "note_type": norm_type,
                    "note_type_label": type_label,
                    "company_name": company,
                    "role_title": role,
                    "subject": subject,
                    "body": body,
                    "draft": f"Subject: {subject}\n\n{body}",
                    "word_count": word_count,
                    "interview_detail": safe_detail,
                }
        except Exception as e:
            logger.warning(f"LLM note generation failed or offline ({e}). Using heuristic generator.")

        # Heuristic fallback
        return self._generate_heuristic_note(
            company_name=company,
            note_type=norm_type,
            interview_detail=safe_detail,
            role_title=role,
        )

    def _default_subject(self, note_type: str, company: str, role: str) -> str:
        role_part = f" - {role}" if role and role != "the position" else ""
        if note_type == "thank_you":
            return f"Thank You - {company} Interview{role_part}"
        elif note_type == "follow_up":
            return f"Following Up - {company} Interview{role_part}"
        elif note_type == "offer_acknowledgement":
            return f"Offer Acknowledgement - {company}{role_part}"
        return f"Thank You - {company} Interview"

    def _detail_in_body(self, detail: str, body: str) -> bool:
        """Checks if key words from detail appear in body."""
        clean_detail = re.sub(r"[^\w\s]", "", detail.lower())
        words = [w for w in clean_detail.split() if len(w) > 3]
        if not words:
            return True
        body_lower = body.lower()
        matched = sum(1 for w in words if w in body_lower)
        return matched >= max(1, len(words) // 2)

    def _weave_detail_into_body(self, body: str, detail: str, note_type: str) -> str:
        """Inserts the detail smoothly into the body if omitted by LLM."""
        sentence = f"I particularly enjoyed our discussion regarding {detail}."
        paragraphs = body.split("\n\n")
        if len(paragraphs) >= 2:
            paragraphs.insert(1, sentence)
            return "\n\n".join(paragraphs)
        return f"{sentence}\n\n{body}"

    def _generate_heuristic_note(
        self,
        company_name: str,
        note_type: str,
        interview_detail: str = "",
        role_title: str = "",
    ) -> Dict[str, Any]:
        """
        Deterministic, high-converting note generator.
        Produces clean drafts under 150 words for each note type.
        """
        company = (company_name or "Target Company").strip()
        role = (role_title or "the position").strip()
        has_role = bool(role and role != "the position")
        role_phrase = f"for the {role} position" if has_role else "for the position"
        subject = self._default_subject(note_type, company, role)

        if note_type == "thank_you":
            if interview_detail:
                body = (
                    f"Dear Hiring Team,\n\n"
                    f"Thank you very much for the opportunity to speak with you yesterday regarding the {role_phrase} "
                    f"at {company}. I especially enjoyed our conversation about {interview_detail}.\n\n"
                    f"Our discussion confirmed my enthusiasm for {company} and the team's mission. "
                    f"Please let me know if you need any additional information from my side.\n\n"
                    f"Thank you again for your time and consideration. I look forward to hearing about the next steps.\n\n"
                    f"Best regards,\n"
                    f"[Your Name]"
                )
            else:
                body = (
                    f"Dear Hiring Team,\n\n"
                    f"Thank you very much for the opportunity to interview yesterday {role_phrase} at {company}. "
                    f"I thoroughly enjoyed learning more about the team, the collaborative culture, and the impactful work you are doing.\n\n"
                    f"Our conversation strongly reinforced my excitement about contributing to {company}. "
                    f"Please feel free to reach out if there is any further information I can provide.\n\n"
                    f"Thank you once again for your time and consideration. I look forward to the next steps in the process.\n\n"
                    f"Best regards,\n"
                    f"[Your Name]"
                )

        elif note_type == "follow_up":
            if interview_detail:
                body = (
                    f"Dear Hiring Team,\n\n"
                    f"I hope you are having a great week. I am writing to politely follow up on our interview last week "
                    f"{role_phrase} at {company}. I really enjoyed our discussion, particularly regarding {interview_detail}.\n\n"
                    f"I remain very enthusiastic about the opportunity to join your team. "
                    f"I wanted to check in to see if there are any updates on the hiring timeline, or if there is any additional information I can share to assist with your decision.\n\n"
                    f"Thank you again for your time and consideration.\n\n"
                    f"Best regards,\n"
                    f"[Your Name]"
                )
            else:
                body = (
                    f"Dear Hiring Team,\n\n"
                    f"I hope you are having a productive week. I am following up on our interview last week {role_phrase} at {company}.\n\n"
                    f"I remain very interested in the role and excited about the prospect of contributing to {company}. "
                    f"I wanted to check if you have any updates regarding the next steps in the selection process, or if you need any supplementary details from me.\n\n"
                    f"Thank you again for your time and consideration. I look forward to hearing from you.\n\n"
                    f"Best regards,\n"
                    f"[Your Name]"
                )

        elif note_type == "offer_acknowledgement":
            if interview_detail:
                body = (
                    f"Dear Hiring Team,\n\n"
                    f"Thank you very much for extending the offer to join {company} as {role if has_role else 'part of your team'}. "
                    f"I am thrilled and grateful for this opportunity.\n\n"
                    f"Our interview discussions, especially regarding {interview_detail}, made me even more enthusiastic about joining the team and contributing to {company}'s goals.\n\n"
                    f"I am currently reviewing the offer details and will follow up shortly with my formal response. In the meantime, please let me know if there is anything needed from my end.\n\n"
                    f"Thank you once again for your confidence in me.\n\n"
                    f"Best regards,\n"
                    f"[Your Name]"
                )
            else:
                body = (
                    f"Dear Hiring Team,\n\n"
                    f"Thank you so much for offering me the opportunity to join {company} as {role if has_role else 'a member of your team'}. "
                    f"I am honored and excited about this offer.\n\n"
                    f"I am currently reviewing the details of the offer and will follow up with you shortly. "
                    f"Please let me know if there are any specific documents or information you need from me in the interim.\n\n"
                    f"Thank you once again for your consideration and support throughout the interview process.\n\n"
                    f"Best regards,\n"
                    f"[Your Name]"
                )
        else:
            # Fallback
            body = (
                f"Dear Hiring Team,\n\n"
                f"Thank you for your time and conversation regarding {company}.\n\n"
                f"Best regards,\n"
                f"[Your Name]"
            )

        body = self._ensure_under_word_limit(body, MAX_WORD_COUNT)
        word_count = self.count_words(body)

        return {
            "success": True,
            "note_type": note_type,
            "note_type_label": NOTE_TYPES.get(note_type, note_type),
            "company_name": company,
            "role_title": role,
            "subject": subject,
            "body": body,
            "draft": f"Subject: {subject}\n\n{body}",
            "word_count": word_count,
            "interview_detail": interview_detail,
        }
