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

# ==============================================================================
# REPORT GENERATION ERROR RECOVERY SYSTEM (#202)
# ==============================================================================

class ReportGenerationError(Exception):
    """
    Diagnostic exception raised when report rendering or data pipeline fails.
    Carries the operational stage and root cause exception for targeted recovery.
    """
    def __init__(self, message: str, stage: str = "initialization", cause: Exception = None):
        super().__init__(message)
        self.message = message
        self.stage = stage
        self.cause = cause


def sanitize_report_data(raw_data: Any) -> dict:
    """
    Validates, normalizes, and sanitizes input data dictionaries before PDF generation.
    Recovers from None, non-dict types, missing keys, or corrupt inner fields (#202).
    Ensures safe integer scores, safe strings, and properly initialized nested lists/dicts.
    """
    if not isinstance(raw_data, dict):
        logger.warning(
            "Sanitizing report data: received non-dict input (%s). Initializing empty schema fallback.",
            type(raw_data).__name__
        )
        raw_data = {}

    data = dict(raw_data)

    # Normalize top-level strings
    data["company_name"] = str(data.get("company_name") or "General Placement Preparation").strip()
    data["resume_filename"] = str(data.get("resume_filename") or "Candidate Resume").strip()
    data["analysis_id"] = str(data.get("analysis_id") or data.get("id") or "analysis_summary").strip()
    data["created_at"] = str(data.get("created_at") or "N/A").strip()

    # Normalize nested results structure
    results = data.get("results")
    if not isinstance(results, dict):
        results = {}

    resume_analysis = results.get("resume_analysis")
    if not isinstance(resume_analysis, dict):
        resume_analysis = {}

    job_match = results.get("job_match")
    if not isinstance(job_match, dict):
        job_match = {}

    # Validate numbers
    try:
        data["ats_score"] = int(data.get("ats_score") or resume_analysis.get("ats_score", 0))
    except (ValueError, TypeError):
        data["ats_score"] = 0

    try:
        data["match_percentage"] = int(data.get("match_percentage") or job_match.get("match_percentage", 0))
    except (ValueError, TypeError):
        data["match_percentage"] = 0

    # Ensure list fields are valid lists
    if not isinstance(results.get("skill_gap"), list):
        results["skill_gap"] = []
    if not isinstance(results.get("study_plan"), list):
        results["study_plan"] = []
    if not isinstance(job_match.get("matched_skills"), list):
        job_match["matched_skills"] = []
    if not isinstance(job_match.get("missing_skills"), list):
        job_match["missing_skills"] = []

    results["resume_analysis"] = resume_analysis
    results["job_match"] = job_match
    data["results"] = results
    return data


def generate_fallback_pdf_report(
    error_message: str,
    output_path: str,
    report_type: str = "Placement Preparation Report"
) -> str:
    """
    Generates a graceful, readable fallback PDF document when unexpected system or rendering errors occur (#202).
    Guarantees students receive a clean notification report rather than a broken page or 500 crash.
    """
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=54,
            leftMargin=54,
            topMargin=54,
            bottomMargin=54
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "FallbackTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#d93025"),
            alignment=TA_CENTER
        )
        subtitle_style = ParagraphStyle(
            "FallbackSub",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=11,
            leading=16,
            textColor=colors.HexColor("#5f6368"),
            alignment=TA_CENTER
        )
        body_style = ParagraphStyle(
            "FallbackBody",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#202124")
        )

        story = [
            Spacer(1, 40),
            Paragraph("AI CAMPUS PLACEMENT AGENT", subtitle_style),
            Spacer(1, 10),
            Paragraph("Notice: Report Generation Recovery", title_style),
            Spacer(1, 15),
            Paragraph(
                f"An unexpected issue occurred while rendering your detailed <b>{escape_xml(report_type)}</b>.",
                subtitle_style
            ),
            Spacer(1, 25),
            Table([
                [Paragraph("<b>Status:</b> Safe Error Recovery Active", body_style)],
                [Paragraph(f"<b>Diagnostic Detail:</b> {escape_xml(error_message)}", body_style)],
                [Paragraph("<b>Recommended Action:</b> Please revisit the dashboard and re-trigger export, or contact campus platform support if the issue persists.", body_style)],
            ], colWidths=[480], style=[
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fef7e0")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#f9ab00")),
                ("PADDING", (0, 0), (-1, -1), 12),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE")
            ]),
            Spacer(1, 40),
            Paragraph("Generated by automated safety watchdog &bull; AI Campus Placement Agent", subtitle_style)
        ]
        doc.build(story)
        logger.info("Successfully generated fallback recovery PDF at: %s", output_path)
        return output_path
    except Exception as fallback_err:
        logger.critical(f"Critical failure inside generate_fallback_pdf_report: {fallback_err}")
        with open(output_path, "wb") as f:
            f.write(
                b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
                b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\nxref\n0 4\n0000000000 65535 f \n"
                b"0000000009 00000 n \n0000000052 00000 n \n0000000101 00000 n \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF\n"
            )
        return output_path


def safe_generate_report_with_recovery(
    generator_func,
    data: Any,
    output_path: str,
    report_type: str = "Placement Report"
) -> str:
    """
    Executes a report generator with automatic pre-validation and graceful error recovery (#202).
    Catches rendering faults, file locks, or missing keys and generates a clean recovery document.
    """
    try:
        sanitized_data = sanitize_report_data(data)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        return generator_func(sanitized_data, output_path)
    except Exception as primary_err:
        logger.error(f"Primary report generation for {report_type} failed: {primary_err}. Initiating safe fallback recovery.")
        return generate_fallback_pdf_report(
            error_message=str(primary_err),
            output_path=output_path,
            report_type=report_type
        )
    except Exception as primary_err:
        return generate_fallback_pdf_report(str(primary_err), output_path, report_type)


def escape_xml(value: Any) -> str:
    """
    Safely escapes text for ReportLab XML/HTML parsing while handling non-strings.
    Prevents ExpatError crashes on special characters like '&', '<', '>'.
    """
    if value is None:
        return ""
    return html.escape(str(value), quote=False)

def generate_pdf_report(analysis_data: dict, output_path: str) -> str:
    analysis_data = sanitize_report_data(analysis_data)
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
    analysis_data = sanitize_report_data(analysis_data)
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


def generate_skills_gap_pdf(analysis_data: dict, output_path: str) -> str:
    analysis_data = sanitize_report_data(analysis_data)
    """
    Generates a dedicated, beautifully formatted standalone Skills Gap & Upskilling PDF report (#136).
    Includes identified missing skills, priority rankings, learning resources, and mini-project recommendations.
    """
    try:
        logger.info("Generating standalone Skills Gap PDF report at: %s", output_path)

        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=45,
            leftMargin=45,
            topMargin=45,
            bottomMargin=45,
        )

        styles = getSampleStyleSheet()

        primary_blue = colors.HexColor("#1a73e8")
        accent_light_blue = colors.HexColor("#e8f0fe")
        dark_text = colors.HexColor("#202124")
        border_grey = colors.HexColor("#dadce0")
        light_grey_bg = colors.HexColor("#f8f9fa")
        high_priority_red = colors.HexColor("#d93025")
        med_priority_orange = colors.HexColor("#f2994a")
        low_priority_green = colors.HexColor("#1e8e3e")

        title_style = ParagraphStyle(
            "SkillsGapTitle",
            parent=styles["Heading1"],
            fontSize=22,
            leading=26,
            textColor=primary_blue,
            alignment=0,
            spaceAfter=4,
        )

        subtitle_style = ParagraphStyle(
            "SkillsGapSubtitle",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#5f6368"),
            spaceAfter=15,
        )

        h2_style = ParagraphStyle(
            "SkillsGapH2",
            parent=styles["Heading2"],
            fontSize=13,
            leading=17,
            textColor=primary_blue,
            spaceBefore=12,
            spaceAfter=8,
            keepWithNext=True,
        )

        body_style = ParagraphStyle(
            "SkillsGapBody",
            parent=styles["Normal"],
            fontSize=9,
            leading=13,
            textColor=dark_text,
        )

        badge_style = ParagraphStyle(
            "SkillsGapBadge",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
            alignment=TA_CENTER,
            textColor=colors.white,
        )

        story = []

        # Header Title
        story.append(Paragraph("<b>Campus Placement — Target Skill Gap & Learning Audit</b>", title_style))
        company = escape_xml(analysis_data.get("company_name", "Target Company"))
        created_at = escape_xml(analysis_data.get("created_at", "N/A"))
        story.append(Paragraph(f"Candidate Placement Audit for <b>{company}</b> &bull; Generated: {created_at}", subtitle_style))

        # Skill Gap data extraction
        results = analysis_data.get("results", {}) if isinstance(analysis_data.get("results"), dict) else {}
        skill_gaps = results.get("skill_gap", [])

        if not skill_gaps or not isinstance(skill_gaps, list):
            # Graceful Empty State
            empty_box = [
                [
                    Paragraph(
                        "<b>🎉 Outstanding Readiness! No Critical Skill Gaps Detected</b><br/><br/>"
                        "Your resume fully satisfies the analyzed baseline requirements for this role. "
                        "Continue sharpening your interview problem solving and algorithmic fundamentals.",
                        body_style
                    )
                ]
            ]
            empty_table = Table(empty_box, colWidths=[520])
            empty_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#e6f4ea")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#34a853")),
                    ("TOPPADDING", (0, 0), (-1, -1), 16),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
                    ("LEFTPADDING", (0, 0), (-1, -1), 16),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 16),
                ])
            )
            story.append(empty_table)
        else:
            story.append(Paragraph(f"<b>Identified Competency Gaps ({len(skill_gaps)} Missing Competencies)</b>", h2_style))

            # Table Header
            table_data = [
                [
                    Paragraph("<b>Missing Skill</b>", body_style),
                    Paragraph("<b>Importance</b>", body_style),
                    Paragraph("<b>Est. Time</b>", body_style),
                    Paragraph("<b>Priority</b>", body_style),
                    Paragraph("<b>Curated Platform / Project</b>", body_style),
                ]
            ]

            for item in skill_gaps:
                skill_name = escape_xml(item.get("skill", "Core Technical Skill"))
                importance = escape_xml(item.get("importance", "High"))
                learning_time = escape_xml(item.get("learning_time", "1-2 weeks"))
                priority = str(item.get("priority", "Medium")).strip().capitalize()
                resource = escape_xml(item.get("learning_resource", "Documentation & Courseware"))
                proj = escape_xml(item.get("project_suggestion", ""))

                p_bg = high_priority_red if priority == "High" else (med_priority_orange if priority == "Medium" else low_priority_green)

                resource_block = f"<b>Resource:</b> {resource}"
                if proj:
                    resource_block += f"<br/><b>Project:</b> {proj}"

                table_data.append([
                    Paragraph(f"<b>{skill_name}</b>", body_style),
                    Paragraph(importance, body_style),
                    Paragraph(learning_time, body_style),
                    Paragraph(f"<b>{priority}</b>", badge_style),
                    Paragraph(resource_block, body_style),
                ])

            gap_table = Table(table_data, colWidths=[100, 75, 65, 60, 220])
            gap_style = [
                ("BACKGROUND", (0, 0), (-1, 0), accent_light_blue),
                ("TEXTCOLOR", (0, 0), (-1, 0), primary_blue),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("ALIGN", (3, 1), (3, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 1, border_grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, border_grey),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]

            for row_idx, item in enumerate(skill_gaps, start=1):
                pri = str(item.get("priority", "Medium")).strip().capitalize()
                bg_col = high_priority_red if pri == "High" else (med_priority_orange if pri == "Medium" else low_priority_green)
                gap_style.append(("BACKGROUND", (3, row_idx), (3, row_idx), bg_col))

            gap_table.setStyle(TableStyle(gap_style))
            story.append(gap_table)

        # Footer Notice
        story.append(Spacer(1, 20))
        footer_p = Paragraph(
            "<i>Report generated by AI Campus Placement Agent. Designed to accelerate syllabus roadmap planning and recruiter interview readiness.</i>",
            subtitle_style
        )
        story.append(footer_p)

        doc.build(story)
        logger.info("Skills gap PDF report compiled successfully.")
        return output_path

    except Exception as exc:
        logger.error("Error generating skills gap PDF: %s", str(exc))
        raise RuntimeError(f"Skills gap PDF generation failed: {exc}") from exc


def generate_interview_transcript_pdf(
    session_data: dict,
    output_path: str,
    company_name: str = "Placement",
    summary_data: dict = None,
) -> str:
    """
    Generates a structured, professional PDF transcript of a mock interview session (#161).
    Exports each question, candidate response, dynamic score evaluations (technical accuracy,
    communication clarity, confidence, verbal articulation), AI feedback, STAR framework coaching,
    and aggregate session summary with safe XML escaping.
    """
    try:
        logger.info("Generating Mock Interview Transcript PDF at: %s", output_path)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=45,
            leftMargin=45,
            topMargin=45,
            bottomMargin=45,
        )

        styles = getSampleStyleSheet()

        primary_blue = colors.HexColor("#1a73e8")
        accent_light_blue = colors.HexColor("#e8f0fe")
        dark_text = colors.HexColor("#202124")
        border_grey = colors.HexColor("#dadce0")
        light_grey_bg = colors.HexColor("#f8f9fa")

        title_style = ParagraphStyle(
            "TranscriptTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=primary_blue,
            alignment=TA_CENTER,
            spaceAfter=4,
        )

        subtitle_style = ParagraphStyle(
            "TranscriptSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#5f6368"),
            alignment=TA_CENTER,
            spaceAfter=14,
        )

        h1_style = ParagraphStyle(
            "TranscriptH1",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=primary_blue,
            spaceBefore=12,
            spaceAfter=6,
            keepWithNext=True,
        )

        h2_style = ParagraphStyle(
            "TranscriptH2",
            parent=styles["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=14,
            textColor=dark_text,
            spaceBefore=6,
            spaceAfter=3,
            keepWithNext=True,
        )

        body_style = ParagraphStyle(
            "TranscriptBody",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=dark_text,
        )

        quote_style = ParagraphStyle(
            "TranscriptQuote",
            parent=styles["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#374151"),
        )

        bullet_style = ParagraphStyle(
            "TranscriptBullet",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=dark_text,
            leftIndent=12,
            firstLineIndent=-8,
        )

        table_hdr_style = ParagraphStyle(
            "TranscriptTableHdr",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11.5,
            textColor=colors.white,
            alignment=TA_CENTER,
        )

        table_body_center = ParagraphStyle(
            "TranscriptTableCellCenter",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11.5,
            textColor=dark_text,
            alignment=TA_CENTER,
        )

        table_body_left = ParagraphStyle(
            "TranscriptTableCellLeft",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11.5,
            textColor=dark_text,
        )

        badge_hdr_style = ParagraphStyle(
            "TranscriptBadgeHdr",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=primary_blue,
        )

        story = []

        if not isinstance(session_data, dict):
            session_data = {}

        target_company = escape_xml(company_name or session_data.get("company_name", "Target Company"))
        answers = session_data.get("answers", [])
        if not isinstance(answers, list):
            answers = []

        if summary_data is None:
            try:
                from agents.interview_agent import InterviewAgent
                summary_data = InterviewAgent().calculate_session_summary(answers)
            except Exception:
                summary_data = {
                    "total_answered": len(answers),
                    "overall_score": 0,
                    "category_scores": {},
                    "readiness_verdict": "Completed Session",
                    "summary_feedback": "Mock interview session record.",
                }

        overall_score = summary_data.get("overall_score", 0)
        verdict = escape_xml(summary_data.get("readiness_verdict", "Completed Session"))
        summary_feedback = escape_xml(summary_data.get("summary_feedback", ""))

        # 1. Header Banner
        story.append(Paragraph("<b>AI Mock Interview Session Transcript</b>", title_style))
        story.append(Paragraph(
            f"Candidate Practice Session for <b>{target_company}</b> &bull; Overall Score: <b>{overall_score}/100</b> ({verdict})",
            subtitle_style
        ))

        # 2. Executive Performance Scorecard
        score_box_data = [
            [
                Paragraph("<b>Overall Score</b>", table_hdr_style),
                Paragraph("<b>Readiness Verdict</b>", table_hdr_style),
                Paragraph("<b>Questions Answered</b>", table_hdr_style),
            ],
            [
                Paragraph(f"<b><font size=14 color='#1a73e8'>{overall_score}/100</font></b>", table_body_center),
                Paragraph(f"<b>{verdict}</b>", table_body_center),
                Paragraph(f"<b>{len(answers)}</b>", table_body_center),
            ],
        ]
        score_table = Table(score_box_data, colWidths=[150, 222, 150])
        score_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), primary_blue),
            ("BACKGROUND", (0, 1), (-1, 1), accent_light_blue),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 1, border_grey),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, border_grey),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(score_table)
        story.append(Spacer(1, 10))

        if summary_feedback:
            summary_box = [
                [
                    Paragraph(
                        f"<b>Performance Overview:</b><br/>{summary_feedback}",
                        body_style
                    )
                ]
            ]
            summary_table = Table(summary_box, colWidths=[522])
            summary_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), light_grey_bg),
                ("BOX", (0, 0), (-1, -1), 0.5, border_grey),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ]))
            story.append(summary_table)
            story.append(Spacer(1, 10))

        cat_scores = summary_data.get("category_scores", {})
        if cat_scores:
            cat_table_data = [
                [
                    Paragraph("<b>Round / Competency</b>", table_hdr_style),
                    Paragraph("<b>Answered</b>", table_hdr_style),
                    Paragraph("<b>Technical</b>", table_hdr_style),
                    Paragraph("<b>Communication</b>", table_hdr_style),
                    Paragraph("<b>Confidence</b>", table_hdr_style),
                    Paragraph("<b>Avg Score</b>", table_hdr_style),
                ]
            ]
            for cat_name, c_data in cat_scores.items():
                cnt = c_data.get("count", 0)
                tech = c_data.get("technical_accuracy", 0)
                comm = c_data.get("communication_score", 0)
                conf = c_data.get("confidence_score", 0)
                avg = c_data.get("average_score", 0)
                cat_table_data.append([
                    Paragraph(f"<b>{escape_xml(cat_name)}</b>", table_body_left),
                    Paragraph(str(cnt), table_body_center),
                    Paragraph(f"{tech}%", table_body_center),
                    Paragraph(f"{comm}%", table_body_center),
                    Paragraph(f"{conf}%", table_body_center),
                    Paragraph(f"<b>{avg}%</b>", table_body_center),
                ])
            cat_table = Table(cat_table_data, colWidths=[132, 65, 80, 85, 80, 80])
            cat_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), primary_blue),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 1, border_grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, border_grey),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(cat_table)
            story.append(Spacer(1, 12))

        verbal_m = summary_data.get("verbal_metrics")
        if isinstance(verbal_m, dict) and verbal_m:
            avg_verbal = verbal_m.get("average_verbal_clarity", "N/A")
            total_fillers = verbal_m.get("total_filler_words", 0)
            star_rate = verbal_m.get("star_adherence_rate", "N/A")
            v_data = [
                [
                    Paragraph(f"<b>Verbal Articulation:</b> {avg_verbal}%", table_body_center),
                    Paragraph(f"<b>Total Filler Words:</b> {total_fillers}", table_body_center),
                    Paragraph(f"<b>STAR Method Adherence:</b> {star_rate}", table_body_center),
                ]
            ]
            v_table = Table(v_data, colWidths=[174, 174, 174])
            v_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), light_grey_bg),
                ("BOX", (0, 0), (-1, -1), 0.5, border_grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, border_grey),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(v_table)
            story.append(Spacer(1, 14))

        # 3. Detailed Questions & Answers Transcript
        story.append(Paragraph("<b>Detailed Q&A Transcript & AI Evaluation</b>", h1_style))
        story.append(Spacer(1, 4))

        if not answers:
            empty_box = [
                [
                    Paragraph(
                        "<b>No interview responses recorded.</b><br/>"
                        "Start your mock interview session to evaluate answers across technical, HR, and behavioral rounds.",
                        body_style,
                    )
                ]
            ]
            empty_table = Table(empty_box, colWidths=[522])
            empty_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), light_grey_bg),
                ("BOX", (0, 0), (-1, -1), 1, border_grey),
                ("PADDING", (0, 0), (-1, -1), 14),
            ]))
            story.append(empty_table)
        else:
            for idx, item in enumerate(answers, 1):
                q_num = item.get("question_index", idx - 1) + 1
                q_type = escape_xml(item.get("type", "General"))
                q_text = escape_xml(item.get("question", "N/A"))
                user_answer = escape_xml(item.get("answer", "No response recorded.")).replace("\n", "<br/>")

                eval_data = item.get("evaluation", {}) if isinstance(item.get("evaluation"), dict) else {}
                tech_score = eval_data.get("technical_accuracy", 50)
                comm_score = eval_data.get("communication_score", 50)
                conf_score = eval_data.get("confidence_score", 50)
                verbal_score = eval_data.get("verbal_clarity_score", comm_score)
                feedback = escape_xml(eval_data.get("feedback", "Evaluation recorded.")).replace("\n", "<br/>")
                suggestions = eval_data.get("suggestions", [])
                if not isinstance(suggestions, list):
                    suggestions = []

                scores_data = [
                    [
                        Paragraph(f"<b>Technical:</b> {tech_score}/100", table_body_center),
                        Paragraph(f"<b>Communication:</b> {comm_score}/100", table_body_center),
                        Paragraph(f"<b>Confidence:</b> {conf_score}/100", table_body_center),
                        Paragraph(f"<b>Verbal Clarity:</b> {verbal_score}/100", table_body_center),
                    ]
                ]
                scores_table = Table(scores_data, colWidths=[130, 130, 130, 132])
                scores_table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), accent_light_blue),
                    ("BOX", (0, 0), (-1, -1), 0.5, border_grey),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, border_grey),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))

                q_hdr_table = Table(
                    [[Paragraph(f"<b>Question {q_num} &bull; {q_type} Round</b>", badge_hdr_style)]],
                    colWidths=[522]
                )
                q_hdr_table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), light_grey_bg),
                    ("BOX", (0, 0), (-1, -1), 0.5, border_grey),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ]))

                q_elements = [
                    q_hdr_table,
                    Spacer(1, 4),
                    Paragraph(f"<b>Question:</b> {q_text}", body_style),
                    Spacer(1, 4),
                    Paragraph(f"<b>Candidate Response:</b><br/>{user_answer}", quote_style),
                    Spacer(1, 6),
                    scores_table,
                    Spacer(1, 6),
                    Paragraph(f"<b>AI Feedback:</b> {feedback}", body_style),
                ]

                if suggestions:
                    q_elements.append(Spacer(1, 4))
                    q_elements.append(Paragraph("<b>Improvement Suggestions:</b>", h2_style))
                    for sug in suggestions:
                        q_elements.append(Paragraph(f"&bull; {escape_xml(sug)}", bullet_style))

                star_data = eval_data.get("star_method_analysis") or eval_data.get("star_evaluation")
                if isinstance(star_data, dict) and star_data.get("feedback"):
                    q_elements.append(Spacer(1, 4))
                    q_elements.append(Paragraph(
                        f"<b>STAR Framework Coaching:</b> {escape_xml(star_data.get('feedback'))}",
                        body_style
                    ))

                fillers = eval_data.get("filler_words_detected", [])
                if fillers and isinstance(fillers, list):
                    q_elements.append(Spacer(1, 3))
                    q_elements.append(Paragraph(
                        f"<b>Filler Words Detected:</b> {escape_xml(', '.join(str(f) for f in fillers))}",
                        body_style
                    ))

                q_elements.append(Spacer(1, 14))

                raw_ans_len = len(item.get("answer", ""))
                if raw_ans_len < 1500:
                    story.append(KeepTogether(q_elements))
                else:
                    story.extend(q_elements)

        # Footer Notice
        story.append(Spacer(1, 15))
        footer_p = Paragraph(
            "<i>Mock Interview Transcript compiled by AI Campus Placement Agent. Designed for student performance review and placement preparation.</i>",
            subtitle_style
        )
        story.append(footer_p)

        doc.build(story)
        logger.info("Mock Interview Transcript PDF compiled successfully.")
        return output_path

    except Exception as exc:
        logger.error("Error generating mock interview transcript PDF: %s", str(exc))
        raise RuntimeError(f"Mock interview transcript PDF generation failed: {exc}") from exc


def generate_interview_transcript_markdown(
    session_data: dict,
    company_name: str = "Placement",
    summary_data: dict = None,
) -> str:
    """
    Generates a structured Markdown / plain-text transcript of a mock interview session (#161).
    Includes overall session scorecard, category breakdown, and detailed per-question Q&A pairs
    with scores, feedback, suggestions, and verbal communication indicators.
    """
    if not isinstance(session_data, dict):
        session_data = {}

    target_company = company_name or session_data.get("company_name", "Target Company")
    answers = session_data.get("answers", [])
    if not isinstance(answers, list):
        answers = []

    if summary_data is None:
        try:
            from agents.interview_agent import InterviewAgent
            summary_data = InterviewAgent().calculate_session_summary(answers)
        except Exception:
            summary_data = {
                "total_answered": len(answers),
                "overall_score": 0,
                "category_scores": {},
                "readiness_verdict": "Completed Session",
                "summary_feedback": "Mock interview session record.",
            }

    total_ans = len(answers)
    overall_score = summary_data.get("overall_score", 0)
    verdict = summary_data.get("readiness_verdict", "Completed Session")
    summary_feedback = summary_data.get("summary_feedback", "")

    lines = [
        f"# AI Mock Interview Session Transcript — {target_company}",
        "",
        f"- **Target Company:** {target_company}",
        f"- **Total Questions Answered:** {total_ans}",
        f"- **Overall Performance Score:** {overall_score}/100",
        f"- **Readiness Verdict:** {verdict}",
        "",
        "## Executive Performance Summary",
        "",
        summary_feedback if summary_feedback else "Session completed.",
        "",
    ]

    cat_scores = summary_data.get("category_scores", {})
    if cat_scores:
        lines.extend([
            "### Competency Breakdown",
            "",
            "| Round / Category | Questions | Technical Accuracy | Communication | Confidence | Average Score |",
            "| :--- | :---: | :---: | :---: | :---: | :---: |",
        ])
        for cat_name, c_data in cat_scores.items():
            cnt = c_data.get("count", 0)
            tech = c_data.get("technical_accuracy", 0)
            comm = c_data.get("communication_score", 0)
            conf = c_data.get("confidence_score", 0)
            avg = c_data.get("average_score", 0)
            lines.append(f"| {cat_name} | {cnt} | {tech}% | {comm}% | {conf}% | **{avg}%** |")
        lines.append("")

    verbal_m = summary_data.get("verbal_metrics")
    if isinstance(verbal_m, dict) and verbal_m:
        lines.extend([
            "### Verbal & Speech Articulation Telemetry",
            "",
            f"- **Average Verbal Clarity:** {verbal_m.get('average_verbal_clarity', 'N/A')}%",
            f"- **Total Filler Words:** {verbal_m.get('total_filler_words', 0)}",
            f"- **STAR Method Adherence:** {verbal_m.get('star_adherence_rate', 'N/A')}",
            "",
        ])

    lines.extend([
        "---",
        "",
        "## Detailed Questions & Answers Transcript",
        "",
    ])

    if not answers:
        lines.extend([
            "*No interview responses recorded for this session.*",
            "",
        ])
    else:
        for idx, item in enumerate(answers, 1):
            q_num = item.get("question_index", idx - 1) + 1
            q_type = item.get("type", "General")
            q_text = item.get("question", "N/A")
            ans_text = item.get("answer", "No response recorded.")
            eval_data = item.get("evaluation", {}) if isinstance(item.get("evaluation"), dict) else {}

            tech = eval_data.get("technical_accuracy", 50)
            comm = eval_data.get("communication_score", 50)
            conf = eval_data.get("confidence_score", 50)
            verbal = eval_data.get("verbal_clarity_score", comm)

            lines.extend([
                f"### Question {q_num} [{q_type} Round]",
                f"**Question:** {q_text}",
                "",
                "**Candidate Response:**",
                f"> {ans_text}",
                "",
                "**Evaluated Scores:**",
                f"- Technical Accuracy: **{tech}/100**",
                f"- Communication Score: **{comm}/100**",
                f"- Confidence Score: **{conf}/100**",
                f"- Verbal Clarity: **{verbal}/100**",
                "",
            ])

            feedback = eval_data.get("feedback")
            if feedback:
                lines.extend([
                    f"**AI Feedback:** {feedback}",
                    "",
                ])

            suggestions = eval_data.get("suggestions", [])
            if suggestions and isinstance(suggestions, list):
                lines.append("**Improvement Suggestions:**")
                for s in suggestions:
                    lines.append(f"- {s}")
                lines.append("")

            star_data = eval_data.get("star_method_analysis") or eval_data.get("star_evaluation")
            if isinstance(star_data, dict) and star_data.get("feedback"):
                lines.extend([
                    f"**STAR Framework Coaching:** {star_data.get('feedback')}",
                    "",
                ])

            fillers = eval_data.get("filler_words_detected", [])
            if fillers and isinstance(fillers, list):
                lines.extend([
                    f"**Filler Words Detected ({len(fillers)}):** {', '.join(str(f) for f in fillers)}",
                    "",
                ])

            lines.extend([
                "---",
                "",
            ])

    return "\n".join(lines)





def generate_student_preparation_summary_pdf(summary_data: dict, output_path: str) -> str:
    """
    Generates a comprehensive printable PDF placement preparation summary report (#200).
    Aggregates profile readiness, resume analysis findings, coding performance,
    mock interview analytics, completed preparation tasks, and identified skill gaps.
    """
    try:
        logger.info("Generating Student Preparation Summary PDF at: %s", output_path)

        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=54,
            leftMargin=54,
            topMargin=54,
            bottomMargin=54,
        )

        styles = getSampleStyleSheet()
        primary_blue = colors.HexColor("#1a73e8")
        dark_text_color = colors.HexColor("#202124")
        light_grey_bg = colors.HexColor("#f8f9fa")
        border_grey = colors.HexColor("#dadce0")

        title_style = ParagraphStyle(
            "PrepSummaryTitle",
            parent=styles["Heading1"],
            fontSize=22,
            leading=26,
            textColor=primary_blue,
            alignment=TA_CENTER,
            spaceAfter=6,
        )
        subtitle_style = ParagraphStyle(
            "PrepSummarySubtitle",
            parent=styles["Normal"],
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#5f6368"),
            alignment=TA_CENTER,
            spaceAfter=15,
        )
        section_heading = ParagraphStyle(
            "PrepSummarySection",
            parent=styles["Heading2"],
            fontSize=13,
            leading=17,
            textColor=primary_blue,
            spaceBefore=12,
            spaceAfter=6,
        )
        body_style = ParagraphStyle(
            "PrepSummaryBody",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=dark_text_color,
        )
        body_bold = ParagraphStyle(
            "PrepSummaryBodyBold",
            parent=body_style,
            fontName="Helvetica-Bold",
        )

        elements = []

        # 1. Title & Header
        elements.append(Paragraph("Placement Preparation Progress Summary", title_style))
        student_id = escape_xml(summary_data.get("student_id", "Candidate"))
        elements.append(Paragraph(f"Candidate: <b>{student_id}</b> &bull; Generated by AI Campus Placement Agent", subtitle_style))
        elements.append(Spacer(1, 10))

        # 2. Profile & Placement Readiness Box
        profile = summary_data.get("profile", {})
        completion = summary_data.get("completion", {})
        comp_pct = completion.get("completion_percentage", 0)

        name_str = escape_xml(profile.get("full_name") or student_id)
        dept_str = escape_xml(profile.get("department") or "Not Specified")
        grad_str = escape_xml(profile.get("grad_year") or "2026")
        cgpa_str = escape_xml(profile.get("cgpa") or "N/A")
        role_str = escape_xml(profile.get("target_role") or "Software Development Engineer")
        comp_str = escape_xml(profile.get("target_company") or "General Tech")

        profile_table_data = [
            [
                Paragraph("<b>Candidate Name:</b>", body_style),
                Paragraph(name_str, body_style),
                Paragraph("<b>Profile Readiness:</b>", body_style),
                Paragraph(f"<b>{comp_pct}%</b>", body_bold),
            ],
            [
                Paragraph("<b>Department:</b>", body_style),
                Paragraph(dept_str, body_style),
                Paragraph("<b>Graduation Year:</b>", body_style),
                Paragraph(str(grad_str), body_style),
            ],
            [
                Paragraph("<b>Target Role:</b>", body_style),
                Paragraph(role_str, body_style),
                Paragraph("<b>Target Company:</b>", body_style),
                Paragraph(comp_str, body_style),
            ]
        ]
        prof_t = Table(profile_table_data, colWidths=[110, 150, 110, 130])
        prof_t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), light_grey_bg),
            ("BOX", (0, 0), (-1, -1), 1, border_grey),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, border_grey),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(prof_t)
        elements.append(Spacer(1, 12))

        # 3. Resume Analysis Findings
        elements.append(Paragraph("1. Resume Analysis & Keyword Optimization", section_heading))
        latest_analysis = summary_data.get("latest_analysis")
        if latest_analysis and latest_analysis.get("results"):
            res = latest_analysis["results"]
            ats = res.get("ats_score") or (res.get("resume_analysis", {}).get("ats_score") if isinstance(res.get("resume_analysis"), dict) else 75)
            match_pct = res.get("job_match_score") or (res.get("job_match", {}).get("match_percentage") if isinstance(res.get("job_match"), dict) else 70)
            resume_file = escape_xml(latest_analysis.get("resume_filename", "Uploaded Resume"))

            analysis_summary = [
                [Paragraph("<b>Evaluated Resume:</b>", body_style), Paragraph(resume_file, body_style)],
                [Paragraph("<b>ATS Optimization Score:</b>", body_style), Paragraph(f"<b>{ats}/100</b>", body_bold)],
                [Paragraph("<b>Job Match Likelihood:</b>", body_style), Paragraph(f"<b>{match_pct}%</b>", body_bold)],
            ]
            at = Table(analysis_summary, colWidths=[160, 340])
            at.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f3f4")),
                ("BOX", (0, 0), (-1, -1), 0.5, border_grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, border_grey),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            elements.append(at)
        else:
            elements.append(Paragraph("<i>No placement resume analysis uploaded yet. Candidates can upload PDF/DOCX resumes for instant ATS metrics.</i>", body_style))
        elements.append(Spacer(1, 10))

        # 4. Coding Practice Progress
        elements.append(Paragraph("2. Coding Assessment & DSA Submissions", section_heading))
        c_stats = summary_data.get("coding_stats", {})
        c_total = c_stats.get("total_submissions", 0)
        c_passed = c_stats.get("passed_count", 0)
        c_rate = round((c_passed / c_total) * 100) if c_total > 0 else 0

        coding_table_data = [
            [
                Paragraph("<b>Total Problems Attempted</b>", body_style),
                Paragraph("<b>Passed / Accepted</b>", body_style),
                Paragraph("<b>Overall Success Rate</b>", body_style),
            ],
            [
                Paragraph(str(c_total), body_bold),
                Paragraph(str(c_passed), body_bold),
                Paragraph(f"{c_rate}%", body_bold),
            ]
        ]
        ct = Table(coding_table_data, colWidths=[165, 165, 170])
        ct.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f0fe")),
            ("BACKGROUND", (0, 1), (-1, 1), colors.white),
            ("BOX", (0, 0), (-1, -1), 1, border_grey),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, border_grey),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(ct)
        elements.append(Spacer(1, 10))

        # 5. Mock Interview Performance
        elements.append(Paragraph("3. Mock Interview Simulation Analytics", section_heading))
        i_stats = summary_data.get("interview_stats", {})
        i_sessions = i_stats.get("total_sessions", 0)
        i_questions = i_stats.get("total_questions_answered", 0)
        i_avg = i_stats.get("average_score", 0.0)

        interview_table_data = [
            [
                Paragraph("<b>Mock Rounds Conducted</b>", body_style),
                Paragraph("<b>Questions Answered</b>", body_style),
                Paragraph("<b>Average Performance Rating</b>", body_style),
            ],
            [
                Paragraph(str(i_sessions), body_bold),
                Paragraph(str(i_questions), body_bold),
                Paragraph(f"{i_avg}/100", body_bold),
            ]
        ]
        it = Table(interview_table_data, colWidths=[165, 165, 170])
        it.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f0fe")),
            ("BACKGROUND", (0, 1), (-1, 1), colors.white),
            ("BOX", (0, 0), (-1, -1), 1, border_grey),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, border_grey),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(it)
        elements.append(Spacer(1, 10))

        # 6. Completed Preparation Tasks & Skill Gaps
        elements.append(Paragraph("4. Preparation Milestones & Identified Skill Gaps", section_heading))
        skill_gaps = summary_data.get("skill_gaps", [])
        if skill_gaps and isinstance(skill_gaps, list):
            gap_table_data = [[
                Paragraph("<b>Identified Skill Gap</b>", body_style),
                Paragraph("<b>Priority</b>", body_style),
                Paragraph("<b>Estimated Learning Time</b>", body_style)
            ]]
            for g in skill_gaps[:5]:
                s_name = escape_xml(g.get("skill") if isinstance(g, dict) else str(g))
                prio = escape_xml(g.get("priority", "High") if isinstance(g, dict) else "High")
                t_est = escape_xml(g.get("learning_time", "2 weeks") if isinstance(g, dict) else "2 weeks")
                gap_table_data.append([
                    Paragraph(s_name, body_style),
                    Paragraph(prio, body_style),
                    Paragraph(t_est, body_style)
                ])
            gt = Table(gap_table_data, colWidths=[240, 120, 140])
            gt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), light_grey_bg),
                ("BOX", (0, 0), (-1, -1), 0.5, border_grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, border_grey),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            elements.append(gt)
        else:
            elements.append(Paragraph("<i>No critical skill gaps flagged. Continue refreshing core CS algorithms and system designs.</i>", body_style))

        elements.append(Spacer(1, 15))
        tasks_count = summary_data.get("completed_tasks_count", 0)
        apps_summary = summary_data.get("applications_summary", {})
        apps_count = apps_summary.get("total", 0)

        footer_text = f"<b>Milestones Completed:</b> {tasks_count} checklist action items &bull; <b>Active Job Applications:</b> {apps_count}"
        elements.append(Paragraph(footer_text, subtitle_style))

        doc.build(elements)
        logger.info("Student Preparation Summary PDF generated successfully.")
        return output_path

    except Exception as e:
        logger.error("Error generating Student Preparation Summary PDF: %s", str(e))
        raise e
