"""
Keyboard shortcut registry service (#634, #691).
Defines standard accessibility and productivity keybindings across major areas:
Search, Clear, Save Draft, and Navigation, with modal help dialog data.
"""

from typing import Dict, Any, List, Optional, Tuple

PLATFORM_SHORTCUTS = [
    {
        "category": "Global Navigation",
        "shortcuts": [
            {"keys": ["g", "d"], "action": "Go to Dashboard", "url": "/"},
            {"keys": ["g", "i"], "action": "Go to Mock Interview Practice", "url": "/interview"},
            {"keys": ["g", "t"], "action": "Go to Applications Tracker", "url": "/applications"},
            {"keys": ["g", "c"], "action": "Go to Coding Practice", "url": "/coding-practice"},
            {"keys": ["g", "h"], "action": "Go to Home / Dashboard (Alternate)", "url": "/"},
            {"keys": ["g", "p"], "action": "Go to Coding Practice (Alternate)", "url": "/coding-practice"},
            {"keys": ["g", "a"], "action": "Go to Applications Tracker (Alternate)", "url": "/applications"},
        ]
    },
    {
        "category": "Search & Help",
        "shortcuts": [
            {"keys": ["/"], "action": "Focus Search Bar", "url": "/search"},
            {"keys": ["?"], "action": "Show Keyboard Shortcuts Dialog", "url": None},
            {"keys": ["Escape"], "action": "Close Dialogs / Cancel", "url": None}
        ]
    },
    {
        "category": "Forms & Editors",
        "shortcuts": [
            {"keys": ["Control", "Enter"], "action": "Submit Answer / Run Code", "url": None},
            {"keys": ["Control", "s"], "action": "Save Draft / Checkpoint", "url": None},
            {"keys": ["Escape"], "action": "Close Modal / Cancel Input", "url": None}
        ]
    }
]


def get_keyboard_shortcuts() -> List[Dict[str, Any]]:
    """Returns platform keyboard shortcut definitions and bindings (#634, #691)."""
    return PLATFORM_SHORTCUTS


class KeyboardShortcutHandler:
    """
    Simulates and evaluates keyboard shortcut state machine logic (#691).
    Used for unit testing and backend verification of simulated key events.
    """
    NAVIGATION_MAP = {
        ("g", "d"): "/",
        ("g", "i"): "/interview",
        ("g", "t"): "/applications",
        ("g", "c"): "/coding-practice",
        ("g", "h"): "/",
        ("g", "p"): "/coding-practice",
        ("g", "a"): "/applications",
    }

    EDITABLE_TAGS = {"input", "textarea", "select"}
    NON_TYPING_INPUT_TYPES = {
        "button", "submit", "reset", "checkbox", "radio", "file", "image", "range", "color"
    }

    def __init__(self):
        self.pending_key: Optional[str] = None

    def is_editable(
        self,
        tag_name: str,
        input_type: Optional[str] = None,
        is_content_editable: bool = False
    ) -> bool:
        if is_content_editable:
            return True
        tag = (tag_name or "").lower()
        if tag in ("textarea", "select"):
            return True
        if tag == "input":
            itype = (input_type or "text").lower()
            return itype not in self.NON_TYPING_INPUT_TYPES
        return False

    def handle_key(
        self,
        key: str,
        ctrl_key: bool = False,
        alt_key: bool = False,
        meta_key: bool = False,
        shift_key: bool = False,
        tag_name: str = "body",
        input_type: Optional[str] = None,
        is_content_editable: bool = False,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Processes a key event and returns (action_type, target_value).
        action_type can be: 'navigate', 'focus_search', 'open_help', 'close_dialog', or None.
        """
        # 1. Ignore if typing inside form field or contenteditable element
        if self.is_editable(tag_name, input_type, is_content_editable):
            self.pending_key = None
            return None, None

        # 2. Ignore if modifier keys pressed (Ctrl, Alt, Meta)
        # Prevents hijacking Ctrl+Enter or browser combinations
        if ctrl_key or alt_key or meta_key:
            self.pending_key = None
            return None, None

        # 3. Escape key closes dialogs
        if key in ("Escape", "Esc"):
            self.pending_key = None
            return "close_dialog", None

        # 4. '?' opens the help dialog
        if key == "?":
            self.pending_key = None
            return "open_help", None

        # 5. '/' focuses search
        if key == "/":
            self.pending_key = None
            return "focus_search", None

        # 6. Navigation sequences starting with 'g'
        lower_key = key.lower()
        if self.pending_key == "g":
            pair = ("g", lower_key)
            self.pending_key = None
            if pair in self.NAVIGATION_MAP:
                return "navigate", self.NAVIGATION_MAP[pair]
            return None, None

        if lower_key == "g":
            self.pending_key = "g"
            return None, None

        self.pending_key = None
        return None, None
