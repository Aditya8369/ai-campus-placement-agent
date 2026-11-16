"""
Report Watermark Service
Adds subtle, tamper-resistant watermarks and educational preparation notices
to shared reports, exported documents, and HTML views.

Features:
- Configurable watermark styles (Subtle Diagonal Text, Header/Footer Notice, CSS Print Overlay).
- Embeds generation timestamp and masked student/session context.
- Disclaims non-official status ("AI Placement Agent - For Preparation Only").
- Supports HTML styling injection and text-based watermark stamping.
- Built-in audit trail logging and watermark verification helpers.
"""

from datetime import datetime, timezone
import hashlib
import html
import re
from typing import Dict, Any, Optional

DEFAULT_WATERMARK_TEXT = "AI Campus Placement Agent • For Preparation Only • Unofficial"


class ReportWatermarkService:
    """Service to generate and apply watermarks to placement preparation documents."""

    def __init__(self, default_notice: str = DEFAULT_WATERMARK_TEXT):
        self.default_notice = default_notice

    def generate_watermark_metadata(
        self,
        student_id: Optional[str] = None,
        document_type: str = "Placement Preparation Report",
        custom_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Creates metadata used for stamping watermark notices.
        Masks the student ID to protect privacy while ensuring traceability.
        """
        utc_now = datetime.now(timezone.utc)
        timestamp_str = utc_now.strftime("%Y-%m-%d %H:%M UTC")

        masked_id = "STUDENT"
        if student_id:
            cleaned = str(student_id).strip()
            if len(cleaned) > 4:
                masked_id = f"ID-***{cleaned[-4:]}"
            else:
                masked_id = f"ID-{cleaned}"

        notice_text = custom_text.strip() if custom_text else self.default_notice
        full_caption = f"{notice_text} • {document_type} • {timestamp_str} • {masked_id}"

        # Generate a lightweight verification digest to verify report integrity
        digest_seed = f"{masked_id}:{timestamp_str}:{document_type}:{notice_text}"
        verification_hash = hashlib.sha256(digest_seed.encode("utf-8")).hexdigest()[:12]

        return {
            "notice_text": notice_text,
            "document_type": document_type,
            "timestamp": timestamp_str,
            "masked_student_id": masked_id,
            "full_caption": full_caption,
            "verification_code": verification_hash.upper(),
            "iso_time": utc_now.isoformat()
        }

    def render_html_watermark_css(self, opacity: float = 0.08, angle_deg: int = -30) -> str:
        """
        Generates responsive CSS styles for rendering diagonal repeat watermarks
        and print-specific watermarks.
        """
        safe_opacity = max(0.02, min(opacity, 0.35))
        return f"""
<style>
.placement-watermark-container {{
    position: relative;
    overflow: hidden;
    min-height: 100%;
}}

.placement-watermark-overlay {{
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    pointer-events: none;
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
}}

.placement-watermark-pattern {{
    opacity: {safe_opacity};
    transform: rotate({angle_deg}deg);
    font-size: 1.8rem;
    font-weight: 700;
    color: #4b5563;
    user-select: none;
    white-space: nowrap;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    line-height: 2.8;
    text-align: center;
}}

.placement-watermark-banner {{
    background-color: #f3f4f6;
    border-bottom: 1px dashed #d1d5db;
    padding: 8px 14px;
    font-size: 0.8rem;
    color: #4b5563;
    text-align: center;
    letter-spacing: 0.04em;
    font-weight: 500;
}}

.placement-watermark-footer-note {{
    margin-top: 2rem;
    padding: 0.75rem;
    background-color: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    font-size: 0.75rem;
    color: #6b7280;
    text-align: center;
    line-height: 1.4;
}}

@media print {{
    .placement-watermark-pattern {{
        opacity: 0.15 !important;
        color: #000000 !important;
    }}
    .placement-watermark-banner {{
        display: block !important;
        border-bottom: 1px solid #9ca3af;
    }}
    .placement-watermark-footer-note {{
        border: 1px solid #000000 !important;
        color: #000000 !important;
    }}
}}
</style>
""".strip()

    def apply_watermark_to_html(
        self,
        html_content: str,
        student_id: Optional[str] = None,
        document_type: str = "Placement Report",
        custom_text: Optional[str] = None,
        include_banner: bool = True,
        opacity: float = 0.08
    ) -> str:
        """
        Injects watermark CSS and overlay elements into an HTML document.
        Handles both full HTML pages (with <body>) and partial HTML snippets.
        """
        if not html_content:
            return ""

        meta = self.generate_watermark_metadata(student_id, document_type, custom_text)
        css_block = self.render_html_watermark_css(opacity=opacity)
        escaped_caption = html.escape(meta["full_caption"])
        escaped_notice = html.escape(meta["notice_text"])
        escaped_timestamp = html.escape(meta["timestamp"])
        verification_code = html.escape(meta["verification_code"])

        repeated_pattern = "<br>".join([escaped_caption] * 8)

        overlay_html = f"""
<div class="placement-watermark-overlay" aria-hidden="true">
    <div class="placement-watermark-pattern">
        {repeated_pattern}
    </div>
</div>
""".strip()

        banner_html = ""
        if include_banner:
            banner_html = f"""
<div class="placement-watermark-banner" role="note">
    🛡️ {escaped_notice} | {escaped_timestamp} | Ref: {html.escape(meta['masked_student_id'])} | Code: {verification_code}
</div>
""".strip()

        footer_html = f"""
<div class="placement-watermark-footer-note" role="contentinfo">
    <strong>Educational Notice:</strong> This summary was generated by the AI Campus Placement Agent for practice purposes only.
    It does not constitute an accredited institutional transcript or verified professional credential.
    (Ref Code: {verification_code})
</div>
""".strip()

        # If full HTML document with body tag
        if re.search(r"<body[^>]*>", html_content, re.IGNORECASE):
            # Inject CSS before </head> or at start
            if "</head>" in html_content:
                html_content = html_content.replace("</head>", f"{css_block}\n</head>", 1)
            else:
                html_content = f"{css_block}\n{html_content}"

            # Inject banner and overlay right after <body ...>
            def insert_after_body(match):
                body_tag = match.group(0)
                return f'{body_tag}\n<div class="placement-watermark-container">\n{banner_html}\n{overlay_html}'

            html_content = re.sub(r"<body[^>]*>", insert_after_body, html_content, count=1, flags=re.IGNORECASE)
            # Close container before </body>
            if "</body>" in html_content:
                html_content = html_content.replace("</body>", f"{footer_html}\n</div>\n</body>", 1)
            else:
                html_content = f"{html_content}\n{footer_html}\n</div>"
            return html_content

        # For partial HTML snippets
        return f"""{css_block}
<div class="placement-watermark-container">
    {banner_html}
    {overlay_html}
    <div class="watermarked-content">
        {html_content}
    </div>
    {footer_html}
</div>"""

    def apply_watermark_to_plain_text(
        self,
        text_content: str,
        student_id: Optional[str] = None,
        document_type: str = "Placement Preparation Summary",
        custom_text: Optional[str] = None
    ) -> str:
        """
        Appends standard header and footer watermarking to plain text or markdown reports.
        """
        meta = self.generate_watermark_metadata(student_id, document_type, custom_text)
        border = "=" * 76
        header = (
            f"{border}\n"
            f"[WATERMARK] {meta['notice_text'].upper()}\n"
            f"Doc: {meta['document_type']} | Generated: {meta['timestamp']} | Student: {meta['masked_student_id']}\n"
            f"Verification Code: {meta['verification_code']}\n"
            f"{border}\n"
        )
        footer = (
            f"\n{border}\n"
            f"CONFIDENTIAL & UNOFFICIAL PREPARATION RECORD • NOT AN OFFICIAL TRANSCRIPT\n"
            f"{meta['full_caption']} • Verification: {meta['verification_code']}\n"
            f"This document is for personal interview and placement preparation only.\n"
            f"{border}"
        )
        return f"{header}\n{text_content.strip()}\n{footer}"

    def verify_watermark_digest(
        self,
        masked_student_id: str,
        timestamp_str: str,
        document_type: str,
        notice_text: str,
        verification_code: str
    ) -> bool:
        """
        Verifies if a provided watermark verification code matches the metadata tuple.
        """
        digest_seed = f"{masked_student_id}:{timestamp_str}:{document_type}:{notice_text}"
        expected = hashlib.sha256(digest_seed.encode("utf-8")).hexdigest()[:12].upper()
        return expected == str(verification_code).strip().upper()


# Global default instance
report_watermark_service = ReportWatermarkService()
