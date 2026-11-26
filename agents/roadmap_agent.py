import logging
import re
from typing import Dict, Any, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prerequisites Knowledge Graph & Importance Defaults (#536)
# ---------------------------------------------------------------------------

SKILL_PREREQUISITES: Dict[str, List[str]] = {
    # Backend Frameworks & Libraries
    "fastapi": ["python", "rest apis"],
    "flask": ["python", "rest apis"],
    "django": ["python", "sql", "rest apis"],
    "pandas": ["python"],
    "numpy": ["python"],
    "scikit-learn": ["python", "machine learning"],
    "spring boot": ["java", "sql"],
    "spring": ["java"],
    "express": ["node.js", "javascript"],
    "node.js": ["javascript"],
    "nest.js": ["typescript", "node.js"],
    "typescript": ["javascript"],

    # Frontend Frameworks & Libraries
    "react": ["javascript", "html", "css"],
    "next.js": ["react", "javascript"],
    "vue": ["javascript", "html", "css"],
    "angular": ["typescript", "javascript", "html", "css"],
    "tailwind css": ["css", "html"],
    "bootstrap": ["css", "html"],

    # Databases & Caching
    "postgresql": ["sql"],
    "mysql": ["sql"],
    "sqlite": ["sql"],
    "mongodb": ["databases"],
    "redis": ["databases"],
    "orm": ["sql", "python"],

    # Cloud, DevOps & Distributed Systems
    "docker": ["linux"],
    "kubernetes": ["docker", "linux"],
    "ci/cd": ["git"],
    "github actions": ["git", "ci/cd"],
    "aws": ["linux", "cloud computing"],
    "google cloud": ["linux", "cloud computing"],
    "azure": ["linux", "cloud computing"],
    "terraform": ["cloud computing", "linux"],

    # Architecture & APIs
    "graphql": ["rest apis"],
    "microservices": ["rest apis", "docker"],
    "system design": ["data structures", "algorithms"],

    # AI / ML
    "deep learning": ["machine learning", "python"],
    "tensorflow": ["deep learning", "python"],
    "pytorch": ["deep learning", "python"],
    "nlp": ["machine learning", "python"],
    "generative ai": ["deep learning", "python"],
    "computer vision": ["deep learning", "python"],
}

SKILL_IMPORTANCE_DEFAULTS: Dict[str, str] = {
    # High Importance: Core languages & fundamental systems
    "python": "High", "java": "High", "c++": "High", "javascript": "High",
    "sql": "High", "data structures": "High", "algorithms": "High",
    "git": "High", "rest apis": "High", "linux": "High", "docker": "High",
    "system design": "High",

    # Medium Importance: Popular frameworks & datastores
    "react": "Medium", "node.js": "Medium", "flask": "Medium", "fastapi": "Medium",
    "django": "Medium", "spring boot": "Medium", "postgresql": "Medium",
    "mongodb": "Medium", "redis": "Medium", "ci/cd": "Medium", "aws": "Medium",
    "typescript": "Medium", "machine learning": "Medium", "cloud computing": "Medium",

    # Low / Specialized Importance: Domain-specific tooling
    "kubernetes": "Low", "graphql": "Low", "kafka": "Low", "terraform": "Low",
    "deep learning": "Low", "tailwind css": "Low", "tableau": "Low",
    "power bi": "Low", "hadoop": "Low", "spark": "Low"
}

# Curated curriculum for prominent technical skills
SKILL_CURRICULUM_DATA: Dict[str, Dict[str, Any]] = {
    "python": {
        "topics": [
            "Data types, control structures, and functional idioms (comprehensions, lambdas)",
            "Object-oriented programming, classes, inheritance, and dunder methods",
            "Exception handling, file I/O, context managers, and standard library modules",
            "Virtual environments, package management (pip/poetry), and pytest basics"
        ],
        "practice_task": "Build a command-line expense tracker with data persistence in JSON and write 3 pytest unit tests.",
        "resource_types": [
            "Official Python Tutorial & Docs (docs.python.org)",
            "Interactive Coding Challenges (Exercism / LeetCode Easy)",
            "Free Community Textbooks (Automate the Boring Stuff with Python)",
            "Video Walkthroughs & Code-alongs (freeCodeCamp YouTube)"
        ]
    },
    "docker": {
        "topics": [
            "Container fundamentals vs virtual machines & container lifecycle commands",
            "Writing Dockerfiles, base images, layers, and caching strategies",
            "Multi-stage builds for minimal production image footprints",
            "Docker Compose for multi-container application stacks and network isolation"
        ],
        "practice_task": "Containerize a sample REST API service with a multi-stage Dockerfile and configure Docker Compose with a database service.",
        "resource_types": [
            "Official Docker Documentation & Getting Started Guides",
            "Interactive Play with Docker Classroom (labs.play-with-docker.com)",
            "Open-Source Sample Microservice Repositories on GitHub",
            "Community DevOps Cheat Sheets & Best Practice Guides"
        ]
    },
    "sql": {
        "topics": [
            "Relational data modeling, schema definition (DDL), and constraints",
            "Data querying (DML), multi-table INNER and OUTER JOINs, and subqueries",
            "Aggregation functions, GROUP BY, HAVING, and Window Functions (ROW_NUMBER, RANK)",
            "Indexing strategies, query execution plans (EXPLAIN), and transaction ACID properties"
        ],
        "practice_task": "Write 6 complex SQL analytical queries (including window functions and joins) on an open eCommerce schema.",
        "resource_types": [
            "Interactive SQL Playgrounds (SQLZoo / Mode Analytics SQL Tutorial)",
            "PostgreSQL & MySQL Official Reference Documentation",
            "Database Schema Design Cheat Sheets & Practice Datasets",
            "Community Video Tutorials on SQL Optimization & Query Planning"
        ]
    },
    "react": {
        "topics": [
            "JSX syntax, component hierarchy, props passing, and pure components",
            "Core React Hooks: useState, useEffect, useRef, and custom hooks",
            "Conditional rendering, list keys, and controlled form inputs",
            "Component lifecycle, state lifting, and context API for global state"
        ],
        "practice_task": "Build an interactive task management dashboard featuring search filtering, state persistence, and modular components.",
        "resource_types": [
            "Official React Documentation (react.dev interactive docs)",
            "Interactive Sandbox Exercises (CodeSandbox / StackBlitz)",
            "Open-Source GitHub Starter Templates & Component Libraries",
            "Community Video Walkthroughs on Modern React Patterns"
        ]
    },
    "kubernetes": {
        "topics": [
            "Kubernetes architecture: control plane, kubelet, and worker node components",
            "Core primitives: Pods, Deployments, ReplicaSets, and Services (ClusterIP, NodePort)",
            "ConfigMaps, Secrets, persistent volumes, and health checks (liveness/readiness)",
            "Basic ingress configuration, namespace isolation, and kubectl debugging commands"
        ],
        "practice_task": "Deploy a multi-pod web app with a ClusterIP Service, ConfigMap, and readiness probes on a local Minikube cluster.",
        "resource_types": [
            "Official Kubernetes Documentation & Interactive Tutorials (kubernetes.io)",
            "Free Interactive Sandboxes (Killercoda / Play with Kubernetes)",
            "Open-Source Cloud Native Architecture Manifests on GitHub",
            "Community DevOps & SRE Video Walkthroughs"
        ]
    },
    "rest apis": {
        "topics": [
            "HTTP methods (GET, POST, PUT, PATCH, DELETE) and standardized status codes",
            "RESTful resource design, URL hierarchies, and pagination conventions",
            "Request validation, serialization, authentication headers (JWT, API keys)",
            "API documentation generation (OpenAPI/Swagger) and automated contract testing"
        ],
        "practice_task": "Design and implement a complete CRUD RESTful resource endpoint with input validation and Swagger/OpenAPI documentation.",
        "resource_types": [
            "RESTful API Design Guidelines & RFC Specifications",
            "Free API Testing Tools (Postman Learning Center / Thunder Client)",
            "Open-Source Reference Architectures & REST Templates on GitHub",
            "Community API Engineering Best Practice Articles"
        ]
    },
    "git": {
        "topics": [
            "Repository initialization, commit history, and the 3-state workflow (working, staging, repo)",
            "Branching models, merge strategies (fast-forward vs 3-way merge), and conflict resolution",
            "Remote synchronization (fetch, pull, push, upstream tracking) and git stash",
            "Interactive rebase, commit squashing, cherry-pick, and pull request workflows"
        ],
        "practice_task": "Simulate a feature branch workflow with a deliberate merge conflict, resolve it using git rebase, and squash commits.",
        "resource_types": [
            "Official Pro Git Book (git-scm.com/book/en/v2 free online)",
            "Interactive Visual Git Tutorials (learngitbranching.js.org)",
            "GitHub Skills Interactive Courses & Quickstart Guides",
            "Visual Git Cheatsheets and Command References"
        ]
    },
    "system design": {
        "topics": [
            "Client-server communication, load balancing algorithms, and reverse proxies",
            "Caching strategies (write-through, cache-aside) with Redis/Memcached and CDNs",
            "Database scaling: replication, read replicas, sharding, and CAP theorem trade-offs",
            "Asynchronous message queues (Kafka, RabbitMQ) and microservice communication"
        ],
        "practice_task": "Draw and document an architectural diagram for a scalable URL shortener handling 1,000 writes/sec and 10,000 reads/sec.",
        "resource_types": [
            "The System Design Primer (Open-Source GitHub Repository)",
            "Engineering Architecture Blogs (Netflix TechBlog, Uber Engineering)",
            "Free System Design Video Walkthroughs (Gaurav Sen / NeetCode)",
            "Whitepapers on Distributed Consensus & High-Availability Architectures"
        ]
    },
    "machine learning": {
        "topics": [
            "Supervised vs unsupervised learning paradigms, feature engineering, and data scaling",
            "Linear regression, logistic regression, decision trees, and ensemble random forests",
            "Model evaluation metrics: accuracy, precision, recall, F1-score, and ROC-AUC curves",
            "Cross-validation techniques, hyperparameter tuning (GridSearchCV), and overfitting prevention"
        ],
        "practice_task": "Train and evaluate a customer churn classification pipeline using Scikit-Learn with 5-fold cross validation.",
        "resource_types": [
            "Scikit-Learn Official User Guide & Tutorials",
            "Free University Course Lectures (Andrew Ng ML Courses / Kaggle Learn)",
            "Kaggle Community Datasets & Interactive Jupyter Notebooks",
            "Community Data Science Articles & Case Studies"
        ]
    },
    "javascript": {
        "topics": [
            "Modern ES6+ syntax: let/const, destructuring, arrow functions, and spread/rest operators",
            "Asynchronous programming: Event Loop, Callbacks, Promises, and async/await",
            "DOM manipulation, event delegation, bubbling, and browser APIs",
            "Prototypes, closures, scope chains, and modular code organization (ES Modules)"
        ],
        "practice_task": "Build an asynchronous weather dashboard widget consuming a public REST API with error handling and dynamic DOM updates.",
        "resource_types": [
            "MDN Web Docs (developer.mozilla.org JavaScript Guide)",
            "Interactive JavaScript Tutorials (javascript.info)",
            "Free Coding Katas (freeCodeCamp JavaScript Algorithms)",
            "Community Video Crash Courses & Mini-Projects"
        ]
    }
}


class RoadmapAgent:
    """
    Agent responsible for processing, validating, and structuring
    personalized learning roadmaps with realistic weekly timelines (#536).
    """

    def __init__(self) -> None:
        pass

    # -----------------------------------------------------------------------
    # Legacy / Coordinator 6-Week Validation
    # -----------------------------------------------------------------------
    def process(self, data: Any) -> List[Dict[str, Any]]:
        """
        Accepts the learning_roadmap list from the coordinator JSON.
        Validates elements, ensures exactly 6 weeks of data, and applies fallback defaults.
        """
        logger.info("RoadmapAgent: Starting roadmap block validation.")
        raw_list = data if isinstance(data, list) else []
        processed_roadmap = []

        for week_num in range(1, 7):
            week_title = f"Week {week_num}"
            found_week_dict = None

            for item in raw_list:
                if isinstance(item, dict) and str(item.get("week", "")).strip().lower() == week_title.lower():
                    found_week_dict = item
                    break

            if not found_week_dict and (week_num - 1) < len(raw_list):
                candidate = raw_list[week_num - 1]
                if isinstance(candidate, dict):
                    found_week_dict = candidate

            if found_week_dict:
                raw_hours = found_week_dict.get("estimated_hours", 10)
                try:
                    estimated_hours = int(raw_hours)
                except (ValueError, TypeError):
                    estimated_hours = 10
                estimated_hours = max(1, min(80, estimated_hours))

                week_data = {
                    "week": week_title,
                    "topics": self._sanitize_string_list(found_week_dict.get("topics")),
                    "coding_practice": self._sanitize_string_list(found_week_dict.get("coding_practice")),
                    "mini_projects": self._sanitize_string_list(found_week_dict.get("mini_projects")),
                    "interview_questions": self._sanitize_string_list(found_week_dict.get("interview_questions")),
                    "revision_tasks": self._sanitize_string_list(found_week_dict.get("revision_tasks")),
                    "estimated_hours": estimated_hours,
                }
            else:
                week_data = {
                    "week": week_title,
                    "topics": ["Technical concept deep dive & DSA fundamentals."],
                    "coding_practice": ["Practice basic and intermediate coding problems (Arrays, Hashmaps)."],
                    "mini_projects": ["Design a small CLI utility or API integrating these concepts."],
                    "interview_questions": ["Explain common concepts and space/time complexities of operations."],
                    "revision_tasks": ["Re-run past programming test cases and verify edge cases."],
                    "estimated_hours": 10,
                }
            processed_roadmap.append(week_data)

        logger.info("RoadmapAgent: Roadmap processing and structural formatting complete.")
        return processed_roadmap

    # -----------------------------------------------------------------------
    # Interactive Timeline Learning Roadmap Generator (#536)
    # -----------------------------------------------------------------------
    def generate_learning_roadmap(
        self,
        missing_skills: List[Any],
        weeks: int = 6,
        hours_per_week: int = 10,
        target_role: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generates a customized week-by-week learning roadmap for missing skills (#536).

        Acceptance Criteria:
        1. The plan length matches the chosen number of weeks.
        2. Every missing skill appears in the plan or is marked as deferred.
        3. Zero missing skills shows a congratulatory message instead of an empty plan.
        """
        # 1. Sanitize & clamp parameters
        try:
            weeks_int = int(weeks)
        except (ValueError, TypeError):
            weeks_int = 6
        weeks_int = max(1, min(24, weeks_int))

        try:
            hours_int = int(hours_per_week)
        except (ValueError, TypeError):
            hours_int = 10
        hours_int = max(1, min(60, hours_int))

        # 2. Extract and clean missing skills
        normalized_skills = self._normalize_missing_skills(missing_skills)

        # 3. Acceptance Criterion: Zero missing skills
        if not normalized_skills:
            return {
                "success": True,
                "weeks": weeks_int,
                "hours_per_week": hours_int,
                "target_role": target_role or "Target Role",
                "is_zero_missing": True,
                "congratulatory_message": (
                    "🎉 Congratulations! You have zero missing skills for this target role. "
                    "Your technical profile fully aligns with all evaluated competencies. "
                    "We recommend focusing on mock technical interviews, system design practice, "
                    "and refining your behavioral STAR responses!"
                ),
                "plan": [],
                "deferred_skills": [],
                "total_missing_skills": 0,
                "scheduled_count": 0,
                "deferred_count": 0,
            }

        # 4. Order missing skills by prerequisites and importance
        ordered_skills = self._order_skills_by_prerequisites_and_importance(normalized_skills)

        # 5. Capacity Partitioning: Schedule vs Deferred
        # Plan length MUST match chosen weeks. Each week covers 1 primary skill focus,
        # or spreads skills if fewer skills than weeks.
        scheduled_skills, deferred_skills = self._partition_skills_for_timeline(
            ordered_skills, weeks_int, hours_int
        )

        # 6. Build Week-by-Week Plan matching exact weeks_int length
        plan = self._build_weekly_plan(
            scheduled_skills=scheduled_skills,
            weeks=weeks_int,
            hours_per_week=hours_int,
            target_role=target_role
        )

        return {
            "success": True,
            "weeks": weeks_int,
            "hours_per_week": hours_int,
            "target_role": target_role or "Target Role",
            "is_zero_missing": False,
            "congratulatory_message": None,
            "plan": plan,
            "deferred_skills": deferred_skills,
            "total_missing_skills": len(normalized_skills),
            "scheduled_count": len(scheduled_skills),
            "deferred_count": len(deferred_skills),
        }

    # -----------------------------------------------------------------------
    # Helper: Normalization of Missing Skills
    # -----------------------------------------------------------------------
    def _normalize_missing_skills(self, raw_skills: Any) -> List[Dict[str, Any]]:
        """Standardizes missing skills into clean objects with name, importance, and difficulty."""
        if not raw_skills:
            return []

        cleaned: List[Dict[str, Any]] = []
        seen: Set[str] = set()

        items = raw_skills if isinstance(raw_skills, list) else [raw_skills]
        for itm in items:
            skill_name = ""
            importance = None
            difficulty = None

            if isinstance(itm, dict):
                skill_name = str(itm.get("skill") or itm.get("missing_skill") or itm.get("name") or "").strip()
                importance = itm.get("importance") or itm.get("priority")
                difficulty = itm.get("difficulty")
            elif isinstance(itm, str):
                skill_name = itm.strip()

            if not skill_name:
                continue

            # Remove bullet prefixes or numbers
            clean_name = re.sub(r"^[-\*•\d\.\)]+\s*", "", skill_name).strip()
            if not clean_name:
                continue

            norm_key = clean_name.lower()
            if norm_key in seen:
                continue
            seen.add(norm_key)

            # Determine importance
            if not importance:
                importance = SKILL_IMPORTANCE_DEFAULTS.get(norm_key, "Medium")
            else:
                imp_str = str(importance).strip().capitalize()
                importance = imp_str if imp_str in ("High", "Medium", "Low") else "Medium"

            if not difficulty:
                difficulty = "Medium"
            else:
                diff_str = str(difficulty).strip().capitalize()
                difficulty = diff_str if diff_str in ("Easy", "Medium", "Hard") else "Medium"

            cleaned.append({
                "name": clean_name,
                "key": norm_key,
                "importance": importance,
                "difficulty": difficulty
            })

        return cleaned

    # -----------------------------------------------------------------------
    # Helper: Topological Sort by Prerequisites and Importance (#536)
    # -----------------------------------------------------------------------
    def _order_skills_by_prerequisites_and_importance(
        self, skills: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Orders skills so prerequisites come strictly before dependent skills,
        and higher importance skills are prioritized when no dependencies exist.
        """
        skill_keys = {s["key"]: s for s in skills}
        in_degree: Dict[str, int] = {s["key"]: 0 for s in skills}
        adj_list: Dict[str, List[str]] = {s["key"]: [] for s in skills}

        # Build graph among the skills present in this missing set
        for s in skills:
            k = s["key"]
            prereqs = SKILL_PREREQUISITES.get(k, [])
            for p in prereqs:
                p_key = p.lower()
                if p_key in skill_keys and p_key != k:
                    # p_key must be learned BEFORE k
                    adj_list[p_key].append(k)
                    in_degree[k] += 1

        importance_weight = {"High": 3, "Medium": 2, "Low": 1}

        # Select candidates with 0 in-degree, prioritize by importance
        available = [k for k, deg in in_degree.items() if deg == 0]
        ordered_keys: List[str] = []

        while available:
            # Sort available by importance descending
            available.sort(key=lambda k: importance_weight.get(skill_keys[k]["importance"], 2), reverse=True)
            chosen = available.pop(0)
            ordered_keys.append(chosen)

            for neighbor in adj_list[chosen]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    available.append(neighbor)

        # Fallback for cycles: add any remaining
        if len(ordered_keys) < len(skills):
            remaining = [s["key"] for s in skills if s["key"] not in ordered_keys]
            remaining.sort(key=lambda k: importance_weight.get(skill_keys[k]["importance"], 2), reverse=True)
            ordered_keys.extend(remaining)

        return [skill_keys[k] for k in ordered_keys]

    # -----------------------------------------------------------------------
    # Helper: Partition Scheduled vs Deferred Skills (#536)
    # -----------------------------------------------------------------------
    def _partition_skills_for_timeline(
        self,
        ordered_skills: List[Dict[str, Any]],
        weeks: int,
        hours_per_week: int
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Splits missing skills into those scheduled within the chosen weeks
        and those marked as deferred.
        """
        # Maximum skills that can fit in the chosen weeks.
        # Typically 1 skill per week; if student commits 20+ hours, up to 1.5x skills.
        max_capacity = weeks
        if hours_per_week >= 25 and len(ordered_skills) > weeks:
            max_capacity = min(len(ordered_skills), int(weeks * 1.5))

        scheduled = ordered_skills[:max_capacity]
        unassigned = ordered_skills[max_capacity:]

        deferred: List[Dict[str, Any]] = []
        for s in unassigned:
            deferred.append({
                "skill": s["name"],
                "importance": s["importance"],
                "difficulty": s["difficulty"],
                "reason": (
                    f"Deferred beyond your chosen {weeks}-week timeline ({hours_per_week} hrs/week). "
                    f"Recommended for phase 2 after completing core prerequisites."
                )
            })

        return scheduled, deferred

    # -----------------------------------------------------------------------
    # Helper: Build Weekly Curriculum Structure
    # -----------------------------------------------------------------------
    def _build_weekly_plan(
        self,
        scheduled_skills: List[Dict[str, Any]],
        weeks: int,
        hours_per_week: int,
        target_role: Optional[str]
    ) -> List[Dict[str, Any]]:
        """
        Constructs a week-by-week plan where len(plan) == weeks exactly.
        Each week contains topics, exactly one small practice task, and free resource types.
        """
        plan: List[Dict[str, Any]] = []

        if not scheduled_skills:
            # Fallback if no scheduled skills
            for w in range(1, weeks + 1):
                plan.append({
                    "week": f"Week {w}",
                    "week_number": w,
                    "skills": ["Core Engineering Fundamentals"],
                    "topics": [
                        "Review data structures, time complexity, and core programming paradigms",
                        "Solve intermediate algorithmic problems on arrays, strings, and hash maps",
                        "Conduct mock interview coding drills under timed constraints"
                    ],
                    "practice_task": f"Complete 5 intermediate algorithmic problems and write unit tests for each solution.",
                    "resource_types": [
                        "Official Language & Platform Documentation",
                        "Interactive Coding Katas (LeetCode / Exercism)",
                        "Open-Source Problem Sets on GitHub"
                    ],
                    "estimated_hours": hours_per_week
                })
            return plan

        num_skills = len(scheduled_skills)

        # Distribute scheduled skills across exact `weeks`
        # If skills >= weeks: map one or more skills per week
        # If skills < weeks: expand skills across multiple weeks with progressive depth
        for w_idx in range(weeks):
            week_num = w_idx + 1
            week_title = f"Week {week_num}"

            if num_skills >= weeks:
                # Group skills into weeks
                start_i = (w_idx * num_skills) // weeks
                end_i = ((w_idx + 1) * num_skills) // weeks
                week_skills_objs = scheduled_skills[start_i:end_i] if start_i < end_i else [scheduled_skills[min(w_idx, num_skills - 1)]]
            else:
                # More weeks than skills: allocate skills progressively
                skill_index = min(w_idx * num_skills // weeks, num_skills - 1)
                week_skills_objs = [scheduled_skills[skill_index]]

            week_skill_names = [s["name"] for s in week_skills_objs]
            primary_skill = week_skills_objs[0]["name"]
            norm_key = week_skills_objs[0]["key"]

            # Pull curriculum template or synthesize
            curriculum = self._get_skill_curriculum(primary_skill, norm_key, week_num, weeks)

            # Match curated learning resources (#885)
            week_resources = []
            try:
                from utils.learning_resource_service import get_resources_for_skill
                for sk in week_skill_names:
                    for r in get_resources_for_skill(sk):
                        if not any(existing.get("id") == r.get("id") for existing in week_resources):
                            week_resources.append(dict(r))
            except Exception:
                pass

            plan.append({
                "week": week_title,
                "week_number": week_num,
                "skills": week_skill_names,
                "topics": curriculum["topics"],
                "practice_task": curriculum["practice_task"],
                "resource_types": curriculum["resource_types"],
                "curated_resources": week_resources,
                "has_curated_resources": len(week_resources) > 0,
                "estimated_hours": hours_per_week
            })

        return plan

    # -----------------------------------------------------------------------
    # Helper: Curate Topics, Single Practice Task, and Free Resource Types
    # -----------------------------------------------------------------------
    def _get_skill_curriculum(
        self,
        skill_name: str,
        norm_key: str,
        week_num: int,
        total_weeks: int
    ) -> Dict[str, Any]:
        """Returns topics, one small practice task, and free resource types for a skill."""
        # 1. Check known curriculum
        if norm_key in SKILL_CURRICULUM_DATA:
            base = SKILL_CURRICULUM_DATA[norm_key]
            # Vary task slightly for later weeks if spanning multiple weeks
            practice_task = base["practice_task"]
            if week_num > 1 and total_weeks > 2 and (week_num == total_weeks or week_num % 2 == 0):
                practice_task = f"Extend your {skill_name} implementation with error handling, test coverage, and documentation."

            return {
                "topics": list(base["topics"]),
                "practice_task": practice_task,
                "resource_types": list(base["resource_types"])
            }

        # 2. Heuristic fallback for any custom or arbitrary technical skill
        topics = [
            f"{skill_name} core architecture, environment setup, and fundamental concepts",
            f"Key syntax patterns, API conventions, and idiomatic workflows in {skill_name}",
            f"Debugging, performance optimization, and testing practices with {skill_name}"
        ]

        practice_task = f"Build a focused proof-of-concept module or utility utilizing {skill_name} and verify its behavior with test assertions."

        resource_types = [
            f"Official {skill_name} Documentation & Quickstart Guides",
            "Interactive Coding Playgrounds & Community Katas (e.g. Exercism, GitHub)",
            "Free Open-Source Starter Repositories & Architecture References",
            "Community Video Masterclasses & Technical Walkthroughs"
        ]

        return {
            "topics": topics,
            "practice_task": practice_task,
            "resource_types": resource_types
        }

    def _sanitize_string_list(self, raw_list: Any) -> List[str]:
        """Standardizes input items into a clean list of strings."""
        if isinstance(raw_list, list):
            return [str(item).strip() for item in raw_list if item and str(item).strip()]
        elif isinstance(raw_list, str) and raw_list.strip():
            return [raw_list.strip()]
        return []


# ---------------------------------------------------------------------------
# Module-level convenience wrapper (#536)
# ---------------------------------------------------------------------------

roadmap_agent = RoadmapAgent()

def generate_learning_roadmap(
    missing_skills: List[Any],
    weeks: int = 6,
    hours_per_week: int = 10,
    target_role: Optional[str] = None
) -> Dict[str, Any]:
    """Module-level wrapper for RoadmapAgent().generate_learning_roadmap."""
    return roadmap_agent.generate_learning_roadmap(
        missing_skills=missing_skills,
        weeks=weeks,
        hours_per_week=hours_per_week,
        target_role=target_role
    )
