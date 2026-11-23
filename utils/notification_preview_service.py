"""
Notification delivery preview service (#633).
Provides sample renderings for email and in-app alerts categorized by event type
(status changes, interview reminders, deadlines) without leaking real candidate data.
"""

from typing import Dict, Any, List

NOTIFICATION_PREVIEW_TEMPLATES = {
    "status_change": {
        "category": "Application Updates",
        "title": "Application Status Changed",
        "sample_subject": "[Sample Alert] Application Update: Google - SDE",
        "sample_body": "Your application for SDE at Google has advanced to the 'Interview' stage.",
        "trigger_event": "Fires immediately when an application moves between stages.",
        "channels": ["email", "in_app"]
    },
    "interview_reminder": {
        "category": "Interviews",
        "title": "Upcoming Mock Interview",
        "sample_subject": "[Sample Alert] Practice Reminder: Technical Round starts in 1 hour",
        "sample_body": "Your scheduled Technical Mock Interview is in 60 minutes. Click to review your preparation notes.",
        "trigger_event": "Fires 1 hour prior to a scheduled mock interview.",
        "channels": ["email", "browser"]
    },
    "deadline_warning": {
        "category": "Deadlines",
        "title": "Application Deadline Approaching",
        "sample_subject": "[Sample Alert] Deadline Reminder: Microsoft Applications close tomorrow",
        "sample_body": "The application window for Microsoft campus drive closes in 24 hours.",
        "trigger_event": "Fires 1 day before an application deadline.",
        "channels": ["email", "in_app"]
    }
}

def get_notification_previews() -> List[Dict[str, Any]]:
    return list(NOTIFICATION_PREVIEW_TEMPLATES.values())

def generate_test_notification(notification_type: str, recipient: str = None) -> Dict[str, Any]:
    tpl = NOTIFICATION_PREVIEW_TEMPLATES.get(notification_type, NOTIFICATION_PREVIEW_TEMPLATES["status_change"])
    return {
        "success": True,
        "is_test": True,
        "recipient": recipient or "candidate@campus.edu",
        "subject": tpl["sample_subject"],
        "body": tpl["sample_body"],
        "disclaimer": "This is an automated simulation preview containing synthetic demo data."
    }
