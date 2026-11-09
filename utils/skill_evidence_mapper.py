import re
import os
import json
import logging
from typing import Dict, Any, List, Optional, Set, Tuple
import config
from utils.pdf_reader import standardize_resume_sections
from utils.resume_info_extractor import (
    extract_skills_list,
    extract_projects_entries,
    extract_experience_entries
)

logger = logging.getLogger(__name__)

# Catalog of known technical, cloud, database, and engineering skills for detection
KNOWN_TECH_SKILLS = [
    # Programming Languages
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "C", "Go", "Golang",
    "Rust", "Ruby", "PHP", "Swift", "Kotlin", "SQL", "HTML", "CSS", "R", "Scala",
    # Frameworks & Libraries
    "React", "React.js", "Angular", "Vue", "Vue.js", "Node.js", "Express", "Express.js",
    "Next.js", "Django", "Flask", "FastAPI", "Spring Boot", "Spring", "ASP.NET",
    "Ruby on Rails", "Tailwind CSS", "Bootstrap", "jQuery", "GraphQL",
    # Databases & Caches
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "SQLite", "Cassandra", "Elasticsearch",
    "DynamoDB", "Oracle", "Firebase", "Snowflake", "Neo4j",
    # Cloud & DevOps
    "AWS", "Amazon Web Services", "Azure", "Google Cloud", "GCP", "Docker", "Kubernetes",
    "CI/CD", "Jenkins", "GitHub Actions", "GitLab CI", "Terraform", "Linux", "Unix",
    "Git", "GitHub", "Nginx", "Apache", "Ansible", "Kafka", "RabbitMQ",
    # AI / ML & Data Science
    "Machine Learning", "Deep Learning", "Artificial Intelligence", "PyTorch", "TensorFlow",
    "Scikit-Learn", "Pandas", "NumPy", "NLP", "Natural Language Processing", "Computer Vision",
    "LLM", "LLMs", "LangChain", "OpenCV", "Tableau", "Power BI",
    # Core Concepts & Architecture
    "Data Structures", "Algorithms", "System Design", "REST APIs", "RESTful API",
    "Microservices", "Object-Oriented Programming", "OOP", "Unit Testing", "TDD",
    "Agile", "Scrum", "Cybersecurity", "Networking"
]

# Actionable templates for project ideas and resume bullet points by skill domain
SKILL_PRACTICAL_GUIDANCE = {
    "Docker": {
        "project": "Containerized Multi-Tier Application using Docker Compose with auto-restarts and volume persistence.",
        "example_bullet": "Containerized multi-service web backend using Docker and Docker Compose, reducing environment setup time by 45% across team development cycles."
    },
    "Kubernetes": {
        "project": "Microservice Deployment on a local Minikube cluster with Rolling Updates, ConfigMaps, and Ingress routing.",
        "example_bullet": "Configured Kubernetes deployment manifests and Horizontal Pod Autoscaling (HPA) to maintain 99.9% uptime under high traffic simulations."
    },
    "Python": {
        "project": "Automated Web Scraping and ETL Data Pipeline processing structured CSV/JSON payloads into PostgreSQL.",
        "example_bullet": "Engineered automated asynchronous ETL data ingestion scripts in Python, processing 50K+ records daily with comprehensive unit test coverage."
    },
    "Java": {
        "project": "Enterprise Banking / Inventory Management API built with Spring Boot, Spring Security, and JPA.",
        "example_bullet": "Architected high-throughput RESTful endpoints using Java and Spring Boot, optimizing database connection pools and Hibernate query performance."
    },
    "React": {
        "project": "Interactive Single Page Application (SPA) with Redux Toolkit / Context API, client-side routing, and responsive UI.",
        "example_bullet": "Developed responsive, accessible web interfaces in React and TypeScript, improving client-side page load performance by 35%."
    },
    "SQL": {
        "project": "Database Schema Design & Query Optimization benchmark for an e-commerce order management system.",
        "example_bullet": "Designed normalized relational schemas and optimized complex SQL JOIN queries using composite B-tree indexing, cutting query latency from 850ms to 45ms."
    },
    "AWS": {
        "project": "Serverless API deployed using AWS Lambda, API Gateway, DynamoDB, and S3 static asset hosting.",
        "example_bullet": "Architected serverless cloud infrastructure on AWS utilizing Lambda, S3, and CloudFront, reducing monthly hosting overhead by 60%."
    },
    "Machine Learning": {
        "project": "Predictive Classification / Regression model deployed as a REST API with FastAPI and model evaluation metrics.",
        "example_bullet": "Trained and deployed a predictive gradient-boosted ML model (Scikit-Learn) with 92% F1-score, serving real-time inference via FastAPI."
    },
    "Git": {
        "project": "Collaborative Open-Source Contribution using feature branch workflows, semantic commit messages, and Pull Request reviews.",
        "example_bullet": "Maintained continuous integration workflows via Git and GitHub Actions, enforcing automated linting, test verification, and branch protection rules."
    },
    "REST APIs": {
        "project": "Secure RESTful Service with JWT Authentication, Rate Limiting, and OpenAPI / Swagger documentation.",
        "example_bullet": "Designed and documented secure RESTful APIs with JWT authentication and redis-backed rate limiting, supporting 200+ concurrent requests."
    }
}


def _build_skill_regex(skill: str) -> re.Pattern:
    """
    Constructs a boundary-safe regular expression pattern for a skill string.
    Accounts for special characters such as C++, C#, .NET, Node.js.
    """
    s = skill.strip()
    if s.lower() == "c++":
        return re.compile(r"(?:^|[\s,;/()\[\]])C\+\+(?:$|[\s,;/()\[\].])", re.IGNORECASE)
    elif s.lower() == "c#":
        return re.compile(r"(?:^|[\s,;/()\[\]])C\#(?:$|[\s,;/()\[\].])", re.IGNORECASE)
    elif s.lower() == "c":
        return re.compile(r"(?:^|[\s,;/()\[\]])C(?:$|[\s,;/()\[\].])")
    elif s.lower() == "r":
        return re.compile(r"(?:^|[\s,;/()\[\]])R(?:$|[\s,;/()\[\].])")
    elif s.lower() == ".net":
        return re.compile(r"(?:^|[\s,;/()\[\]])\.NET(?:$|[\s,;/()\[\].])", re.IGNORECASE)
    else:
        escaped = re.escape(s)
        return re.compile(r"\b" + escaped + r"\b", re.IGNORECASE)


def extract_contextual_snippet(text: str, skill: str, max_chars: int = 150) -> str:
    """
    Extracts the most relevant sentence or bullet point containing the skill from the section text.
    """
    if not text:
        return ""
    
    pattern = _build_skill_regex(skill)
    lines = text.splitlines()
    for line in lines:
        clean = line.strip().lstrip("-•*– ").strip()
        if clean and pattern.search(clean):
            if len(clean) > max_chars:
                # Truncate nicely around the match
                match = pattern.search(clean)
                start = max(0, match.start() - 40)
                end = min(len(clean), match.end() + 70)
                snippet = clean[start:end].strip()
                if start > 0:
                    snippet = "..." + snippet
                if end < len(clean):
                    snippet = snippet + "..."
                return snippet
            return clean

    # Fallback to sentence search
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sent in sentences:
        clean = sent.strip()
        if clean and pattern.search(clean):
            if len(clean) > max_chars:
                return clean[:max_chars].strip() + "..."
            return clean

    return ""


def detect_skills_in_resume(
    resume_text: str,
    sections: Optional[Dict[str, str]] = None,
    explicit_skills: Optional[List[str]] = None
) -> List[str]:
    """
    Identifies all technical skills mentioned in the resume text or its sections.
    Deduplicates and standardizes skill names.
    """
    detected: Dict[str, str] = {}  # lower_name -> display_name

    # 1. Add explicitly passed skills (e.g. from matched_skills)
    if explicit_skills:
        for s in explicit_skills:
            clean = str(s).strip()
            if clean and len(clean) >= 2:
                detected[clean.lower()] = clean

    # 2. Extract from Technical Skills section if parsed
    if not sections:
        sections = standardize_resume_sections(resume_text)
    
    extracted_from_skills_sec = extract_skills_list(sections.get("skills", ""), resume_text)
    for s in extracted_from_skills_sec:
        clean = s.strip()
        if clean and len(clean) >= 2:
            if clean.lower() not in detected:
                detected[clean.lower()] = clean

    # 3. Check for presence of curated known technical skills
    full_text = resume_text or " ".join(sections.values())
    for skill in KNOWN_TECH_SKILLS:
        if skill.lower() not in detected:
            rx = _build_skill_regex(skill)
            if rx.search(full_text):
                detected[skill.lower()] = skill

    # Return sorted by display name
    return sorted(list(detected.values()), key=lambda x: x.lower())


def generate_skill_guidance(skill_name: str) -> Tuple[str, str, List[str]]:
    """
    Generates recommended practical project, resume bullet point, and improvement tips
    for an unsupported or weakly supported skill.
    """
    clean_name = skill_name.strip()
    
    # Check exact or partial match in guidance library
    matched_guidance = None
    for k, v in SKILL_PRACTICAL_GUIDANCE.items():
        if k.lower() == clean_name.lower() or k.lower() in clean_name.lower():
            matched_guidance = v
            break

    if matched_guidance:
        rec_project = matched_guidance["project"]
        example_bullet = matched_guidance["example_bullet"]
    else:
        rec_project = f"Hands-on portfolio project or microservice implementing {clean_name} with automated testing and documentation."
        example_bullet = f"Utilized {clean_name} to develop core application features, improving workflow efficiency and ensuring reliable execution."

    suggestions = [
        f"Add a concrete bullet point under your 'Projects' or 'Work Experience' section detailing how you utilized {clean_name}.",
        f"Recommended Project: {rec_project}",
        f"Sample Resume Bullet: \"{example_bullet}\""
    ]

    return rec_project, example_bullet, suggestions


def map_skill_evidence(
    resume_text: str = "",
    analysis_record: Optional[Dict[str, Any]] = None,
    target_skills: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Maps each detected skill to specific sections of the resume.
    Identifies evidence locations (Projects, Experience, Education, Certifications, Summary, Skills List),
    determines evidence strength (Strong, Partial, No Supporting Evidence),
    and generates concrete suggestions for skills lacking practical demonstration.
    """
    raw_text = (resume_text or "").strip()

    # Fallback to load text from analysis_record if omitted
    if not raw_text and analysis_record:
        raw_text = (analysis_record.get("resume_text") or "").strip()
        if not raw_text:
            filename = analysis_record.get("resume_filename", "")
            if filename:
                candidate_path = os.path.join(config.UPLOAD_FOLDER, filename)
                if os.path.exists(candidate_path):
                    try:
                        from utils.pdf_reader import extract_text_from_file
                        raw_text = extract_text_from_file(candidate_path)
                    except Exception as err:
                        logger.warning(f"Could not read upload resume file {candidate_path}: {err}")

    # Standardize sections
    sections = standardize_resume_sections(raw_text)

    # Extract structured project and experience blocks
    projects_list = extract_projects_entries(sections.get("projects", ""))
    experience_list = extract_experience_entries(sections.get("experience", ""))

    # If no raw resume text is available, synthesize context from analysis_record results
    analysis_results = (analysis_record.get("results") or {}) if analysis_record else {}
    job_match = analysis_results.get("job_match") or {}
    matched_from_jm = job_match.get("matched_skills") or job_match.get("matching_skills") or []
    if isinstance(matched_from_jm, str):
        matched_from_jm = [s.strip() for s in matched_from_jm.split(",") if s.strip()]

    # Collect list of skills to map
    if target_skills:
        skills_to_evaluate = target_skills
    else:
        skills_to_evaluate = detect_skills_in_resume(
            resume_text=raw_text,
            sections=sections,
            explicit_skills=matched_from_jm
        )

    # If still empty, supply common baseline from results
    if not skills_to_evaluate and matched_from_jm:
        skills_to_evaluate = matched_from_jm

    mapped_skills: List[Dict[str, Any]] = []
    strong_count = 0
    partial_count = 0
    unsupported_count = 0

    for skill in skills_to_evaluate:
        skill_name = str(skill).strip()
        if not skill_name:
            continue

        rx = _build_skill_regex(skill_name)
        locations: List[Dict[str, Any]] = []
        sections_found: List[str] = []

        # 1. Check in Projects
        has_project_evidence = False
        if projects_list:
            for proj in projects_list:
                p_title = proj.get("title", "Project")
                p_desc = proj.get("description", "")
                p_tech = proj.get("technologies", "")
                full_proj = f"{p_title} {p_tech} {p_desc}"

                if rx.search(full_proj):
                    has_project_evidence = True
                    snippet = extract_contextual_snippet(f"{p_tech}\n{p_desc}", skill_name) or p_desc[:120]
                    locations.append({
                        "section": "Projects",
                        "context_title": p_title,
                        "snippet": snippet or f"Demonstrated in {p_title} tech stack.",
                        "evidence_type": "project_implementation"
                    })
                    if "Projects" not in sections_found:
                        sections_found.append("Projects")
        elif sections.get("projects") and rx.search(sections["projects"]):
            has_project_evidence = True
            snippet = extract_contextual_snippet(sections["projects"], skill_name)
            locations.append({
                "section": "Projects",
                "context_title": "Academic / Personal Projects",
                "snippet": snippet or "Referenced in projects section.",
                "evidence_type": "project_implementation"
            })
            if "Projects" not in sections_found:
                sections_found.append("Projects")

        # 2. Check in Work Experience
        has_experience_evidence = False
        if experience_list:
            for exp in experience_list:
                e_role = exp.get("role", "Role")
                e_comp = exp.get("company", "Company")
                e_resp = exp.get("responsibilities", "")
                full_exp = f"{e_role} {e_comp} {e_resp}"

                if rx.search(full_exp):
                    has_experience_evidence = True
                    snippet = extract_contextual_snippet(e_resp, skill_name) or e_resp[:120]
                    locations.append({
                        "section": "Work Experience",
                        "context_title": f"{e_role} at {e_comp}" if e_comp else e_role,
                        "snippet": snippet or f"Employed during tenure as {e_role}.",
                        "evidence_type": "work_experience"
                    })
                    if "Work Experience" not in sections_found:
                        sections_found.append("Work Experience")
        elif sections.get("experience") and rx.search(sections["experience"]):
            has_experience_evidence = True
            snippet = extract_contextual_snippet(sections["experience"], skill_name)
            locations.append({
                "section": "Work Experience",
                "context_title": "Professional Experience",
                "snippet": snippet or "Referenced in employment history.",
                "evidence_type": "work_experience"
            })
            if "Work Experience" not in sections_found:
                sections_found.append("Work Experience")

        # 3. Check in Education & Certifications
        has_academic_evidence = False
        if sections.get("education") and rx.search(sections["education"]):
            has_academic_evidence = True
            snippet = extract_contextual_snippet(sections["education"], skill_name)
            locations.append({
                "section": "Education",
                "context_title": "Academic Coursework",
                "snippet": snippet or "Referenced in academic coursework.",
                "evidence_type": "coursework"
            })
            if "Education" not in sections_found:
                sections_found.append("Education")

        if sections.get("certifications") and rx.search(sections["certifications"]):
            has_academic_evidence = True
            snippet = extract_contextual_snippet(sections["certifications"], skill_name)
            locations.append({
                "section": "Certifications",
                "context_title": "Certifications & Achievements",
                "snippet": snippet or "Verified certification / credential.",
                "evidence_type": "certification"
            })
            if "Certifications" not in sections_found:
                sections_found.append("Certifications")

        # 4. Check in Summary
        has_summary_mention = False
        if sections.get("summary") and rx.search(sections["summary"]):
            has_summary_mention = True
            snippet = extract_contextual_snippet(sections["summary"], skill_name)
            locations.append({
                "section": "Profile Summary",
                "context_title": "Career Profile",
                "snippet": snippet or "Highlighted in summary statement.",
                "evidence_type": "summary_claim"
            })
            if "Profile Summary" not in sections_found:
                sections_found.append("Profile Summary")

        # 5. Check in Skills section
        in_skills_list = False
        if sections.get("skills") and rx.search(sections["skills"]):
            in_skills_list = True
            locations.append({
                "section": "Technical Skills",
                "context_title": "Skills Inventory",
                "snippet": extract_contextual_snippet(sections["skills"], skill_name) or f"Listed in skills section under {skill_name}.",
                "evidence_type": "skills_list"
            })
            if "Technical Skills" not in sections_found:
                sections_found.append("Technical Skills")

        # Fallback if no sections parsed: search raw text directly
        if not locations and raw_text and rx.search(raw_text):
            snippet = extract_contextual_snippet(raw_text, skill_name)
            locations.append({
                "section": "Resume Body",
                "context_title": "Resume Text",
                "snippet": snippet,
                "evidence_type": "text_mention"
            })
            sections_found.append("Resume Body")

        # Determine Evidence Strength Level
        if has_project_evidence or has_experience_evidence:
            evidence_level = "Strong Evidence"
            status = "supported"
            is_supported = True
            badge_class = "success"
            badge_icon = "fa-circle-check"
            strong_count += 1
            evidence_summary = (
                f"Demonstrated with tangible evidence in {' and '.join(sections_found[:2])}."
            )
            rec_project, example_bullet, suggestions = "", "", []
        elif has_academic_evidence or has_summary_mention:
            evidence_level = "Partial Evidence"
            status = "partial"
            is_supported = False
            badge_class = "warning"
            badge_icon = "fa-triangle-exclamation"
            partial_count += 1
            unsupported_count += 1
            evidence_summary = (
                f"Mentioned in {sections_found[0] if sections_found else 'coursework'}, but lacks detailed implementation in Projects or Work Experience."
            )
            rec_project, example_bullet, suggestions = generate_skill_guidance(skill_name)
        else:
            evidence_level = "No Supporting Evidence"
            status = "unsupported"
            is_supported = False
            badge_class = "danger"
            badge_icon = "fa-circle-exclamation"
            unsupported_count += 1
            evidence_summary = (
                "Listed in skills section only, without supporting project or work experience."
            )
            rec_project, example_bullet, suggestions = generate_skill_guidance(skill_name)

        mapped_skills.append({
            "skill": skill_name,
            "status": status,
            "evidence_level": evidence_level,
            "is_supported": is_supported,
            "badge_class": badge_class,
            "badge_icon": badge_icon,
            "evidence_locations": locations,
            "sections_found": sections_found,
            "evidence_summary": evidence_summary,
            "suggestions": suggestions,
            "recommended_project": rec_project,
            "example_bullet": example_bullet
        })

    # Sort so skills needing evidence appear first, followed by well-supported ones
    priority_order = {"unsupported": 0, "partial": 1, "supported": 2}
    mapped_skills.sort(key=lambda item: (priority_order.get(item["status"], 3), item["skill"].lower()))

    total_evaluated = len(mapped_skills)
    evidence_score = round((strong_count / total_evaluated) * 100) if total_evaluated > 0 else 100

    if unsupported_count == 0:
        overall_summary = f"Excellent! All {total_evaluated} identified skills have verified supporting evidence in your projects or work experience."
    elif strong_count > 0:
        overall_summary = (
            f"{strong_count} of {total_evaluated} skills have strong project/experience evidence. "
            f"{unsupported_count} skill{'s' if unsupported_count > 1 else ''} need practical demonstration or project bullets."
        )
    else:
        overall_summary = (
            f"Most skills ({unsupported_count} of {total_evaluated}) are listed without supporting project evidence. "
            "Add project bullet points demonstrating practical implementation."
        )

    return {
        "total_skills": total_evaluated,
        "supported_skills_count": strong_count,
        "unsupported_skills_count": unsupported_count,
        "partial_skills_count": partial_count,
        "evidence_score": evidence_score,
        "summary": overall_summary,
        "skills": mapped_skills
    }

