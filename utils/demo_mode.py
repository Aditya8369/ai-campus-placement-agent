"""
Safe Demo Mode Utilities & Synthetic Sample Data (#360).

Allows project evaluators and visitors to explore the primary application features
(Candidate Evaluation Dashboard, ATS scoring, Skill Evidence Mapping, and 6-Week
Preparation Plans) using realistic synthetic sample data without submitting a real
resume, needing a Gemini API key, or invoking paid AI services.
"""

import copy
import logging
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

# ==============================================================================
# Synthetic Sample Resume & Job Description
# ==============================================================================

SYNTHETIC_SAMPLE_RESUME_TEXT = """
ALEX CHEN
San Francisco, CA | (555) 019-2834 | alex.chen.demo@example.com | github.com/alexchen-demo | linkedin.com/in/alexchen-demo

EDUCATION
Bachelor of Science in Computer Science | GPA: 3.82 / 4.0
University of California, Berkeley | Expected Graduation: May 2027
Relevant Coursework: Data Structures & Algorithms, Operating Systems, Database Management, Computer Networks, Distributed Systems

TECHNICAL SKILLS
Languages: Python, JavaScript, TypeScript, SQL, C++, Go (Familiar)
Frameworks & Libraries: Flask, FastAPI, Node.js, Express, React, Tailwind CSS
Databases & Tools: PostgreSQL, SQLite, Redis (In-Memory Caching), Docker, Git, GitHub Actions, Linux/Unix

PROJECTS
Distributed Task Queue & Background Worker System | Python, FastAPI, Redis, Docker
- Architected an asynchronous distributed task queue processing 5,000+ simulated jobs per minute with priority scheduling.
- Implemented exponential backoff retries and dead-letter queues reducing failed job dropouts by 40%.
- Containerized the application using Docker and Docker Compose for reproducible local deployment across microservices.

Campus Placement & Skill Assessment Portal | Python, Flask, PostgreSQL, React
- Developed a full-stack campus recruitment preparation portal featuring interactive interview prep and automated scoring.
- Implemented secure JWT-based authentication, role-based access control, and comprehensive CSRF protection.
- Designed normalized relational database schemas with indexed queries achieving sub-50ms API response latency.

Real-Time Collaborative Code Editor | JavaScript, Node.js, WebSockets, Redis
- Built a web-based multi-user collaborative code editor supporting syntax highlighting for 12 programming languages.
- Leveraged operational transformation algorithms and WebSockets for real-time document synchronization across 50 concurrent peers.

PROFESSIONAL EXPERIENCE
Software Engineering Intern | CloudTech Solutions, San Jose, CA | June 2026 - Aug 2026
- Built and optimized internal RESTful microservices in Python, improving reporting pipeline throughput by 25%.
- Collaborated in an Agile Scrum team using Git, participating in daily standups and bi-weekly sprint reviews.
- Authored comprehensive unit and integration test suites achieving 88% test coverage using pytest.

AWARDS & LEADERSHIP
- 1st Place - Golden Gate Hackathon 2026 (Best Infrastructure Project)
- Solved 350+ algorithmic challenges across LeetCode and Codeforces
"""

SYNTHETIC_SAMPLE_JOB_DESCRIPTION = """
Software Development Engineer (SDE 1) - Campus Recruitment
Google LLC - Mountain View, CA / Remote

About the Role:
We are seeking motivated graduate Software Development Engineers to join our core systems and cloud engineering teams. You will collaborate with experienced engineers to design, build, and deploy high-performance distributed systems, robust backend APIs, and developer platforms powering billions of users.

Key Responsibilities:
- Design, write, test, and maintain high-quality, scalable code in Python, C++, Go, or Java.
- Build resilient backend services, RESTful APIs, and distributed data processing pipelines.
- Partner with cross-functional teams including product managers, site reliability engineers, and UX designers.
- Diagnose and resolve subtle performance bottlenecks and architectural constraints.

Minimum Qualifications:
- Currently pursuing or recently completed a Bachelor's or Master's degree in Computer Science, Software Engineering, or related technical field.
- Strong foundational knowledge of Data Structures, Algorithms, Operating Systems, and Object-Oriented Design.
- Practical experience coding in Python, JavaScript/TypeScript, C++, or Go.
- Familiarity with version control (Git) and relational databases (SQL).

Preferred Qualifications:
- Experience with containerization technologies (Docker, Kubernetes) and in-memory caches (Redis).
- Hands-on experience designing and debugging distributed microservices or cloud architectures.
- Demonstrated problem-solving ability through competitive programming or high-impact open-source contributions.
"""

# ==============================================================================
# Comprehensive Synthetic Placement Analysis Record
# ==============================================================================

SYNTHETIC_SAMPLE_ANALYSIS_RECORD: Dict[str, Any] = {
    "id": "demo-sample-analysis",
    "analysis_id": "demo-sample-analysis",
    "student_id": "demo_visitor",
    "is_demo": True,
    "version_number": 1,
    "created_at": "2026-11-11 10:00:00",
    "company_name": "Google",
    "resume_filename": "alex_chen_synthetic_sample_resume.pdf",
    "job_description": SYNTHETIC_SAMPLE_JOB_DESCRIPTION,
    "resume_text": SYNTHETIC_SAMPLE_RESUME_TEXT,
    "results": {
        "is_demo": True,
        "resume_analysis": {
            "ats_score": 86,
            "summary": "Alex Chen presents a standout technical profile with strong foundations in Python, algorithms, and distributed microservices. Demonstrates solid academic credentials and practical full-stack project implementations.",
            "strengths": [
                "Quantified project impacts (e.g., 40% failed job reduction in Distributed Task Queue).",
                "Clean section structure, uniform technical headers, and strong algorithmic foundations.",
                "Practical full-stack and distributed systems exposure with Docker and Redis."
            ],
            "weaknesses": [
                "Lacks direct production cloud orchestration experience with Kubernetes or Helm.",
                "Could highlight deeper system design trade-offs, load balancing, and consistent hashing."
            ],
            "grammar_suggestions": [
                "Use active voice throughout experience bullets (e.g. 'Engineered scalable APIs' rather than 'Was responsible for APIs')."
            ],
            "formatting_suggestions": [
                "Ensure consistent bullet indentation and standardize date formats to MMM YYYY."
            ],
            "project_feedback": "Projects demonstrate genuine backend architecture depth. Adding unit test coverage metrics and CI/CD pipeline descriptions will further elevate ATS parsing.",
            "experience_feedback": "Internship bullets showcase good collaborative fundamentals with Git and RESTful API integrations in an Agile team.",
            "missing_skills": [
                "Kubernetes",
                "Redis Caching",
                "Distributed System Design"
            ],
            "overall_recommendation": "Strong campus placement candidate. Prioritize learning distributed caching patterns and container orchestration to maximize tier-1 placement chances.",
            "status": "available"
        },
        "job_match": {
            "match_percentage": 84,
            "matched_skills": [
                "Python",
                "Data Structures & Algorithms",
                "REST APIs",
                "SQL",
                "Git",
                "Docker"
            ],
            "missing_skills": [
                "Kubernetes",
                "Redis",
                "Distributed System Design"
            ],
            "required_certifications": [
                "Kubernetes Fundamentals (Optional)",
                "AWS / GCP Associate Cloud Engineer (Beneficial)"
            ],
            "recommended_improvements": [
                "Add a bullet point under the Task Queue project demonstrating how Redis was used for caching.",
                "Explicitly mention concurrency, multithreading, or async handling in Python.",
                "Detail system design trade-offs in distributed architecture projects."
            ],
            "top_5_resume_changes": [
                "Incorporate 'Distributed Systems' and 'Redis In-Memory Caching' into the core skills section.",
                "Highlight Docker containerization in the project deployment summary.",
                "State specific latency reduction and throughput metrics in the Distributed Task Queue project.",
                "Ensure Git and GitHub collaboration practices are explicitly called out.",
                "Include a brief summary statement aligned to target Software Development Engineer roles."
            ],
            "company_benchmark": {
                "company": "Google",
                "target_ats": 80,
                "target_match": 75,
                "assessment": "Alex's profile exceeds Google's baseline technical screening benchmarks for entry-level Software Engineers.",
                "guidance": "Focus on algorithmic problem-solving speed (Tree & Graph traversals, Dynamic Programming) and clean, modular coding style."
            },
            "status": "available"
        },
        "skill_gap": [
            {
                "skill": "Distributed System Design",
                "importance": "High",
                "difficulty": "Hard",
                "learning_time": "3 weeks",
                "learning_resource": "Designing Data-Intensive Applications (Martin Kleppmann) & System Design Primer",
                "project_suggestion": "Build a distributed URL shortener or rate limiter with consistent hashing.",
                "priority": "High"
            },
            {
                "skill": "Redis & In-Memory Caching",
                "importance": "High",
                "difficulty": "Medium",
                "learning_time": "1-2 weeks",
                "learning_resource": "Redis University (RU101) & Official Documentation",
                "project_suggestion": "Integrate a Redis cache layer in the Task Queue with LRU eviction policy.",
                "priority": "High"
            },
            {
                "skill": "Kubernetes Orchestration",
                "importance": "Medium",
                "difficulty": "Hard",
                "learning_time": "2 weeks",
                "learning_resource": "Kubernetes for Beginners (CNCF & KodeKloud)",
                "project_suggestion": "Deploy a multi-service application with Minikube, ConfigMaps, and Ingress routing.",
                "priority": "Medium"
            }
        ],
        "learning_roadmap": [
            {
                "week": "Week 1",
                "topics": ["Advanced Data Structures (Segment Trees, Trie, Disjoint Set)", "Time & Space Complexity Analysis"],
                "coding_practice": ["LeetCode 208 (Implement Trie)", "LeetCode 547 (Number of Provinces)"],
                "mini_projects": ["In-Memory Trie-based Autocomplete Search Service"],
                "interview_questions": ["How do you detect a cycle in a directed graph using Kahn's algorithm?", "Explain amortized time complexity."],
                "revision_tasks": ["Review BFS vs DFS traversal trade-offs", "Implement union-find with path compression"],
                "estimated_hours": 12
            },
            {
                "week": "Week 2",
                "topics": ["Dynamic Programming (1D & 2D)", "Knapsack Patterns and State Optimization"],
                "coding_practice": ["LeetCode 322 (Coin Change)", "LeetCode 300 (Longest Increasing Subsequence)"],
                "mini_projects": ["Dynamic Knapsack Asset Allocator Script"],
                "interview_questions": ["Explain bottom-up vs top-down memoization.", "When does the greedy approach fail compared to DP?"],
                "revision_tasks": ["Practice 5 standard DP transformation recurrence relations"],
                "estimated_hours": 14
            },
            {
                "week": "Week 3",
                "topics": ["System Design Fundamentals (Scalability, Load Balancing, Consistent Hashing)"],
                "coding_practice": ["Implement a token-bucket rate limiter in Python"],
                "mini_projects": ["Scalable URL Shortener with Base62 encoding and SQLite/Redis"],
                "interview_questions": ["How does horizontal scaling compare to vertical scaling?", "How would you design a distributed ID generator (Snowflake)?"],
                "revision_tasks": ["Study CAP Theorem and ACID vs BASE properties"],
                "estimated_hours": 15
            },
            {
                "week": "Week 4",
                "topics": ["In-Memory Caching with Redis & Database Indexing (B-Trees, Composite Keys)"],
                "coding_practice": ["Implement cache-aside pattern with TTL invalidation"],
                "mini_projects": ["High-throughput API cache layer with Redis Sentinel simulation"],
                "interview_questions": ["How do you prevent cache stampede and cache penetration?", "Explain clustered vs non-clustered database indexes."],
                "revision_tasks": ["Analyze EXPLAIN query plans for SQL indexing benchmarks"],
                "estimated_hours": 12
            },
            {
                "week": "Week 5",
                "topics": ["Docker Multi-Stage Builds & Kubernetes Cluster Deployment"],
                "coding_practice": ["Write a production-grade Dockerfile with non-root security", "Configure Kubernetes Deployments & ClusterIP Services"],
                "mini_projects": ["Containerized Microservices Cluster deployed locally on Minikube"],
                "interview_questions": ["What is the difference between a Container and a Virtual Machine?", "How do Kubernetes liveness and readiness probes differ?"],
                "revision_tasks": ["Verify zero-downtime rolling updates on a test service"],
                "estimated_hours": 14
            },
            {
                "week": "Week 6",
                "topics": ["Behavioral STAR Stories & Comprehensive Mock Interview Rehearsals"],
                "coding_practice": ["Timed 45-minute technical problem solving with live explanation"],
                "mini_projects": ["Curate a personal portfolio README showcasing all projects with architectural diagrams"],
                "interview_questions": ["Tell me about your most technically challenging bug and how you diagnosed it.", "Why Google?"],
                "revision_tasks": ["Rehearse 4 structured STAR responses for leadership, conflict resolution, and technical setbacks"],
                "estimated_hours": 10
            }
        ],
        "interview_questions": {
            "technical": [
                "How does Python's GIL impact multithreaded CPU-bound vs I/O-bound tasks?",
                "Design a scalable LRU cache supporting O(1) get and put operations.",
                "Explain the difference between optimistic and pessimistic locking in relational databases.",
                "How do B-trees differ from binary search trees, and why are they favored for filesystem indexes?",
                "Walk through what happens under the hood when a user visits https://www.google.com in a browser."
            ],
            "behavioral": [
                "Tell me about a time you identified a subtle performance bottleneck in code you did not write.",
                "Describe a disagreement you had with a team member on software architecture and how you reached consensus.",
                "Give an example of a situation where project specifications changed abruptly near a deadline.",
                "How do you approach learning an unfamiliar framework when onboarding to a fast-moving team?"
            ],
            "hr": [
                "Walk me through your journey into computer science and what excites you about software engineering.",
                "Why are you interested in joining Google over other tech recruiters?",
                "Where do you see your engineering contributions growing over the next 3 to 5 years?",
                "How do you balance high code quality with aggressive delivery timelines?"
            ]
        },
        "overall_recommendation_summary": "Alex is an outstanding candidate with demonstrated engineering curiosity and strong problem-solving skills. Following this 6-week roadmap will solidify advanced system design and caching competencies to ensure top placement results.",
        "skill_evidence_mapping": {
            "supported_skills_count": 5,
            "unsupported_skills_count": 1,
            "partial_skills_count": 1,
            "evidence_score": 85,
            "summary": "5 of 7 core skills are demonstrated with practical evidence in project descriptions.",
            "skills": [
                {
                    "skill": "Python",
                    "status": "supported",
                    "source_section": "Projects & Experience",
                    "snippet": "Implemented distributed task workers and REST APIs in Python (Flask/FastAPI)."
                },
                {
                    "skill": "Data Structures & Algorithms",
                    "status": "supported",
                    "source_section": "Projects & Education",
                    "snippet": "Solved 350+ LeetCode problems; implemented Trie and Union-Find in projects."
                },
                {
                    "skill": "REST APIs",
                    "status": "supported",
                    "source_section": "Projects",
                    "snippet": "Engineered microservice endpoints handling JSON payloads with JWT authentication."
                },
                {
                    "skill": "Docker",
                    "status": "supported",
                    "source_section": "Projects",
                    "snippet": "Containerized multi-container application using Docker and Docker Compose."
                },
                {
                    "skill": "SQL",
                    "status": "supported",
                    "source_section": "Projects",
                    "snippet": "Designed normalized relational schemas and optimized queries achieving sub-50ms latency."
                },
                {
                    "skill": "Redis",
                    "status": "partial",
                    "source_section": "Skills List",
                    "snippet": "Listed in skills section; practical caching layer implementation recommended."
                },
                {
                    "skill": "Kubernetes",
                    "status": "unsupported",
                    "source_section": "Missing",
                    "snippet": "Mentioned as desired skill; no project bullets or hands-on evidence found."
                }
            ]
        }
    }
}

# ==============================================================================
# Synthetic Role Preparation Plan
# ==============================================================================

SYNTHETIC_SAMPLE_ROLE_PREPARATION: Dict[str, Any] = {
    "target_role": "Software Engineer",
    "role_title": "Software Engineer (SDE 1)",
    "company_name": "Google",
    "is_demo": True,
    "total_roadmap_tasks": 24,
    "match_score": 84,
    "role_summary": "Specialized curriculum focusing on algorithmic rigor, distributed microservices, caching architecture, and system scalability.",
    "core_technologies": [
        {"name": "Python", "category": "Primary Language", "level": "Advanced"},
        {"name": "Data Structures & Algorithms", "category": "Foundations", "level": "Advanced"},
        {"name": "System Design", "category": "Architecture", "level": "Intermediate"},
        {"name": "Redis", "category": "Caching", "level": "Intermediate"},
        {"name": "Docker", "category": "DevOps", "level": "Intermediate"},
        {"name": "SQL & PostgreSQL", "category": "Databases", "level": "Advanced"}
    ],
    "roadmap": copy.deepcopy(SYNTHETIC_SAMPLE_ANALYSIS_RECORD["results"]["learning_roadmap"]),
    "bridged_skill_gaps": [
        {
            "skill": "Distributed System Design",
            "curriculum_week": "Week 3",
            "practical_project": "Scalable URL Shortener with Base62 encoding and SQLite/Redis"
        },
        {
            "skill": "Redis Caching",
            "curriculum_week": "Week 4",
            "practical_project": "High-throughput API cache layer with Redis Sentinel simulation"
        },
        {
            "skill": "Kubernetes Orchestration",
            "curriculum_week": "Week 5",
            "practical_project": "Containerized Microservices Cluster deployed locally on Minikube"
        }
    ],
    "recommended_interview_focus": [
        "Time & Space complexity analysis for graph and DP problems.",
        "System design scalability bottlenecks, caching invalidation, and data partitioning.",
        "Behavioral STAR responses emphasizing team collaboration and technical debugging."
    ]
}


# ==============================================================================
# Helper Accessor Functions
# ==============================================================================

def get_synthetic_sample_analysis() -> Dict[str, Any]:
    """Returns a fresh deep copy of the synthetic sample analysis record."""
    record = copy.deepcopy(SYNTHETIC_SAMPLE_ANALYSIS_RECORD)
    # Ensure nested dictionary results is properly populated
    return record


def get_synthetic_sample_role_prep() -> Dict[str, Any]:
    """Returns a fresh deep copy of the synthetic role preparation plan."""
    return copy.deepcopy(SYNTHETIC_SAMPLE_ROLE_PREPARATION)


def is_demo_session(session: Dict[str, Any]) -> bool:
    """Checks whether the current session is executing in safe demo mode."""
    if not session:
        return False
    return bool(session.get("is_demo_mode") or session.get("user_id") == "demo_visitor")


def enter_demo_session(session: Dict[str, Any], current_time: float) -> None:
    """
    Safely transitions a session into safe demo mode.
    Preserves real user account credentials in pre_demo_* keys so real accounts
    remain completely unaffected upon exit.
    """
    real_uid = session.get("user_id")
    if real_uid and real_uid != "demo_visitor" and not session.get("is_demo_mode"):
        session["pre_demo_user_id"] = real_uid
        session["pre_demo_user_name"] = session.get("user_name", "")
        session["pre_demo_user_email"] = session.get("user_email", "")

    session["is_demo_mode"] = True
    session["user_id"] = "demo_visitor"
    session["user_name"] = "Demo Visitor"
    session["user_email"] = "visitor@demo.local"
    session["last_activity"] = current_time


def exit_demo_session(session: Dict[str, Any], current_time: float) -> Tuple[bool, str]:
    """
    Exits demo mode and restores the pre-existing user session if one existed.
    Returns (was_authenticated, restored_uid_or_empty).
    """
    pre_uid = session.pop("pre_demo_user_id", None)
    pre_name = session.pop("pre_demo_user_name", "")
    pre_email = session.pop("pre_demo_user_email", "")

    session.pop("is_demo_mode", None)

    if pre_uid and pre_uid != "demo_visitor":
        session["user_id"] = pre_uid
        if pre_name:
            session["user_name"] = pre_name
        if pre_email:
            session["user_email"] = pre_email
        session["last_activity"] = current_time
        return True, pre_uid
    else:
        session.pop("user_id", None)
        session.pop("user_name", None)
        session.pop("user_email", None)
        return False, ""

