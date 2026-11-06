-- Migration 001: Initial Core Schema
-- Created: 2026-11-06

CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    resume_filename TEXT,
    company_name TEXT,
    job_description TEXT,
    results_json TEXT,
    student_id TEXT DEFAULT 'default_student',
    version_number INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS interviews (
    id TEXT PRIMARY KEY,
    analysis_id TEXT,
    questions_json TEXT,
    answers_json TEXT,
    evaluations_json TEXT,
    completed INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (analysis_id) REFERENCES analyses (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS batch_comparisons (
    id TEXT PRIMARY KEY,
    resume_filename TEXT,
    companies_list TEXT,
    results_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_applications (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL DEFAULT 'default_student',
    company_name TEXT NOT NULL,
    role_title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Applied',
    applied_date TEXT NOT NULL,
    notes TEXT,
    salary_range TEXT,
    job_type TEXT DEFAULT 'Full-time',
    application_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cohort_benchmarks (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    department TEXT NOT NULL,
    grad_year INTEGER NOT NULL,
    overall_score REAL NOT NULL,
    ats_score REAL NOT NULL,
    analysis_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_analyses_created_at ON analyses (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analyses_student_version ON analyses (student_id, version_number ASC);
CREATE INDEX IF NOT EXISTS idx_interviews_analysis_id ON interviews (analysis_id);
CREATE INDEX IF NOT EXISTS idx_job_applications_student ON job_applications (student_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cohort_overall ON cohort_benchmarks (overall_score DESC);
