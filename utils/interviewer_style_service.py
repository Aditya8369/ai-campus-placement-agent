"""
Interview personality & interviewer style service (#612).
Allows candidates to select interviewer personas (Friendly Recruiter, Strict Technical, Panel)
to adjust question tone, follow-up behavior, and demeanor without altering core technical difficulty
or misrepresenting AI as human.
"""

from typing import Dict, Any, List

INTERVIEWER_STYLES = {
    "friendly": {
        "id": "friendly",
        "name": "Friendly Recruiter",
        "tone": "Warm, encouraging, conversational",
        "icon": "fa-face-smile",
        "badge_class": "bg-success-subtle text-success border border-success-subtle",
        "system_instruction_addon": (
            "Interviewer Persona: Friendly Recruiter. Be warm, supportive, and approachable. "
            "Praise good points and encourage the candidate when probing deeper. "
            "Keep technical difficulty identical, but frame questions with welcoming phrasing."
        ),
        "question_prefix": "I'd love to hear more about your background: "
    },
    "technical": {
        "id": "technical",
        "name": "Strict Technical Architect",
        "tone": "Direct, precise, analytical",
        "icon": "fa-microchip",
        "badge_class": "bg-primary-subtle text-primary border border-primary-subtle",
        "system_instruction_addon": (
            "Interviewer Persona: Strict Technical Architect. Be direct, concise, and focused on architectural depth, "
            "trade-offs, algorithmic complexity, and edge cases. Avoid excessive pleasantries."
        ),
        "question_prefix": "Focusing on architectural rigour: "
    },
    "panel": {
        "id": "panel",
        "name": "Multi-Stakeholder Panel",
        "tone": "Diverse viewpoints, holistic, rigorous",
        "icon": "fa-users",
        "badge_class": "bg-purple-subtle text-purple border border-purple-subtle",
        "system_instruction_addon": (
            "Interviewer Persona: Multi-Stakeholder Panel. Simulate alternating inquiries between an engineering manager, "
            "product lead, and senior peer. Focus on both business value and engineering execution."
        ),
        "question_prefix": "The panel would like to explore both business and technical angles: "
    }
}

DEFAULT_STYLE = "friendly"

def get_available_styles() -> List[Dict[str, Any]]:
    """Returns all available interviewer styles."""
    return list(INTERVIEWER_STYLES.values())

def get_style_config(style_id: str) -> Dict[str, Any]:
    """Retrieves style configuration or defaults to friendly."""
    clean_id = (style_id or DEFAULT_STYLE).lower().strip()
    return INTERVIEWER_STYLES.get(clean_id, INTERVIEWER_STYLES[DEFAULT_STYLE])

def format_prompt_for_style(question_text: str, style_id: str) -> str:
    """Formats interview question framing based on the chosen interviewer persona."""
    cfg = get_style_config(style_id)
    if not question_text:
        return ""
    # Adjust tone without altering core subject matter
    prefix = cfg.get("question_prefix", "")
    return f"[{cfg['name']} Mode] {question_text}"
