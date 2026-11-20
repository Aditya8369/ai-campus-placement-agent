"""
ATS-Friendly Resume Generation Engine and Template Gallery (#561).

Provides:
- 3 single-column ATS templates (classic, compact, project-focused).
- Clean, non-distracting single-column formatting:
  * Standard section headings (SUMMARY, EDUCATION, TECHNICAL SKILLS, EXPERIENCE, PROJECTS, CERTIFICATIONS).
  * Plain standard fonts (Times New Roman / Georgia or Helvetica / Arial / Calibri).
  * Absolutely NO tables, columns, text boxes, or embedded images.
- Valid in-memory DOCX and PDF generation streamed on the fly without disk persistence.
- Interactive HTML preview generator for in-browser inspection.
- Optional section inclusion/exclusion toggling without blank gaps.
- Complete text escaping and robust rendering of special characters (&, <, >, quotes, dashes, bullets).
"""

import io
import html
import xml.sax.saxutils as saxutils
from typing import Dict, Any, List, Optional

import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# Supported template IDs
TEMPLATES = {
    "classic": {
        "id": "classic",
        "name": "Classic Academic / Corporate",
        "description": "Traditional single-column layout with balanced margins and serif typography. Ideal for corporate, finance, and traditional engineering campus drives.",
        "font_family_docx": "Times New Roman",
        "font_family_pdf": "Times-Roman",
        "font_family_bold_pdf": "Times-Bold",
        "font_family_italic_pdf": "Times-Italic",
        "default_order": ["summary", "education", "skills", "experience", "projects", "certifications"],
        "margin_inches": 0.75,
        "primary_color": "#111827",
    },
    "compact": {
        "id": "compact",
        "name": "Compact 1-Page Modern",
        "description": "Space-optimized single-column layout with tighter line heights and inline contact details. Ensures rich experience fits cleanly on a single page.",
        "font_family_docx": "Calibri",
        "font_family_pdf": "Helvetica",
        "font_family_bold_pdf": "Helvetica-Bold",
        "font_family_italic_pdf": "Helvetica-Oblique",
        "default_order": ["summary", "skills", "experience", "projects", "education", "certifications"],
        "margin_inches": 0.5,
        "primary_color": "#1f2937",
    },
    "project-focused": {
        "id": "project-focused",
        "name": "Project-Focused Tech",
        "description": "Highlights software projects, open source, and technical stacks immediately after skills. Tailored for software developer, data science, and fresher placement drives.",
        "font_family_docx": "Arial",
        "font_family_pdf": "Helvetica",
        "font_family_bold_pdf": "Helvetica-Bold",
        "font_family_italic_pdf": "Helvetica-Oblique",
        "default_order": ["summary", "skills", "projects", "experience", "education", "certifications"],
        "margin_inches": 0.65,
        "primary_color": "#0f172a",
    },
}

ALL_SECTIONS = ["summary", "education", "skills", "experience", "projects", "certifications"]

DEFAULT_SAMPLE_RESUME: Dict[str, Any] = {
    "candidate_name": "Alex Chen",
    "email": "alex.chen@campus.edu",
    "phone": "+1 (555) 234-5678",
    "location": "San Francisco, CA",
    "linkedin": "linkedin.com/in/alexchen",
    "github": "github.com/alexchen",
    "portfolio": "alexchen.dev",
    "summary": "Motivated Computer Science graduate with strong foundations in data structures, algorithms, and full-stack software development. Proficient in Python, C++, and React with practical experience building distributed cloud microservices.",
    "education": [
        {
            "degree": "B.S. in Computer Science",
            "institution": "University of California, Berkeley",
            "year": "2021 – 2025",
            "cgpa": "3.85 / 4.0",
            "highlights": "Dean's Honors List, Relevant Coursework: Data Structures, Operating Systems, Computer Networks, Database Systems."
        }
    ],
    "skills": [
        "Python", "C++", "Java", "JavaScript", "TypeScript",
        "React", "Node.js", "Flask", "FastAPI",
        "PostgreSQL", "Redis", "Docker", "Kubernetes", "AWS (EC2, S3)", "Git"
    ],
    "experience": [
        {
            "role": "Software Engineering Intern",
            "company": "CloudScale Systems",
            "duration": "Jun 2024 – Aug 2024",
            "responsibilities": (
                "Engineered a high-throughput event processing pipeline in Python and Redis handling 10,000+ events/sec.\n"
                "Optimized SQL database query latency by 35% through indexing and connection pool tuning.\n"
                "Collaborated with cross-functional engineering teams in an Agile sprint environment to ship automated integration tests."
            )
        }
    ],
    "projects": [
        {
            "title": "AI Campus Placement Preparation Agent",
            "technologies": "Python, Flask, Google Gemini API, SQLite",
            "description": (
                "Developed an end-to-end recruitment preparation platform featuring automated ATS scoring and mock interview simulations.\n"
                "Implemented deterministic resume analysis rules evaluating 6 core sections with structured feedback.\n"
                "Achieved 95%+ unit test coverage across 30+ automated test suites with sub-second response times."
            )
        },
        {
            "title": "Distributed In-Memory Key-Value Cache",
            "technologies": "C++, TCP Sockets, Multithreading, LRU Eviction",
            "description": (
                "Architected a multithreaded caching server supporting concurrent GET/SET requests with mutex locking.\n"
                "Implemented LRU cache eviction policy maintaining sub-millisecond p99 read latencies under synthetic load."
            )
        }
    ],
    "certifications": [
        "AWS Certified Solutions Architect – Associate (2024)",
        "Certified Kubernetes Application Developer (CKAD) (2024)"
    ]
}


def sanitize_text(text: Any) -> str:
    """Normalize text and replace problematic unicode typography with clean ATS-friendly equivalents."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)

    # Normalize special unicode dashes and smart quotes to clean ASCII equivalents
    replacements = {
        "—": " - ",
        "–": "-",
        "―": " - ",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "•": "*",
        "·": "*",
        "…": "...",
        "\u00a0": " ",  # Non-breaking space
    }
    for orig, rep in replacements.items():
        text = text.replace(orig, rep)
    return text.strip()


def safe_reportlab_escape(text: Any) -> str:
    """Safely escapes text for ReportLab Paragraphs, handling XML entities (&, <, >)."""
    clean = sanitize_text(text)
    return saxutils.escape(clean)


def get_available_templates() -> List[Dict[str, Any]]:
    """Returns metadata for all available ATS-friendly resume templates."""
    return list(TEMPLATES.values())


def _normalize_sections(sections: Optional[List[str]]) -> List[str]:
    """Ensures a valid ordered list of section names."""
    if not sections:
        return ALL_SECTIONS
    normalized = []
    for s in sections:
        clean = str(s).strip().lower()
        if clean in ALL_SECTIONS and clean not in normalized:
            normalized.append(clean)
    return normalized or ALL_SECTIONS


def _parse_bullet_points(content: Any) -> List[str]:
    """Splits freeform description or responsibility text into clean bullet points."""
    if not content:
        return []
    if isinstance(content, list):
        bullets = []
        for item in content:
            s = sanitize_text(item)
            if s:
                bullets.append(s.lstrip("-*•· ").strip())
        return bullets

    text = sanitize_text(content)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    bullets = []
    for line in lines:
        clean = line.lstrip("-*•· ").strip()
        if clean:
            bullets.append(clean)
    return bullets


# ==============================================================================
# DOCX GENERATION (Single-Column, No Tables, Plain Fonts)
# ==============================================================================

def generate_resume_docx(
    resume_data: Dict[str, Any],
    template: str = "classic",
    sections: Optional[List[str]] = None
) -> bytes:
    """
    Generates an ATS-compliant DOCX file in memory without saving to disk.
    Enforces single-column flow, standard headings, plain fonts, and zero tables.
    """
    tpl = TEMPLATES.get(template, TEMPLATES["classic"])
    font_name = tpl["font_family_docx"]
    margin_val = Inches(tpl["margin_inches"])
    active_sections = _normalize_sections(sections)

    doc = docx.Document()

    # Configure page margins
    for section in doc.sections:
        section.top_margin = margin_val
        section.bottom_margin = margin_val
        section.left_margin = margin_val
        section.right_margin = margin_val

    # Set normal style font
    style_normal = doc.styles["Normal"]
    style_normal.font.name = font_name
    style_normal.font.size = Pt(10 if template == "compact" else 10.5)
    style_normal.font.color.rgb = RGBColor(17, 24, 39)

    # 1. Header: Candidate Name
    name = sanitize_text(resume_data.get("candidate_name") or "Candidate Name")
    p_name = doc.add_paragraph()
    p_name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_name.paragraph_format.space_before = Pt(0)
    p_name.paragraph_format.space_after = Pt(2)
    run_name = p_name.add_run(name)
    run_name.font.name = font_name
    run_name.font.size = Pt(18 if template == "compact" else 20)
    run_name.font.bold = True

    # 2. Contact Information Line
    contact_parts = []
    if resume_data.get("email"):
        contact_parts.append(sanitize_text(resume_data["email"]))
    if resume_data.get("phone"):
        contact_parts.append(sanitize_text(resume_data["phone"]))
    if resume_data.get("location"):
        contact_parts.append(sanitize_text(resume_data["location"]))
    if resume_data.get("linkedin"):
        contact_parts.append(sanitize_text(resume_data["linkedin"]))
    if resume_data.get("github"):
        contact_parts.append(sanitize_text(resume_data["github"]))
    if resume_data.get("portfolio"):
        contact_parts.append(sanitize_text(resume_data["portfolio"]))

    if contact_parts:
        p_contact = doc.add_paragraph()
        p_contact.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_contact.paragraph_format.space_before = Pt(0)
        p_contact.paragraph_format.space_after = Pt(8 if template == "compact" else 12)
        run_contact = p_contact.add_run(" | ".join(contact_parts))
        run_contact.font.name = font_name
        run_contact.font.size = Pt(9.5)

    def _add_section_heading(heading_text: str):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(8 if template == "compact" else 12)
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(heading_text.upper())
        run.font.name = font_name
        run.font.size = Pt(11.5 if template == "compact" else 12)
        run.font.bold = True
        run.font.color.rgb = RGBColor(17, 24, 39)

        # Add single bottom border line under heading for ATS visual structure without tables
        pPr = p._element.get_or_add_pPr()
        pBdr = OxmlElement('w:pBdr')
        bottom = OxmlElement('w:bottom')
        bottom.set(qn('w:val'), 'single')
        bottom.set(qn('w:sz'), '6')
        bottom.set(qn('w:space'), '1')
        bottom.set(qn('w:color'), '9CA3AF')
        pBdr.append(bottom)
        pPr.append(pBdr)

    # Render sections according to template order
    order = [s for s in tpl.get("default_order", ALL_SECTIONS) if s in active_sections]

    for sec in order:
        if sec == "summary":
            summary_text = sanitize_text(resume_data.get("summary") or "")
            if summary_text:
                _add_section_heading("Professional Summary")
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(6)
                p.paragraph_format.line_spacing = 1.15
                run = p.add_run(summary_text)
                run.font.name = font_name
                run.font.size = Pt(10)

        elif sec == "education":
            edu_list = resume_data.get("education") or []
            valid_edu = [e for e in edu_list if e.get("institution") or e.get("degree")]
            if valid_edu:
                _add_section_heading("Education")
                for e in valid_edu:
                    deg = sanitize_text(e.get("degree", ""))
                    inst = sanitize_text(e.get("institution", ""))
                    yr = sanitize_text(e.get("year", ""))
                    cgpa = sanitize_text(e.get("cgpa", ""))

                    line1_parts = []
                    if inst:
                        line1_parts.append(inst)
                    if yr:
                        line1_parts.append(yr)

                    p = doc.add_paragraph()
                    p.paragraph_format.space_before = Pt(2)
                    p.paragraph_format.space_after = Pt(1)
                    r_inst = p.add_run(" - ".join(line1_parts))
                    r_inst.font.name = font_name
                    r_inst.font.bold = True

                    line2_parts = []
                    if deg:
                        line2_parts.append(deg)
                    if cgpa:
                        line2_parts.append(f"GPA / Score: {cgpa}")

                    if line2_parts:
                        p2 = doc.add_paragraph()
                        p2.paragraph_format.space_before = Pt(0)
                        p2.paragraph_format.space_after = Pt(4)
                        r_deg = p2.add_run(" | ".join(line2_parts))
                        r_deg.font.name = font_name
                        r_deg.font.italic = True

                    highlights = sanitize_text(e.get("highlights", ""))
                    if highlights:
                        p_hl = doc.add_paragraph(style="List Bullet")
                        p_hl.paragraph_format.space_before = Pt(0)
                        p_hl.paragraph_format.space_after = Pt(2)
                        r_hl = p_hl.add_run(highlights)
                        r_hl.font.name = font_name

        elif sec == "skills":
            skills_data = resume_data.get("skills") or []
            if skills_data:
                _add_section_heading("Technical Skills")
                if isinstance(skills_data, list):
                    skills_str = ", ".join(sanitize_text(s) for s in skills_data if s)
                elif isinstance(skills_data, dict):
                    parts = []
                    for cat, items in skills_data.items():
                        if isinstance(items, list):
                            cat_skills = ", ".join(sanitize_text(i) for i in items if i)
                        else:
                            cat_skills = sanitize_text(items)
                        if cat_skills:
                            parts.append(f"{cat}: {cat_skills}")
                    skills_str = " | ".join(parts)
                else:
                    skills_str = sanitize_text(skills_data)

                if skills_str:
                    p = doc.add_paragraph()
                    p.paragraph_format.space_before = Pt(2)
                    p.paragraph_format.space_after = Pt(6)
                    r = p.add_run(skills_str)
                    r.font.name = font_name

        elif sec == "experience":
            exp_list = resume_data.get("experience") or []
            valid_exp = [x for x in exp_list if x.get("role") or x.get("company")]
            if valid_exp:
                _add_section_heading("Work Experience")
                for x in valid_exp:
                    role = sanitize_text(x.get("role", ""))
                    comp = sanitize_text(x.get("company", ""))
                    dur = sanitize_text(x.get("duration", ""))

                    p_header = doc.add_paragraph()
                    p_header.paragraph_format.space_before = Pt(3)
                    p_header.paragraph_format.space_after = Pt(1)
                    r_role = p_header.add_run(role)
                    r_role.font.name = font_name
                    r_role.font.bold = True

                    if comp or dur:
                        r_comp = p_header.add_run(f" - {comp}" if comp else "")
                        r_comp.font.name = font_name
                        if dur:
                            r_dur = p_header.add_run(f" ({dur})")
                            r_dur.font.name = font_name
                            r_dur.font.italic = True

                    bullets = _parse_bullet_points(x.get("responsibilities") or x.get("description"))
                    for b in bullets:
                        p_bullet = doc.add_paragraph(style="List Bullet")
                        p_bullet.paragraph_format.space_before = Pt(0)
                        p_bullet.paragraph_format.space_after = Pt(2)
                        r_b = p_bullet.add_run(b)
                        r_b.font.name = font_name

        elif sec == "projects":
            proj_list = resume_data.get("projects") or []
            valid_proj = [pr for pr in proj_list if pr.get("title")]
            if valid_proj:
                _add_section_heading("Projects & Technical Work")
                for pr in valid_proj:
                    title = sanitize_text(pr.get("title", ""))
                    tech = sanitize_text(pr.get("technologies") or pr.get("tech_stack", ""))
                    link = sanitize_text(pr.get("link") or pr.get("url", ""))

                    p_proj = doc.add_paragraph()
                    p_proj.paragraph_format.space_before = Pt(3)
                    p_proj.paragraph_format.space_after = Pt(1)
                    r_title = p_proj.add_run(title)
                    r_title.font.name = font_name
                    r_title.font.bold = True

                    if tech:
                        r_tech = p_proj.add_run(f" | Technologies: {tech}")
                        r_tech.font.name = font_name
                        r_tech.font.italic = True

                    if link:
                        r_link = p_proj.add_run(f" ({link})")
                        r_link.font.name = font_name

                    bullets = _parse_bullet_points(pr.get("description") or pr.get("points"))
                    for b in bullets:
                        p_bullet = doc.add_paragraph(style="List Bullet")
                        p_bullet.paragraph_format.space_before = Pt(0)
                        p_bullet.paragraph_format.space_after = Pt(2)
                        r_b = p_bullet.add_run(b)
                        r_b.font.name = font_name

        elif sec == "certifications":
            certs = resume_data.get("certifications") or []
            if certs:
                if isinstance(certs, str):
                    certs = [c.strip() for c in certs.splitlines() if c.strip()]
                valid_certs = [sanitize_text(c) for c in certs if sanitize_text(c)]
                if valid_certs:
                    _add_section_heading("Certifications & Achievements")
                    for c in valid_certs:
                        p_cert = doc.add_paragraph(style="List Bullet")
                        p_cert.paragraph_format.space_before = Pt(0)
                        p_cert.paragraph_format.space_after = Pt(2)
                        r_c = p_cert.add_run(c)
                        r_c.font.name = font_name

    output_buffer = io.BytesIO()
    doc.save(output_buffer)
    output_buffer.seek(0)
    return output_buffer.getvalue()


# ==============================================================================
# REPORTLAB PDF GENERATION (Single-Column, No Tables, Plain Fonts)
# ==============================================================================

def generate_resume_pdf(
    resume_data: Dict[str, Any],
    template: str = "classic",
    sections: Optional[List[str]] = None
) -> bytes:
    """
    Generates an ATS-compliant PDF in memory using ReportLab.
    Enforces a pure single-column stream without layout tables or image elements.
    """
    tpl = TEMPLATES.get(template, TEMPLATES["classic"])
    font_body = tpl["font_family_pdf"]
    font_bold = tpl["font_family_bold_pdf"]
    font_italic = tpl["font_family_italic_pdf"]
    margin_pts = tpl["margin_inches"] * 72.0
    active_sections = _normalize_sections(sections)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=margin_pts,
        rightMargin=margin_pts,
        topMargin=margin_pts,
        bottomMargin=margin_pts,
    )

    styles = getSampleStyleSheet()

    # Define custom ATS typography styles
    style_name = ParagraphStyle(
        "ATS_CandidateName",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=18 if template == "compact" else 20,
        leading=22 if template == "compact" else 24,
        alignment=1,  # Center
        textColor=colors.HexColor("#111827"),
        spaceAfter=2,
    )

    style_contact = ParagraphStyle(
        "ATS_Contact",
        parent=styles["Normal"],
        fontName=font_body,
        fontSize=9.5,
        leading=13,
        alignment=1,  # Center
        textColor=colors.HexColor("#374151"),
        spaceAfter=8 if template == "compact" else 12,
    )

    style_heading = ParagraphStyle(
        "ATS_Heading",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=11.5 if template == "compact" else 12,
        leading=15,
        textColor=colors.HexColor("#111827"),
        spaceBefore=8 if template == "compact" else 12,
        spaceAfter=3,
        keepWithNext=True,
    )

    style_body = ParagraphStyle(
        "ATS_Body",
        parent=styles["Normal"],
        fontName=font_body,
        fontSize=10 if template == "compact" else 10.5,
        leading=13 if template == "compact" else 14,
        textColor=colors.HexColor("#1F2937"),
        spaceAfter=4,
    )

    style_item_title = ParagraphStyle(
        "ATS_ItemTitle",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#111827"),
        spaceBefore=3,
        spaceAfter=1,
        keepWithNext=True,
    )

    style_item_sub = ParagraphStyle(
        "ATS_ItemSub",
        parent=styles["Normal"],
        fontName=font_italic,
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#4B5563"),
        spaceAfter=3,
        keepWithNext=True,
    )

    style_bullet = ParagraphStyle(
        "ATS_Bullet",
        parent=styles["Normal"],
        fontName=font_body,
        fontSize=9.5 if template == "compact" else 10,
        leading=12.5 if template == "compact" else 13.5,
        textColor=colors.HexColor("#1F2937"),
        leftIndent=14,
        spaceAfter=2,
    )

    story: List[Any] = []

    # 1. Candidate Name
    name = safe_reportlab_escape(resume_data.get("candidate_name") or "Candidate Name")
    story.append(Paragraph(name, style_name))

    # 2. Contact Information Line
    contact_parts = []
    for key in ["email", "phone", "location", "linkedin", "github", "portfolio"]:
        val = resume_data.get(key)
        if val:
            contact_parts.append(safe_reportlab_escape(val))

    if contact_parts:
        contact_line = " | ".join(contact_parts)
        story.append(Paragraph(contact_line, style_contact))

    def _add_pdf_section_heading(title: str):
        story.append(Paragraph(safe_reportlab_escape(title.upper()), style_heading))
        story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#9CA3AF"), spaceBefore=1, spaceAfter=4))

    order = [s for s in tpl.get("default_order", ALL_SECTIONS) if s in active_sections]

    for sec in order:
        if sec == "summary":
            summary_text = resume_data.get("summary")
            if summary_text:
                _add_pdf_section_heading("Professional Summary")
                story.append(Paragraph(safe_reportlab_escape(summary_text), style_body))

        elif sec == "education":
            edu_list = resume_data.get("education") or []
            valid_edu = [e for e in edu_list if e.get("institution") or e.get("degree")]
            if valid_edu:
                _add_pdf_section_heading("Education")
                for e in valid_edu:
                    inst = safe_reportlab_escape(e.get("institution", ""))
                    yr = safe_reportlab_escape(e.get("year", ""))
                    deg = safe_reportlab_escape(e.get("degree", ""))
                    cgpa = safe_reportlab_escape(e.get("cgpa", ""))

                    line1_parts = [p for p in [inst, yr] if p]
                    story.append(Paragraph(" - ".join(line1_parts), style_item_title))

                    line2_parts = []
                    if deg:
                        line2_parts.append(deg)
                    if cgpa:
                        line2_parts.append(f"GPA / Score: {cgpa}")
                    if line2_parts:
                        story.append(Paragraph(" | ".join(line2_parts), style_item_sub))

                    hl = e.get("highlights")
                    if hl:
                        story.append(Paragraph(f"&bull; {safe_reportlab_escape(hl)}", style_bullet))

        elif sec == "skills":
            skills_data = resume_data.get("skills") or []
            if skills_data:
                _add_pdf_section_heading("Technical Skills")
                if isinstance(skills_data, list):
                    skills_str = ", ".join(safe_reportlab_escape(s) for s in skills_data if s)
                elif isinstance(skills_data, dict):
                    parts = []
                    for cat, items in skills_data.items():
                        if isinstance(items, list):
                            cat_items = ", ".join(safe_reportlab_escape(i) for i in items if i)
                        else:
                            cat_items = safe_reportlab_escape(items)
                        if cat_items:
                            parts.append(f"<b>{safe_reportlab_escape(cat)}</b>: {cat_items}")
                    skills_str = " | ".join(parts)
                else:
                    skills_str = safe_reportlab_escape(skills_data)

                if skills_str:
                    story.append(Paragraph(skills_str, style_body))

        elif sec == "experience":
            exp_list = resume_data.get("experience") or []
            valid_exp = [x for x in exp_list if x.get("role") or x.get("company")]
            if valid_exp:
                _add_pdf_section_heading("Work Experience")
                for x in valid_exp:
                    role = safe_reportlab_escape(x.get("role", ""))
                    comp = safe_reportlab_escape(x.get("company", ""))
                    dur = safe_reportlab_escape(x.get("duration", ""))

                    header = f"<b>{role}</b>"
                    if comp:
                        header += f" - {comp}"
                    if dur:
                        header += f" <i>({dur})</i>"
                    story.append(Paragraph(header, style_item_title))

                    bullets = _parse_bullet_points(x.get("responsibilities") or x.get("description"))
                    for b in bullets:
                        story.append(Paragraph(f"&bull; {safe_reportlab_escape(b)}", style_bullet))

        elif sec == "projects":
            proj_list = resume_data.get("projects") or []
            valid_proj = [pr for pr in proj_list if pr.get("title")]
            if valid_proj:
                _add_pdf_section_heading("Projects & Technical Work")
                for pr in valid_proj:
                    title = safe_reportlab_escape(pr.get("title", ""))
                    tech = safe_reportlab_escape(pr.get("technologies") or pr.get("tech_stack", ""))
                    link = safe_reportlab_escape(pr.get("link") or pr.get("url", ""))

                    line = f"<b>{title}</b>"
                    if tech:
                        line += f" | <i>Technologies: {tech}</i>"
                    if link:
                        line += f" ({link})"
                    story.append(Paragraph(line, style_item_title))

                    bullets = _parse_bullet_points(pr.get("description") or pr.get("points"))
                    for b in bullets:
                        story.append(Paragraph(f"&bull; {safe_reportlab_escape(b)}", style_bullet))

        elif sec == "certifications":
            certs = resume_data.get("certifications") or []
            if certs:
                if isinstance(certs, str):
                    certs = [c.strip() for c in certs.splitlines() if c.strip()]
                valid_certs = [c for c in certs if c]
                if valid_certs:
                    _add_pdf_section_heading("Certifications & Achievements")
                    for c in valid_certs:
                        story.append(Paragraph(f"&bull; {safe_reportlab_escape(c)}", style_bullet))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# ==============================================================================
# HTML PREVIEW GENERATION (For In-Browser Inspection)
# ==============================================================================

def generate_resume_preview_html(
    resume_data: Dict[str, Any],
    template: str = "classic",
    sections: Optional[List[str]] = None
) -> str:
    """
    Renders an accessible, single-column HTML preview of the generated resume.
    Allows students to preview layout and verify sections before downloading.
    """
    tpl = TEMPLATES.get(template, TEMPLATES["classic"])
    font_css = "Georgia, 'Times New Roman', serif" if template == "classic" else ("'Segoe UI', Arial, sans-serif" if template == "compact" else "'Helvetica Neue', Arial, sans-serif")
    active_sections = _normalize_sections(sections)

    name = html.escape(sanitize_text(resume_data.get("candidate_name") or "Candidate Name"))

    contact_parts = []
    for k in ["email", "phone", "location", "linkedin", "github", "portfolio"]:
        val = resume_data.get(k)
        if val:
            contact_parts.append(html.escape(sanitize_text(val)))
    contact_line = " &bull; ".join(contact_parts)

    body_html = [
        f'<div class="resume-preview-sheet" style="font-family: {font_css}; max-width: 800px; margin: 0 auto; background: #ffffff; color: #111827; padding: {int(tpl["margin_inches"]*40)}px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); border-radius: 8px; line-height: 1.45;">',
        '<div style="text-align: center; border-bottom: 2px solid #e5e7eb; padding-bottom: 12px; margin-bottom: 16px;">',
        f'<h1 style="margin: 0 0 6px 0; font-size: 24px; font-weight: 700; color: #111827;">{name}</h1>',
        f'<div style="font-size: 13px; color: #4b5563;">{contact_line}</div>',
        '</div>',
    ]

    def _heading_html(title: str) -> str:
        return (
            f'<div style="margin-top: 14px; margin-bottom: 6px; border-bottom: 1px solid #d1d5db; padding-bottom: 2px;">'
            f'<h2 style="margin: 0; font-size: 14px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: #111827;">{html.escape(title)}</h2>'
            f'</div>'
        )

    order = [s for s in tpl.get("default_order", ALL_SECTIONS) if s in active_sections]

    for sec in order:
        if sec == "summary":
            summary_text = resume_data.get("summary")
            if summary_text:
                body_html.append(_heading_html("Professional Summary"))
                body_html.append(f'<p style="margin: 4px 0 10px 0; font-size: 13.5px; color: #374151;">{html.escape(sanitize_text(summary_text))}</p>')

        elif sec == "education":
            edu_list = resume_data.get("education") or []
            valid_edu = [e for e in edu_list if e.get("institution") or e.get("degree")]
            if valid_edu:
                body_html.append(_heading_html("Education"))
                for e in valid_edu:
                    inst = html.escape(sanitize_text(e.get("institution", "")))
                    deg = html.escape(sanitize_text(e.get("degree", "")))
                    yr = html.escape(sanitize_text(e.get("year", "")))
                    cgpa = html.escape(sanitize_text(e.get("cgpa", "")))
                    hl = html.escape(sanitize_text(e.get("highlights", "")))

                    body_html.append('<div style="margin-bottom: 8px;">')
                    body_html.append(f'<div style="display: flex; justify-content: space-between; font-weight: 600; font-size: 13.5px;"><span>{inst}</span><span>{yr}</span></div>')
                    body_html.append(f'<div style="font-size: 13px; color: #4b5563; font-style: italic;">{deg}{(" | GPA: " + cgpa) if cgpa else ""}</div>')
                    if hl:
                        body_html.append(f'<div style="font-size: 12.5px; color: #4b5563; margin-top: 2px;">&bull; {hl}</div>')
                    body_html.append('</div>')

        elif sec == "skills":
            skills_data = resume_data.get("skills") or []
            if skills_data:
                body_html.append(_heading_html("Technical Skills"))
                if isinstance(skills_data, list):
                    skills_str = ", ".join(html.escape(sanitize_text(s)) for s in skills_data if s)
                elif isinstance(skills_data, dict):
                    parts = []
                    for cat, items in skills_data.items():
                        if isinstance(items, list):
                            cat_items = ", ".join(html.escape(sanitize_text(i)) for i in items if i)
                        else:
                            cat_items = html.escape(sanitize_text(items))
                        if cat_items:
                            parts.append(f"<strong>{html.escape(cat)}</strong>: {cat_items}")
                    skills_str = " | ".join(parts)
                else:
                    skills_str = html.escape(sanitize_text(skills_data))

                if skills_str:
                    body_html.append(f'<p style="margin: 4px 0 10px 0; font-size: 13.5px; color: #374151;">{skills_str}</p>')

        elif sec == "experience":
            exp_list = resume_data.get("experience") or []
            valid_exp = [x for x in exp_list if x.get("role") or x.get("company")]
            if valid_exp:
                body_html.append(_heading_html("Work Experience"))
                for x in valid_exp:
                    role = html.escape(sanitize_text(x.get("role", "")))
                    comp = html.escape(sanitize_text(x.get("company", "")))
                    dur = html.escape(sanitize_text(x.get("duration", "")))

                    body_html.append('<div style="margin-bottom: 10px;">')
                    body_html.append(f'<div style="display: flex; justify-content: space-between; font-weight: 600; font-size: 13.5px;"><span>{role} &ndash; {comp}</span><span>{dur}</span></div>')
                    bullets = _parse_bullet_points(x.get("responsibilities") or x.get("description"))
                    if bullets:
                        body_html.append('<ul style="margin: 4px 0 6px 18px; padding: 0; font-size: 13px; color: #374151;">')
                        for b in bullets:
                            body_html.append(f'<li style="margin-bottom: 2px;">{html.escape(b)}</li>')
                        body_html.append('</ul>')
                    body_html.append('</div>')

        elif sec == "projects":
            proj_list = resume_data.get("projects") or []
            valid_proj = [pr for pr in proj_list if pr.get("title")]
            if valid_proj:
                body_html.append(_heading_html("Projects & Technical Work"))
                for pr in valid_proj:
                    title = html.escape(sanitize_text(pr.get("title", "")))
                    tech = html.escape(sanitize_text(pr.get("technologies") or pr.get("tech_stack", "")))
                    link = html.escape(sanitize_text(pr.get("link") or pr.get("url", "")))

                    body_html.append('<div style="margin-bottom: 10px;">')
                    header_line = f'<strong>{title}</strong>'
                    if tech:
                        header_line += f' <span style="font-size: 12.5px; color: #4b5563; font-style: italic;">| Tech: {tech}</span>'
                    if link:
                        header_line += f' <span style="font-size: 12px; color: #2563eb;">({link})</span>'
                    body_html.append(f'<div style="font-size: 13.5px;">{header_line}</div>')

                    bullets = _parse_bullet_points(pr.get("description") or pr.get("points"))
                    if bullets:
                        body_html.append('<ul style="margin: 4px 0 6px 18px; padding: 0; font-size: 13px; color: #374151;">')
                        for b in bullets:
                            body_html.append(f'<li style="margin-bottom: 2px;">{html.escape(b)}</li>')
                        body_html.append('</ul>')
                    body_html.append('</div>')

        elif sec == "certifications":
            certs = resume_data.get("certifications") or []
            if certs:
                if isinstance(certs, str):
                    certs = [c.strip() for c in certs.splitlines() if c.strip()]
                valid_certs = [c for c in certs if c]
                if valid_certs:
                    body_html.append(_heading_html("Certifications & Achievements"))
                    body_html.append('<ul style="margin: 4px 0 10px 18px; padding: 0; font-size: 13px; color: #374151;">')
                    for c in valid_certs:
                        body_html.append(f'<li style="margin-bottom: 2px;">{html.escape(sanitize_text(c))}</li>')
                    body_html.append('</ul>')

    body_html.append('</div>')
    return "\n".join(body_html)
