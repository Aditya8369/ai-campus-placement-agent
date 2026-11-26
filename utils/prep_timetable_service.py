"""
Personalized Weekly Preparation Timetable & Daily Study-Time Allocation Service (#605)
=====================================================================================
Transforms roadmap topics and tasks into a realistic day-by-day weekly timetable
and structured daily preparation schedule based on student availability (free hours per day).

Guarantees:
- Total allocated study time never exceeds the user's availability.
- Generates structured daily preparation schedule partitioned into prioritized pillars:
  Coding (35%), Projects (25%), Interviews (20%), Revision (20%).
- Supports morning, afternoon, or evening study blocks.
- Allocates time fairly and prevents cognitive fatigue with balanced study intervals.
- Enforces strict input validation on empty, negative, or unrealistic (>16 hrs/day) availability.
"""

from typing import Dict, Any, List, Optional, Tuple, Union
import math


VALID_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TIME_SLOTS = ["Morning (08:00 - 11:00)", "Afternoon (14:00 - 17:00)", "Evening (18:00 - 21:00)"]

# Core pillar time allocation weights (XYZ formula for balanced preparation)
PILLAR_WEIGHTS = {
    "Coding": 0.35,      # DSA, LeetCode / problem solving
    "Projects": 0.25,    # System design, architecture, feature deep dive
    "Interviews": 0.20,  # Mock interviews, STAR behavioral stories
    "Revision": 0.20     # Core CS: OS, DBMS, Networks, OOP
}


def validate_daily_availability(availability: Any) -> Tuple[bool, Optional[str], Dict[str, float]]:
    """
    Validates daily availability mapping of day -> hours or single daily hours number.
    Enforces non-empty, float >= 0 and <= 16 hours/day.
    """
    if availability is None:
        return False, "Please provide availability for days of the week.", {}

    # Support single daily study time passed directly as a number
    if isinstance(availability, (int, float)):
        try:
            h = float(availability)
        except (ValueError, TypeError):
            return False, "Invalid hours value: must be a number.", {}
        if h < 0:
            return False, "Study hours cannot be negative.", {}
        if h > 16:
            return False, f"Study hours ({h} hrs) exceeds realistic daily study limits (max 16 hrs).", {}
        if h <= 0:
            return False, "Daily study hours must be greater than 0.", {}
        cleaned = {day: h for day in VALID_DAYS}
        return True, None, cleaned

    if not isinstance(availability, dict) or not availability:
        return False, "Please provide availability for days of the week.", {}

    # Check if a single daily_hours / available_hours key was provided instead of full days
    single_key = None
    for k in ["daily_hours", "daily_study_time", "available_hours", "hours", "study_time"]:
        if k in availability and availability[k] is not None:
            single_key = k
            break

    if single_key and not any(day in availability for day in VALID_DAYS):
        val = availability[single_key]
        try:
            h = float(val)
        except (ValueError, TypeError):
            return False, f"Invalid hours value for {single_key}: must be a number.", {}
        if h < 0:
            return False, "Study hours cannot be negative.", {}
        if h > 16:
            return False, f"Study hours ({h} hrs) exceeds realistic daily study limits (max 16 hrs).", {}
        if h <= 0:
            return False, "Daily study hours must be greater than 0.", {}
        cleaned = {day: h for day in VALID_DAYS}
        return True, None, cleaned

    cleaned: Dict[str, float] = {}
    total_hours = 0.0

    for day in VALID_DAYS:
        val = availability.get(day, 0)
        try:
            h = float(val) if val is not None else 0.0
        except (ValueError, TypeError):
            return False, f"Invalid hours value for {day}: must be a number.", {}

        if h < 0:
            return False, f"Hours for {day} cannot be negative.", {}
        if h > 16:
            return False, f"Hours for {day} ({h} hrs) exceeds realistic daily study limits (max 16 hrs).", {}

        cleaned[day] = h
        total_hours += h

    if total_hours <= 0:
        return False, "Total weekly study availability must be greater than 0 hours.", {}

    return True, None, cleaned


def generate_daily_study_schedule(
    daily_hours: Union[int, float],
    preferred_slot: str = "Evening (18:00 - 21:00)",
    custom_tasks: Optional[List[Dict[str, Any]]] = None,
    target_role: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generates a structured daily preparation schedule partitioned into prioritized
    study blocks based on the user's available study time.

    Pillar Distribution:
    - Coding & Problem Solving (35%): DSA, algorithmic problem solving
    - Project Architecture (25%): Codebase review, API design, scalability
    - Mock Interviews & Behavioral (20%): STAR stories, leadership, communication
    - Core CS Fundamentals Revision (20%): OS, DBMS, Networks, OOP

    Guarantees:
    - Total allocated study time never exceeds available daily_hours.
    - Prevents cognitive fatigue with realistic session durations.
    """
    try:
        hours = float(daily_hours)
    except (ValueError, TypeError):
        raise ValueError("Daily study hours must be a valid number.")

    if hours <= 0:
        raise ValueError("Daily study hours must be greater than 0.")
    if hours > 16:
        raise ValueError(f"Daily study hours ({hours} hrs) exceeds realistic daily study limits (max 16 hrs).")

    selected_slot = preferred_slot if preferred_slot in TIME_SLOTS else TIME_SLOTS[2]

    # Task blueprints by pillar
    pillar_tasks = {
        "Coding": [
            {"title": "DSA & Problem Solving: Arrays, Two-Pointer & Binary Search", "desc": "Focus on high-frequency interview patterns on LeetCode / HackerRank."},
            {"title": "DSA: Dynamic Programming, Graphs & Tree Traversals", "desc": "Solve medium-level graph traversals (BFS/DFS) and state transitions."},
            {"title": "Coding Assessment Timed Mock Practice", "desc": "Simulate 45-minute company online assessment environment under time pressure."}
        ],
        "Projects": [
            {"title": "System Architecture: Microservices, APIs & Data Flow", "desc": "Analyze end-to-end component flow, caching layers, and database queries."},
            {"title": "Codebase Walkthrough & Technical Trade-offs", "desc": "Review resume projects and prepare deep-dive justifications for tech stack choices."},
            {"title": "Scalability & Performance Optimization Review", "desc": "Design for high-concurrency, asynchronous queues, and fault tolerance."}
        ],
        "Interviews": [
            {"title": "STAR Behavioral Stories & Leadership Scenarios", "desc": "Draft Situation-Task-Action-Result narratives for team conflict, ambiguity, and failure."},
            {"title": "Technical Mock Interview & Resume Drill", "desc": "Practice answering 'Tell me about yourself' and deep technical project questions out loud."},
            {"title": "Company-Specific Culture & Values Alignment", "desc": "Research target company core values, engineering blog, and recent technical milestones."}
        ],
        "Revision": [
            {"title": "DBMS: Indexing, Transactions & SQL Query Optimization", "desc": "Revise ACID properties, B-Tree indexes, isolation levels, and complex joins."},
            {"title": "Operating Systems & Concurrency: Threads & Memory", "desc": "Review processes vs threads, deadlock prevention, mutexes, and virtual memory."},
            {"title": "Computer Networks: TCP/IP, HTTP/HTTPS & WebSockets", "desc": "Master TCP handshake, flow control, DNS lookup flow, and REST principles."}
        ]
    }

    schedule_blocks: List[Dict[str, Any]] = []
    allocated_by_pillar: Dict[str, float] = {p: 0.0 for p in PILLAR_WEIGHTS}

    if hours <= 1.25:
        # Short session: 2 high-impact blocks to prevent fragmentation
        # 60% Coding + 40% Interview/Revision
        t1 = round(hours * 0.60, 2)
        t2 = round(hours - t1, 2)

        schedule_blocks.append({
            "id": "block_1",
            "title": pillar_tasks["Coding"][0]["title"],
            "category": "Coding",
            "allocated_hours": t1,
            "allocated_minutes": int(round(t1 * 60)),
            "time_slot": selected_slot,
            "focus_area": "Problem Solving",
            "description": pillar_tasks["Coding"][0]["desc"],
            "status": "pending"
        })
        allocated_by_pillar["Coding"] += t1

        schedule_blocks.append({
            "id": "block_2",
            "title": pillar_tasks["Interviews"][0]["title"],
            "category": "Interviews",
            "allocated_hours": t2,
            "allocated_minutes": int(round(t2 * 60)),
            "time_slot": selected_slot,
            "focus_area": "Behavioral & Technical Prep",
            "description": pillar_tasks["Interviews"][0]["desc"],
            "status": "pending"
        })
        allocated_by_pillar["Interviews"] += t2

    elif hours <= 2.5:
        # Standard 3-block schedule
        # Coding 40%, Projects 30%, Interviews/Revision 30%
        c_h = round(hours * 0.40, 2)
        p_h = round(hours * 0.30, 2)
        r_h = round(hours - c_h - p_h, 2)

        schedule_blocks.append({
            "id": "block_1",
            "title": pillar_tasks["Coding"][0]["title"],
            "category": "Coding",
            "allocated_hours": c_h,
            "allocated_minutes": int(round(c_h * 60)),
            "time_slot": selected_slot,
            "focus_area": "Data Structures & Algorithms",
            "description": pillar_tasks["Coding"][0]["desc"],
            "status": "pending"
        })
        allocated_by_pillar["Coding"] += c_h

        schedule_blocks.append({
            "id": "block_2",
            "title": pillar_tasks["Projects"][0]["title"],
            "category": "Projects",
            "allocated_hours": p_h,
            "allocated_minutes": int(round(p_h * 60)),
            "time_slot": selected_slot,
            "focus_area": "System Architecture & Deep Dive",
            "description": pillar_tasks["Projects"][0]["desc"],
            "status": "pending"
        })
        allocated_by_pillar["Projects"] += p_h

        schedule_blocks.append({
            "id": "block_3",
            "title": pillar_tasks["Interviews"][0]["title"],
            "category": "Interviews",
            "allocated_hours": r_h,
            "allocated_minutes": int(round(r_h * 60)),
            "time_slot": selected_slot,
            "focus_area": "Behavioral & Storytelling",
            "description": pillar_tasks["Interviews"][0]["desc"],
            "status": "pending"
        })
        allocated_by_pillar["Interviews"] += r_h

    else:
        # Comprehensive 4-pillar schedule
        # Coding 35%, Projects 25%, Interviews 20%, Revision 20%
        c_h = round(hours * 0.35, 2)
        p_h = round(hours * 0.25, 2)
        i_h = round(hours * 0.20, 2)
        r_h = round(hours - c_h - p_h - i_h, 2)

        pillars_plan = [
            ("Coding", c_h, pillar_tasks["Coding"][0]),
            ("Projects", p_h, pillar_tasks["Projects"][0]),
            ("Interviews", i_h, pillar_tasks["Interviews"][0]),
            ("Revision", r_h, pillar_tasks["Revision"][0]),
        ]

        for idx, (pillar, b_hours, task_info) in enumerate(pillars_plan, start=1):
            schedule_blocks.append({
                "id": f"block_{idx}",
                "title": task_info["title"],
                "category": pillar,
                "allocated_hours": b_hours,
                "allocated_minutes": int(round(b_hours * 60)),
                "time_slot": selected_slot,
                "focus_area": pillar,
                "description": task_info["desc"],
                "status": "pending"
            })
            allocated_by_pillar[pillar] += b_hours

    total_allocated = sum(b["allocated_hours"] for b in schedule_blocks)

    return {
        "status": "success",
        "daily_hours": round(hours, 2),
        "total_allocated_hours": round(total_allocated, 2),
        "preferred_slot": selected_slot,
        "schedule": schedule_blocks,
        "pillar_breakdown": {k: round(v, 2) for k, v in allocated_by_pillar.items()},
        "is_within_limit": total_allocated <= (hours + 0.05),
        "tips": [
            "Take a 5-10 minute rest between intensive coding and architectural design blocks.",
            "Prioritize deep problem solving over volume: master core edge cases thoroughly.",
            "Practice articulating your thought process out loud to simulate real interviews."
        ]
    }


def generate_weekly_timetable(
    availability: Any,
    preferred_slot: str = "Evening (18:00 - 21:00)",
    custom_tasks: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Generates a structured weekly timetable distributing tasks across study blocks:
    - Coding & Problem Solving (35%)
    - Project Architecture (25%)
    - Mock Interviews & Behavioral (20%)
    - Core CS Fundamentals Revision (20%)

    Guarantees:
    - Total allocated study time never exceeds the user's weekly availability.
    - Each day receives a structured daily preparation schedule matching its available hours.
    """
    is_valid, err_msg, cleaned_avail = validate_daily_availability(availability)
    if not is_valid:
        raise ValueError(err_msg)

    total_weekly_hours = sum(cleaned_avail.values())
    selected_slot = preferred_slot if preferred_slot in TIME_SLOTS else TIME_SLOTS[2]

    # Standard starter task pool
    default_task_pool = [
        {"title": "DSA: Arrays, Two-Pointer & Binary Search", "category": "Coding", "hours": 2.0},
        {"title": "Backend API Optimization & Database Schema", "category": "Projects", "hours": 2.0},
        {"title": "STAR Behavioral Stories & Leadership Scenarios", "category": "Interviews", "hours": 1.5},
        {"title": "DBMS Indexing & SQL Query Review", "category": "Revision", "hours": 1.5},
        {"title": "DSA: Dynamic Programming & Recursion", "category": "Coding", "hours": 2.5},
        {"title": "System Design: Cache & Microservices", "category": "Projects", "hours": 2.0},
        {"title": "Technical Mock Interview & Resume Walkthrough", "category": "Interviews", "hours": 1.5},
        {"title": "Operating Systems: Concurrency & Virtual Memory", "category": "Revision", "hours": 1.5},
        {"title": "Computer Networks: TCP/IP & HTTP Protocols", "category": "Revision", "hours": 1.0},
    ]

    tasks_to_allocate = list(custom_tasks) if custom_tasks else list(default_task_pool)
    timetable: Dict[str, List[Dict[str, Any]]] = {day: [] for day in VALID_DAYS}
    day_allocated_hours: Dict[str, float] = {day: 0.0 for day in VALID_DAYS}
    daily_schedules: Dict[str, Dict[str, Any]] = {}

    task_idx = 0
    num_tasks = len(tasks_to_allocate)

    # Distribute tasks across available days without exceeding each day's quota
    for day in VALID_DAYS:
        day_limit = cleaned_avail[day]
        if day_limit > 0:
            daily_schedules[day] = generate_daily_study_schedule(
                daily_hours=day_limit,
                preferred_slot=selected_slot,
                custom_tasks=custom_tasks
            )

        while day_allocated_hours[day] < day_limit and task_idx < num_tasks * 2:
            base_task = tasks_to_allocate[task_idx % num_tasks]
            task_duration = min(base_task.get("hours", 1.5), day_limit - day_allocated_hours[day])
            if task_duration <= 0.25:
                break

            timetable[day].append({
                "id": f"task_{day.lower()}_{len(timetable[day])+1}",
                "title": base_task["title"],
                "category": base_task.get("category", "General"),
                "allocated_hours": round(task_duration, 1),
                "time_slot": selected_slot,
                "status": "pending"
            })
            day_allocated_hours[day] += task_duration
            task_idx += 1

    total_allocated = sum(day_allocated_hours.values())

    return {
        "status": "success",
        "availability": cleaned_avail,
        "total_weekly_hours": total_weekly_hours,
        "total_allocated_hours": round(total_allocated, 1),
        "preferred_slot": selected_slot,
        "timetable": timetable,
        "daily_schedules": daily_schedules,
        "is_within_limit": total_allocated <= (total_weekly_hours + 0.1)
    }


def allocate_daily_study_time(
    available_time: Any,
    preferred_slot: str = "Evening (18:00 - 21:00)",
    custom_tasks: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Unified entry point for Daily Study-Time Allocation.
    Accepts daily hours (e.g. 2.5) or a full weekly mapping, returning a structured
    daily preparation schedule and weekly allocation overview.
    """
    # If a scalar daily study time was supplied
    if isinstance(available_time, (int, float)):
        daily_schedule = generate_daily_study_schedule(
            daily_hours=available_time,
            preferred_slot=preferred_slot,
            custom_tasks=custom_tasks
        )
        weekly = generate_weekly_timetable(
            availability=available_time,
            preferred_slot=preferred_slot,
            custom_tasks=custom_tasks
        )
        return {
            "status": "success",
            "daily_schedule": daily_schedule,
            "weekly_timetable": weekly,
            "daily_hours": daily_schedule["daily_hours"],
            "total_allocated_hours": daily_schedule["total_allocated_hours"],
            "preferred_slot": preferred_slot
        }

    # If a dict was provided
    if isinstance(available_time, dict):
        # Check if single daily hour field present
        for key in ["daily_hours", "daily_study_time", "available_hours", "hours", "study_time"]:
            if key in available_time and available_time[key] is not None:
                val = available_time[key]
                daily_schedule = generate_daily_study_schedule(
                    daily_hours=val,
                    preferred_slot=preferred_slot,
                    custom_tasks=custom_tasks
                )
                weekly = generate_weekly_timetable(
                    availability=available_time,
                    preferred_slot=preferred_slot,
                    custom_tasks=custom_tasks
                )
                return {
                    "status": "success",
                    "daily_schedule": daily_schedule,
                    "weekly_timetable": weekly,
                    "daily_hours": daily_schedule["daily_hours"],
                    "total_allocated_hours": daily_schedule["total_allocated_hours"],
                    "preferred_slot": preferred_slot
                }

        # Otherwise full weekly availability dict
        weekly = generate_weekly_timetable(
            availability=available_time,
            preferred_slot=preferred_slot,
            custom_tasks=custom_tasks
        )
        # Average non-zero day for daily schedule preview
        non_zero_days = [h for h in weekly["availability"].values() if h > 0]
        avg_daily = sum(non_zero_days) / len(non_zero_days) if non_zero_days else 2.0
        daily_schedule = generate_daily_study_schedule(
            daily_hours=avg_daily,
            preferred_slot=preferred_slot,
            custom_tasks=custom_tasks
        )
        return {
            "status": "success",
            "daily_schedule": daily_schedule,
            "weekly_timetable": weekly,
            "daily_hours": round(avg_daily, 1),
            "total_allocated_hours": weekly["total_allocated_hours"],
            "preferred_slot": preferred_slot
        }

    raise ValueError("Invalid availability input: must be a number or dictionary.")
