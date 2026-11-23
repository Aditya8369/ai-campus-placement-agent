"""
Coding performance comparison service (#617).
Compares candidate solution execution time and memory against canonical baselines,
labeling small variations as approximate without exposing other students' private data.
"""

from typing import Dict, Any, Optional

CANONICAL_PERFORMANCE_BASELINES = {
    "two-sum": {
        "optimal_time_complexity": "O(N)",
        "optimal_space_complexity": "O(N)",
        "baseline_runtime_ms": 45,
        "baseline_memory_mb": 17.5,
        "explanation": "One-pass hash map achieves linear time by trading linear auxiliary space."
    },
    "default": {
        "optimal_time_complexity": "O(N log N)",
        "optimal_space_complexity": "O(1)",
        "baseline_runtime_ms": 60,
        "baseline_memory_mb": 18.0,
        "explanation": "Standard benchmark solution uses standard in-place algorithms."
    }
}

def compare_performance(problem_id: str, candidate_time_ms: Optional[float], candidate_memory_mb: Optional[float]) -> Dict[str, Any]:
    baseline = CANONICAL_PERFORMANCE_BASELINES.get(problem_id, CANONICAL_PERFORMANCE_BASELINES["default"])

    if candidate_time_ms is None or candidate_memory_mb is None:
        return {
            "success": True,
            "status": "fallback",
            "message": "Performance metrics unavailable for this submission environment.",
            "baseline": baseline
        }

    # Time delta
    time_delta = candidate_time_ms - baseline["baseline_runtime_ms"]
    time_pct = round((abs(time_delta) / baseline["baseline_runtime_ms"]) * 100, 1)
    if abs(time_delta) <= 5:
        time_status = "Comparable to optimal baseline (~within variation limits)"
    elif time_delta < 0:
        time_status = f"{time_pct}% faster than canonical baseline"
    else:
        time_status = f"{time_pct}% slower than canonical baseline"

    # Memory delta
    mem_delta = candidate_memory_mb - baseline["baseline_memory_mb"]
    mem_pct = round((abs(mem_delta) / baseline["baseline_memory_mb"]) * 100, 1)
    if abs(mem_delta) <= 1.0:
        mem_status = "Comparable memory usage (~within variation limits)"
    elif mem_delta < 0:
        mem_status = f"{mem_pct}% more memory efficient than baseline"
    else:
        mem_status = f"{mem_pct}% higher memory usage than baseline"

    return {
        "success": True,
        "status": "measured",
        "units": {
            "time": "milliseconds (ms)",
            "memory": "megabytes (MB)"
        },
        "candidate": {
            "runtime_ms": round(candidate_time_ms, 1),
            "memory_mb": round(candidate_memory_mb, 1)
        },
        "baseline": {
            "runtime_ms": baseline["baseline_runtime_ms"],
            "memory_mb": baseline["baseline_memory_mb"],
            "optimal_time_complexity": baseline["optimal_time_complexity"],
            "optimal_space_complexity": baseline["optimal_space_complexity"],
            "complexity_notes": baseline["explanation"]
        },
        "comparison": {
            "time_assessment": time_status,
            "memory_assessment": mem_status,
            "disclaimer": "Measurements are approximate and subject to runtime environment variations."
        }
    }
