-- Migration 002: Student Preparation and Engagement Modules
-- Created: 2026-11-06

CREATE TABLE IF NOT EXISTS student_profiles (
    student_id TEXT PRIMARY KEY,
    full_name TEXT,
    email TEXT,
    phone TEXT,
    department TEXT,
    grad_year INTEGER,
    cgpa REAL,
    target_role TEXT,
    target_company TEXT,
    skills_json TEXT,
    linkedin_url TEXT,
    github_url TEXT,
    has_resume_uploaded INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_feedback (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
    category TEXT NOT NULL,
    comment TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS technical_self_assessments (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    category TEXT NOT NULL,
    proficiency_level TEXT NOT NULL,
    years_experience REAL DEFAULT 0,
    notes TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(student_id, skill_name)
);

CREATE TABLE IF NOT EXISTS coding_submissions (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL DEFAULT 'default_student',
    analysis_id TEXT,
    question_title TEXT NOT NULL,
    company_name TEXT NOT NULL DEFAULT 'General',
    language TEXT NOT NULL DEFAULT 'python',
    code TEXT NOT NULL,
    passed INTEGER NOT NULL DEFAULT 0,
    score INTEGER NOT NULL DEFAULT 0,
    tests_passed INTEGER NOT NULL DEFAULT 0,
    total_tests INTEGER NOT NULL DEFAULT 0,
    test_results_json TEXT,
    complexity_analysis TEXT,
    feedback TEXT,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS company_preparation_checklists (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL DEFAULT 'default_student',
    company_name TEXT NOT NULL,
    checklist_json TEXT NOT NULL,
    completion_percentage REAL NOT NULL DEFAULT 0.0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS preparation_calendar_events (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL DEFAULT 'default_student',
    title TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'preparation',
    event_date TEXT NOT NULL,
    event_time TEXT,
    company_name TEXT,
    description TEXT,
    priority TEXT NOT NULL DEFAULT 'Medium',
    completed INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS interview_experiences (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    candidate_name TEXT NOT NULL DEFAULT 'Anonymous Candidate',
    company_name TEXT NOT NULL,
    role_title TEXT NOT NULL,
    interview_date TEXT NOT NULL,
    rounds_json TEXT NOT NULL,
    overall_verdict TEXT NOT NULL DEFAULT 'Offer',
    difficulty_level TEXT NOT NULL DEFAULT 'Medium',
    tips_and_preparation TEXT,
    reported_flag INTEGER NOT NULL DEFAULT 0,
    report_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS email_notification_preferences (
    student_id TEXT PRIMARY KEY,
    email TEXT,
    email_enabled INTEGER NOT NULL DEFAULT 1,
    notify_welcome INTEGER NOT NULL DEFAULT 1,
    notify_application_created INTEGER NOT NULL DEFAULT 1,
    notify_status_change INTEGER NOT NULL DEFAULT 1,
    notify_interview_reminder INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recently_viewed_jobs (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    role_title TEXT NOT NULL,
    location TEXT DEFAULT 'Remote',
    salary_range TEXT,
    apply_url TEXT,
    viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(student_id, job_id)
);

CREATE INDEX IF NOT EXISTS idx_coding_subs_student ON coding_submissions (student_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_tech_assessments_student ON technical_self_assessments (student_id, category);
CREATE INDEX IF NOT EXISTS idx_user_feedback_student ON user_feedback (student_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_calendar_student_date ON preparation_calendar_events (student_id, event_date ASC);
CREATE INDEX IF NOT EXISTS idx_experiences_company ON interview_experiences (company_name, interview_date DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_checklist_student_comp ON company_preparation_checklists (student_id, company_name);
CREATE INDEX IF NOT EXISTS idx_viewed_jobs_student ON recently_viewed_jobs (student_id, viewed_at DESC);
