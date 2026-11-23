"""
Profile completion checklist service (#627).
Evaluates student profile completeness across required (target role, graduation year, skills)
and optional fields, providing direct links and percentage tracking.
"""

from typing import Dict, Any, List

CHECKLIST_ITEMS = [
    {
        "id": "target_role",
        "label": "Target Placement Role",
        "required": True,
        "weight": 25,
        "link": "/profile",
        "description": "Specify the role you are preparing for (e.g., Software Development Engineer)"
    },
    {
        "id": "graduation_year",
        "label": "Graduation Year & Degree",
        "required": True,
        "weight": 20,
        "link": "/profile",
        "description": "Set your expected batch graduation year"
    },
    {
        "id": "skills",
        "label": "Core Technical Skills",
        "required": True,
        "weight": 25,
        "link": "/profile",
        "description": "Add at least 3 programming languages or technologies"
    },
    {
        "id": "resume_uploaded",
        "label": "Master Resume Upload",
        "required": True,
        "weight": 20,
        "link": "/",
        "description": "Upload a PDF/DOCX resume for ATS scoring"
    },
    {
        "id": "applications_tracked",
        "label": "First Tracked Application",
        "required": False,
        "weight": 10,
        "link": "/applications",
        "description": "Track at least one company application on your board"
    }
]

def calculate_profile_completion(profile_data: Dict[str, Any]) -> Dict[str, Any]:
    profile_data = profile_data or {}
    items = []
    earned_points = 0

    # 1. Target role
    role_ok = bool(profile_data.get("target_role") and str(profile_data.get("target_role")).strip())
    # 2. Grad year
    grad_ok = bool(profile_data.get("graduation_year"))
    # 3. Skills
    skills = profile_data.get("skills", [])
    skills_ok = isinstance(skills, list) and len(skills) >= 1
    # 4. Resume
    resume_ok = bool(profile_data.get("resume_uploaded"))
    # 5. Apps
    apps_ok = bool(profile_data.get("applications_count", 0) > 0)

    status_map = {
        "target_role": role_ok,
        "graduation_year": grad_ok,
        "skills": skills_ok,
        "resume_uploaded": resume_ok,
        "applications_tracked": apps_ok
    }

    for item in CHECKLIST_ITEMS:
        is_completed = status_map.get(item["id"], False)
        if is_completed:
            earned_points += item["weight"]
        items.append({
            "id": item["id"],
            "label": item["label"],
            "required": item["required"],
            "weight": item["weight"],
            "link": item["link"],
            "description": item["description"],
            "completed": is_completed
        })

    return {
        "success": True,
        "completion_percentage": earned_points,
        "checklist": items,
        "missing_required_count": sum(1 for it in items if it["required"] and not it["completed"])
    }
