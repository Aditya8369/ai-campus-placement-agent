"""
Coding hint ladder service (#615).
Provides graduated 3-level hints (Gentle Nudge, Conceptual Direction, Near-Solution Algorithm)
and records hint consumption count for user attempts without leaking full solutions prematurely.
"""

from typing import Dict, Any, List, Optional

PROBLEM_HINT_LADDERS = {
    "two-sum": [
        {"level": 1, "title": "Gentle Nudge", "hint": "Consider what value you need to pair with the current number to reach the target sum."},
        {"level": 2, "title": "Conceptual Direction", "hint": "Can you use a Hash Map (dictionary) to remember elements you have already inspected in O(1) time?"},
        {"level": 3, "title": "Algorithm Outline", "hint": "Iterate through the array. For each num, calculate complement = target - num. If complement is in seen_map, return indices [seen_map[complement], current_index]. Otherwise store seen_map[num] = current_index."}
    ],
    "default": [
        {"level": 1, "title": "Gentle Clue", "hint": "Check the problem constraints and boundary conditions (empty input, single element)."},
        {"level": 2, "title": "Data Structure Suggestion", "hint": "Consider whether sorting, a hash table, or two pointers can reduce time complexity."},
        {"level": 3, "title": "Algorithmic Approach", "hint": "Break down the core invariant and structure your loop invariants before implementing edge conditions."}
    ]
}

def get_hint_for_problem(problem_id: str, requested_level: int) -> Dict[str, Any]:
    """Returns a specific hint level (1, 2, or 3) for a problem."""
    ladder = PROBLEM_HINT_LADDERS.get(problem_id, PROBLEM_HINT_LADDERS["default"])
    level = max(1, min(3, requested_level))
    hint_obj = ladder[level - 1]
    return {
        "success": True,
        "problem_id": problem_id,
        "level": level,
        "title": hint_obj["title"],
        "hint": hint_obj["hint"],
        "has_next_hint": level < 3
    }
