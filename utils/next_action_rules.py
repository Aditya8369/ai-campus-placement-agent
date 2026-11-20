"""
Recommended Next Action Rules Engine (#558)
===========================================
Computes the single best recommended next action for a student, chosen by simple,
documented, deterministic rules from existing candidate data:
- Impending application deadline -> Go to application tracker
- Very low ATS score (< 60) -> Fix critical resume bullet points
- Large skill gap (>= 3 missing skills) -> Follow customized learning roadmap
- Active weak topics detected -> Practice focus areas in weak topics notebook
- Stale interview practice (>= 7 days or 0 interviews) -> Start mock interview
- Low recent interview score (< 70) -> Retry interview questions
- Unpracticed coding -> Solve target company DSA problems
- Low aptitude readiness -> Take speed aptitude test
- High readiness maintenance -> Maintain preparation streak
- Brand new user fallback -> Run first placement analysis

Supports up to two alternative actions and a 24-hour "not now" dismissal option.
Zero extra AI calls: fully deterministic and rule-based.
Strictly isolated per student.
"""

from dataclasses import dataclass, field
import datetime
from datetime import timezone, timedelta
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from utils.database import get_db_connection

logger = logging.getLogger(__name__)


@dataclass
class CandidateState:
    """Represents the candidate's current placement preparation posture."""
    student_id: str = "default_student"
    has_analysis: bool = False
    latest_analysis_id: Optional[str] = None
    target_company: str = ""
    target_role: str = ""
    ats_score: Optional[int] = None
    match_percentage: Optional[int] = None
    skill_gaps: List[str] = field(default_factory=list)

    # Job Applications
    has_urgent_deadline: bool = False
    urgent_application_company: str = ""
    urgent_application_role: str = ""
    urgent_deadline_date: Optional[str] = None
    urgent_days_remaining: Optional[int] = None

    # Mock Interviews
    total_interviews: int = 0
    days_since_last_interview: Optional[int] = None  # None if 0 interviews
    last_interview_score: Optional[float] = None

    # Weak Topics
    weak_topic_count: int = 0
    top_weak_topic: Optional[str] = None

    # Coding Practice
    coding_submissions_count: int = 0
    passed_coding_count: int = 0
    has_hard_bookmarks: bool = False

    # Aptitude Practice
    aptitude_attempts: int = 0
    aptitude_accuracy: Optional[float] = None


@dataclass
class RecommendedAction:
    """Represents a recommended action card recommendation."""
    id: str
    title: str
    description: str
    category: str
    badge: str
    badge_class: str
    icon: str
    button_text: str
    button_url: str
    priority: int
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "badge": self.badge,
            "badge_class": self.badge_class,
            "icon": self.icon,
            "button_text": self.button_text,
            "button_url": self.button_url,
            "priority": self.priority,
            "reason": self.reason,
        }


# ============================================================================
# DOCUMENTED RULE EVALUATORS
# ============================================================================

def rule_urgent_application_deadline(state: CandidateState) -> Optional[RecommendedAction]:
    """
    Priority 10: An active application deadline is imminent (<= 3 days).
    Urges candidate to finalize application materials and follow up.
    """
    if not state.has_urgent_deadline:
        return None

    days = state.urgent_days_remaining if state.urgent_days_remaining is not None else 0
    comp = state.urgent_application_company or "Target Company"
    role = state.urgent_application_role or "Role"

    if days <= 0:
        time_desc = "is due today!"
        badge = "Due Today"
    elif days == 1:
        time_desc = "is due tomorrow!"
        badge = "Due Tomorrow"
    else:
        time_desc = f"is due in {days} days."
        badge = f"Due in {days}d"

    return RecommendedAction(
        id="urgent_application_deadline",
        title=f"Upcoming Application Deadline: {comp}",
        description=f"Your application for {role} at {comp} {time_desc} Review your documents and track your submission.",
        category="application",
        badge=badge,
        badge_class="danger",
        icon="fa-clock",
        button_text="Open Application Tracker",
        button_url="/applications",
        priority=10,
        reason=f"Application for {comp} has an imminent deadline.",
    )


def rule_critical_low_ats(state: CandidateState) -> Optional[RecommendedAction]:
    """
    Priority 20: ATS resume score is very low (< 60).
    Candidate's resume risks automatic ATS rejection before recruiter review.
    """
    if not state.has_analysis or state.ats_score is None:
        return None

    if state.ats_score < 60:
        aid = state.latest_analysis_id
        target_url = f"/dashboard/{aid}#bulletRewriterSection" if aid else "/compare-resumes"
        return RecommendedAction(
            id="fix_critical_ats_score",
            title="Improve Low Resume ATS Score",
            description=(
                f"Your ATS score is {state.ats_score}/100. Standard recruitment screeners typically require 70+ "
                "to pass automated screening. Strengthen your bullet points with quantitative impact."
            ),
            category="resume",
            badge="High Impact",
            badge_class="danger",
            icon="fa-file-circle-exclamation",
            button_text="Fix Resume Bullet Points",
            button_url=target_url,
            priority=20,
            reason=f"ATS score ({state.ats_score}/100) is below the 60% passing benchmark.",
        )
    return None


def rule_large_skill_gap(state: CandidateState) -> Optional[RecommendedAction]:
    """
    Priority 30: Large skill gap (>= 3 missing skills for the target role).
    Directs the student to follow the step-by-step weekly learning roadmap.
    """
    if not state.has_analysis or len(state.skill_gaps) < 3:
        return None

    gap_count = len(state.skill_gaps)
    top_skills = ", ".join(state.skill_gaps[:3])
    comp = state.target_company or "your target role"
    aid = state.latest_analysis_id
    target_url = f"/dashboard/{aid}#roadmapSection" if aid else "/dashboard#roadmapSection"

    return RecommendedAction(
        id="follow_skill_gap_roadmap",
        title=f"Close Skill Gaps ({gap_count} Missing)",
        description=(
            f"Your profile is missing key competencies for {comp} ({top_skills}). "
            "Follow your personalized weekly roadmap to acquire these skills."
        ),
        category="skills",
        badge="Recommended",
        badge_class="warning",
        icon="fa-map-location-dot",
        button_text="View Learning Roadmap",
        button_url=target_url,
        priority=30,
        reason=f"{gap_count} missing skills detected in latest analysis.",
    )


def rule_weak_topics_practice(state: CandidateState) -> Optional[RecommendedAction]:
    """
    Priority 40: Candidate has identified weak topics across interviews or coding.
    Directs the student to focus practice on their recurring weak areas.
    """
    if state.weak_topic_count <= 0:
        return None

    topic_str = f" in {state.top_weak_topic}" if state.top_weak_topic else ""
    return RecommendedAction(
        id="practice_weak_topics",
        title=f"Review Weak Focus Areas ({state.weak_topic_count} Found)",
        description=(
            f"You have recurring low scores{topic_str}. Concentrate your preparation on identified weak topics "
            "to maximize score gains."
        ),
        category="practice",
        badge="Focus Area",
        badge_class="warning",
        icon="fa-bullseye",
        button_text="Open Weak Topics Notebook",
        button_url="/weak-topics",
        priority=40,
        reason=f"{state.weak_topic_count} weak topics accumulated across preparation activities.",
    )


def rule_stale_interview_practice(state: CandidateState) -> Optional[RecommendedAction]:
    """
    Priority 50: No mock interview conducted in the last 7 days (or 0 mock interviews).
    Ensures the student maintains verbal interview readiness and STAR communication.
    """
    if not state.has_analysis:
        return None

    is_stale = (
        state.total_interviews == 0
        or state.days_since_last_interview is None
        or state.days_since_last_interview >= 7
    )
    if not is_stale:
        return None

    aid = state.latest_analysis_id
    target_url = f"/interview/{aid}" if aid else "/topic-practice"
    days_txt = (
        "never taken a mock interview"
        if state.total_interviews == 0
        else f"not practiced an interview in {state.days_since_last_interview} days"
    )

    return RecommendedAction(
        id="conduct_mock_interview",
        title="Schedule Mock Technical Interview",
        description=(
            f"You have {days_txt}. Regular mock interviews build confidence, "
            "structure STAR responses, and reduce placement anxiety."
        ),
        category="interview",
        badge="Recommended",
        badge_class="primary",
        icon="fa-headset",
        button_text="Start Mock Interview",
        button_url=target_url,
        priority=50,
        reason="No mock interview practiced within the last 7 days.",
    )


def rule_low_recent_interview_score(state: CandidateState) -> Optional[RecommendedAction]:
    """
    Priority 60: Last interview score was low (< 70).
    Encourages retrying answers and reviewing evaluation feedback.
    """
    if state.last_interview_score is None or state.last_interview_score >= 70.0:
        return None

    score_val = int(state.last_interview_score)
    return RecommendedAction(
        id="retry_interview_responses",
        title="Review & Retry Past Interview Answers",
        description=(
            f"Your most recent mock interview score was {score_val}/100. "
            "Review your feedback, check STAR suggestions, and retry questions to improve."
        ),
        category="interview",
        badge="Review Needed",
        badge_class="primary",
        icon="fa-rotate-left",
        button_text="View Interview History",
        button_url="/interview-history",
        priority=60,
        reason=f"Recent interview score was {score_val}/100 (< 70).",
    )


def rule_unpracticed_coding(state: CandidateState) -> Optional[RecommendedAction]:
    """
    Priority 70: Candidate has solved fewer than 3 DSA problems or has Hard problems waiting.
    """
    if state.passed_coding_count < 3 or state.has_hard_bookmarks:
        desc = (
            "You have difficult coding problems bookmarked. Practice optimal time and space complexity approaches."
            if state.has_hard_bookmarks
            else "Campus technical rounds filter heavily on algorithmic problem solving. Practice curated LeetCode questions."
        )
        return RecommendedAction(
            id="practice_coding_dsa",
            title="Practice Core Coding & Algorithms",
            description=desc,
            category="coding",
            badge="Coding Prep",
            badge_class="info",
            icon="fa-code",
            button_text="Practice DSA",
            button_url="/coding-practice",
            priority=70,
            reason="Fewer than 3 passed coding submissions or bookmarked problems waiting.",
        )
    return None


def rule_aptitude_readiness(state: CandidateState) -> Optional[RecommendedAction]:
    """
    Priority 80: Candidate has 0 aptitude attempts or low accuracy (< 60%).
    """
    if state.has_analysis and (state.aptitude_attempts == 0 or (state.aptitude_accuracy is not None and state.aptitude_accuracy < 60.0)):
        acc_txt = f"accuracy is {int(state.aptitude_accuracy)}%" if state.aptitude_accuracy is not None else "no practice attempts recorded"
        return RecommendedAction(
            id="practice_speed_aptitude",
            title="Sharpen Aptitude & Speed Tests",
            description=(
                f"Your aptitude test {acc_txt}. First-round campus screening tests rely heavily on speed and accuracy."
            ),
            category="aptitude",
            badge="Screening Prep",
            badge_class="info",
            icon="fa-stopwatch",
            button_text="Take Aptitude Test",
            button_url="/aptitude",
            priority=80,
            reason="Aptitude screening accuracy is below 60% or unattempted.",
        )
    return None


def rule_placement_ready_maintain_streak(state: CandidateState) -> Optional[RecommendedAction]:
    """
    Priority 90: Candidate is in great shape (ATS >= 75, recent interview, good score).
    Encourages maintaining preparation consistency and daily habit.
    """
    if state.has_analysis and (state.ats_score or 0) >= 75 and (state.last_interview_score or 0) >= 70:
        return RecommendedAction(
            id="maintain_prep_streak",
            title="Maintain Preparation Consistency & Streak",
            description=(
                "Your profile, interview scores, and ATS benchmarks are in strong shape! "
                "Keep your daily preparation streak active to stay sharp."
            ),
            category="general",
            badge="Well Done",
            badge_class="success",
            icon="fa-fire",
            button_text="View Streak Tracker",
            button_url="/streak",
            priority=90,
            reason="Profile meets high readiness criteria; focus is on consistency.",
        )
    return None


def rule_brand_new_user_fallback(state: CandidateState) -> Optional[RecommendedAction]:
    """
    Priority 15: Default primary action for brand new users with no analysis uploaded yet.
    """
    if not state.has_analysis:
        return RecommendedAction(
            id="run_first_analysis",
            title="Upload Resume for Placement Readiness Audit",
            description=(
                "Welcome! Start by analyzing your resume against target campus recruiters to receive an instant "
                "ATS score, missing skill analysis, and personalized study roadmap."
            ),
            category="getting_started",
            badge="Get Started",
            badge_class="success",
            icon="fa-file-arrow-up",
            button_text="Analyze Resume",
            button_url="/#analysisForm",
            priority=15,
            reason="New user without an existing placement analysis report.",
        )
    return None


def rule_general_cheatsheet_fallback(state: CandidateState) -> Optional[RecommendedAction]:
    """
    Priority 110: Secondary fallback offering company preparation tips and checklists.
    """
    comp = state.target_company or "Target Companies"
    return RecommendedAction(
        id="explore_company_checklist",
        title=f"Review Company Hiring Checklist: {comp}",
        description="Explore interview rounds, typical questions, and hiring patterns for campus recruitment.",
        category="company",
        badge="Tips",
        badge_class="secondary",
        icon="fa-list-check",
        button_text="View Company Checklist",
        button_url="/company-checklist",
        priority=110,
        reason="General preparation and company knowledge building.",
    )


ALL_RULES = [
    rule_urgent_application_deadline,
    rule_critical_low_ats,
    rule_large_skill_gap,
    rule_weak_topics_practice,
    rule_stale_interview_practice,
    rule_low_recent_interview_score,
    rule_unpracticed_coding,
    rule_aptitude_readiness,
    rule_placement_ready_maintain_streak,
    rule_brand_new_user_fallback,
    rule_general_cheatsheet_fallback,
]


def evaluate_next_actions(state: CandidateState) -> Dict[str, Any]:
    """
    Evaluates all rules on the candidate state and returns:
    - 'primary': the single highest priority matching action
    - 'alternatives': up to 2 other matching actions (excluding primary)
    - 'all_matched': full list of matched actions
    """
    matched: List[RecommendedAction] = []
    seen_ids = set()

    for rule_fn in ALL_RULES:
        try:
            action = rule_fn(state)
            if action and action.id not in seen_ids:
                matched.append(action)
                seen_ids.add(action.id)
        except Exception as e:
            logger.warning(f"Error evaluating rule {rule_fn.__name__}: {e}")

    # Sort matching actions by priority (lowest number = highest priority)
    matched.sort(key=lambda a: (a.priority, a.id))

    # Guarantee at least 1 action even in extreme edge cases
    if not matched:
        fallback = rule_brand_new_user_fallback(state) or rule_general_cheatsheet_fallback(state)
        if fallback:
            matched.append(fallback)

    primary = matched[0]
    alternatives = matched[1:3]

    return {
        "primary": primary.to_dict(),
        "alternatives": [a.to_dict() for a in alternatives],
        "all_matched_count": len(matched),
    }


# ============================================================================
# DISMISSAL ("NOT NOW") PERSISTENCE
# ============================================================================

def ensure_dismissals_table() -> None:
    """Ensures student_action_card_dismissals table exists."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS student_action_card_dismissals (
                student_id TEXT PRIMARY KEY,
                dismissed_at TIMESTAMP NOT NULL,
                dismissed_until TIMESTAMP NOT NULL,
                action_id TEXT DEFAULT ''
            )
        """)
        conn.commit()
    except Exception as e:
        logger.error(f"Error creating student_action_card_dismissals table: {e}")
    finally:
        conn.close()


def is_action_card_dismissed(student_id: str) -> Tuple[bool, Optional[str]]:
    """
    Checks if the recommended action card is currently hidden for the student.
    Returns (is_dismissed, dismissed_until_iso).
    """
    ensure_dismissals_table()
    effective_student_id = (student_id or "default_student").strip()
    now_utc = datetime.datetime.now(timezone.utc)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT dismissed_until, action_id
            FROM student_action_card_dismissals
            WHERE student_id = ?
        """, (effective_student_id,))
        row = cursor.fetchone()
        if not row:
            return False, None

        until_str = row["dismissed_until"]
        try:
            # Parse ISO or SQLite timestamp
            clean_str = until_str.replace("Z", "+00:00")
            if "+" not in clean_str:
                until_dt = datetime.datetime.fromisoformat(clean_str).replace(tzinfo=timezone.utc)
            else:
                until_dt = datetime.datetime.fromisoformat(clean_str)

            if now_utc < until_dt:
                return True, until_dt.isoformat()
            return False, None
        except Exception:
            return False, None
    except Exception as e:
        logger.error(f"Error checking action dismissal for {effective_student_id}: {e}")
        return False, None
    finally:
        conn.close()


def dismiss_action_card(student_id: str, hours: int = 24, action_id: str = "") -> datetime.datetime:
    """
    Hides the recommended action suggestion for the given duration (default 24 hours).
    Returns the expiry datetime in UTC.
    """
    ensure_dismissals_table()
    effective_student_id = (student_id or "default_student").strip()
    now_utc = datetime.datetime.now(timezone.utc)
    until_utc = now_utc + timedelta(hours=hours)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO student_action_card_dismissals (
                student_id, dismissed_at, dismissed_until, action_id
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(student_id) DO UPDATE SET
                dismissed_at = excluded.dismissed_at,
                dismissed_until = excluded.dismissed_until,
                action_id = excluded.action_id
        """, (effective_student_id, now_utc.isoformat(), until_utc.isoformat(), action_id))
        conn.commit()
    except Exception as e:
        logger.error(f"Error dismissing action card for {effective_student_id}: {e}")
    finally:
        conn.close()

    return until_utc


def undismiss_action_card(student_id: str) -> None:
    """Clears any active dismissal for a student."""
    ensure_dismissals_table()
    effective_student_id = (student_id or "default_student").strip()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM student_action_card_dismissals WHERE student_id = ?", (effective_student_id,))
        conn.commit()
    except Exception as e:
        logger.error(f"Error undismissing action card for {effective_student_id}: {e}")
    finally:
        conn.close()


# ============================================================================
# STATE LOADER FROM DATABASE
# ============================================================================

def _parse_date(date_str: Optional[str]) -> Optional[datetime.date]:
    """Helper to parse varied date string formats safely."""
    if not date_str:
        return None
    try:
        clean = str(date_str).strip()
        if "T" in clean:
            clean = clean.split("T")[0]
        if " " in clean:
            clean = clean.split(" ")[0]
        return datetime.date.fromisoformat(clean)
    except Exception:
        return None


def load_student_candidate_state(
    student_id: str,
    analysis_record: Optional[Dict[str, Any]] = None
) -> CandidateState:
    """
    Loads candidate metrics from stored database tables for student_id.
    Strictly isolated per user; zero extra AI calls.
    """
    effective_student_id = (student_id or "default_student").strip()
    state = CandidateState(student_id=effective_student_id)
    today = datetime.date.today()

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 1. Latest Analysis
        rec = analysis_record
        if not rec:
            cursor.execute("""
                SELECT id, company_name, target_role, results_json, created_at
                FROM analyses
                WHERE student_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
            """, (effective_student_id,))
            row = cursor.fetchone()
            if row:
                rec = dict(row)

        if rec:
            state.has_analysis = True
            state.latest_analysis_id = rec.get("id")
            state.target_company = rec.get("company_name", "")
            state.target_role = rec.get("target_role", "")

            # Parse results JSON
            res = rec.get("results_dict")
            if not res and rec.get("results_json"):
                try:
                    res = json.loads(rec["results_json"])
                except Exception:
                    res = {}
            if not isinstance(res, dict):
                res = {}

            # ATS Score
            resume_analysis = res.get("resume_analysis") or {}
            ats_val = resume_analysis.get("ats_score") or res.get("ats_score")
            if ats_val is not None:
                try:
                    state.ats_score = int(ats_val)
                except Exception:
                    pass

            # Match Percentage
            job_match = res.get("job_match") or {}
            match_val = job_match.get("match_percentage") or res.get("match_score")
            if match_val is not None:
                try:
                    state.match_percentage = int(match_val)
                except Exception:
                    pass

            # Missing Skills / Skill Gaps
            skills_found = []
            for item in res.get("skill_gap") or []:
                if isinstance(item, dict):
                    sk = item.get("missing_skill") or item.get("skill")
                    if sk:
                        skills_found.append(str(sk).strip())
                elif isinstance(item, str) and item.strip():
                    skills_found.append(item.strip())
            for sk in job_match.get("missing_skills") or []:
                if isinstance(sk, str) and sk.strip() and sk.strip() not in skills_found:
                    skills_found.append(sk.strip())

            state.skill_gaps = skills_found

        # 2. Urgent Application Deadlines
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='job_applications'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(job_applications)")
            app_cols = {col[1] for col in cursor.fetchall()}
            if "deadline_date" in app_cols:
                cursor.execute("""
                    SELECT company_name, role_title, deadline_date
                    FROM job_applications
                    WHERE student_id = ?
                      AND deadline_date IS NOT NULL
                      AND deadline_date != ''
                      AND LOWER(status) NOT IN ('rejected', 'offer_accepted', 'withdrawn')
                    ORDER BY deadline_date ASC
                """, (effective_student_id,))
                app_rows = cursor.fetchall()
                for a_row in app_rows:
                    d_parsed = _parse_date(a_row["deadline_date"])
                    if d_parsed:
                        delta = (d_parsed - today).days
                        # Deadline is considered urgent if within next 3 days (or overdue)
                        if delta <= 3:
                            state.has_urgent_deadline = True
                            state.urgent_application_company = a_row["company_name"]
                            state.urgent_application_role = a_row["role_title"]
                            state.urgent_deadline_date = a_row["deadline_date"]
                            state.urgent_days_remaining = max(0, delta)
                            break

        # 3. Mock Interviews & Last Interview Activity
        cursor.execute("""
            SELECT i.id, i.answers_json, i.completed, a.created_at as analysis_date
            FROM interviews i
            JOIN analyses a ON i.analysis_id = a.id
            WHERE a.student_id = ?
            ORDER BY a.created_at DESC, i.id DESC
        """, (effective_student_id,))
        interview_rows = cursor.fetchall()

        # Also check custom_topic_practice_sessions
        topic_practice_rows = []
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='custom_topic_practice_sessions'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT created_at, score
                FROM custom_topic_practice_sessions
                WHERE student_id = ?
                ORDER BY created_at DESC
            """, (effective_student_id,))
            topic_practice_rows = cursor.fetchall()

        total_int = len(interview_rows) + len(topic_practice_rows)
        state.total_interviews = total_int

        # Find most recent date and score
        recent_dates = []
        for ir in interview_rows:
            d = _parse_date(ir["analysis_date"])
            if d:
                recent_dates.append(d)
                # Compute score if present
                try:
                    answers = json.loads(ir["answers_json"] or "[]")
                    for ans in answers:
                        sc = (ans.get("evaluation") or {}).get("score")
                        if sc is not None and state.last_interview_score is None:
                            state.last_interview_score = float(sc)
                except Exception:
                    pass
        for tpr in topic_practice_rows:
            d = _parse_date(tpr["created_at"])
            if d:
                recent_dates.append(d)
                if tpr["score"] is not None and state.last_interview_score is None:
                    state.last_interview_score = float(tpr["score"])

        if recent_dates:
            most_recent = max(recent_dates)
            state.days_since_last_interview = max(0, (today - most_recent).days)

        # 4. Coding Submissions & Hard Bookmarks
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='coding_submissions'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT COUNT(*), SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END)
                FROM coding_submissions
                WHERE student_id = ?
            """, (effective_student_id,))
            row = cursor.fetchone()
            if row:
                state.coding_submissions_count = row[0] or 0
                state.passed_coding_count = row[1] or 0

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bookmarked_coding_questions'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT problem_data FROM bookmarked_coding_questions WHERE student_id = ?
            """, (effective_student_id,))
            b_rows = cursor.fetchall()
            for br in b_rows:
                try:
                    pdata = json.loads(br["problem_data"] or "{}")
                    if str(pdata.get("difficulty") or "").strip().lower() == "hard":
                        state.has_hard_bookmarks = True
                        break
                except Exception:
                    pass

        # 5. Weak Topics Count
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='student_weak_topic_statuses'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT topic_key, status FROM student_weak_topic_statuses WHERE student_id = ? AND status != 'resolved'
            """, (effective_student_id,))
            w_rows = cursor.fetchall()
            state.weak_topic_count = len(w_rows)
            if w_rows:
                state.top_weak_topic = w_rows[0]["topic_key"].replace("_", " ").title()

        # 6. Aptitude Summary
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='aptitude_evaluations'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT COUNT(*), AVG(percentage) FROM aptitude_evaluations WHERE student_id = ?
            """, (effective_student_id,))
            apt_row = cursor.fetchone()
            if apt_row:
                state.aptitude_attempts = apt_row[0] or 0
                state.aptitude_accuracy = float(apt_row[1]) if apt_row[1] is not None else None

    except Exception as e:
        logger.error(f"Error loading candidate state for {effective_student_id}: {e}")
    finally:
        conn.close()

    return state


def get_recommended_action_card_data(
    student_id: str,
    analysis_record: Optional[Dict[str, Any]] = None,
    force_show: bool = False
) -> Dict[str, Any]:
    """
    Main entry point for generating the dashboard recommended action card.
    Respects 24-hour dismissal unless force_show=True.
    """
    is_dismissed, dismissed_until = is_action_card_dismissed(student_id)

    if is_dismissed and not force_show:
        return {
            "is_dismissed": True,
            "dismissed_until": dismissed_until,
            "primary": None,
            "alternatives": [],
            "student_id": student_id,
        }

    state = load_student_candidate_state(student_id=student_id, analysis_record=analysis_record)
    result = evaluate_next_actions(state)

    return {
        "is_dismissed": False,
        "dismissed_until": None,
        "primary": result["primary"],
        "alternatives": result["alternatives"],
        "student_id": student_id,
        "state_summary": {
            "has_analysis": state.has_analysis,
            "ats_score": state.ats_score,
            "has_urgent_deadline": state.has_urgent_deadline,
            "days_since_interview": state.days_since_last_interview,
            "skill_gaps_count": len(state.skill_gaps),
        }
    }
