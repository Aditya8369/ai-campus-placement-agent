"""
Keyboard shortcut registry service (#634).
Defines standard accessibility and productivity keybindings across major areas:
Search, Clear, Save Draft, and Navigation, with modal help dialog data.
"""

from typing import Dict, Any, List

PLATFORM_SHORTCUTS = [
    {
        "category": "Global Navigation",
        "shortcuts": [
            {"keys": ["g", "h"], "action": "Go to Home / Dashboard", "url": "/"},
            {"keys": ["g", "p"], "action": "Go to Coding Practice", "url": "/practice"},
            {"keys": ["g", "a"], "action": "Go to Applications Tracker", "url": "/applications"},
            {"keys": ["g", "i"], "action": "Go to Mock Interview", "url": "/interview"},
            {"keys": ["?"], "action": "Show Keyboard Shortcuts Modal", "url": None}
        ]
    },
    {
        "category": "Forms & Editors",
        "shortcuts": [
            {"keys": ["Control", "s"], "action": "Save Draft / Checkpoint", "url": None},
            {"keys": ["Control", "Enter"], "action": "Submit Answer / Run Code", "url": None},
            {"keys": ["Escape"], "action": "Close Modal / Cancel Input", "url": None}
        ]
    }
]

def get_keyboard_shortcuts() -> List[Dict[str, Any]]:
    return PLATFORM_SHORTCUTS
