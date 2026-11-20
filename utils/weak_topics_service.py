"""
Weak Topics Aggregation Notebook Service (#559)
================================================
Aggregates weak focus areas across multiple student activities:
1. Low-scored mock interview answers (score < 70) and custom topic practice sessions.
2. Missing skills & weaknesses identified in the student's latest resume analysis.
3. Coding practice marked as difficult (bookmarked Hard problems and failed submissions).

Features:
- Purely computed from stored database records (Zero extra AI calls).
- Merges topic names and canonical aliases (e.g. 'dp' -> 'Dynamic Programming').
- Computes occurrence counts and aggregates evidence.
- Status transitions: 'active' (default), 'improving', 'resolved'.
- Hides resolved topics by default, keeping them recoverable.
- Strict multi-tenant isolation ensuring only the signed-in user's records are read/updated.
"""

import json
import logging
import re
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional, Tuple

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

# Canonical synonym dictionary: lowercase raw string -> (canonical_key, canonical_display_name)
CANONICAL_SYNONYMS: Dict[str, Tuple[str, str]] = {
    # Algorithms & Core DSA
    "dp": ("dynamic_programming", "Dynamic Programming"),
    "dynamic programming": ("dynamic_programming", "Dynamic Programming"),
    "dynamic_programming": ("dynamic_programming", "Dynamic Programming"),
    "dsa": ("data_structures_algorithms", "Data Structures & Algorithms"),
    "data structures": ("data_structures_algorithms", "Data Structures & Algorithms"),
    "data structures & algorithms": ("data_structures_algorithms", "Data Structures & Algorithms"),
    "data structures and algorithms": ("data_structures_algorithms", "Data Structures & Algorithms"),
    "algorithms": ("data_structures_algorithms", "Data Structures & Algorithms"),
    "two pointers": ("two_pointers", "Two Pointers"),
    "two-pointers": ("two_pointers", "Two Pointers"),
    "sliding window": ("sliding_window", "Sliding Window"),
    "sliding-window": ("sliding_window", "Sliding Window"),
    "binary search": ("binary_search", "Binary Search"),
    "binary tree": ("binary_trees", "Binary Trees"),
    "binary trees": ("binary_trees", "Binary Trees"),
    "trees": ("binary_trees", "Binary Trees"),
    "bst": ("binary_trees", "Binary Trees"),
    "graphs": ("graphs", "Graphs & BFS/DFS"),
    "graph": ("graphs", "Graphs & BFS/DFS"),
    "graphs & bfs/dfs": ("graphs", "Graphs & BFS/DFS"),
    "bfs": ("graphs", "Graphs & BFS/DFS"),
    "dfs": ("graphs", "Graphs & BFS/DFS"),
    "topological sort": ("graphs", "Graphs & BFS/DFS"),
    "linked list": ("linked_lists", "Linked Lists"),
    "linked lists": ("linked_lists", "Linked Lists"),
    "arrays": ("arrays_hashing", "Arrays & Hashing"),
    "arrays & hashing": ("arrays_hashing", "Arrays & Hashing"),
    "hashmap": ("arrays_hashing", "Arrays & Hashing"),
    "hash table": ("arrays_hashing", "Arrays & Hashing"),
    "recursion": ("recursion_backtracking", "Recursion & Backtracking"),
    "backtracking": ("recursion_backtracking", "Recursion & Backtracking"),
    "heaps": ("heaps_priority_queues", "Heaps & Priority Queues"),
    "heap": ("heaps_priority_queues", "Heaps & Priority Queues"),
    "trie": ("trie", "Trie"),
    "greedy": ("greedy_algorithms", "Greedy Algorithms"),

    # Systems & Architecture
    "system design": ("system_design", "System Design"),
    "system-design": ("system_design", "System Design"),
    "distributed systems": ("system_design", "System Design"),
    "microservices": ("system_design", "System Design"),
    "scalability": ("system_design", "System Design"),
    "caching": ("system_design", "System Design"),
    "load balancing": ("system_design", "System Design"),
    "database": ("database_systems", "Database Systems"),
    "databases": ("database_systems", "Database Systems"),
    "dbms": ("database_systems", "Database Systems"),
    "sql": ("sql", "SQL"),
    "nosql": ("nosql", "NoSQL"),
    "postgresql": ("postgresql", "PostgreSQL"),
    "postgres": ("postgresql", "PostgreSQL"),
    "mysql": ("mysql", "MySQL"),
    "mongodb": ("mongodb", "MongoDB"),
    "redis": ("redis", "Redis"),
    "operating systems": ("operating_systems", "Operating Systems"),
    "operating system": ("operating_systems", "Operating Systems"),
    "os": ("operating_systems", "Operating Systems"),
    "concurrency": ("operating_systems", "Operating Systems"),
    "multithreading": ("operating_systems", "Operating Systems"),
    "networking": ("computer_networking", "Computer Networking"),
    "computer networks": ("computer_networking", "Computer Networking"),
    "tcp/ip": ("computer_networking", "Computer Networking"),

    # Cloud, DevOps & Engineering
    "docker": ("docker", "Docker"),
    "kubernetes": ("kubernetes", "Kubernetes"),
    "k8s": ("kubernetes", "Kubernetes"),
    "devops": ("devops_cloud", "DevOps & Cloud"),
    "ci/cd": ("ci_cd", "CI/CD"),
    "aws": ("aws", "AWS"),
    "gcp": ("gcp", "GCP"),
    "cloud": ("devops_cloud", "DevOps & Cloud"),
    "terraform": ("terraform", "Terraform"),
    "linux": ("linux", "Linux"),

    # Languages & Frameworks
    "python": ("python", "Python"),
    "java": ("java", "Java"),
    "c++": ("cpp", "C++"),
    "cpp": ("cpp", "C++"),
    "javascript": ("javascript", "JavaScript"),
    "typescript": ("typescript", "TypeScript"),
    "react": ("react", "React"),
    "reactjs": ("react", "React"),
    "node.js": ("nodejs", "Node.js"),
    "nodejs": ("nodejs", "Node.js"),
    "rest api": ("rest_api", "REST API"),
    "graphql": ("graphql", "GraphQL"),
    "git": ("git", "Git"),
    "oop": ("object_oriented_programming", "Object Oriented Programming"),
    "object oriented programming": ("object_oriented_programming", "Object Oriented Programming"),
}

# Known acronyms to preserve uppercase in display names
UPPERCASE_ACRONYMS = {
    "sql", "nosql", "aws", "gcp", "dsa", "dbms", "api", "rest", "ci/cd", "cd", "ci",
    "tcp/ip", "tcp", "udp", "http", "https", "dns", "os", "ip", "oop", "jwt", "oauth",
    "html", "css", "ui", "ux", "cpu", "ram", "iot", "ai", "ml", "nlp"
}

# Heuristic topic detection keywords for interview questions lacking an explicit topic tag
KEYWORD_TO_TOPIC = [
    ("dynamic_programming", "Dynamic Programming", ["dynamic programming", "dp", "memoization", "bottom-up", "knapsack"]),
    ("database_systems", "Database Systems", ["database", "dbms", "sql", "indexing", "b-tree", "acid", "normalization", "postgres", "mysql", "mongodb", "transactions"]),
    ("system_design", "System Design", ["system design", "distributed system", "scalability", "load balancer", "microservices", "caching", "redis", "sharding", "cap theorem", "kafka"]),
    ("operating_systems", "Operating Systems", ["operating system", "os", "deadlock", "process", "thread", "virtual memory", "paging", "mutex", "semaphore", "concurrency"]),
    ("computer_networking", "Computer Networking", ["networking", "network", "tcp", "udp", "http", "https", "dns", "three-way handshake", "socket"]),
    ("binary_trees", "Binary Trees", ["binary tree", "tree traversal", "bst", "lowest common ancestor"]),
    ("graphs", "Graphs & BFS/DFS", ["graph", "bfs", "dfs", "dijkstra", "topological sort"]),
    ("docker", "Docker", ["docker", "container", "dockerfile", "containerization"]),
    ("kubernetes", "Kubernetes", ["kubernetes", "k8s", "pod", "deployment", "kubectl"]),
    ("arrays_hashing", "Arrays & Hashing", ["array", "hash map", "hash table", "hashmap", "two sum"]),
    ("linked_lists", "Linked Lists", ["linked list", "doubly linked"]),
    ("object_oriented_programming", "Object Oriented Programming", ["oop", "polymorphism", "inheritance", "encapsulation", "design patterns"]),
]


def normalize_topic_name(raw_name: str) -> Tuple[str, str]:
    """
    Normalizes and canonicalizes a raw topic or skill name.
    Merges casing differences, removes excess whitespace, maps known synonyms/aliases,
    and returns a tuple of (topic_key, display_name).

    Examples:
        'docker' -> ('docker', 'Docker')
        ' Docker  ' -> ('docker', 'Docker')
        'dp' -> ('dynamic_programming', 'Dynamic Programming')
        'Dynamic Programming' -> ('dynamic_programming', 'Dynamic Programming')
        'two-pointers' -> ('two_pointers', 'Two Pointers')
    """
    if not raw_name or not str(raw_name).strip():
        return "general_technical", "General Technical"

    cleaned = str(raw_name).strip()
    lookup_key = cleaned.lower()

    # 1. Exact alias / synonym match
    if lookup_key in CANONICAL_SYNONYMS:
        return CANONICAL_SYNONYMS[lookup_key]

    # 2. Check without hyphens / underscores
    simplified = re.sub(r"[\-_]+", " ", lookup_key).strip()
    if simplified in CANONICAL_SYNONYMS:
        return CANONICAL_SYNONYMS[simplified]

    # 3. Slugify key for grouping
    topic_key = re.sub(r"[^a-z0-9]+", "_", lookup_key).strip("_")
    if not topic_key:
        topic_key = "topic"

    # 4. Synthesize clean display name
    words = re.split(r"[\s_\-]+", cleaned)
    display_words = []
    for w in words:
        if not w:
            continue
        w_lower = w.lower()
        if w_lower in UPPERCASE_ACRONYMS:
            display_words.append(w.upper())
        elif w.isupper() and len(w) <= 5:
            display_words.append(w)
        else:
            display_words.append(w.capitalize())

    display_name = " ".join(display_words) if display_words else cleaned
    return topic_key, display_name


def ensure_weak_topic_status_table() -> None:
    """
    Ensures the student_weak_topic_statuses table exists in the database.
    Stores status transitions ('active', 'improving', 'resolved') per student and topic.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS student_weak_topic_statuses (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                topic_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                notes TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(student_id, topic_key)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_student_weak_topic_statuses
            ON student_weak_topic_statuses (student_id, topic_key)
        """)
        conn.commit()
    except Exception as e:
        logger.error(f"Error ensuring student_weak_topic_statuses table: {e}")
    finally:
        conn.close()


def _infer_topic_from_question(question_text: str, default_type: str = "Technical") -> Tuple[str, str]:
    """Infers canonical topic key and display name from question phrasing when no explicit tag exists."""
    q_lower = (question_text or "").lower()
    for key, display, keywords in KEYWORD_TO_TOPIC:
        if any(kw in q_lower for kw in keywords):
            return key, display
    return normalize_topic_name(default_type)


def extract_interview_weak_topics(student_id: str) -> List[Dict[str, Any]]:
    """
    Extracts weak areas from low-scored interview answers (score < 70).
    Queries both full mock interviews and custom topic practice sessions for the student.
    """
    results: List[Dict[str, Any]] = []
    effective_student_id = (student_id or "default_student").strip()
    conn = get_db_connection()

    try:
        cursor = conn.cursor()

        # 1. Mock interview sessions joined with analyses for this student
        cursor.execute("""
            SELECT i.id, i.analysis_id, i.questions_json, i.answers_json, a.company_name, a.created_at
            FROM interviews i
            JOIN analyses a ON i.analysis_id = a.id
            WHERE a.student_id = ?
            ORDER BY a.created_at DESC, i.id DESC
        """, (effective_student_id,))
        rows = cursor.fetchall()

        for r in rows:
            rec = dict(r)
            try:
                questions = json.loads(rec.get("questions_json") or "[]")
            except Exception:
                questions = []
            try:
                answers = json.loads(rec.get("answers_json") or "[]")
            except Exception:
                answers = []

            # Map questions by index or question string for easy lookup
            q_map = {}
            for q in questions:
                if isinstance(q, dict):
                    idx = q.get("index")
                    if idx is not None:
                        q_map[idx] = q
                    if q.get("question"):
                        q_map[q.get("question").strip()] = q

            for ans in answers:
                if not isinstance(ans, dict):
                    continue
                eval_data = ans.get("evaluation") or {}
                if not isinstance(eval_data, dict):
                    eval_data = {}

                # Score resolution: check score, technical_accuracy, or overall_score
                score = eval_data.get("score")
                if score is None:
                    score = eval_data.get("technical_accuracy")
                if score is None:
                    score = eval_data.get("overall_score")

                if score is None:
                    continue

                try:
                    score_val = float(score)
                except (ValueError, TypeError):
                    continue

                if score_val < 70.0:
                    q_idx = ans.get("question_index")
                    q_obj = q_map.get(q_idx) or q_map.get((ans.get("question") or "").strip()) or {}
                    q_text = ans.get("question") or q_obj.get("question") or "Interview Question"

                    # Determine topic name
                    raw_topic = (
                        ans.get("topic")
                        or q_obj.get("topic")
                        or q_obj.get("category")
                        or None
                    )
                    if not raw_topic:
                        key, display = _infer_topic_from_question(q_text, ans.get("type", "Technical"))
                    else:
                        key, display = normalize_topic_name(raw_topic)

                    company_prefix = f" ({rec.get('company_name')})" if rec.get("company_name") else ""
                    clean_q_preview = (q_text[:75] + "...") if len(q_text) > 75 else q_text
                    evidence_msg = f"Low score ({int(score_val)}/100) on interview question{company_prefix}: \"{clean_q_preview}\""

                    results.append({
                        "source": "interview",
                        "topic_key": key,
                        "topic_name": display,
                        "raw_topic": raw_topic or display,
                        "score": score_val,
                        "evidence": evidence_msg,
                        "analysis_id": rec.get("analysis_id"),
                        "company_name": rec.get("company_name", "")
                    })

        # 2. Check custom topic practice sessions if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='custom_topic_practice_sessions'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT id, topic_key, topic_title, difficulty, question_text, score, created_at
                FROM custom_topic_practice_sessions
                WHERE student_id = ? AND score < 70
                ORDER BY created_at DESC
            """, (effective_student_id,))
            session_rows = cursor.fetchall()
            for s_row in session_rows:
                s_rec = dict(s_row)
                t_key, t_display = normalize_topic_name(s_rec.get("topic_title") or s_rec.get("topic_key") or "Technical")
                q_txt = (s_rec.get("question_text") or "Practice Question").strip()
                clean_q_preview = (q_txt[:75] + "...") if len(q_txt) > 75 else q_txt
                sc = s_rec.get("score", 0)
                evidence_msg = f"Low score ({sc}/100) in {t_display} practice: \"{clean_q_preview}\""
                results.append({
                    "source": "interview",
                    "topic_key": t_key,
                    "topic_name": t_display,
                    "raw_topic": s_rec.get("topic_title") or t_display,
                    "score": sc,
                    "evidence": evidence_msg,
                    "analysis_id": None,
                    "company_name": ""
                })

    except Exception as e:
        logger.error(f"Error extracting interview weak topics for {student_id}: {e}")
    finally:
        conn.close()

    return results


def extract_analysis_skill_gaps(student_id: str) -> List[Dict[str, Any]]:
    """
    Extracts missing skills and weaknesses from the student's latest resume analysis.
    """
    results: List[Dict[str, Any]] = []
    effective_student_id = (student_id or "default_student").strip()
    conn = get_db_connection()

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, company_name, target_role, results_json, created_at
            FROM analyses
            WHERE student_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        """, (effective_student_id,))
        row = cursor.fetchone()

        if row:
            rec = dict(row)
            try:
                res = json.loads(rec.get("results_json") or "{}")
            except Exception:
                res = {}

            company_name = rec.get("company_name") or "Target Role"
            analysis_id = rec.get("id")

            # Collect raw missing skill strings from standard analysis fields
            raw_skills: List[str] = []

            # 1. skill_gap list (can be dicts with 'missing_skill' or direct strings)
            for item in res.get("skill_gap") or []:
                if isinstance(item, dict):
                    skill_name = item.get("missing_skill") or item.get("skill") or item.get("topic")
                    if skill_name:
                        raw_skills.append(str(skill_name))
                elif isinstance(item, str) and item.strip():
                    raw_skills.append(item.strip())

            # 2. job_match missing_skills
            job_match = res.get("job_match") or {}
            if isinstance(job_match, dict):
                for skill in job_match.get("missing_skills") or []:
                    if isinstance(skill, str) and skill.strip():
                        raw_skills.append(skill.strip())

            # 3. resume_analysis missing_skills & weaknesses
            resume_analysis = res.get("resume_analysis") or {}
            if isinstance(resume_analysis, dict):
                for skill in resume_analysis.get("missing_skills") or []:
                    if isinstance(skill, str) and skill.strip():
                        raw_skills.append(skill.strip())
                for weakness in resume_analysis.get("weaknesses") or []:
                    if isinstance(weakness, str) and weakness.strip():
                        raw_skills.append(weakness.strip())

            # Deduplicate raw skills while preserving order
            seen_skills = set()
            for skill in raw_skills:
                norm_key = skill.strip().lower()
                if norm_key in seen_skills:
                    continue
                seen_skills.add(norm_key)

                t_key, t_display = normalize_topic_name(skill)
                evidence_msg = f"Missing skill identified in latest analysis for {company_name}: {t_display}"
                results.append({
                    "source": "analysis",
                    "topic_key": t_key,
                    "topic_name": t_display,
                    "raw_topic": skill,
                    "evidence": evidence_msg,
                    "analysis_id": analysis_id,
                    "company_name": company_name
                })

    except Exception as e:
        logger.error(f"Error extracting analysis skill gaps for {student_id}: {e}")
    finally:
        conn.close()

    return results


def extract_coding_difficult_topics(student_id: str) -> List[Dict[str, Any]]:
    """
    Extracts weak areas from coding practice marked as difficult:
    - Bookmarked coding problems with 'Hard' difficulty.
    - Coding submissions that failed or scored below threshold.
    """
    results: List[Dict[str, Any]] = []
    effective_student_id = (student_id or "default_student").strip()
    conn = get_db_connection()

    try:
        cursor = conn.cursor()

        # 1. Bookmarked coding questions marked as 'Hard'
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bookmarked_coding_questions'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT problem_id, problem_data, created_at
                FROM bookmarked_coding_questions
                WHERE student_id = ?
                ORDER BY created_at DESC
            """, (effective_student_id,))
            rows = cursor.fetchall()
            for r in rows:
                rec = dict(r)
                try:
                    prob = json.loads(rec.get("problem_data") or "{}")
                except Exception:
                    prob = {}

                difficulty = str(prob.get("difficulty") or "").strip().lower()
                if difficulty == "hard":
                    raw_topic = prob.get("topic") or prob.get("category") or "Algorithms"
                    title = prob.get("title") or prob.get("id") or "Hard Problem"
                    t_key, t_display = normalize_topic_name(raw_topic)
                    evidence_msg = f"Difficult coding challenge bookmarked: {title} (Hard)"
                    results.append({
                        "source": "coding",
                        "topic_key": t_key,
                        "topic_name": t_display,
                        "raw_topic": raw_topic,
                        "problem_title": title,
                        "difficulty": "Hard",
                        "evidence": evidence_msg,
                    })

        # 2. Failed or low-scoring coding submissions
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='coding_submissions'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT question_title, passed, score, language, submitted_at
                FROM coding_submissions
                WHERE student_id = ? AND (passed = 0 OR score < 60)
                ORDER BY submitted_at DESC
            """, (effective_student_id,))
            sub_rows = cursor.fetchall()

            # Import catalog for problem topic lookup
            catalog_by_title = {}
            try:
                from agents.coding_practice_agent import DSA_PROBLEMS_CATALOG
                for p in DSA_PROBLEMS_CATALOG:
                    if isinstance(p, dict):
                        catalog_by_title[p.get("title", "").strip().lower()] = p
            except Exception:
                pass

            for s in sub_rows:
                s_rec = dict(s)
                q_title = s_rec.get("question_title", "Coding Problem").strip()
                cat_match = catalog_by_title.get(q_title.lower())

                raw_topic = cat_match.get("topic") if cat_match else "Algorithms"
                t_key, t_display = normalize_topic_name(raw_topic)

                score_str = f"score: {s_rec.get('score', 0)}" if s_rec.get("score") is not None else "failed"
                evidence_msg = f"Unresolved coding submission: {q_title} ({score_str})"
                results.append({
                    "source": "coding",
                    "topic_key": t_key,
                    "topic_name": t_display,
                    "raw_topic": raw_topic,
                    "problem_title": q_title,
                    "difficulty": cat_match.get("difficulty", "Medium") if cat_match else "Medium",
                    "evidence": evidence_msg,
                })

    except Exception as e:
        logger.error(f"Error extracting coding weak topics for {student_id}: {e}")
    finally:
        conn.close()

    return results


def get_student_weak_topics(
    student_id: str,
    include_resolved: bool = False
) -> Dict[str, Any]:
    """
    Aggregates weak topics across all 3 sources (interviews, resume skill gaps, coding),
    merging topics by canonical key, accumulating counts and specific evidence.
    Overlays student status transitions ('active', 'improving', 'resolved').
    Hides resolved topics by default while keeping them recoverable.
    """
    ensure_weak_topic_status_table()
    effective_student_id = (student_id or "default_student").strip()

    # 1. Extract signals from each source
    interview_signals = extract_interview_weak_topics(effective_student_id)
    analysis_signals = extract_analysis_skill_gaps(effective_student_id)
    coding_signals = extract_coding_difficult_topics(effective_student_id)

    # 2. Retrieve student status overrides from student_weak_topic_statuses
    status_overrides: Dict[str, Dict[str, Any]] = {}
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT topic_key, status, notes, updated_at
            FROM student_weak_topic_statuses
            WHERE student_id = ?
        """, (effective_student_id,))
        for row in cursor.fetchall():
            rec = dict(row)
            status_overrides[rec["topic_key"]] = rec
    except Exception as e:
        logger.error(f"Error reading weak topic statuses for {effective_student_id}: {e}")
    finally:
        conn.close()

    # 3. Aggregate by canonical topic_key
    topics_map: Dict[str, Dict[str, Any]] = {}

    all_signals = interview_signals + analysis_signals + coding_signals

    for sig in all_signals:
        t_key = sig["topic_key"]
        t_name = sig["topic_name"]
        source = sig["source"]

        if t_key not in topics_map:
            topics_map[t_key] = {
                "topic_key": t_key,
                "topic_name": t_name,
                "total_count": 0,
                "interview_count": 0,
                "analysis_count": 0,
                "coding_count": 0,
                "evidence_list": [],
                "latest_analysis_id": sig.get("analysis_id"),
                "status": "active",
                "notes": "",
                "updated_at": None,
                "practice_links": {
                    "interview_url": "/topic-practice",
                    "coding_url": f"/coding-practice?skills={urllib.parse.quote(t_name)}",
                    "roadmap_url": "/dashboard#roadmapSection",
                }
            }

        topic_entry = topics_map[t_key]
        topic_entry["total_count"] += 1

        if source == "interview":
            topic_entry["interview_count"] += 1
            if sig.get("analysis_id"):
                topic_entry["practice_links"]["interview_url"] = f"/interview/{sig['analysis_id']}"
        elif source == "analysis":
            topic_entry["analysis_count"] += 1
            if sig.get("analysis_id"):
                topic_entry["latest_analysis_id"] = sig["analysis_id"]
                topic_entry["practice_links"]["roadmap_url"] = f"/dashboard/{sig['analysis_id']}#roadmapSection"
        elif source == "coding":
            topic_entry["coding_count"] += 1

        if sig.get("evidence"):
            topic_entry["evidence_list"].append({
                "source": source,
                "text": sig["evidence"]
            })

    # 4. Also support topics that were previously tracked in student_weak_topic_statuses
    #    even if currently without signals (e.g. marked resolved previously)
    for t_key, meta in status_overrides.items():
        if t_key not in topics_map and include_resolved:
            _, display_name = normalize_topic_name(t_key)
            topics_map[t_key] = {
                "topic_key": t_key,
                "topic_name": display_name,
                "total_count": 0,
                "interview_count": 0,
                "analysis_count": 0,
                "coding_count": 0,
                "evidence_list": [{"source": "manual", "text": "Previously tracked topic"}],
                "latest_analysis_id": None,
                "status": meta.get("status", "active"),
                "notes": meta.get("notes", ""),
                "updated_at": meta.get("updated_at"),
                "practice_links": {
                    "interview_url": "/topic-practice",
                    "coding_url": f"/coding-practice?skills={urllib.parse.quote(display_name)}",
                    "roadmap_url": "/dashboard#roadmapSection",
                }
            }

    # 5. Apply status overrides to all aggregated topics
    all_topics: List[Dict[str, Any]] = []
    total_active = 0
    total_improving = 0
    total_resolved = 0

    for t_key, entry in topics_map.items():
        if t_key in status_overrides:
            entry["status"] = status_overrides[t_key].get("status", "active")
            entry["notes"] = status_overrides[t_key].get("notes", "")
            entry["updated_at"] = status_overrides[t_key].get("updated_at")

        if entry["status"] == "improving":
            total_improving += 1
        elif entry["status"] == "resolved":
            total_resolved += 1
        else:
            entry["status"] = "active"
            total_active += 1

        all_topics.append(entry)

    # 6. Filter resolved topics if not include_resolved
    if not include_resolved:
        filtered_topics = [t for t in all_topics if t["status"] != "resolved"]
    else:
        filtered_topics = list(all_topics)

    # 7. Sort: active & improving first (highest occurrence count descending), then resolved
    def _sort_key(item: Dict[str, Any]) -> Tuple[int, int, str]:
        # 0 for active/improving, 1 for resolved
        resolved_rank = 1 if item["status"] == "resolved" else 0
        return (resolved_rank, -item["total_count"], item["topic_name"].lower())

    filtered_topics.sort(key=_sort_key)

    return {
        "student_id": effective_student_id,
        "topics": filtered_topics,
        "summary": {
            "total": len(all_topics),
            "active": total_active,
            "improving": total_improving,
            "resolved": total_resolved,
            "visible_count": len(filtered_topics),
        },
        "include_resolved": include_resolved,
    }


def update_weak_topic_status(
    student_id: str,
    topic_key: str,
    status: str,
    notes: str = ""
) -> Tuple[bool, Optional[str]]:
    """
    Updates or creates a status record for a student's weak topic ('active', 'improving', 'resolved').
    Returns (success, error_message).
    """
    ensure_weak_topic_status_table()
    effective_student_id = (student_id or "default_student").strip()
    norm_key = (topic_key or "").strip().lower()

    if not norm_key:
        return False, "Topic key is required."

    allowed_statuses = {"active", "improving", "resolved"}
    clean_status = (status or "").strip().lower()
    if clean_status not in allowed_statuses:
        return False, f"Invalid status '{status}'. Must be one of: {', '.join(sorted(allowed_statuses))}."

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        record_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO student_weak_topic_statuses (
                id, student_id, topic_key, status, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(student_id, topic_key) DO UPDATE SET
                status = excluded.status,
                notes = CASE WHEN excluded.notes != '' THEN excluded.notes ELSE student_weak_topic_statuses.notes END,
                updated_at = CURRENT_TIMESTAMP
        """, (record_id, effective_student_id, norm_key, clean_status, notes))
        conn.commit()
        return True, None
    except Exception as e:
        logger.error(f"Error updating weak topic status for {effective_student_id}, {norm_key}: {e}")
        return False, f"Database error updating weak topic status: {str(e)}"
    finally:
        conn.close()
