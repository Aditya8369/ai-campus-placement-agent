"""
Resume Exporter - Generates finalized, ATS-compliant resume documents
in both Microsoft Word (.docx) and PDF (.pdf) formats from optimized bullet points.
"""

import os
import time
import logging
from typing import List, Dict, Any, Optional

import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

import config

logger = logging.getLogger(__name__)


def generate_optimized_resume_docx(
    bullets: List[str],
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """
    Generates a professionally formatted .docx resume document incorporating
    the finalized, AI-optimized bullet points.
    Returns the file path of the generated document.
    """
    if metadata is None:
        metadata = {}

    candidate_name = metadata.get("candidate_name") or "Candidate Placement Resume"
    company_name = metadata.get("company_name") or "General"
    role_target = metadata.get("role_target") or "Software Development Engineer"
    skills = metadata.get("skills") or ["Python", "Java", "Data Structures", "REST APIs", "SQL", "Git"]

    doc = docx.Document()

    # Set 0.75-inch standard margins
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    # 1. Candidate Header
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_name = title_p.add_run(candidate_name)
    run_name.font.size = Pt(20)
    run_name.font.bold = True
    run_name.font.color.rgb = RGBColor(26, 115, 232)  # Primary Google Blue

    contact_p = doc.add_paragraph()
    contact_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_contact = contact_p.add_run(f"Campus Placement Candidate • Target Company: {company_name} • Role: {role_target}")
    run_contact.font.size = Pt(10)
    run_contact.font.color.rgb = RGBColor(95, 99, 104)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # 2. Section: Professional Summary
    h1 = doc.add_paragraph()
    run_h1 = h1.add_run("PLACEMENT READINESS SUMMARY")
    run_h1.font.size = Pt(12)
    run_h1.font.bold = True
    run_h1.font.color.rgb = RGBColor(32, 33, 36)

    summary_p = doc.add_paragraph(
        f"Early-career engineering graduate with rigorous technical foundations in data structures, "
        f"scalable systems, and software engineering cycles. Actively preparing for {company_name} campus hiring "
        f"with quantified achievements and verified algorithmic problem-solving abilities."
    )
    summary_p.paragraph_format.space_after = Pt(10)

    # 3. Section: Technical Competencies
    h2 = doc.add_paragraph()
    run_h2 = h2.add_run("TECHNICAL SKILLS & COMPETENCIES")
    run_h2.font.size = Pt(12)
    run_h2.font.bold = True
    run_h2.font.color.rgb = RGBColor(32, 33, 36)

    skills_str = ", ".join(skills) if isinstance(skills, list) else str(skills)
    skills_p = doc.add_paragraph(f"Languages & Tools: {skills_str}")
    skills_p.paragraph_format.space_after = Pt(10)

    # 4. Section: AI-Optimized Project & Work Experience Achievements
    h3 = doc.add_paragraph()
    run_h3 = h3.add_run("TECHNICAL PROJECTS & EXPERIENCE (AI-OPTIMIZED)")
    run_h3.font.size = Pt(12)
    run_h3.font.bold = True
    run_h3.font.color.rgb = RGBColor(32, 33, 36)

    if bullets:
        for b in bullets:
            clean_b = b.strip()
            if clean_b:
                p = doc.add_paragraph(clean_b, style="List Bullet")
                p.paragraph_format.space_after = Pt(4)
    else:
        doc.add_paragraph("No optimized bullet points provided.", style="List Bullet")

    # Save to reports folder
    os.makedirs(config.REPORT_FOLDER, exist_ok=True)
    filename = f"optimized_resume_{int(time.time())}.docx"
    output_path = os.path.join(config.REPORT_FOLDER, filename)
    doc.save(output_path)
    logger.info(f"Generated optimized resume .docx document at: {output_path}")

    return output_path


def generate_optimized_resume_pdf(
    bullets: List[str],
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """
    Generates a clean, ATS-compliant PDF resume incorporating
    the finalized, AI-optimized bullet points.
    Returns the file path of the generated document.
    """
    if metadata is None:
        metadata = {}

    candidate_name = metadata.get("candidate_name") or "Candidate Placement Resume"
    company_name = metadata.get("company_name") or "General"
    role_target = metadata.get("role_target") or "Software Development Engineer"
    skills = metadata.get("skills") or ["Python", "Java", "Data Structures", "REST APIs", "SQL", "Git"]

    os.makedirs(config.REPORT_FOLDER, exist_ok=True)
    filename = f"optimized_resume_{int(time.time())}.pdf"
    output_path = os.path.join(config.REPORT_FOLDER, filename)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "ResumeTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#1a73e8"),
        alignment=1  # Centered
    )

    subtitle_style = ParagraphStyle(
        "ResumeSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#5f6368"),
        alignment=1  # Centered
    )

    section_header_style = ParagraphStyle(
        "ResumeSectionHeader",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#202124"),
        spaceBefore=12,
        spaceAfter=4
    )

    body_style = ParagraphStyle(
        "ResumeBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#3c4043")
    )

    bullet_style = ParagraphStyle(
        "ResumeBullet",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor("#202124"),
        leftIndent=15,
        spaceAfter=4
    )

    story = []

    # 1. Header
    story.append(Paragraph(candidate_name, title_style))
    story.append(Spacer(1, 3))
    story.append(Paragraph(f"Campus Placement Candidate • Target Company: {company_name} • Role: {role_target}", subtitle_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#dadce0"), spaceAfter=10))

    # 2. Placement Readiness Summary
    story.append(Paragraph("PLACEMENT READINESS SUMMARY", section_header_style))
    story.append(Paragraph(
        f"Early-career engineering graduate with rigorous technical foundations in data structures, "
        f"scalable systems, and software engineering cycles. Actively preparing for {company_name} campus hiring "
        f"with quantified achievements and verified algorithmic problem-solving abilities.",
        body_style
    ))
    story.append(Spacer(1, 8))

    # 3. Technical Competencies
    story.append(Paragraph("TECHNICAL SKILLS & COMPETENCIES", section_header_style))
    skills_str = ", ".join(skills) if isinstance(skills, list) else str(skills)
    story.append(Paragraph(f"<b>Languages & Tools:</b> {skills_str}", body_style))
    story.append(Spacer(1, 8))

    # 4. AI-Optimized Project & Experience Bullets
    story.append(Paragraph("TECHNICAL PROJECTS & EXPERIENCE (AI-OPTIMIZED)", section_header_style))
    story.append(Spacer(1, 4))

    if bullets:
        for b in bullets:
            clean_b = b.strip()
            if clean_b:
                story.append(Paragraph(f"• {clean_b}", bullet_style))
    else:
        story.append(Paragraph("• No optimized bullet points provided.", bullet_style))

    doc.build(story)
    logger.info(f"Generated optimized resume .pdf document at: {output_path}")

    return output_path

