import os
import html
import logging
from typing import Any
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

def escape_xml(value: Any) -> str:
    """
    Safely escapes text for ReportLab XML/HTML parsing while handling non-strings.
    Prevents ExpatError crashes on special characters like '&', '<', '>'.
    """
    if value is None:
        return ""
    return html.escape(str(value), quote=False)

def generate_pdf_report(analysis_data: dict, output_path: str) -> str:
    """
    Generates a beautifully structured PDF placement readiness report.
    Converts metrics, skill gap, conflict advisories, and roadmap into a professional printable PDF.
    """
    try:
        logger.info("Generating PDF report at: %s", output_path)

        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=54,
            leftMargin=54,
            topMargin=54,
            bottomMargin=54,
        )

        styles = getSampleStyleSheet()

        # Color palette definition matching the existing blue-and-white style.
        primary_blue = colors.HexColor("#1a73e8")
        accent_light_blue = colors.HexColor("#e8f0fe")
        dark_text_color = colors.HexColor("#202124")
        light_grey_bg = colors.HexColor("#f8f9fa")
        border_grey = colors.HexColor("#dadce0")
        warning_amber = colors.HexColor("#d93025")
        
        title_style = ParagraphStyle(
            "ReportTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=28,
            textColor=primary_blue,
            alignment=TA_CENTER,
        )

        subtitle_style = ParagraphStyle(
            "ReportSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=13,
            leading=17,
            textColor=colors.HexColor("#5f6368"),
            alignment=TA_CENTER,
        )

        h1_style = ParagraphStyle(
            "SectionH1",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=primary_blue,
            spaceBefore=14,
            spaceAfter=8,
            keepWithNext=True,
        )

        h2_style = ParagraphStyle(
            "SectionH2",
            parent=styles["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=15,
            textColor=dark_text_color,
            spaceBefore=8,
            spaceAfter=4,
            keepWithNext=True,
        )

        body_style = ParagraphStyle(
            "ReportBody",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.5,
            textColor=dark_text_color,
        )

        bullet_style = ParagraphStyle(
            "ReportBullet",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.5,
            textColor=dark_text_color,
            leftIndent=15,
            firstLineIndent=-10,
        )

        table_hdr_style = ParagraphStyle(
            "TableHdr",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11.5,
            textColor=colors.white,
        )

        table_body_style = ParagraphStyle(
            "TableBody",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11.5,
            textColor=dark_text_color,
        )

        story = []

        # Cover section
        story.append(Spacer(1, 30))
        story.append(Paragraph("AI CAMPUS PLACEMENT REPORT", title_style))
        story.append(Spacer(1, 10))
        target_company = escape_xml(analysis_data.get('company_name', 'Target Company'))
        story.append(Paragraph(f"Preparation Analysis & Learning Roadmap for {target_company}", subtitle_style))
        story.append(Spacer(1, 20))

        # Summary metrics
        resume_analysis = analysis_data.get("results", {}).get("resume_analysis", {})
        job_match = analysis_data.get("results", {}).get("job_match", {})
        
        ats_score = escape_xml(resume_analysis.get('ats_score', 'N/A'))
        match_pct = escape_xml(job_match.get('match_percentage', 'N/A'))
        
        metrics_grid_data = [
            [
                Paragraph("<b>ATS Score:</b>", body_style),
                Paragraph(f"<b>{ats_score}/100</b>", body_style),
                Paragraph("<b>Job Match Score:</b>", body_style),
                Paragraph(f"<b>{match_pct}%</b>", body_style)
            ]
        ]

        metrics_table = Table(metrics_grid_data, colWidths=[100, 100, 120, 100])
        metrics_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), accent_light_blue),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("PADDING", (0, 0), (-1, -1), 10),
                    ("BOX", (0, 0), (-1, -1), 1.5, primary_blue),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#b0d4ff")),
                ]
            )
        )
        story.append(metrics_table)
        story.append(Spacer(1, 25))

        # Summary block
        story.append(Paragraph("Executive Resume Summary", h1_style))
        summary_text = escape_xml(resume_analysis.get("summary", "No summary available."))
        story.append(Paragraph(summary_text, body_style))
        story.append(Spacer(1, 15))
        
        # Overall Recommendation (fallback from root results or resume_analysis)
        story.append(Paragraph("Overall Recommendation", h1_style))
        rec_text = escape_xml(
            analysis_data.get("results", {}).get("overall_recommendation_summary")
            or resume_analysis.get("overall_recommendation")
            or "Overall campus placement analysis successfully compiled."
        )
        story.append(Paragraph(rec_text, body_style))
        story.append(Spacer(1, 15))
        
        # Cross-section conflict advisory if contradictions detected
        conflicts = analysis_data.get("results", {}).get("conflicts", [])
        if conflicts:
            story.append(Paragraph("Placement Advisory: Contradictions Detected", h1_style))
            story.append(Paragraph(
                "Our automated verification flagged conflicting recommendations between the job match analysis and the skill gap roadmap. Review the following items before finalizing your preparation plan:",
                body_style
            ))
            story.append(Spacer(1, 6))
            for c in conflicts:
                skill_name = escape_xml(c.get("skill", "Unknown"))
                rule_desc = escape_xml(c.get("rule_description", "Potential contradiction in skill classification."))
                conflict_type = escape_xml(c.get("conflict_type", "Advisory"))
                story.append(Paragraph(f"&bull; <b>[{conflict_type}]</b> Skill: <i>{skill_name}</i> &mdash; {rule_desc}", bullet_style))
            story.append(Spacer(1, 15))
        
        story.append(PageBreak())

        # Resume feedback
        story.append(Paragraph("Resume Analysis Details", h1_style))
        story.append(Paragraph("Strengths", h2_style))
        strengths = resume_analysis.get("strengths", [])
        if strengths:
            for strength in strengths:
                story.append(Paragraph(f"&bull; {escape_xml(strength)}", bullet_style))
        else:
            story.append(Paragraph("No specific strengths noted.", body_style))
        story.append(Spacer(1, 10))

        story.append(Paragraph("Weaknesses / Areas of Improvement", h2_style))
        weaknesses = resume_analysis.get("weaknesses", [])
        if weaknesses:
            for weakness in weaknesses:
                story.append(Paragraph(f"&bull; {escape_xml(weakness)}", bullet_style))
        else:
            story.append(Paragraph("No critical weaknesses detected.", body_style))
        story.append(Spacer(1, 10))
        
        story.append(Paragraph("Grammar & Formatting Suggestions", h2_style))
        all_suggs = resume_analysis.get("grammar_suggestions", []) + resume_analysis.get("formatting_suggestions", [])
        if all_suggs:
            for suggestion in all_suggs:
                story.append(Paragraph(f"&bull; {escape_xml(suggestion)}", bullet_style))
        else:
            story.append(Paragraph("Formatting and grammar follow standard industry guidelines.", body_style))
        story.append(Spacer(1, 15))

        # Job-match adjustments
        story.append(Paragraph("Top 5 Job Matching Adjustments", h1_style))
        changes = job_match.get("top_5_resume_changes", [])
        if changes:
            for idx, change in enumerate(changes, 1):
                story.append(Paragraph(f"<b>{idx}.</b> {escape_xml(change)}", bullet_style))
        else:
            story.append(Paragraph("No critical adjustments required for the target profile.", body_style))
            
        story.append(PageBreak())

        # Skill-gaps table
        story.append(Paragraph("Skill Gap Assessment", h1_style))
        story.append(
            Paragraph(
                "The table below documents critical skills required for your target role and "
                "company that were not identified in your resume. Follow the recommended "
                "learning paths and projects to build these skills.",
                body_style,
            )
        )
        story.append(Spacer(1, 10))

        results = analysis_data.get("results", {})
        skill_gaps = results.get("skill_gap", [])
        if skill_gaps:
            gap_table_data = [
                [
                    Paragraph("Skill", table_hdr_style),
                    Paragraph("Importance", table_hdr_style),
                    Paragraph("Estimated Time", table_hdr_style),
                    Paragraph("Learning Resource &amp; Mini-Project", table_hdr_style),
                    Paragraph("Priority", table_hdr_style),
                ]
            ]

            for gap in skill_gaps:
                res_esc = escape_xml(gap.get('learning_resource', 'N/A'))
                proj_esc = escape_xml(gap.get('project_suggestion', 'N/A'))
                description_str = f"<b>Resource:</b> {res_esc}<br/><b>Project:</b> {proj_esc}"
                gap_table_data.append([
                    Paragraph(escape_xml(gap.get("skill", "N/A")), table_body_style),
                    Paragraph(escape_xml(gap.get("importance", "N/A")), table_body_style),
                    Paragraph(escape_xml(gap.get("learning_time", "N/A")), table_body_style),
                    Paragraph(description_str, table_body_style),
                    Paragraph(escape_xml(gap.get("priority", "N/A")), table_body_style)
                ])
                
            gap_table = Table(gap_table_data, colWidths=[90, 65, 65, 220, 64])
            gap_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), primary_blue),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("PADDING", (0, 0), (-1, -1), 8),
                        ("GRID", (0, 0), (-1, -1), 0.5, border_grey),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, light_grey_bg]),
                    ]
                )
            )
            story.append(gap_table)
        else:
            story.append(
                Paragraph("No major skill gaps identified relative to the target role.", body_style)
            )

        story.append(Spacer(1, 15))
        story.append(PageBreak())

        # Six-week learning roadmap
        story.append(Paragraph("6-Week Learning Roadmap", h1_style))
        story.append(
            Paragraph(
                "Follow this personalized study plan step-by-step over the next 6 weeks to "
                "bridge any gaps and practice for interviews.",
                body_style,
            )
        )
        story.append(Spacer(1, 10))
        
        roadmap_list = analysis_data.get("results", {}).get("learning_roadmap", [])
        for w in roadmap_list:
            week_title = escape_xml(w.get('week', 'Week X'))
            hours = escape_xml(w.get('estimated_hours', 10))
            topics = ", ".join(escape_xml(t) for t in w.get('topics', [])) or "None"
            coding = ", ".join(escape_xml(c) for c in w.get('coding_practice', [])) or "None"
            projects = ", ".join(escape_xml(p) for p in w.get('mini_projects', [])) or "None"
            revision = ", ".join(escape_xml(r) for r in w.get('revision_tasks', [])) or "None"
            
            w_story = [
                Paragraph(f"<b>{week_title}</b> ({hours} Hours)", h2_style),
                Paragraph(f"<b>Topics to Cover:</b> {topics}", body_style),
                Paragraph(f"<b>Coding Practice:</b> {coding}", body_style),
                Paragraph(f"<b>Mini Project:</b> {projects}", body_style),
                Paragraph(f"<b>Interview Questions:</b>", body_style)
            ]
            for iq in w.get("interview_questions", []):
                w_story.append(Paragraph(f"  &bull; {escape_xml(iq)}", bullet_style))
            w_story.append(Paragraph(f"<b>Revision Tasks:</b> {revision}", body_style))
            w_story.append(Spacer(1, 12))
            
            story.append(KeepTogether(w_story))
            
        doc.build(story)
        logger.info("PDF report compiled successfully.")
        return output_path

    except Exception as e:
        logger.error("Error compiling PDF report using ReportLab: %s", str(e))
        raise RuntimeError(f"ReportLab failure: {e}") from e


def generate_certificate_pdf(analysis_data: dict, output_path: str) -> str:
    """
    Generates a formal, printable PDF Certificate of Placement Readiness using ReportLab.
    Includes certificate borders, candidate filename, target company name, ATS and Job Match scores,
    and verification metadata.
    """
    try:
        logger.info("Generating Placement Readiness Certificate PDF at: %s", output_path)

        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=40,
            leftMargin=40,
            topMargin=40,
            bottomMargin=40,
        )

        styles = getSampleStyleSheet()

        cert_title_style = ParagraphStyle(
            "CertTitle",
            parent=styles["Heading1"],
            fontSize=24,
            leading=28,
            textColor=colors.HexColor("#1a73e8"),
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            spaceAfter=6,
        )

        cert_subtitle_style = ParagraphStyle(
            "CertSubtitle",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#5f6368"),
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            spaceAfter=15,
        )

        cert_body_style = ParagraphStyle(
            "CertBody",
            parent=styles["Normal"],
            fontSize=12,
            leading=18,
            textColor=colors.HexColor("#202124"),
            alignment=TA_CENTER,
            fontName="Helvetica",
            spaceAfter=10,
        )

        cert_candidate_style = ParagraphStyle(
            "CertCandidate",
            parent=styles["Heading2"],
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#202124"),
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            spaceAfter=10,
        )

        cert_target_style = ParagraphStyle(
            "CertTarget",
            parent=styles["Heading2"],
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#1a73e8"),
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            spaceAfter=15,
        )

        cert_meta_style = ParagraphStyle(
            "CertMeta",
            parent=styles["Normal"],
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#5f6368"),
            alignment=TA_CENTER,
            fontName="Helvetica",
        )

        story = []
        story.append(Spacer(1, 15))
        story.append(Paragraph("AI CAMPUS PLACEMENT AGENT", cert_subtitle_style))
        story.append(Paragraph("CERTIFICATE OF PLACEMENT READINESS", cert_title_style))
        story.append(Paragraph("OFFICIAL ASSESSMENT &amp; EVALUATION VERIFICATION", cert_subtitle_style))
        story.append(Spacer(1, 15))

        story.append(Paragraph("This official placement readiness certificate is proudly presented for evaluation of:", cert_body_style))

        candidate_name = escape_xml(analysis_data.get("resume_filename", "Candidate Resume"))
        story.append(Paragraph(f"<b>{candidate_name}</b>", cert_candidate_style))

        story.append(Paragraph(
            "Having successfully completed comprehensive multi-agent ATS resume parsing, competitive job matching, "
            "and skill gap benchmarking for the target company:",
            cert_body_style
        ))

        company_name = escape_xml(analysis_data.get("company_name", "General Placement Preparation"))
        story.append(Paragraph(f"<b>{company_name}</b>", cert_target_style))
        story.append(Spacer(1, 10))

        # Metrics Score Table
        ats_score = escape_xml(analysis_data.get("results", {}).get("resume_analysis", {}).get("ats_score", 0))
        match_score = escape_xml(analysis_data.get("results", {}).get("job_match", {}).get("match_percentage", 0))

        score_table_data = [
            [
                Paragraph(f"<b>{ats_score} / 100</b>", cert_candidate_style),
                Paragraph(f"<b>{match_score}%</b>", cert_candidate_style),
            ],
            [
                Paragraph("<b>ATS Resume Score</b>", cert_meta_style),
                Paragraph("<b>Role Match Score</b>", cert_meta_style),
            ],
        ]

        score_table = Table(score_table_data, colWidths=[200, 200])
        score_table.setStyle(
            TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8f9fa")),
                ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#f8f9fa")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#dadce0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dadce0")),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ])
        )
        story.append(score_table)
        story.append(Spacer(1, 30))

        # Verification Footer
        created_at = escape_xml(analysis_data.get("created_at", "N/A"))
        record_id = escape_xml(str(analysis_data.get("analysis_id", ""))[:16])

        footer_table_data = [
            [
                Paragraph(f"<b>Issued On:</b> {created_at}<br/><b>Verification ID:</b> {record_id}", cert_meta_style),
                Paragraph("<b>Status:</b> Verified Placement Candidate<br/><b>Evaluator:</b> AI Campus Placement Agent", cert_meta_style),
            ]
        ]
        footer_table = Table(footer_table_data, colWidths=[250, 250])
        footer_table.setStyle(
            TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEABOVE", (0, 0), (-1, -1), 1, colors.HexColor("#dadce0")),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
            ])
        )
        story.append(footer_table)

        doc.build(story)
        logger.info("Placement certificate PDF compiled successfully.")
        return output_path

    except Exception as exc:
        logger.error("Error generating certificate PDF: %s", str(exc))
        raise RuntimeError(f"Certificate PDF generation failed: {exc}") from exc

