"""
Interviewer Personas & Style Service (#686, #612).
==================================================
Allows candidates to practice against different interviewer personas:
1. Friendly HR: Warm, conversational, encouraging, focuses on cultural fit & motivation.
2. Strict Technical: Direct, demanding, rigorous, challenges complexity, edge cases, and asks probing follow-ups.
3. Rapid-Fire: Fast-paced, concise, punchy questions testing quick thinking and crisp answers.

All persona prompt fragments are maintained in this single reviewed module.
Scoring criteria and numerical rating ranges (0-100) remain strictly identical
across all styles so that results remain objectively comparable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Core reviewed prompt fragments and persona specifications (#686)
INTERVIEWER_STYLES: Dict[str, Dict[str, Any]] = {
    "friendly": {
        "id": "friendly",
        "alias_id": "friendly_hr",
        "name": "Friendly HR",
        "tone": "Warm, conversational, encouraging",
        "description": "Warm, supportive conversation focused on team collaboration, cultural alignment, and personal growth.",
        "icon": "fa-face-smile",
        "badge_class": "bg-success-subtle text-success border border-success-subtle",
        "prompt_fragment": (
            "[Interviewer Style: Friendly HR]\n"
            "- Question Tone: Warm, conversational, welcoming, and encouraging. Frame questions conversationally (e.g. \"I'd love to hear about...\", \"Could you tell me about...\").\n"
            "- Follow-up Behavior: Warm and supportive, prompting the candidate to elaborate on personal values, teamwork, and growth without aggressive pushback.\n"
            "- Question Length: Standard conversational length with approachable pacing.\n"
            "- Evaluation Note: Offer constructive, encouraging feedback highlighting strengths alongside gentle improvement areas."
        ),
        "system_instruction_addon": (
            "Interviewer Persona: Friendly HR. Be warm, supportive, and approachable. "
            "Praise good points and encourage the candidate when probing deeper. "
            "Keep technical evaluation standard and objective, but frame questions with welcoming phrasing."
        ),
        "question_prefix": "I'd love to hear more: ",
        "probing_follow_up": False,
        "pacing": "conversational",
    },
    "technical": {
        "id": "technical",
        "alias_id": "strict_technical",
        "name": "Strict Technical",
        "tone": "Direct, demanding, analytical",
        "description": "Rigorous technical evaluation probing architectural depth, edge cases, algorithmic complexity, and trade-offs.",
        "icon": "fa-microchip",
        "badge_class": "bg-primary-subtle text-primary border border-primary-subtle",
        "prompt_fragment": (
            "[Interviewer Style: Strict Technical]\n"
            "- Question Tone: Direct, demanding, concise, and uncompromising. Zero pleasantries or sugarcoating.\n"
            "- Follow-up Behavior: Strictly challenge the candidate's answer with one probing follow-up question (e.g. \"What is the Big-O time and space complexity?\", \"How would your design fail under 10x traffic spikes?\", \"Why this approach over alternatives?\").\n"
            "- Question Length: Deep, technical inquiries demanding architectural rigour and precision.\n"
            "- Evaluation Note: Provide direct, analytical feedback dissecting flaws, edge cases, and trade-offs."
        ),
        "system_instruction_addon": (
            "Interviewer Persona: Strict Technical. Be direct, concise, and focused on architectural depth, "
            "trade-offs, algorithmic complexity, and edge cases. Avoid excessive pleasantries."
        ),
        "question_prefix": "Focusing on technical rigour and trade-offs: ",
        "probing_follow_up": True,
        "pacing": "rigorous",
    },
    "rapid_fire": {
        "id": "rapid_fire",
        "alias_id": "rapid_fire",
        "name": "Rapid-Fire",
        "tone": "Fast-paced, concise, punchy",
        "description": "High-tempo, punchy questions testing quick recall, rapid decision making, and crisp articulation.",
        "icon": "fa-bolt",
        "badge_class": "bg-warning-subtle text-warning-emphasis border border-warning-subtle",
        "prompt_fragment": (
            "[Interviewer Style: Rapid-Fire]\n"
            "- Question Tone: Fast-paced, concise, punchy, and direct (1 to 2 sentences max).\n"
            "- Follow-up Behavior: Swift transition between core concepts; brief follow-ups testing quick thinking and crisp articulation.\n"
            "- Question Length: Punchy, short questions (1-2 sentences maximum).\n"
            "- Evaluation Note: Emphasize quickness of thought, crispness of explanation, and direct relevance."
        ),
        "system_instruction_addon": (
            "Interviewer Persona: Rapid-Fire. Keep question phrasing short, crisp, and high-tempo. "
            "Test quick thinking and concise communication without long setups."
        ),
        "question_prefix": "Quick-fire question: ",
        "probing_follow_up": False,
        "pacing": "fast",
    },
    "panel": {
        "id": "panel",
        "alias_id": "panel",
        "name": "Multi-Stakeholder Panel",
        "tone": "Diverse viewpoints, holistic, rigorous",
        "description": "Simulates alternating inquiries from engineering, product, and leadership stakeholders.",
        "icon": "fa-users",
        "badge_class": "bg-info-subtle text-info border border-info-subtle",
        "prompt_fragment": (
            "[Interviewer Style: Multi-Stakeholder Panel]\n"
            "- Question Tone: Diverse viewpoints spanning business, product, and engineering.\n"
            "- Question Style: Evaluates both business value and technical execution.\n"
            "- Follow-up Behavior: Probes both technical trade-offs and user/product impact.\n"
            "- Question Length: Balanced multi-perspective questions."
        ),
        "system_instruction_addon": (
            "Interviewer Persona: Multi-Stakeholder Panel. Simulate alternating inquiries between an engineering manager, "
            "product lead, and senior peer. Focus on both business value and engineering execution."
        ),
        "question_prefix": "The panel would like to explore both business and technical angles: ",
        "probing_follow_up": False,
        "pacing": "holistic",
    },
}

STYLE_ALIASES: Dict[str, str] = {
    "friendly": "friendly",
    "friendly_hr": "friendly",
    "friendly-hr": "friendly",
    "hr": "friendly",
    "technical": "technical",
    "strict": "technical",
    "strict_technical": "technical",
    "strict-technical": "technical",
    "rapid": "rapid_fire",
    "rapid_fire": "rapid_fire",
    "rapid-fire": "rapid_fire",
    "panel": "panel",
}

DEFAULT_STYLE: str = "friendly"


def get_available_styles() -> List[Dict[str, Any]]:
    """Returns all available interviewer styles in display order."""
    order = ["friendly", "technical", "rapid_fire", "panel"]
    return [INTERVIEWER_STYLES[k] for k in order if k in INTERVIEWER_STYLES]


def normalize_style_id(style_id: Optional[str]) -> str:
    """Normalizes a raw style identifier into a canonical key."""
    if not style_id:
        return DEFAULT_STYLE
    clean = style_id.strip().lower().replace(" ", "_")
    return STYLE_ALIASES.get(clean, DEFAULT_STYLE)


def get_style_config(style_id: Optional[str]) -> Dict[str, Any]:
    """Retrieves the style configuration dictionary for a given style ID, with safe fallback."""
    canonical = normalize_style_id(style_id)
    return INTERVIEWER_STYLES.get(canonical, INTERVIEWER_STYLES[DEFAULT_STYLE])


def format_prompt_for_style(question_text: str, style_id: Optional[str]) -> str:
    """Formats interview question framing based on the chosen interviewer persona."""
    cfg = get_style_config(style_id)
    if not question_text:
        return ""
    # Maintain compatibility with legacy test label expectations
    label = "Strict Technical Architect" if cfg["id"] == "technical" else cfg["name"]
    return f"[{label} Mode] {question_text}"


def apply_interviewer_style_to_questions(
    questions: List[Dict[str, Any]], style_id: Optional[str]
) -> List[Dict[str, Any]]:
    """
    Applies the chosen persona styling to a list of generated interview questions:
    - Attaches style metadata and badge attributes.
    - Adjusts question phrasing tone and prefix.
    """
    cfg = get_style_config(style_id)
    styled_questions: List[Dict[str, Any]] = []

    for q in questions:
        q_copy = dict(q)
        q_copy["interviewer_style"] = cfg["id"]
        q_copy["interviewer_style_name"] = cfg["name"]
        q_copy["interviewer_style_badge"] = cfg["badge_class"]
        q_copy["interviewer_style_icon"] = cfg["icon"]

        # Adapt question wording if not already adapted
        raw_text = q_copy.get("question", "")
        if raw_text and not raw_text.startswith("[") and cfg["id"] != "friendly":
            # For rapid-fire: keep questions punchy and concise
            if cfg["id"] == "rapid_fire":
                # Ensure question is single-sentence punchy if possible
                sentences = raw_text.split(".")
                punchy = sentences[0].strip() + ("?" if not sentences[0].endswith("?") else "")
                q_copy["question"] = punchy
        styled_questions.append(q_copy)

    return styled_questions
