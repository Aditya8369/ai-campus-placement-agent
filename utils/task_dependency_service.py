"""
Preparation Task Dependency Service (#606)
==========================================
Manages prerequisite relationships between preparation tasks (e.g. Arrays -> Dynamic Programming,
Basic SQL -> Sharding/Indexing).

Guarantees:
- Tasks can declare prerequisite task IDs.
- Tracks task status: 'locked' (unmet prerequisites), 'available' (prerequisites satisfied), 'completed'.
- Prevents completing dependent tasks before all prerequisites are marked completed.
- Detects and rejects circular dependencies using cycle detection (DFS).
- Allows students to add/edit personal task dependencies safely.
"""

from typing import Dict, Any, List, Optional, Set, Tuple


DEFAULT_TASK_DEPENDENCY_GRAPH = [
    {
        "id": "task_arrays",
        "title": "Arrays, Strings & Two-Pointer Basics",
        "category": "Data Structures",
        "prerequisites": [],
        "description": "Master array operations, two-pointer techniques, and prefix sums."
    },
    {
        "id": "task_linked_lists",
        "title": "Linked Lists & Pointer Manipulation",
        "category": "Data Structures",
        "prerequisites": ["task_arrays"],
        "description": "Singly and doubly linked lists, fast & slow pointers, reversing."
    },
    {
        "id": "task_trees",
        "title": "Binary Trees, BSTs & Traversals",
        "category": "Data Structures",
        "prerequisites": ["task_linked_lists"],
        "description": "Tree traversals (BFS, DFS, Inorder, Preorder, Postorder), diameter, height."
    },
    {
        "id": "task_graphs",
        "title": "Graphs & Topological Sort",
        "category": "Algorithms",
        "prerequisites": ["task_trees"],
        "description": "Adjacency lists, BFS, DFS, Dijkstra, cycle detection, topological sort."
    },
    {
        "id": "task_dp",
        "title": "Dynamic Programming & Recursion",
        "category": "Algorithms",
        "prerequisites": ["task_arrays", "task_trees"],
        "description": "Memoization, tabulation, 1D/2D knapsack and subsequence patterns."
    },
    {
        "id": "task_sql_basics",
        "title": "Relational Databases & SQL Queries",
        "category": "Databases",
        "prerequisites": [],
        "description": "CRUD operations, joins, group by, aggregations, primary & foreign keys."
    },
    {
        "id": "task_sql_advanced",
        "title": "Database Indexing, CTEs & Transactions",
        "category": "Databases",
        "prerequisites": ["task_sql_basics"],
        "description": "B-trees, query plans, isolation levels, ACID guarantees, window functions."
    },
    {
        "id": "task_system_design",
        "title": "Distributed System Architecture & Caching",
        "category": "System Design",
        "prerequisites": ["task_sql_advanced", "task_graphs"],
        "description": "Scalability, load balancers, CDN, Redis cache-aside, message queues."
    }
]


def detect_cycle_in_dependencies(tasks: List[Dict[str, Any]]) -> Tuple[bool, Optional[List[str]]]:
    """
    Detects whether adding or having a set of task dependencies creates a circular dependency.
    Returns (has_cycle, cycle_path).
    """
    adj: Dict[str, List[str]] = {}
    for t in tasks:
        tid = t["id"]
        adj[tid] = list(t.get("prerequisites", []))

    visited: Set[str] = set()
    rec_stack: Set[str] = set()
    cycle_path: List[str] = []

    def dfs(node: str, path: List[str]) -> bool:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                if dfs(neighbor, path):
                    return True
            elif neighbor in rec_stack:
                cycle_path.extend(path[path.index(neighbor):] + [neighbor])
                return True

        rec_stack.remove(node)
        path.pop()
        return False

    for task_id in list(adj.keys()):
        if task_id not in visited:
            if dfs(task_id, []):
                return True, cycle_path

    return False, None


def evaluate_task_dependency_states(
    tasks: List[Dict[str, Any]],
    completed_task_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Evaluates availability of each task in the dependency graph.
    Status values:
    - 'completed': Task is marked done.
    - 'available': All prerequisites are completed.
    - 'locked': One or more prerequisites are pending.
    """
    has_cycle, cycle_info = detect_cycle_in_dependencies(tasks)
    if has_cycle:
        raise ValueError(f"Circular dependency detected: {' -> '.join(cycle_info or [])}")

    completed_set = set(completed_task_ids or [])
    task_map = {t["id"]: t for t in tasks}

    evaluated_tasks: List[Dict[str, Any]] = []

    for t in tasks:
        tid = t["id"]
        prereqs = t.get("prerequisites", [])
        
        # Check unmet prerequisites
        unmet_prereqs = [p for p in prereqs if p not in completed_set]
        unmet_titles = [task_map[p]["title"] for p in unmet_prereqs if p in task_map]

        if tid in completed_set:
            status = "completed"
        elif len(unmet_prereqs) == 0:
            status = "available"
        else:
            status = "locked"

        evaluated_tasks.append({
            "id": tid,
            "title": t["title"],
            "category": t.get("category", "General"),
            "description": t.get("description", ""),
            "prerequisites": prereqs,
            "unmet_prerequisites": unmet_prereqs,
            "unmet_prerequisite_titles": unmet_titles,
            "status": status,
            "can_complete": status == "available"
        })

    return {
        "status": "success",
        "tasks": evaluated_tasks,
        "completed_count": len(completed_set),
        "available_count": sum(1 for t in evaluated_tasks if t["status"] == "available"),
        "locked_count": sum(1 for t in evaluated_tasks if t["status"] == "locked")
    }


def complete_task_with_validation(
    task_id: str,
    tasks: List[Dict[str, Any]],
    completed_task_ids: List[str]
) -> Tuple[bool, Optional[str], List[str]]:
    """
    Validates whether a task can be marked as complete.
    Prevents marking complete if any prerequisite is unfinished.
    Returns (success, error_message, updated_completed_task_ids).
    """
    task_map = {t["id"]: t for t in tasks}
    target = task_map.get(task_id)
    if not target:
        return False, f"Task '{task_id}' not found.", completed_task_ids

    completed_set = set(completed_task_ids)
    unmet = [p for p in target.get("prerequisites", []) if p not in completed_set]

    if unmet:
        unmet_titles = [task_map.get(p, {}).get("title", p) for p in unmet]
        return False, f"Cannot complete task '{target['title']}' because prerequisites are unfinished: {', '.join(unmet_titles)}.", completed_task_ids

    completed_set.add(task_id)
    return True, None, sorted(list(completed_set))
