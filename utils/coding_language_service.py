"""
Coding editor multi-language switcher service (#614).
Manages language options, syntax mappings, validation, and language-specific draft storage.
"""

from typing import Dict, Any, List

SUPPORTED_LANGUAGES = {
    "python": {
        "id": "python",
        "name": "Python 3",
        "monaco_lang": "python",
        "extension": ".py",
        "default_boilerplate": "def solve():\n    # Write your solution here\n    pass\n"
    },
    "javascript": {
        "id": "javascript",
        "name": "JavaScript (Node.js)",
        "monaco_lang": "javascript",
        "extension": ".js",
        "default_boilerplate": "function solve() {\n    // Write your solution here\n}\n"
    },
    "java": {
        "id": "java",
        "name": "Java 17",
        "monaco_lang": "java",
        "extension": ".java",
        "default_boilerplate": "public class Solution {\n    public static void main(String[] args) {\n        // Write solution\n    }\n}\n"
    },
    "cpp": {
        "id": "cpp",
        "name": "C++ (GCC)",
        "monaco_lang": "cpp",
        "extension": ".cpp",
        "default_boilerplate": "#include <iostream>\nusing namespace std;\n\nint main() {\n    // Write solution\n    return 0;\n}\n"
    }
}

def get_supported_languages() -> List[Dict[str, Any]]:
    return list(SUPPORTED_LANGUAGES.values())

def is_language_supported(lang_id: str) -> bool:
    return bool(lang_id and lang_id.lower().strip() in SUPPORTED_LANGUAGES)

def get_language_config(lang_id: str) -> Dict[str, Any]:
    clean_id = (lang_id or "python").lower().strip()
    return SUPPORTED_LANGUAGES.get(clean_id, SUPPORTED_LANGUAGES["python"])
