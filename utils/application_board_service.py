"""
Application tracker board service (#619).
Validates stage transitions, keyboard navigation moves, and drag-and-drop operations
between application tracking columns (Applied, Assessment, Interview, Selected, Rejected).
"""

from typing import Dict, Any, List

VALID_BOARD_COLUMNS = ["Applied", "Assessment", "Interview", "Selected", "Rejected"]

def validate_stage_transition(current_stage: str, target_stage: str, requires_confirmation: bool = False) -> Dict[str, Any]:
    if target_stage not in VALID_BOARD_COLUMNS:
        return {
            "valid": False,
            "error": f"Invalid target stage '{target_stage}'. Valid stages: {', '.join(VALID_BOARD_COLUMNS)}"
        }

    # Moving to terminal stages like Rejected or Withdrawn requires confirmation
    needs_confirm = target_stage in ["Rejected"] and not requires_confirmation

    return {
        "valid": True,
        "current_stage": current_stage,
        "target_stage": target_stage,
        "requires_confirmation": needs_confirm,
        "message": "Confirmation recommended for rejection/withdrawal" if needs_confirm else "Valid transition"
    }

def get_next_previous_stages(current_stage: str) -> Dict[str, Any]:
    """Provides keyboard-navigable stage movements (left/right column shifts)."""
    if current_stage not in VALID_BOARD_COLUMNS:
        idx = 0
    else:
        idx = VALID_BOARD_COLUMNS.index(current_stage)

    prev_stage = VALID_BOARD_COLUMNS[idx - 1] if idx > 0 else None
    next_stage = VALID_BOARD_COLUMNS[idx + 1] if idx < len(VALID_BOARD_COLUMNS) - 1 else None

    return {
        "current_stage": current_stage,
        "previous_stage": prev_stage,
        "next_stage": next_stage
    }
