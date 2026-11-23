"""
Answer Benchmark Service (#610)
Provides a community/contributor-maintained repository of good, average, and poor
interview responses across technical, behavioral, and HR categories.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional

BENCHMARK_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "answer_benchmarks.json"

def get_answer_benchmarks(category: Optional[str] = None, topic: Optional[str] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieves answer benchmarks, optionally filtered by category, topic, or keyword search.
    """
    if not BENCHMARK_DATA_FILE.exists():
        return []

    try:
        with open(BENCHMARK_DATA_FILE, "r", encoding="utf-8") as f:
            benchmarks = json.load(f)
    except Exception:
        return []

    results = []
    cat_filter = category.lower().strip() if category else None
    topic_filter = topic.lower().strip() if topic else None
    search_filter = search.lower().strip() if search else None

    for item in benchmarks:
        if cat_filter and item.get("category", "").lower() != cat_filter:
            continue
        if topic_filter and topic_filter not in item.get("topic", "").lower():
            continue
        if search_filter:
            q_text = item.get("question", "").lower()
            topic_text = item.get("topic", "").lower()
            if search_filter not in q_text and search_filter not in topic_text:
                continue
        results.append(item)

    return results

def get_benchmark_by_id(benchmark_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a single benchmark item by ID."""
    benchmarks = get_answer_benchmarks()
    for b in benchmarks:
        if b.get("id") == benchmark_id:
            return b
    return None
