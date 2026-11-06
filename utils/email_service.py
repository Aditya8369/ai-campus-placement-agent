import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Any, List, Optional
import config

logger = logging.getLogger(__name__)

class EmailNotificationService:
    """
    Placement Activity Email Notification Service (#186).
    Handles sending responsive transactional emails to candidates for important placement activities:
      - Welcome registration confirmation
      - New job application logged
      - Application stage/status transitions (e.g. Interview Scheduled, Offer Extended)
      - Interview schedule reminders
      - Configurable user preference toggle (enable/disable email notifications)
      - Non-crashing delivery error handling with fallback logging
    """

    def __init__(self):
        # Email settings from config or environment with sensible local test defaults
        self.smtp_server = getattr(config, "SMTP_SERVER", "localhost")
        self.smtp_port = int(getattr(config, "SMTP_PORT", 25))
        self.smtp_user = getattr(config, "SMTP_USER", "")
        self.smtp_password = getattr(config, "SMTP_PASSWORD", "")
        self.sender_email = getattr(config, "NOTIFICATION_SENDER_EMAIL", "placements@aicampus.edu")
        self.sender_name = "AI Campus Placement Agent"

    def _format_html_layout(self, title: str, headline: str, body_content: str, cta_url: Optional[str] = None, cta_text: Optional[str] = None) -> str:
        """
        Creates a clean, mobile-responsive HTML email template.
        """
        cta_block = ""
        if cta_url and cta_text:
            cta_block = f"""
            <div style="margin: 28px 0; text-align: center;">
              <a href="{cta_url}" style="background-color: #4f46e5; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 9999px; font-weight: 600; display: inline-block;">
                {cta_text}
              </a>
            </div>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>{title}</title>
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b;">
          <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
            <div style="background-color: #4f46e5; padding: 24px 32px; color: #ffffff; text-align: center;">
              <h2 style="margin: 0; font-size: 20px; font-weight: 700; letter-spacing: -0.02em;">🎓 AI Campus Placement Agent</h2>
              <p style="margin: 4px 0 0 0; opacity: 0.9; font-size: 13px;">Your Intelligent Campus Placement Mentor</p>
            </div>
            <div style="padding: 32px;">
              <h3 style="margin-top: 0; color: #0f172a; font-size: 18px; font-weight: 600;">{headline}</h3>
              <div style="font-size: 14px; line-height: 1.6; color: #334155;">
                {body_content}
              </div>
              {cta_block}
              <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 32px 0 20px 0;">
              <div style="font-size: 12px; color: #94a3b8; text-align: center; line-height: 1.5;">
                You received this notification regarding your placement activities. To manage your email preferences, visit your account settings.<br>
                &copy; AI Campus Placement Agent. All rights reserved.
              </div>
            </div>
          </div>
        </body>
        </html>
        """

    def send_email(
        self,
        recipient_email: str,
        subject: str,
        html_content: str,
        plain_text: Optional[str] = None
    ) -> bool:
        """
        Sends an HTML email with text fallback.
        Catches all network and SMTP failures gracefully without crashing calling workflows.
        """
        recipient_email = (recipient_email or "").strip()
        if not recipient_email or "@" not in recipient_email:
            logger.warning(f"Invalid recipient email provided: '{recipient_email}'. Delivery skipped.")
            return False

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"{self.sender_name} <{self.sender_email}>"
        message["To"] = recipient_email

        fallback_text = plain_text or "Please view this email in an HTML-compatible client."
        message.attach(MIMEText(fallback_text, "plain", "utf-8"))
        message.attach(MIMEText(html_content, "html", "utf-8"))

        try:
            # Check if running in simulated or live environment
            if getattr(config, "EMAIL_DELIVERY_DISABLED", False) or self.smtp_server in ("localhost", "127.0.0.1", ""):
                # Simulated dispatch mode for local development/testing
                logger.info(f"[SIMULATED EMAIL DISPATCH] To: {recipient_email} | Subject: {subject}")
                return True

            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=8.0) as server:
                if self.smtp_port in (587, 465):
                    server.starttls()
                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)
                server.send_message(message)
                logger.info(f"Successfully sent email notification to {recipient_email}")
                return True

        except smtplib.SMTPException as smtpe:
            logger.error(f"SMTP error transmitting email to {recipient_email}: {smtpe}")
            return False
        except Exception as ex:
            logger.error(f"Unexpected error in email dispatch to {recipient_email}: {ex}")
            return False

    def send_welcome_email(self, recipient_email: str, student_name: str) -> bool:
        """
        Dispatches welcome email upon student registration (#186).
        """
        title = "Welcome to AI Campus Placement Agent"
        headline = f"Welcome aboard, {student_name or 'Candidate'}!"
        body = f"""
        <p>Congratulations on taking the first proactive step toward your placement preparation!</p>
        <p>With your new account, you can:</p>
        <ul style="padding-left: 20px;">
          <li>Analyze your resume against top tier tech companies (ATS scoring and gap detection).</li>
          <li>Practice realistic AI-driven mock interviews with dynamic STAR behavioral grading.</li>
          <li>Track all your campus job and internship applications through a unified pipeline.</li>
          <li>Access personalized coding roadmap and practice recommendations.</li>
        </ul>
        <p>Best of luck with your preparation!</p>
        """
        html = self._format_html_layout(
            title=title,
            headline=headline,
            body_content=body,
            cta_url="http://localhost:5000/",
            cta_text="Start First Placement Analysis"
        )
        return self.send_email(
            recipient_email=recipient_email,
            subject="Welcome to AI Campus Placement Agent! 🎓",
            html_content=html
        )
    def send_password_reset_email(
        self,
        recipient_email: str,
        reset_url: str,
        student_name: str = ""
    ) -> bool:
        """Send a secure password reset email."""

        import html

        safe_name = html.escape(student_name or "there")

        body_content = f"""
            <p>Hello {safe_name},</p>
            <p>We received a request to reset your AI Campus Placement Agent password.</p>
            <p>Click the button below to create a new password.</p>
            <p>This link will expire in <strong>30 minutes</strong>.</p>
            <p>If you did not request this reset, you can safely ignore this email.</p>
        """

        html_content = self._format_html_layout(
            title="Reset Your Password",
            headline="Password Reset Request",
            body_content=body_content,
            cta_url=reset_url,
            cta_text="Reset Password"
        )

        plain_text = (
            f"Hello {student_name or 'there'},\n\n"
            "We received a request to reset your password.\n"
            f"Use this link to reset it: {reset_url}\n\n"
            "This link expires in 30 minutes.\n"
            "If you did not request this reset, ignore this email."
        )

        return self.send_email(
            recipient_email=recipient_email,
            subject="Reset Your AI Campus Placement Agent Password",
            html_content=html_content,
            plain_text=plain_text
        )

    def send_application_created_email(
        self,
        recipient_email: str,
        student_name: str,
        company_name: str,
        role_title: str,
        applied_date: str
    ) -> bool:
        """
        Dispatches confirmation when candidate logs a new application (#186).
        """
        title = f"Application Recorded: {company_name}"
        headline = f"New Job Application Recorded for {company_name}"
        body = f"""
        <p>Hi {student_name or 'there'},</p>
        <p>You have successfully logged a new job application in your Placement Tracker:</p>
        <div style="background-color: #f1f5f9; padding: 16px; border-radius: 8px; margin: 16px 0;">
          <strong>Company:</strong> {company_name}<br>
          <strong>Role:</strong> {role_title}<br>
          <strong>Date Applied:</strong> {applied_date}<br>
          <strong>Initial Stage:</strong> Applied
        </div>
        <p>Keep your resume tailored and practice company-specific interview questions while you wait for updates.</p>
        """
        html = self._format_html_layout(
            title=title,
            headline=headline,
            body_content=body,
            cta_url="http://localhost:5000/applications",
            cta_text="View Application Pipeline"
        )
        return self.send_email(
            recipient_email=recipient_email,
            subject=f"Application Tracked: {role_title} at {company_name}",
            html_content=html
        )

    def send_status_change_email(
        self,
        recipient_email: str,
        student_name: str,
        company_name: str,
        role_title: str,
        previous_status: str,
        new_status: str,
        notes: Optional[str] = None
    ) -> bool:
        """
        Dispatches notification when application pipeline stage changes (#186).
        """
        status_colors = {
            "Interview": "#4f46e5",
            "Offer": "#16a34a",
            "Selected": "#16a34a",
            "Rejected": "#dc2626",
            "Assessment": "#d97706"
        }
        color = status_colors.get(new_status, "#4f46e5")

        title = f"Application Status Updated: {company_name}"
        headline = f"Status Update: {company_name} - {role_title}"
        notes_html = f"<p><strong>Notes:</strong> {notes}</p>" if notes else ""
        body = f"""
        <p>Hi {student_name or 'there'},</p>
        <p>The status of your application for <strong>{role_title}</strong> at <strong>{company_name}</strong> has transitioned:</p>
        <div style="background-color: #f8fafc; border-left: 4px solid {color}; padding: 16px; margin: 16px 0; border-radius: 4px;">
          <div><span style="color: #64748b; font-size: 13px;">Previous Stage:</span> <strike>{previous_status}</strike></div>
          <div style="font-size: 18px; font-weight: bold; color: {color}; margin-top: 4px;">New Stage: {new_status}</div>
          {notes_html}
        </div>
        <p>Make sure to review upcoming deadlines and practice tailored interview rounds on your dashboard.</p>
        """
        html = self._format_html_layout(
            title=title,
            headline=headline,
            body_content=body,
            cta_url="http://localhost:5000/applications",
            cta_text="Open Job Tracker"
        )
        return self.send_email(
            recipient_email=recipient_email,
            subject=f"Stage Update [{new_status}]: {company_name} ({role_title})",
            html_content=html
        )

    def send_interview_reminder_email(
        self,
        recipient_email: str,
        student_name: str,
        company_name: str,
        interview_round: str,
        scheduled_time: str,
        interview_link: Optional[str] = None
    ) -> bool:
        """
        Dispatches reminder for upcoming interview dates (#186).
        """
        title = f"Reminder: Upcoming Interview with {company_name}"
        headline = f"Interview Scheduled: {company_name}"
        link_html = f"<p><strong>Meeting / Round Link:</strong> <a href='{interview_link}'>{interview_link}</a></p>" if interview_link else ""
        body = f"""
        <p>Hi {student_name or 'there'},</p>
        <p>This is a reminder about your upcoming placement interview round:</p>
        <div style="background-color: #eef2ff; border: 1px solid #c7d2fe; padding: 16px; border-radius: 8px; margin: 16px 0;">
          <strong>Target Company:</strong> {company_name}<br>
          <strong>Round Category:</strong> {interview_round}<br>
          <strong>Scheduled Date/Time:</strong> {scheduled_time}<br>
          {link_html}
        </div>
        <p>Quick Tip: Warm up your communication by doing a 5-minute simulated mock interview session before your real call.</p>
        """
        html = self._format_html_layout(
            title=title,
            headline=headline,
            body_content=body,
            cta_url="http://localhost:5000/interview-history",
            cta_text="Launch Practice Warmup"
        )
        return self.send_email(
            recipient_email=recipient_email,
            subject=f"Reminder: {interview_round} Interview with {company_name} at {scheduled_time}",
            html_content=html
        )
