"""
Interview Question Difficulty Selection Service (#266).

Provides:
- Supported difficulty tiers: Beginner, Intermediate, Advanced.
- Difficulty-aware question generator, question categorizer, and fallback banks.
- Dynamic question scaling: calibrating technical depth, behavioral complexity,
  and HR scenarios to match candidate preparation level.
- Display metadata and difficulty persistence in session records.
- Validation and fallback handling for invalid or unspecified difficulties.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DIFFICULTY_BEGINNER = "Beginner"
DIFFICULTY_INTERMEDIATE = "Intermediate"
DIFFICULTY_ADVANCED = "Advanced"

VALID_DIFFICULTIES = {
    DIFFICULTY_BEGINNER.lower(): DIFFICULTY_BEGINNER,
    DIFFICULTY_INTERMEDIATE.lower(): DIFFICULTY_INTERMEDIATE,
    DIFFICULTY_ADVANCED.lower(): DIFFICULTY_ADVANCED,
}

DEFAULT_DIFFICULTY = DIFFICULTY_INTERMEDIATE

# Curated question catalogs categorized by tier
DIFFICULTY_QUESTION_CATALOG: Dict[str, Dict[str, List[str]]] = {
    DIFFICULTY_BEGINNER: {
        "hr": [
            "Tell me about yourself, your educational background, and your key interests.",
            "Why did you choose your major and what subjects did you enjoy the most?",
            "What extracurricular activities or campus projects are you most proud of?",
            "What motivates you to pursue a career in technology and software engineering?",
            "How do you usually organize your study schedule and project deadlines?"
        ],
        "technical": [
            "What is the difference between a variable and a constant in programming?",
            "Explain the difference between an Array and a Linked List with simple examples.",
            "What are the four fundamental pillars of Object-Oriented Programming (OOP)?",
            "What is a primary key in a relational database and why is it important?",
            "What is the difference between HTTP and HTTPS?"
        ],
        "behavioral": [
            "Describe a time you collaborated with classmates on a group assignment.",
            "Tell me about a time you encountered a coding bug that took effort to fix.",
            "How do you handle situations when you don't know the answer to a question in class?",
            "Share an example of a goal you set for yourself and how you achieved it.",
            "Describe a situation where a teammate disagreed with your idea and how you reached consensus."
        ]
    },
    DIFFICULTY_INTERMEDIATE: {
        "hr": [
            "Tell me about yourself and how your internship/project experience aligns with this role.",
            "Why are you interested in joining our engineering team specifically?",
            "What are your core technical strengths and two areas you are actively improving?",
            "Where do you see your technical trajectory five years from now?",
            "How do you manage stress and prioritize competing feature deliveries?"
        ],
        "technical": [
            "Explain the time and space complexity differences between QuickSort and MergeSort.",
            "What are database indexes, how do B-Trees work under the hood, and when can indexing hurt performance?",
            "Explain the concept of RESTful API design and how idempotency applies to HTTP methods.",
            "How does asynchronous programming (e.g. event loop, promises, async/await) differ from multi-threading?",
            "Explain how virtual memory, paging, and page faults operate in modern operating systems."
        ],
        "behavioral": [
            "Describe a challenging technical project where you faced unexpected scope changes.",
            "Tell me about a time you had to learn an unfamiliar library or framework under tight deadlines.",
            "Share an instance where you made an engineering mistake in code and how you resolved it.",
            "Describe a situation where you had to advocate for code quality or testing against a delivery deadline.",
            "How do you give constructive peer review feedback when reviewing pull requests?"
        ]
    },
    DIFFICULTY_ADVANCED: {
        "hr": [
            "Walk me through your engineering journey, key architectural achievements, and technical philosophy.",
            "How do you evaluate engineering trade-offs between rapid product iteration and long-term tech debt?",
            "Describe how you stay ahead of fast-evolving distributed systems and AI technologies.",
            "What kind of engineering culture brings out your best performance, and what role do you play in fostering it?",
            "Tell me about a high-stakes engineering initiative you spearheaded with cross-functional dependencies."
        ],
        "technical": [
            "How would you design a globally distributed, fault-tolerant rate limiting service capable of 100k QPS?",
            "Explain how the Raft and Paxos consensus algorithms handle network partitions and split-brain scenarios.",
            "Analyze lock contention, memory barriers, and cache invalidation protocols (MESI) in high-throughput concurrent systems.",
            "Describe how write-ahead logging (WAL), LSM trees, and SSTables differ from traditional B+ Tree storage engines.",
            "Explain zero-copy I/O (epoll/kqueue, sendfile) and how kernel-to-user space context switches impact high-performance network proxies."
        ],
        "behavioral": [
            "Tell me about a catastrophic production incident or outage you diagnosed under extreme pressure.",
            "Describe a situation where you fundamentally disagreed with an architectural direction set by leadership.",
            "Tell me about a time you had to mentor a struggling junior engineer while meeting your own sprint commitments.",
            "Describe how you handled a scenario where business stakeholders demanded a feature that compromised system security or integrity.",
            "Share an experience where you had to refactor a mission-critical legacy system with zero downtime."
        ]
    }
}


def normalize_difficulty(difficulty_input: Optional[str]) -> str:
    """
    Normalizes and validates a requested interview difficulty string.
    Returns 'Intermediate' if None or unrecogized.
    """
    if not difficulty_input or not isinstance(difficulty_input, str):
        return DEFAULT_DIFFICULTY
    clean = difficulty_input.strip().lower()
    return VALID_DIFFICULTIES.get(clean, DEFAULT_DIFFICULTY)


def get_difficulty_metadata(difficulty: str) -> Dict[str, Any]:
    """
    Returns presentation metadata for a given difficulty level.
    """
    diff = normalize_difficulty(difficulty)
    meta = {
        DIFFICULTY_BEGINNER: {
            "name": DIFFICULTY_BEGINNER,
            "badge_class": "bg-success text-white",
            "icon": "fa-seedling",
            "description": "Fundamental concepts, foundational data structures, and academic project scenarios.",
            "target_experience": "Freshmen, sophomores, and candidates beginning placement preparation."
        },
        DIFFICULTY_INTERMEDIATE: {
            "name": DIFFICULTY_INTERMEDIATE,
            "badge_class": "bg-primary text-white",
            "icon": "fa-chart-line",
            "description": "Core algorithms, systems design principles, database optimizations, and team collaboration.",
            "target_experience": "Graduating students targeting standard campus hiring and tech product companies."
        },
        DIFFICULTY_ADVANCED: {
            "name": DIFFICULTY_ADVANCED,
            "badge_class": "bg-danger text-white",
            "icon": "fa-fire",
            "description": "High-scale distributed systems, complex concurrency, internal architecture, and production incident management.",
            "target_experience": "Candidates preparing for Tier-1 FAANG / high-frequency trading / senior developer rounds."
        }
    }
    return meta[diff]


def generate_difficulty_interview_questions(
    difficulty: str,
    target_company: str = "General",
    target_role: str = "Software Engineer",
    custom_topics: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Constructs a standardized 15-question interview batch scaled precisely
    to the requested difficulty level (5 HR, 5 Technical, 5 Behavioral).
    """
    diff = normalize_difficulty(difficulty)
    catalog = DIFFICULTY_QUESTION_CATALOG[diff]

    flat_questions = []
    idx = 0

    for category, key in [("HR", "hr"), ("Technical", "technical"), ("Behavioral", "behavioral")]:
        q_texts = catalog.get(key, [])
        for q_text in q_texts:
            is_behav = (category.lower() == "behavioral")
            flat_questions.append({
                "index": idx,
                "type": category,
                "question": q_text,
                "difficulty": diff,
                "is_behavioral": is_behav,
                "target_company": target_company,
                "target_role": target_role
            })
            idx += 1

    return flat_questions
