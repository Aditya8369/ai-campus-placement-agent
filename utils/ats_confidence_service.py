"""
ATS Score Confidence Indicator Service (#598).
==============================================
Calculates a transparent confidence score (High, Medium, Low) for an ATS resume evaluation.
Explains exactly which extracted resume sections, text characteristics, or formatting issues
affected confidence, and provides links to review or recheck resume data.
"""

from typing import Any, Dict, List, Optional


def calculate_ats_score_confidence(
    resume_text: str,
    format_compat: Optional[Dict[str, Any]] = None,
    ats_breakdown: Optional[Dict[str, Any]] = None,
    review_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Computes an explainable confidence level (High, Medium, Low) for the ATS score.

    Evaluation factors:
    1. Text legibility and length (minimum characters and words).
    2. Crucial section detectability (Education, Experience/Projects, Skills, Contact).
    3. Document formatting issues (multi-column layouts, table grids, embedded raster images).
    4. Student review status (pre-reviewed vs unreviewed raw extraction).

    Returns:
        Dict containing:
        - confidence_level: 'High' | 'Medium' | 'Low'
        - confidence_score: int (0 to 100)
        - is_low_confidence: bool
        - factors: List[Dict] with explanation of each factor and its impact
        - recheck_url: str (link to review and recheck resume data)
        - plain_explanation: str
        - recommendations: List[str]
    """
    cleaned_text = (resume_text or "").strip()
    char_count = len(cleaned_text)
    words = cleaned_text.split()
    word_count = len(words)

    confidence_points = 100
    factors: List[Dict[str, Any]] = []

    # 1. Text volume and readability
    if char_count < 150 or word_count < 30:
        confidence_points -= 45
        factors.append({
            "factor": "Extremely Short or Incomplete Text",
            "impact": "critical",
            "score_reduction": 45,
            "description": f"Only {word_count} words were detected. ATS parsers need complete text to accurately assess placement readiness.",
            "remedy": "Ensure your resume contains complete details on education, skills, and projects."
        })
    elif char_count < 450 or word_count < 80:
        confidence_points -= 25
        factors.append({
            "factor": "Limited Content Volume",
            "impact": "moderate",
            "score_reduction": 25,
            "description": f"Limited text volume ({word_count} words). Some sections may be missing or truncated.",
            "remedy": "Expand on your project achievements and technical competencies."
        })
    else:
        factors.append({
            "factor": "Sufficient Text Volume",
            "impact": "positive",
            "score_reduction": 0,
            "description": f"Clean text stream detected with {word_count} words across the resume.",
            "remedy": None
        })

    # 2. Section detection verification
    lowered = cleaned_text.lower()
    missing_critical_sections = []
    if not any(k in lowered for k in ["education", "degree", "university", "college", "gpa", "b.tech", "cgpa"]):
        missing_critical_sections.append("Education")
    if not any(k in lowered for k in ["skill", "skills", "technologies", "tech stack", "languages"]):
        missing_critical_sections.append("Skills")
    if not any(k in lowered for k in ["project", "projects", "experience", "work experience", "internship"]):
        missing_critical_sections.append("Projects/Experience")
    if not any(k in lowered for k in ["@", "email", "phone", "github", "linkedin"]):
        missing_critical_sections.append("Contact Details")

    if missing_critical_sections:
        deduction = min(40, len(missing_critical_sections) * 15)
        confidence_points -= deduction
        factors.append({
            "factor": "Undetected Critical Resume Sections",
            "impact": "high" if len(missing_critical_sections) > 1 else "moderate",
            "score_reduction": deduction,
            "description": f"Could not detect clear headings for: {', '.join(missing_critical_sections)}. The ATS score may not reflect your true readiness.",
            "remedy": f"Add explicit, standard section headers like 'Education', 'Technical Skills', or 'Projects'."
        })
    else:
        factors.append({
            "factor": "All Core Sections Detected",
            "impact": "positive",
            "score_reduction": 0,
            "description": "Found standard headings for Education, Technical Skills, Projects, and Contact details.",
            "remedy": None
        })

    # 3. Document formatting issues (from format_compat if provided)
    if format_compat:
        checks = format_compat.get("checks", [])
        for chk in checks:
            if chk.get("status") == "warn":
                chk_id = chk.get("id")
                if chk_id == "multi_column":
                    confidence_points -= 15
                    factors.append({
                        "factor": "Multi-Column Layout Detected",
                        "impact": "moderate",
                        "score_reduction": 15,
                        "description": "Multi-column layouts or sidebars cause ATS parsers to mix horizontal text, reducing parsing confidence.",
                        "remedy": "Switch to a linear single-column layout."
                    })
                elif chk_id == "tables":
                    confidence_points -= 10
                    factors.append({
                        "factor": "Table Grids Detected",
                        "impact": "moderate",
                        "score_reduction": 10,
                        "description": "Tables and grids can cause cell contents to be concatenated out of order.",
                        "remedy": "Replace table cells with bulleted lists."
                    })
                elif chk_id == "images":
                    confidence_points -= 10
                    factors.append({
                        "factor": "Embedded Graphics / Icons",
                        "impact": "minor",
                        "score_reduction": 10,
                        "description": "Embedded icons or images might contain untracked skill ratings or contact links.",
                        "remedy": "Use standard plain text characters instead of graphic icons."
                    })
                elif chk_id == "text_extraction":
                    confidence_points -= 20
                    factors.append({
                        "factor": "Suspicious Font Encoding or Low Density",
                        "impact": "high",
                        "score_reduction": 20,
                        "description": "Non-standard font encodings or sparse characters detected on one or more pages.",
                        "remedy": "Re-export PDF with standard Unicode fonts."
                    })

    # 4. Final score clamping and confidence level assignment
    confidence_points = max(10, min(100, confidence_points))

    if confidence_points >= 80:
        level = "High"
        badge_class = "bg-success-subtle text-success border border-success-subtle"
        plain_explanation = "High confidence: All major sections and text streams were cleanly parsed without structural confusion."
    elif confidence_points >= 55:
        level = "Medium"
        badge_class = "bg-warning-subtle text-warning-emphasis border border-warning-subtle"
        plain_explanation = "Medium confidence: Some resume sections or formatting styles may have affected full text parsing accuracy."
    else:
        level = "Low"
        badge_class = "bg-danger-subtle text-danger border border-danger-subtle"
        plain_explanation = "Low confidence: Significant content appears unreadable, missing, or obscured by complex layouts. Review extracted text before relying on this score."

    recommendations = []
    for f in factors:
        if f.get("remedy") and f["remedy"] not in recommendations:
            recommendations.append(f["remedy"])

    return {
        "confidence_level": level,
        "confidence_score": confidence_points,
        "is_low_confidence": (level == "Low"),
        "badge_class": badge_class,
        "plain_explanation": plain_explanation,
        "factors": factors,
        "recommendations": recommendations,
        "recheck_url": "/resume/review",
    }
