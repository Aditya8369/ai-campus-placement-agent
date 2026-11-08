"""
Resume Information Extractor and Review Engine.

Extracts structured information from resume text:
- Candidate Name
- Contact Information (Email, Phone)
- Professional Summary
- Education (Institutions, Degrees, Fields, Years, Scores)
- Technical & Soft Skills
- Projects (Titles, Tech Stacks, Descriptions)
- Work & Internship Experience (Roles, Companies, Durations, Contributions)

Detects missing or incomplete fields and flags them for candidate review.
Validates candidate-corrected information and reconstructs standardized markdown
for downstream placement analysis agents while keeping original documents pristine.
"""

import re
import uuid
from typing import Dict, List, Any, Tuple, Optional
from utils.pdf_reader import standardize_resume_sections


# Common technical skills dictionary for heuristic extraction
COMMON_TECH_SKILLS = [
    "Python", "Java", "C++", "C", "C#", "JavaScript", "TypeScript", "Go", "Rust", "Ruby",
    "PHP", "Swift", "Kotlin", "Scala", "R", "MATLAB", "Dart", "HTML", "CSS", "Sass",
    "React", "React Native", "Angular", "Vue.js", "Next.js", "Node.js", "Express.js",
    "Django", "Flask", "FastAPI", "Spring Boot", "ASP.NET", "Hibernate", "jQuery",
    "Tailwind CSS", "Bootstrap", "Redux", "GraphQL", "REST APIs", "Microservices",
    "SQL", "MySQL", "PostgreSQL", "SQLite", "MongoDB", "Redis", "Cassandra", "Oracle",
    "AWS", "Microsoft Azure", "Google Cloud", "GCP", "Docker", "Kubernetes", "Terraform",
    "Jenkins", "GitHub Actions", "CI/CD", "Git", "GitHub", "GitLab", "Linux", "Unix",
    "Machine Learning", "Deep Learning", "Artificial Intelligence", "NLP", "Computer Vision",
    "TensorFlow", "PyTorch", "Keras", "Scikit-Learn", "Pandas", "NumPy", "OpenCV",
    "Data Structures", "Algorithms", "Object-Oriented Programming", "OOP", "DBMS",
    "Operating Systems", "Computer Networks", "System Design", "Agile", "Scrum",
    "Unit Testing", "PyTest", "Jest", "Selenium", "Postman", "Kafka", "RabbitMQ"
]


def extract_candidate_name(raw_text: str, summary_text: str = "") -> Tuple[str, str]:
    """
    Extracts the candidate's name from header lines with confidence status.
    Returns (candidate_name, status). Status is 'extracted' or 'needs_review'.
    """
    if not raw_text:
        return "", "needs_review"

    # Stop before major resume section headers
    first_sec = re.search(
        r"(?:^|\n)\s*(?:[#*_\-~=]+\s*)?(?:education|academic|skills|experience|work|projects|certifications|summary|objective|profile)\b",
        raw_text,
        re.IGNORECASE
    )
    header_chunk = raw_text[:first_sec.start()] if first_sec else raw_text
    lines = [line.strip() for line in header_chunk.splitlines() if line.strip()]
    if not lines:
        return "Candidate", "needs_review"

    # Common non-name keywords in headers
    stop_words = {
        "resume", "curriculum", "vitae", "cv", "page", "email", "phone", "contact",
        "github", "linkedin", "profile", "summary", "objective", "education", "skills",
        "experience", "projects", "certifications", "portfolio", "address", "http", "https",
        "student", "studying", "college", "university", "school", "background", "work",
        "academic", "programming", "developer", "engineer", "looking", "seeking", "intern",
        "helped", "developed", "building", "passionate", "undergraduate", "graduate", "fresher"
    }

    candidate_name = ""
    for line in lines[:6]:
        clean = re.sub(r"[#*_\-~=]+", " ", line).strip()
        clean = re.sub(r"\s+", " ", clean)

        # Exclude lines with email, phone, or URLs
        if "@" in clean or re.search(r"\b\d{4,}\b", clean) or "http" in clean.lower():
            continue

        words = clean.split()
        if 2 <= len(words) <= 4:
            lower_words = [w.lower().strip(".,:;()") for w in words]
            if any(w in stop_words for w in lower_words):
                continue
            # Person names are typically capitalized and purely alphabetic
            if all(w[0].isupper() and re.match(r"^[A-Za-z.\-']+$", w) for w in words):
                candidate_name = clean
                break

    if candidate_name and len(candidate_name.split()) >= 2:
        return candidate_name, "extracted"
    elif candidate_name:
        return candidate_name, "needs_review"
    return "Candidate", "needs_review"


def extract_emails(raw_text: str) -> Tuple[str, str]:
    """Extracts candidate email with extraction status."""
    match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", raw_text)
    if match:
        return match.group(0), "extracted"
    return "", "needs_review"


def extract_phone(raw_text: str) -> Tuple[str, str]:
    """Extracts candidate phone number with extraction status."""
    patterns = [
        r"(?:\+?91[\s-]?)?[6789]\d{9}\b",
        r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
        r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_text)
        if match:
            return match.group(0).strip(), "extracted"
    return "", "needs_review"


def extract_education_entries(education_text: str) -> List[Dict[str, Any]]:
    """
    Parses education text into structured degree/institution entries.
    Flags entries with incomplete information.
    """
    if not education_text or not education_text.strip():
        return []

    lines = [l.strip() for l in education_text.splitlines() if l.strip()]
    entries: List[Dict[str, Any]] = []

    # Degree patterns
    degree_pattern = re.compile(
        r"\b(B\.?Tech|B\.?E\.?|B\.?Sc|B\.?S|M\.?Tech|M\.?S|M\.?Sc|MCA|BCA|Bachelor|Master|High School|12th|10th|Diploma|Intermediate)\b[^\n,]*",
        re.IGNORECASE
    )
    year_pattern = re.compile(r"\b(19\d{2}|20\d{2})\s*(?:[-–to]+\s*(19\d{2}|20\d{2}|present|current))?\b", re.IGNORECASE)
    score_pattern = re.compile(r"\b(?:CGPA|GPA|Score|Percentage|Marks)?\s*[:=\-]?\s*(\d+(?:\.\d+)?\s*(?:/\s*\d+(?:\.\d+)?)?%?)\b", re.IGNORECASE)

    current_entry: Dict[str, Any] = {}

    for line in lines:
        has_degree = degree_pattern.search(line)
        has_year = year_pattern.search(line)
        has_institution = any(k in line.lower() for k in ["university", "college", "institute", "school", "academy", "polytechnic", "vidyalaya", "iit", "nit", "bits"])

        # New entry indicator if line has degree or strong institution match
        if (has_degree or has_institution) and current_entry.get("institution") and current_entry.get("degree"):
            entries.append(current_entry)
            current_entry = {}

        if not current_entry:
            current_entry = {
                "id": str(uuid.uuid4())[:8],
                "institution": "",
                "degree": "",
                "field_of_study": "",
                "graduation_year": "",
                "score": "",
                "is_incomplete": False,
                "extraction_status": "extracted"
            }

        if has_degree and not current_entry["degree"]:
            current_entry["degree"] = has_degree.group(0).strip()
            # Check for field of study
            field_match = re.search(r"in\s+([A-Za-z\s&]+)", line, re.IGNORECASE)
            if field_match:
                current_entry["field_of_study"] = field_match.group(1).strip()

        if has_institution and not current_entry["institution"]:
            current_entry["institution"] = line.strip(" -•*")
        elif not current_entry["institution"] and not has_degree:
            current_entry["institution"] = line.strip(" -•*")

        if has_year and not current_entry["graduation_year"]:
            current_entry["graduation_year"] = has_year.group(0).strip()

        score_match = score_pattern.search(line)
        if score_match and not current_entry["score"]:
            current_entry["score"] = score_match.group(1).strip()

    if current_entry and (current_entry.get("degree") or current_entry.get("institution")):
        entries.append(current_entry)

    # If parsing couldn't isolate structured items, create a single item from the text
    if not entries and education_text.strip():
        first_line = lines[0] if lines else education_text[:100]
        deg_match = degree_pattern.search(education_text)
        year_match = year_pattern.search(education_text)
        score_match = score_pattern.search(education_text)
        entries.append({
            "id": str(uuid.uuid4())[:8],
            "institution": first_line if "university" in first_line.lower() or "college" in first_line.lower() else "University / Institution",
            "degree": deg_match.group(0).strip() if deg_match else "Degree / Diploma",
            "field_of_study": "Computer Science / Engineering",
            "graduation_year": year_match.group(0).strip() if year_match else "",
            "score": score_match.group(1).strip() if score_match else "",
            "is_incomplete": True,
            "extraction_status": "needs_review"
        })

    # Validate each entry completeness
    for e in entries:
        if not e.get("institution") or not e.get("degree") or not e.get("graduation_year"):
            e["is_incomplete"] = True
            e["extraction_status"] = "needs_review"
        else:
            e["is_incomplete"] = False
            e["extraction_status"] = "extracted"

    return entries


def extract_skills_list(skills_text: str, full_resume_text: str) -> List[str]:
    """
    Extracts individual skill keywords from skills section and full text.
    Returns deduplicated list of skills.
    """
    detected_skills = set()

    # Search explicitly in skills section first
    target_text = skills_text if skills_text and len(skills_text.strip()) > 10 else full_resume_text

    # 1. Look for known skills via regex word boundaries
    lower_target = target_text.lower()
    for skill in COMMON_TECH_SKILLS:
        skill_clean = skill.lower()
        if re.search(r"\b" + re.escape(skill_clean) + r"\b", lower_target):
            detected_skills.add(skill)

    # 2. Also split skills section by delimiters (comma, bullet, pipes, newlines)
    if skills_text:
        parts = re.split(r"[,|\n•\*\t;/]+", skills_text)
        for part in parts:
            item = part.strip()
            # Clean category prefixes like "Programming Languages:", "Frameworks:"
            item = re.sub(r"^[A-Za-z\s]+:\s*", "", item).strip()
            if 2 <= len(item) <= 30 and not any(k in item.lower() for k in ["skill", "proficient", "familiar", "technical", "competencies"]):
                # Capitalize nicely if not already in detected
                if not any(item.lower() == s.lower() for s in detected_skills):
                    detected_skills.add(item.title() if item.islower() else item)

    return sorted(list(detected_skills))


def extract_projects_entries(projects_text: str) -> List[Dict[str, Any]]:
    """
    Parses projects section into structured list of project cards.
    """
    if not projects_text or not projects_text.strip():
        return []

    lines = [l.strip() for l in projects_text.splitlines() if l.strip()]
    projects: List[Dict[str, Any]] = []
    current_proj: Dict[str, Any] = {}

    for line in lines:
        is_bullet = line.startswith(("-", "•", "*", "–"))
        clean_line = line.lstrip("-•*– ").strip()

        # Check if this line looks like a project title (short, not a bullet, or bold header)
        is_title_candidate = (
            not is_bullet and
            len(clean_line) < 70 and
            not clean_line.endswith((".", ";")) and
            not any(clean_line.lower().startswith(p) for p in ["tech:", "technologies:", "tools:", "developed", "built", "implemented", "created"])
        )

        if is_title_candidate and current_proj.get("title"):
            projects.append(current_proj)
            current_proj = {}

        if not current_proj:
            current_proj = {
                "id": str(uuid.uuid4())[:8],
                "title": "",
                "technologies": "",
                "description": "",
                "link": "",
                "is_incomplete": False,
                "extraction_status": "extracted"
            }

        if not current_proj["title"]:
            # If line contains tech stack e.g. "E-Commerce App | React, Node.js"
            if "|" in clean_line:
                t_parts = clean_line.split("|", 1)
                current_proj["title"] = t_parts[0].strip()
                current_proj["technologies"] = t_parts[1].strip()
            elif "(" in clean_line and ")" in clean_line:
                match = re.match(r"^(.*?)\((.*?)\)", clean_line)
                if match:
                    current_proj["title"] = match.group(1).strip()
                    current_proj["technologies"] = match.group(2).strip()
                else:
                    current_proj["title"] = clean_line
            else:
                current_proj["title"] = clean_line
        elif any(clean_line.lower().startswith(p) for p in ["tech:", "technologies:", "tools:", "stack:"]):
            tech_val = re.sub(r"^(tech|technologies|tools|stack):\s*", "", clean_line, flags=re.IGNORECASE)
            current_proj["technologies"] = tech_val.strip()
        else:
            if current_proj["description"]:
                current_proj["description"] += "\n" + clean_line
            else:
                current_proj["description"] = clean_line

    if current_proj and current_proj.get("title"):
        projects.append(current_proj)

    for p in projects:
        if not p["title"] or not p["description"]:
            p["is_incomplete"] = True
            p["extraction_status"] = "needs_review"
        else:
            p["is_incomplete"] = False
            p["extraction_status"] = "extracted"

    return projects


def extract_experience_entries(experience_text: str) -> List[Dict[str, Any]]:
    """
    Parses experience / internship section into structured experience cards.
    """
    if not experience_text or not experience_text.strip():
        return []

    lines = [l.strip() for l in experience_text.splitlines() if l.strip()]
    experiences: List[Dict[str, Any]] = []
    current_exp: Dict[str, Any] = {}

    date_regex = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Present|\d{4})\b", re.IGNORECASE)

    for line in lines:
        is_bullet = line.startswith(("-", "•", "*", "–"))
        clean_line = line.lstrip("-•*– ").strip()

        has_dates = date_regex.search(clean_line)
        is_heading_candidate = not is_bullet and len(clean_line) < 80 and (
            has_dates or any(k in clean_line.lower() for k in ["intern", "engineer", "developer", "lead", "assistant", "associate", "trainee", "analyst"])
        )

        if is_heading_candidate and current_exp.get("role") and current_exp.get("company"):
            experiences.append(current_exp)
            current_exp = {}

        if not current_exp:
            current_exp = {
                "id": str(uuid.uuid4())[:8],
                "role": "",
                "company": "",
                "duration": "",
                "responsibilities": "",
                "is_incomplete": False,
                "extraction_status": "extracted"
            }

        if not current_exp["role"]:
            # Check for combined formats: "Software Engineer Intern - Google (May 2023 - Aug 2023)"
            if " - " in clean_line or " at " in clean_line or " | " in clean_line:
                sep = " at " if " at " in clean_line else (" - " if " - " in clean_line else " | ")
                parts = clean_line.split(sep, 1)
                current_exp["role"] = parts[0].strip()
                rem = parts[1].strip()
                date_match = re.search(r"\((.*?)\)", rem)
                if date_match:
                    current_exp["duration"] = date_match.group(1).strip()
                    current_exp["company"] = rem.replace(date_match.group(0), "").strip()
                else:
                    current_exp["company"] = rem
            else:
                current_exp["role"] = clean_line
        elif not current_exp["company"]:
            current_exp["company"] = clean_line
        elif not current_exp["duration"] and has_dates:
            current_exp["duration"] = clean_line
        else:
            if current_exp["responsibilities"]:
                current_exp["responsibilities"] += "\n" + clean_line
            else:
                current_exp["responsibilities"] = clean_line

    if current_exp and (current_exp.get("role") or current_exp.get("company")):
        experiences.append(current_exp)

    for exp in experiences:
        if not exp["role"] or not exp["company"]:
            exp["is_incomplete"] = True
            exp["extraction_status"] = "needs_review"
        else:
            exp["is_incomplete"] = False
            exp["extraction_status"] = "extracted"

    return experiences


def extract_resume_information(raw_text: str, filename: str = "", file_uuid: Optional[str] = None) -> Dict[str, Any]:
    """
    Main extraction pipeline.
    Parses raw resume text into structured components with review flags, quality assessments,
    and missing information indicators.
    """
    if not file_uuid:
        file_uuid = str(uuid.uuid4())

    sections = standardize_resume_sections(raw_text)

    # 1. Header Information
    summary_text = sections.get("summary", "")
    name, name_status = extract_candidate_name(raw_text, summary_text)
    email, email_status = extract_emails(raw_text)
    phone, phone_status = extract_phone(raw_text)

    # Clean summary of extracted header info
    clean_summary = summary_text
    if name and name in clean_summary:
        clean_summary = clean_summary.replace(name, "").strip()
    if email and email in clean_summary:
        clean_summary = clean_summary.replace(email, "").strip()
    if phone and phone in clean_summary:
        clean_summary = clean_summary.replace(phone, "").strip()
    clean_summary = re.sub(r"^[,\s|;\n]+", "", clean_summary).strip()
    summary_status = "extracted" if len(clean_summary) >= 20 else "needs_review"

    # 2. Education
    education_list = extract_education_entries(sections.get("education", ""))
    education_status = "extracted" if education_list and not any(e["is_incomplete"] for e in education_list) else "needs_review"

    # 3. Skills
    skills_list = extract_skills_list(sections.get("skills", ""), raw_text)
    skills_status = "extracted" if len(skills_list) >= 3 else "needs_review"

    # 4. Projects
    projects_list = extract_projects_entries(sections.get("projects", ""))
    projects_status = "extracted" if projects_list and not any(p["is_incomplete"] for p in projects_list) else "needs_review"

    # 5. Experience
    experience_list = extract_experience_entries(sections.get("experience", ""))
    experience_status = "extracted" if experience_list and not any(exp["is_incomplete"] for exp in experience_list) else "needs_review"

    # Compile field-level review flags and guidance messages
    review_flags: Dict[str, Dict[str, Any]] = {
        "candidate_name": {
            "status": name_status,
            "message": "Candidate name extracted from resume header." if name_status == "extracted" else "Could not confidently identify your full name. Please verify or enter your full name."
        },
        "email": {
            "status": email_status,
            "message": "Email address detected." if email_status == "extracted" else "No email address found. Adding contact details is recommended."
        },
        "phone": {
            "status": phone_status,
            "message": "Phone number detected." if phone_status == "extracted" else "No phone number detected. You can provide your mobile number."
        },
        "summary": {
            "status": summary_status,
            "message": "Professional summary detected." if summary_status == "extracted" else "Summary is missing or very brief. You can enhance your profile with an objective statement."
        },
        "education": {
            "status": education_status,
            "incomplete_count": sum(1 for e in education_list if e.get("is_incomplete")),
            "message": "Education credentials verified." if education_status == "extracted" else "One or more education fields (institution, degree, or year) require review or completion."
        },
        "skills": {
            "status": skills_status,
            "count": len(skills_list),
            "message": f"{len(skills_list)} technical skills identified." if skills_status == "extracted" else "Few or no technical skills were detected. Please add your key technologies and tools."
        },
        "projects": {
            "status": projects_status,
            "count": len(projects_list),
            "incomplete_count": sum(1 for p in projects_list if p.get("is_incomplete")),
            "message": f"{len(projects_list)} projects identified." if projects_status == "extracted" else "No projects detected or some descriptions are missing. Add your portfolio projects."
        },
        "experience": {
            "status": experience_status,
            "count": len(experience_list),
            "incomplete_count": sum(1 for exp in experience_list if exp.get("is_incomplete")),
            "message": f"{len(experience_list)} work/internship experiences identified." if experience_status == "extracted" else "No work experience found. If you have internships, add them below; freshers can leave this optional."
        }
    }

    # Count items needing attention
    total_review_items = sum(1 for f in review_flags.values() if f.get("status") == "needs_review")

    if total_review_items == 0:
        quality = "good"
    elif total_review_items <= 3:
        quality = "needs_attention"
    else:
        quality = "poor"

    return {
        "file_uuid": file_uuid,
        "original_filename": filename or "Resume.pdf",
        "raw_text": raw_text,
        "candidate_name": name,
        "email": email,
        "phone": phone,
        "summary": clean_summary,
        "education": education_list,
        "skills": skills_list,
        "projects": projects_list,
        "experience": experience_list,
        "review_flags": review_flags,
        "total_review_items": total_review_items,
        "overall_extraction_quality": quality
    }


def validate_reviewed_information(data: Dict[str, Any]) -> Tuple[bool, Dict[str, str]]:
    """
    Validates reviewed candidate resume information before submitting to AI placement analysis.
    Returns (is_valid, error_dict).
    """
    errors: Dict[str, str] = {}

    # 1. Candidate Name Validation
    name = (data.get("candidate_name") or "").strip()
    if not name:
        errors["candidate_name"] = "Candidate name is required."
    elif len(name) < 2:
        errors["candidate_name"] = "Candidate name must be at least 2 characters long."
    elif re.match(r"^\d+$", name):
        errors["candidate_name"] = "Candidate name cannot consist solely of digits."

    # 2. Email Validation (if provided)
    email = (data.get("email") or "").strip()
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        errors["email"] = "Please provide a valid email address (e.g., student@example.com)."

    # 3. Skills Validation (must have at least 1 technical skill)
    skills = data.get("skills") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]
    if not skills or len(skills) == 0:
        errors["skills"] = "Please provide at least one core skill or technology."

    # 4. Education Validation
    education = data.get("education") or []
    if education:
        for idx, edu in enumerate(education):
            inst = (edu.get("institution") or "").strip()
            deg = (edu.get("degree") or "").strip()
            if not inst and not deg:
                errors[f"education_{idx}"] = f"Education entry #{idx + 1} must have an institution or degree specified."

    # 5. Projects Validation
    projects = data.get("projects") or []
    if projects:
        for idx, proj in enumerate(projects):
            title = (proj.get("title") or "").strip()
            if not title:
                errors[f"project_{idx}"] = f"Project #{idx + 1} must include a title."

    # 6. Experience Validation
    experiences = data.get("experience") or []
    if experiences:
        for idx, exp in enumerate(experiences):
            role = (exp.get("role") or "").strip()
            company = (exp.get("company") or "").strip()
            if not role and not company:
                errors[f"experience_{idx}"] = f"Experience #{idx + 1} must include a role or company name."

    is_valid = len(errors) == 0
    return is_valid, errors


def reconstruct_resume_markdown(data: Dict[str, Any]) -> str:
    """
    Reconstructs standardized, high-clarity Markdown representation from reviewed resume data.
    This structured representation is consumed by the Coordinator Agent and specialized AI agents.
    """
    sections: List[str] = []

    # 1. Header & Contact
    name = (data.get("candidate_name") or "Candidate").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()

    header_parts = [f"# {name}"]
    contacts = []
    if email:
        contacts.append(f"Email: {email}")
    if phone:
        contacts.append(f"Phone: {phone}")
    if contacts:
        header_parts.append(" | ".join(contacts))

    sections.append("\n".join(header_parts))

    # 2. Summary
    summary = (data.get("summary") or "").strip()
    if summary:
        sections.append(f"### Contact & Professional Summary\n{summary}")

    # 3. Education
    education_entries = data.get("education") or []
    if education_entries:
        edu_lines = ["### Education & Qualifications"]
        for edu in education_entries:
            deg = (edu.get("degree") or "Degree").strip()
            field = (edu.get("field_of_study") or "").strip()
            inst = (edu.get("institution") or "").strip()
            year = (edu.get("graduation_year") or "").strip()
            score = (edu.get("score") or "").strip()

            line = f"- **{deg}**"
            if field:
                line += f" in {field}"
            if inst:
                line += f", {inst}"
            if year:
                line += f" ({year})"
            if score:
                line += f" - Score: {score}"
            edu_lines.append(line)
        sections.append("\n".join(edu_lines))

    # 4. Skills
    skills = data.get("skills") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]
    if skills:
        sections.append("### Technical Skills & Competencies\n" + ", ".join(skills))

    # 5. Projects
    projects = data.get("projects") or []
    if projects:
        proj_lines = ["### Key Projects & Portfolio"]
        for proj in projects:
            title = (proj.get("title") or "Project").strip()
            tech = (proj.get("technologies") or "").strip()
            desc = (proj.get("description") or "").strip()
            link = (proj.get("link") or "").strip()

            line = f"- **{title}**"
            if tech:
                line += f" ({tech})"
            if link:
                line += f" [Link: {link}]"
            if desc:
                # Indent description
                desc_formatted = "\n  ".join(desc.splitlines())
                line += f"\n  {desc_formatted}"
            proj_lines.append(line)
        sections.append("\n".join(proj_lines))

    # 6. Experience
    experience = data.get("experience") or []
    if experience:
        exp_lines = ["### Work Experience & Internships"]
        for exp in experience:
            role = (exp.get("role") or "Role").strip()
            comp = (exp.get("company") or "").strip()
            dur = (exp.get("duration") or "").strip()
            resp = (exp.get("responsibilities") or "").strip()

            line = f"- **{role}**"
            if comp:
                line += f" at **{comp}**"
            if dur:
                line += f" ({dur})"
            if resp:
                resp_formatted = "\n  ".join(resp.splitlines())
                line += f"\n  {resp_formatted}"
            exp_lines.append(line)
        sections.append("\n".join(exp_lines))

    return "\n\n".join(sections).strip()
