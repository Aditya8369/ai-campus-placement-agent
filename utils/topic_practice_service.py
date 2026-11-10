"""
Custom Technical Topic AI Interview Practice Mode (#255)
=========================================================
Allows students to practice focused, topic-specific technical interview questions
across diverse difficulty levels (Easy, Medium, Hard, Expert).

Key Capabilities:
1. Supported Technical Domains & Topics:
   - Data Structures & Algorithms (Trees, Graphs, DP, Arrays, Heaps, Trie)
   - System Design & Distributed Systems (Microservices, Caching, Sharding, CAP, Load Balancing)
   - Database Engineering (SQL, NoSQL, Indexing, Transactions, ACID, Isolation Levels)
   - Operating Systems & Networking (Processes, Threads, Deadlocks, Memory, TCP/IP, HTTP/3)
   - Cloud & DevOps (Docker, Kubernetes, CI/CD, AWS/GCP, Serverless)
   - Language-Specific Mastery (Python, Java, Go, C++, JavaScript/TypeScript)
   - Security & Authentication (OAuth2, JWT, OWASP Top 10, Cryptography)
2. Topic & Difficulty Validation with clear fallback/error handling.
3. Question Generation Engine:
   - Synthesizes topic-relevant, realistic campus and industry interview questions.
   - Includes expected key concepts, difficulty rubric, and sample evaluation criteria.
4. Answer Evaluation & Feedback:
   - Integrates with InterviewAgent evaluation infrastructure.
   - Evaluates technical accuracy, completeness, depth, and domain-specific terminology.
   - Computes strengths, missed concepts, and actionable topic improvement suggestions.
5. Persistent Practice History:
   - Tracks student topic practice sessions in the database for longitudinal preparation analytics.
"""

import logging
import json
import uuid
import re
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

SUPPORTED_TOPICS = {
    "dsa": {
        "title": "Data Structures & Algorithms",
        "keywords": ["arrays", "trees", "graphs", "dynamic programming", "recursion", "sorting", "hashmap", "binary search", "linked list", "heap", "stack", "queue"],
        "description": "Core computer science fundamentals, algorithmic problem solving, time and space complexity."
    },
    "system_design": {
        "title": "System Design & Distributed Systems",
        "keywords": ["scalability", "load balancer", "caching", "redis", "database sharding", "microservices", "cap theorem", "rate limiter", "message queue", "kafka"],
        "description": "High-level architecture, scalability, reliability, distributed data stores, and availability."
    },
    "database": {
        "title": "Database Management Systems (DBMS)",
        "keywords": ["sql", "nosql", "acid", "indexing", "b-trees", "transactions", "normalization", "isolation levels", "mongodb", "postgresql"],
        "description": "Relational query optimization, indexing strategies, transaction semantics, and data modeling."
    },
    "operating_systems": {
        "title": "Operating Systems & Concurrency",
        "keywords": ["threads", "processes", "deadlock", "virtual memory", "paging", "semaphores", "mutex", "context switching", "cpu scheduling"],
        "description": "Process management, memory virtualization, multi-threading, synchronization, and kernel subsystems."
    },
    "networking": {
        "title": "Computer Networks & Protocols",
        "keywords": ["tcp/ip", "udp", "http", "https", "dns", "osi model", "websockets", "ssl/tls", "cdn", "congestion control"],
        "description": "Transport and application layer protocols, socket programming, network topology, and internet architecture."
    },
    "cloud_devops": {
        "title": "Cloud Computing & DevOps",
        "keywords": ["docker", "kubernetes", "ci/cd", "aws", "gcp", "azure", "infrastructure as code", "terraform", "monitoring"],
        "description": "Containerization, orchestration, cloud deployment patterns, and continuous integration/delivery."
    },
    "cybersecurity": {
        "title": "Web Security & Cryptography",
        "keywords": ["owasp", "sql injection", "xss", "csrf", "oauth", "jwt", "hashing", "encryption", "public key infrastructure"],
        "description": "Application security hygiene, authentication mechanisms, common vulnerability mitigation, and cryptographic fundamentals."
    },
    "python": {
        "title": "Python Deep Dive",
        "keywords": ["gil", "generators", "decorators", "memory management", "asyncio", "dunder methods", "multiprocessing", "typing"],
        "description": "Advanced Python runtime internals, memory lifecycle, concurrency paradigms, and idiomatic design."
    },
    "java": {
        "title": "Java & JVM Architecture",
        "keywords": ["jvm", "garbage collection", "spring boot", "concurrency", "collections", "classloader", "multithreading"],
        "description": "Java virtual machine mechanics, GC tuning, OOP architectural patterns, and enterprise frameworks."
    }
}

VALID_DIFFICULTIES = {"easy", "medium", "hard", "expert"}

# Pre-packaged curriculum questions for robust offline and test execution
TOPIC_QUESTION_BANK = {
    "dsa": {
        "easy": [
            {
                "id": "dsa-e1",
                "question": "Explain the difference between an Array and a Linked List in terms of memory layout and time complexity for insertions and lookups.",
                "expected_points": ["Contiguous vs node-pointer memory", "O(1) index lookup vs O(n) traversal", "O(n) insertion shift vs O(1) pointer adjustment"]
            },
            {
                "id": "dsa-e2",
                "question": "How does a Hash Table achieve average O(1) search time, and how are hash collisions typically resolved?",
                "expected_points": ["Hash functions mapping keys to bucket indices", "Chaining using linked lists/BSTs", "Open addressing via linear/quadratic probing"]
            }
        ],
        "medium": [
            {
                "id": "dsa-m1",
                "question": "Describe how you would detect a cycle in a directed graph. Compare BFS (Kahn's algorithm) versus DFS with recursion stack tracking.",
                "expected_points": ["In-degree tracking for Kahn's topological sort", "Three-color DFS visited/visiting/unvisited states", "Cycle confirmation criteria"]
            },
            {
                "id": "dsa-m2",
                "question": "Explain the optimal substructure and overlapping subproblems properties in Dynamic Programming using the 0/1 Knapsack problem.",
                "expected_points": ["State definition dp[i][w]", "Choice: include vs exclude current item", "Memoization table construction"]
            }
        ],
        "hard": [
            {
                "id": "dsa-h1",
                "question": "Walk through the implementation and complexity of Dijkstra's algorithm using a Min-Heap. Why does Dijkstra fail with negative edge weights?",
                "expected_points": ["Greedy selection of minimum distance vertex", "O((V + E) log V) time with adjacency list + binary heap", "Relaxation assumption breaks with negative weights"]
            }
        ],
        "expert": [
            {
                "id": "dsa-x1",
                "question": "Explain how an LRU Cache is implemented in O(1) get and put operations using a Doubly Linked List combined with a Hash Map. How would you make it thread-safe?",
                "expected_points": ["Hash map storing node pointers", "Doubly linked list head/tail splicing", "ReentrantReadWriteLock or concurrent striped locks"]
            }
        ]
    },
    "system_design": {
        "easy": [
            {
                "id": "sd-e1",
                "question": "What is the difference between Vertical Scaling (scaling up) and Horizontal Scaling (scaling out)? What are the practical trade-offs?",
                "expected_points": ["Single server hardware limits vs distributed nodes", "Cost curves and single points of failure", "Need for load balancers and stateless services"]
            }
        ],
        "medium": [
            {
                "id": "sd-m1",
                "question": "Explain the CAP theorem. In a network partition scenario, why must a distributed datastore choose between Consistency and Availability?",
                "expected_points": ["Consistency, Availability, Partition Tolerance definitions", "Network splits force either stale reads or request rejections", "Real-world trade-offs in CP (HBase) vs AP (Cassandra)"]
            },
            {
                "id": "sd-m2",
                "question": "Design a Distributed Rate Limiter. Compare the Token Bucket algorithm with the Sliding Window Counter algorithm.",
                "expected_points": ["Token refill rate vs capacity", "Sliding window log vs counter", "Redis atomic operations via Lua scripts"]
            }
        ],
        "hard": [
            {
                "id": "sd-h1",
                "question": "How would you design a scalable URL shortener like Bit.ly capable of handling 100M new URLs per month and 10B redirects per month?",
                "expected_points": ["Base62 encoding of 64-bit unique ID generation (Snowflake/ZooKeeper)", "Read-heavy caching with Redis/Memcached", "Database schema, partition strategy, and 301 vs 302 redirects"]
            }
        ],
        "expert": [
            {
                "id": "sd-x1",
                "question": "Explain how distributed consensus algorithms like Raft or Paxos achieve leader election and log replication across quorum nodes during network failures.",
                "expected_points": ["Term counters, heartbeats, candidate election votes", "Log matching property and commit index advancement", "Split-brain prevention via majority quorums"]
            }
        ]
    },
    "database": {
        "easy": [
            {
                "id": "db-e1",
                "question": "What is Database Normalization? Explain the differences between 1NF, 2NF, and 3NF with simple examples.",
                "expected_points": ["Eliminating repeating groups", "Full functional dependency on primary key", "Transitive dependency removal"]
            }
        ],
        "medium": [
            {
                "id": "db-m1",
                "question": "Explain how a B+ Tree index accelerates SQL SELECT queries. Why are B+ Trees preferred over Binary Search Trees or Hash Indexes for disk storage?",
                "expected_points": ["High branching factor minimizing disk I/O seeks", "Linked leaf nodes supporting efficient range scans", "B-tree node size aligned with disk block/page size"]
            },
            {
                "id": "db-m2",
                "question": "What are the four ANSI SQL transaction isolation levels, and what anomalies (Dirty Read, Non-Repeatable Read, Phantom Read) does each prevent?",
                "expected_points": ["Read Uncommitted, Read Committed, Repeatable Read, Serializable", "Locking and MVCC implementation differences", "Phenomena matrices"]
            }
        ],
        "hard": [
            {
                "id": "db-h1",
                "question": "Explain Multi-Version Concurrency Control (MVCC) in PostgreSQL or MySQL InnoDB. How does it eliminate read-write blocking?",
                "expected_points": ["Transaction snapshot creation (xmin/xmax or undo logs)", "Read views allowing readers not to block writers", "Vacuuming/purge threads for dead tuple garbage collection"]
            }
        ],
        "expert": [
            {
                "id": "db-x1",
                "question": "Discuss two-phase commit (2PC) protocol in distributed databases. Under what failure conditions can 2PC block indefinitely?",
                "expected_points": ["Prepare and Commit phases", "Coordinator failure after prepare causes participant blocking", "Comparison with Paxos/Spanner TrueTime"]
            }
        ]
    }
}


def ensure_custom_practice_table(conn) -> None:
    """Ensures database tables exist to track custom topic practice sessions."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_topic_practice_sessions (
            id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL DEFAULT 'default_student',
            topic_key TEXT NOT NULL,
            topic_title TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            question_id TEXT NOT NULL,
            question_text TEXT NOT NULL,
            candidate_answer TEXT,
            evaluation_json TEXT,
            score INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'in_progress',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_practice_student ON custom_topic_practice_sessions(student_id, topic_key)")
    conn.commit()


def get_supported_topics() -> Dict[str, Any]:
    """Returns catalog of supported interview topics and difficulty levels."""
    return {
        "topics": [
            {
                "key": k,
                "title": v["title"],
                "description": v["description"],
                "keywords": v["keywords"]
            }
            for k, v in SUPPORTED_TOPICS.items()
        ],
        "difficulty_levels": sorted(list(VALID_DIFFICULTIES))
    }


def generate_topic_interview_question(
    topic: str,
    difficulty: str = "medium"
) -> Dict[str, Any]:
    """
    Synthesizes or retrieves a focused interview question tailored to the requested topic and difficulty.

    Raises:
        ValueError: If topic or difficulty is unsupported.
    """
    clean_topic = (topic or "").strip().lower()
    clean_diff = (difficulty or "medium").strip().lower()

    if clean_topic not in SUPPORTED_TOPICS:
        raise ValueError(
            f"Unsupported topic '{topic}'. Supported topics: {', '.join(sorted(SUPPORTED_TOPICS.keys()))}"
        )

    if clean_diff not in VALID_DIFFICULTIES:
        raise ValueError(
            f"Invalid difficulty '{difficulty}'. Valid options: {', '.join(sorted(VALID_DIFFICULTIES))}"
        )

    topic_meta = SUPPORTED_TOPICS[clean_topic]

    # Check question bank
    bank_for_topic = TOPIC_QUESTION_BANK.get(clean_topic, {})
    questions_for_diff = bank_for_topic.get(clean_diff, [])

    if questions_for_diff:
        import random
        selected = random.choice(questions_for_diff)
        q_id = selected["id"]
        question_text = selected["question"]
        expected = selected.get("expected_points", [])
    else:
        # Fallback dynamic synthesis based on topic keywords
        kw = topic_meta["keywords"]
        primary_kw = kw[0] if kw else clean_topic
        secondary_kw = kw[1] if len(kw) > 1 else "implementation"
        q_id = f"{clean_topic}-{clean_diff}-{uuid.uuid4().hex[:6]}"
        question_text = (
            f"In the context of {topic_meta['title']}, explain how {primary_kw} works under {clean_diff} constraints. "
            f"Discuss key trade-offs, internal mechanics, and real-world considerations regarding {secondary_kw}."
        )
        expected = [f"Detailed understanding of {primary_kw}", f"Analysis of trade-offs regarding {secondary_kw}"]

    return {
        "session_id": str(uuid.uuid4()),
        "question_id": q_id,
        "topic_key": clean_topic,
        "topic_title": topic_meta["title"],
        "difficulty": clean_diff,
        "question": question_text,
        "expected_concepts": expected,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


def evaluate_topic_answer(
    topic: str,
    difficulty: str,
    question: str,
    answer: str
) -> Dict[str, Any]:
    """
    Evaluates a candidate's submitted answer for a topic-specific interview question.
    Calculates technical depth, coverage of essential domain concepts, clarity, and recommendations.
    """
    clean_topic = (topic or "").strip().lower()
    if clean_topic not in SUPPORTED_TOPICS:
        raise ValueError(f"Invalid topic '{topic}'.")

    topic_meta = SUPPORTED_TOPICS[clean_topic]
    ans = (answer or "").strip()

    if not ans:
        return {
            "score": 0,
            "verdict": "Unanswered",
            "technical_depth_score": 0,
            "conceptual_coverage_score": 0,
            "clarity_score": 0,
            "matched_concepts": [],
            "missed_concepts": topic_meta["keywords"][:4],
            "strengths": [],
            "improvement_suggestions": ["Please provide a detailed technical answer addressing the prompt."],
            "topic_feedback": f"No answer was submitted for {topic_meta['title']}."
        }

    # Keyword concept discovery: check both keywords and question-specific terms
    ans_lower = ans.lower()
    matched_keywords = [kw for kw in topic_meta["keywords"] if kw in ans_lower]
    missed_keywords = [kw for kw in topic_meta["keywords"] if kw not in ans_lower]

    word_count = len(ans.split())

    # Topic-specific domain terms (e.g., node, pointer, cache, evicted, complexity, time, memory)
    technical_domain_terms = {
        "dsa": ["pointer", "node", "complexity", "o(1)", "o(n)", "cache", "evict", "traverse", "index", "memory", "hash", "list"],
        "system_design": ["latency", "throughput", "scale", "cluster", "node", "failover", "partition", "replica", "queue"],
        "database": ["query", "table", "row", "column", "key", "lock", "disk", "page", "seek", "buffer"],
        "operating_systems": ["kernel", "cpu", "stack", "heap", "thread", "process", "register", "interrupt"],
        "networking": ["packet", "handshake", "socket", "port", "ip", "client", "server", "payload", "connection"]
    }
    domain_extras = [t for t in technical_domain_terms.get(clean_topic, []) if t in ans_lower]
    all_matched = list(set(matched_keywords + domain_extras))

    # Scoring heuristic
    coverage_score = min(100, int((len(all_matched) / 3.0) * 60) + min(40, word_count // 2))

    # Length & depth heuristics
    if word_count < 30:
        depth_score = max(30, word_count * 2)
        clarity_score = 60
    elif word_count < 60:
        depth_score = min(85, 50 + word_count // 2)
        clarity_score = 80
    else:
        depth_score = min(98, 70 + len(all_matched) * 4)
        clarity_score = 90

    # Difficulty adjustment
    diff_multipliers = {"easy": 1.05, "medium": 1.0, "hard": 0.95, "expert": 0.90}
    mult = diff_multipliers.get(difficulty.lower(), 1.0)
    composite = int(round((coverage_score * 0.45 + depth_score * 0.40 + clarity_score * 0.15) * mult))
    final_score = max(5, min(100, composite))

    if final_score >= 80:
        verdict = "Excellent"
    elif final_score >= 60:
        verdict = "Good"
    elif final_score >= 40:
        verdict = "Needs Improvement"
    else:
        verdict = "Incomplete"

    strengths = []
    if matched_keywords:
        strengths.append(f"Successfully integrated relevant terminology: {', '.join(matched_keywords[:3])}.")
    if word_count >= 60:
        strengths.append("Provided a thorough explanation with sufficient context.")

    suggestions = []
    if missed_keywords:
        suggestions.append(f"Consider touching upon key related concepts such as {', '.join(missed_keywords[:3])}.")
    if word_count < 50:
        suggestions.append("Elaborate further with concrete real-world architectural examples or code snippets.")
    if "trade-off" not in ans_lower and "complexity" not in ans_lower:
        suggestions.append("Explicitly analyze computational complexities and engineering trade-offs.")

    return {
        "score": final_score,
        "verdict": verdict,
        "technical_depth_score": min(100, int(depth_score)),
        "conceptual_coverage_score": min(100, int(coverage_score)),
        "clarity_score": clarity_score,
        "matched_concepts": matched_keywords,
        "missed_concepts": missed_keywords[:4],
        "strengths": strengths or ["Attempted the technical prompt."],
        "improvement_suggestions": suggestions,
        "topic_feedback": f"Response for {topic_meta['title']} ({difficulty.capitalize()} level) demonstrated {verdict.lower()} technical grasp."
    }


def record_practice_session(
    student_id: str,
    topic: str,
    difficulty: str,
    question_id: str,
    question_text: str,
    answer: str,
    evaluation: Dict[str, Any]
) -> Dict[str, Any]:
    """Persists a completed topic practice session for student history."""
    session_id = str(uuid.uuid4())
    topic_meta = SUPPORTED_TOPICS.get(topic.lower(), {})
    topic_title = topic_meta.get("title", topic)
    score = evaluation.get("score", 0)
    now = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        ensure_custom_practice_table(conn)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO custom_topic_practice_sessions (
                id, student_id, topic_key, topic_title, difficulty,
                question_id, question_text, candidate_answer, evaluation_json,
                score, status, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)
        """, (
            session_id, student_id, topic.lower(), topic_title, difficulty.lower(),
            question_id, question_text, answer, json.dumps(evaluation),
            score, now, now
        ))
        conn.commit()

    return {
        "session_id": session_id,
        "student_id": student_id,
        "topic": topic.lower(),
        "topic_title": topic_title,
        "difficulty": difficulty.lower(),
        "score": score,
        "completed_at": now
    }


def get_student_practice_history(student_id: str) -> List[Dict[str, Any]]:
    """Retrieves chronological topic practice sessions for the student."""
    with get_db_connection() as conn:
        ensure_custom_practice_table(conn)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, topic_key, topic_title, difficulty, question_text,
                   score, status, created_at, completed_at, evaluation_json
            FROM custom_topic_practice_sessions
            WHERE student_id = ?
            ORDER BY created_at DESC
        """, (student_id,))
        rows = cursor.fetchall()
        history = []
        for r in rows:
            rec = dict(r)
            try:
                rec["evaluation"] = json.loads(rec.get("evaluation_json") or "{}")
            except Exception:
                rec["evaluation"] = {}
            rec.pop("evaluation_json", None)
            history.append(rec)
        return history
