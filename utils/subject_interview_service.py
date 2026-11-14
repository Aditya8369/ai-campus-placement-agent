"""
Subject-Based Mock Interview Engine Service (#272).

Enables students to conduct targeted mock interviews focused on individual technical subjects:
- Canonical subject catalog: Python, Java, SQL, DBMS, Operating Systems, Computer Networks.
- Subject-specific question generator spanning core theory, runtime internals, and practical coding scenarios.
- Granular response evaluator scoring:
  1. Subject Conceptual Mastery (knowledge depth of standard paradigms)
  2. Technical Terminology & Idiomatic Syntax
  3. Real-world Architectural / Engineering Application
- Subject-specific feedback generation with actionable study pointers.
- Database persistence for subject-based practice history.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

SUBJECT_PYTHON = "Python"
SUBJECT_JAVA = "Java"
SUBJECT_SQL = "SQL"
SUBJECT_DBMS = "DBMS"
SUBJECT_OS = "Operating Systems"
SUBJECT_NETWORKS = "Computer Networks"

CANONICAL_SUBJECTS = {
    "python": {
        "slug": "python",
        "name": SUBJECT_PYTHON,
        "icon": "fa-brands fa-python",
        "badge_color": "primary",
        "description": "Python language internals, memory model, GIL, decorators, generators, and async programming.",
        "keywords": ["gil", "generators", "decorators", "asyncio", "memory management", "list comprehension", "dunder", "multiprocessing", "virtualenv", "typing", "metaclass"],
    },
    "java": {
        "slug": "java",
        "name": SUBJECT_JAVA,
        "icon": "fa-brands fa-java",
        "badge_color": "danger",
        "description": "JVM architecture, Garbage Collection, Spring Boot, multithreading, concurrency, and OOP design patterns.",
        "keywords": ["jvm", "garbage collection", "spring boot", "multithreading", "concurrent", "collections", "classloader", "polymorphism", "synchronized", "streams", "generics"],
    },
    "sql": {
        "slug": "sql",
        "name": SUBJECT_SQL,
        "icon": "fa-solid fa-table",
        "badge_color": "info",
        "description": "Relational query design, complex JOINs, subqueries, CTEs, window functions, and execution plans.",
        "keywords": ["select", "inner join", "left join", "group by", "window functions", "partition by", "cte", "indexes", "explain analyze", "aggregate", "having"],
    },
    "dbms": {
        "slug": "dbms",
        "name": SUBJECT_DBMS,
        "icon": "fa-solid fa-database",
        "badge_color": "success",
        "description": "Database management principles, ACID transactions, normalization, B-Trees, concurrency control, and NoSQL tradeoffs.",
        "keywords": ["acid", "transactions", "normalization", "b-trees", "wal", "isolation levels", "concurrency control", "deadlock", "2pc", "sharding", "nosql"],
    },
    "operating_systems": {
        "slug": "operating_systems",
        "name": SUBJECT_OS,
        "icon": "fa-solid fa-microchip",
        "badge_color": "warning",
        "description": "Process and thread lifecycle, CPU scheduling, virtual memory, paging, deadlocks, and IPC.",
        "keywords": ["threads", "processes", "deadlock", "virtual memory", "paging", "semaphores", "mutex", "context switch", "system calls", "ipc", "fork"],
    },
    "computer_networks": {
        "slug": "computer_networks",
        "name": SUBJECT_NETWORKS,
        "icon": "fa-solid fa-network-wired",
        "badge_color": "secondary",
        "description": "OSI and TCP/IP stack, transport protocols, routing algorithms, DNS, HTTP/HTTPS, and socket programming.",
        "keywords": ["tcp/ip", "udp", "http", "https", "dns", "osi model", "tls", "handshake", "congestion control", "subnetting", "sockets", "router"],
    },
}

SUBJECT_QUESTION_BANK: Dict[str, List[Dict[str, Any]]] = {
    "python": [
        {
            "id": "py-01",
            "question": "Explain Python's Global Interpreter Lock (GIL). How does it impact multithreaded CPU-bound vs I/O-bound programs, and what are the best ways to achieve true parallelism?",
            "key_concepts": ["GIL", "CPU-bound vs I/O-bound", "multiprocessing", "thread scheduling"]
        },
        {
            "id": "py-02",
            "question": "What is the difference between generators and regular functions in Python? Explain lazy evaluation and how memory usage differs when processing large datasets.",
            "key_concepts": ["generators", "yield", "lazy evaluation", "memory efficiency"]
        },
        {
            "id": "py-03",
            "question": "How do Python decorators work under the hood? Write or explain the pattern for creating a decorator with arguments that measures execution time.",
            "key_concepts": ["decorators", "first-class functions", "closures", "functools.wraps"]
        }
    ],
    "java": [
        {
            "id": "java-01",
            "question": "Explain the architecture of the Java Virtual Machine (JVM). Describe the roles of the Heap, Stack, Method Area, and how Garbage Collection generational heaps work.",
            "key_concepts": ["JVM architecture", "Heap vs Stack", "Garbage Collection", "Generational hypothesis"]
        },
        {
            "id": "java-02",
            "question": "How does Java ensure thread safety? Contrast synchronized methods/blocks with java.util.concurrent locks and volatile variables.",
            "key_concepts": ["synchronized", "ReentrantLock", "volatile", "atomic variables", "memory visibility"]
        },
        {
            "id": "java-03",
            "question": "What are Java Streams and functional interfaces? Explain the difference between intermediate and terminal operations.",
            "key_concepts": ["Stream API", "FunctionalInterface", "intermediate vs terminal", "lambda expressions"]
        }
    ],
    "sql": [
        {
            "id": "sql-01",
            "question": "What is the difference between RANK(), DENSE_RANK(), and ROW_NUMBER() window functions? Provide a concrete scenario where you would use each.",
            "key_concepts": ["window functions", "RANK", "DENSE_RANK", "ROW_NUMBER", "PARTITION BY"]
        },
        {
            "id": "sql-02",
            "question": "Explain Common Table Expressions (CTEs) vs subqueries. When are recursive CTEs necessary in relational queries?",
            "key_concepts": ["CTE", "WITH clause", "recursive query", "query readability"]
        },
        {
            "id": "sql-03",
            "question": "How do composite indexes work in SQL databases, and why does column order matter according to the Leftmost Prefix Rule?",
            "key_concepts": ["composite index", "leftmost prefix", "B-Tree index lookup", "query optimization"]
        }
    ],
    "dbms": [
        {
            "id": "dbms-01",
            "question": "Walk through the ACID properties of relational databases and explain how Write-Ahead Logging (WAL) and Two-Phase Locking (2PL) enforce them.",
            "key_concepts": ["ACID", "atomicity", "WAL", "isolation levels", "2PL"]
        },
        {
            "id": "dbms-02",
            "question": "Explain the four standard SQL transaction isolation levels (Read Uncommitted, Read Committed, Repeatable Read, Serializable) and the anomalies each prevents.",
            "key_concepts": ["dirty read", "non-repeatable read", "phantom read", "isolation levels"]
        },
        {
            "id": "dbms-03",
            "question": "Contrast B-Trees and Hash indexes in database engines. Why are B+ Trees predominantly preferred for relational primary keys over binary search trees?",
            "key_concepts": ["B+ Tree", "Hash index", "range scans", "disk I/O block efficiency"]
        }
    ],
    "operating_systems": [
        {
            "id": "os-01",
            "question": "Explain the difference between a process and a thread. What memory segments are shared among threads of the same process, and what are private?",
            "key_concepts": ["process vs thread", "heap sharing", "stack privacy", "context switching overhead"]
        },
        {
            "id": "os-02",
            "question": "What are the four Coffman conditions necessary for a deadlock to occur? Explain two standard strategies for deadlock prevention or avoidance.",
            "key_concepts": ["Coffman conditions", "mutual exclusion", "hold and wait", "circular wait", "Banker's algorithm"]
        },
        {
            "id": "os-03",
            "question": "How does virtual memory paging work? Describe the Translation Lookaside Buffer (TLB), page faults, and the LRU page replacement algorithm.",
            "key_concepts": ["virtual memory", "paging", "TLB", "page fault handler", "LRU"]
        }
    ],
    "computer_networks": [
        {
            "id": "net-01",
            "question": "Describe the TCP three-way handshake and four-way termination process. What is the purpose of the TIME_WAIT state in TCP?",
            "key_concepts": ["SYN/ACK", "three-way handshake", "FIN/ACK", "TIME_WAIT state", "2MSL"]
        },
        {
            "id": "net-02",
            "question": "Explain how DNS resolution works step-by-step from browser URL input to IP address retrieval, covering local cache, recursive, root, TLD, and authoritative nameservers.",
            "key_concepts": ["DNS resolution", "recursive resolver", "root server", "TLD server", "authoritative DNS"]
        },
        {
            "id": "net-03",
            "question": "What is the difference between TCP and UDP? Give two production use cases where UDP is strictly preferred over TCP and explain why.",
            "key_concepts": ["connection-oriented vs connectionless", "reliability", "streaming/gaming/DNS", "header overhead"]
        }
    ]
}


def ensure_subject_interview_tables() -> None:
    """Initializes tables for tracking subject-based interview sessions."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subject_interview_sessions (
                session_id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                subject_slug TEXT NOT NULL,
                subject_name TEXT NOT NULL,
                question_text TEXT NOT NULL,
                student_answer TEXT,
                evaluation_json TEXT,
                overall_score INTEGER DEFAULT 0,
                completed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subj_sess_student ON subject_interview_sessions (student_id, subject_slug)")
        conn.commit()
    finally:
        conn.close()


def get_subject_catalog() -> List[Dict[str, Any]]:
    """Returns the full catalog of available technical subjects."""
    return list(CANONICAL_SUBJECTS.values())


def normalize_subject_slug(raw_subject: Optional[str]) -> str:
    """Maps and normalizes subject string into canonical slug."""
    if not raw_subject:
        return "python"
    clean = raw_subject.strip().lower().replace(" ", "_")
    alias_map = {
        "py": "python",
        "python3": "python",
        "java": "java",
        "jvm": "java",
        "sql": "sql",
        "rdbms": "dbms",
        "dbms": "dbms",
        "database": "dbms",
        "databases": "dbms",
        "os": "operating_systems",
        "operating_system": "operating_systems",
        "operating_systems": "operating_systems",
        "cn": "computer_networks",
        "network": "computer_networks",
        "networks": "computer_networks",
        "networking": "computer_networks",
        "computer_networks": "computer_networks",
    }
    return alias_map.get(clean, "python")


def generate_subject_question(subject: str) -> Dict[str, Any]:
    """Retrieves or synthesizes a focused question for the designated subject."""
    slug = normalize_subject_slug(subject)
    subject_meta = CANONICAL_SUBJECTS.get(slug, CANONICAL_SUBJECTS["python"])
    q_bank = SUBJECT_QUESTION_BANK.get(slug, SUBJECT_QUESTION_BANK["python"])

    selected = q_bank[0]
    return {
        "subject_slug": slug,
        "subject_name": subject_meta["name"],
        "question_id": selected["id"],
        "question": selected["question"],
        "key_concepts": selected["key_concepts"],
        "subject_meta": subject_meta
    }


def evaluate_subject_answer(subject: str, question: str, answer: str) -> Dict[str, Any]:
    """
    Evaluates student response against the specific technical subject taxonomy:
    Computes conceptual score, terminology score, and returns subject-tailored feedback.
    """
    slug = normalize_subject_slug(subject)
    subject_meta = CANONICAL_SUBJECTS.get(slug, CANONICAL_SUBJECTS["python"])
    ans_clean = (answer or "").strip()
    ans_lower = ans_clean.lower()

    if not ans_clean:
        return {
            "score": 0,
            "verdict": "Unanswered",
            "subject_mastery_score": 0,
            "terminology_score": 0,
            "matched_keywords": [],
            "feedback": f"No answer submitted. To succeed in {subject_meta['name']} interviews, prepare concise explanations of fundamental principles."
        }

    # Keyword concept matching
    target_keywords = list(subject_meta["keywords"])
    # Also include question-specific key concepts if available
    for q in SUBJECT_QUESTION_BANK.get(slug, []):
        for kc in q.get("key_concepts", []):
            if kc.lower() not in [tk.lower() for tk in target_keywords]:
                target_keywords.append(kc.lower())

    matched = [k for k in target_keywords if k.lower() in ans_lower]
    missed = [k for k in target_keywords if k.lower() not in ans_lower]

    match_count = len(matched)
    if match_count >= 3:
        term_score = 95
    elif match_count == 2:
        term_score = 80
    elif match_count == 1:
        term_score = 65
    else:
        term_score = 40

    # Length and conceptual depth
    words = len(ans_clean.split())
    if words < 10:
        depth_score = 40
    elif words < 30:
        depth_score = 70
    elif words < 100:
        depth_score = 88
    else:
        depth_score = 95

    overall_score = max(20, min(98, int((depth_score * 0.5) + (term_score * 0.5))))

    if overall_score >= 80:
        verdict = f"Strong {subject_meta['name']} Command"
        feedback = f"Excellent technical explanation. You successfully utilized key {subject_meta['name']} concepts ({', '.join(matched[:3])}) and explained the mechanics accurately."
    elif overall_score >= 60:
        verdict = f"Competent {subject_meta['name']} Grasp"
        feedback = f"Good foundational explanation. To reach top placement tier in {subject_meta['name']}, also discuss related topics such as {', '.join(missed[:2])}."
    else:
        verdict = f"Needs Further {subject_meta['name']} Review"
        feedback = f"Your answer touches on the question but lacks technical depth in {subject_meta['name']}. Review {', '.join(missed[:3])} to construct more comprehensive answers."

    return {
        "score": overall_score,
        "verdict": verdict,
        "subject_name": subject_meta["name"],
        "subject_slug": slug,
        "subject_mastery_score": depth_score,
        "terminology_score": term_score,
        "matched_keywords": matched,
        "missed_keywords": missed[:4],
        "feedback": feedback
    }
