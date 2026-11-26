# AI Campus Placement Agent - Architecture & System Design

This document details the software architecture, data flow, multi-agent AI execution pipelines, interview session state machine, and core database schema of the **AI Campus Placement Agent**.

---

## 1. High-Level System Architecture

The application is structured into a modular Flask multi-blueprint service interacting with specialized AI agents, local SQLite persistence with migrations, and a responsive frontend template system.

```mermaid
flowchart TD
    Client["Web Browser / Client API"] -->|HTTP / REST| BlueprintRouter["Flask App & Blueprints (routes/)"]

    subgraph Blueprints["Routing Layer (routes/)"]
        AuthBP["auth.py"]
        AnalysisBP["analysis.py"]
        InterviewBP["interview.py"]
        CodingBP["coding_practice.py"]
        TrackerBP["tracker.py"]
        JobsBP["jobs.py"]
        ReportsBP["reports.py"]
        AdminBP["admin.py"]
    end

    BlueprintRouter --> Blueprints

    subgraph Middleware["Security & Middleware"]
        CSRF["utils/csrf.py"]
        RateLimiter["utils/rate_limiter.py"]
        AuthSession["auth_sessions & require_login"]
        PIIRedactor["utils/pii_redactor.py"]
        PromptSec["utils/prompt_security.py"]
    end

    Blueprints --> Middleware

    subgraph Agents["Multi-Agent AI Pipeline (agents/)"]
        Coordinator["CoordinatorAgent (coordinator.py)"]
        ResumeAgent["ResumeAgent (resume_agent.py)"]
        InterviewAgent["InterviewAgent (interview_agent.py)"]
        CodingAgent["CodingAgent (coding_agent.py)"]
        RolePrepAgent["RolePrepAgent (role_prep_agent.py)"]
        RoadmapAgent["RoadmapAgent (roadmap_agent.py)"]
        STARAgent["STARAgent (star_agent.py)"]
    end

    Blueprints --> Agents
    Agents -->|Structured JSON / Prompts| GeminiClient["Gemini LLM API (utils/gemini.py)"]

    subgraph Storage["Persistence & Cache"]
        DB[(SQLite Database)]
        DBMigrations["db/migrations.py & utils/database.py"]
        AnalysisCache["utils/analysis_cache.py"]
        StaticData["data/*.json (companies, questions)"]
    end

    Blueprints --> Storage
    Agents --> Storage
```

---

## 2. Request Flow: Resume Analysis to Dashboard

When a student uploads a resume (PDF, DOCX, or plain text) along with a target company and job description, the system validates the input, extracts content, executes the coordinator agent, and persists the analysis.

```mermaid
sequenceDiagram
    autonumber
    actor Student as Student / User
    participant Route as routes/analysis.py<br/>(upload_resume / analyze_async)
    participant Reader as utils/pdf_reader.py &<br/>utils/format_checker.py
    participant Redactor as utils/pii_redactor.py &<br/>utils/prompt_security.py
    participant Coordinator as agents/coordinator.py<br/>(CoordinatorAgent)
    participant Gemini as utils/gemini.py<br/>(call_gemini_with_retry)
    participant DB as utils/database.py<br/>(analyses & student_profiles)
    participant Dashboard as templates/dashboard.html

    Student->>Route: POST /upload (resume_file, company, job_description)
    Route->>Reader: Extract text & validate file format (size, extension, MIME)
    Reader-->>Route: Clean resume plain text
    Route->>Redactor: Check prompt injection & redact personal contact PII
    Redactor-->>Route: Sanitized & boundary-encapsulated text
    Route->>Coordinator: analyze(resume_text, job_desc, company_name)
    Coordinator->>Coordinator: Standardize resume sections & load data/companies.json
    Coordinator->>Gemini: Execute structured prompt (ANALYSIS_SYSTEM_INSTRUCTION)
    Gemini-->>Coordinator: Validated JSON analysis response
    Coordinator-->>Route: Structured analysis dictionary
    Route->>DB: save_analysis(analysis_id, student_id, results_dict)
    DB-->>Route: Record saved (analysis_id)
    Route-->>Student: 302 Redirect to /dashboard/<analysis_id>
    Student->>Route: GET /dashboard/<analysis_id>
    Route->>DB: get_analysis(analysis_id)
    DB-->>Route: Analysis record & metrics
    Route->>Dashboard: Render dashboard.html with scores, gaps, and roadmap
    Dashboard-->>Student: Interactive Dashboard UI
```

---

## 3. The Agent Pipeline & Specialization

The platform uses a coordinated multi-agent model governed by `CoordinatorAgent`. Each agent handles a distinct dimension of candidate evaluation:

```mermaid
flowchart LR
    Input["Candidate Resume & Job Description"] --> Coord["CoordinatorAgent<br/>(agents/coordinator.py)"]

    subgraph AgentPipeline["Agent Pipeline"]
        Coord --> ResumeAg["ResumeAgent<br/>(agents/resume_agent.py)<br/>• ATS Score<br/>• Formatting Checks<br/>• Section Completeness"]
        Coord --> RolePrepAg["RolePrepAgent<br/>(agents/role_prep_agent.py)<br/>• Skill Gap Extraction<br/>• Matched vs Missing Skills<br/>• Keyword Overlap"]
        Coord --> RoadmapAg["RoadmapAgent<br/>(agents/roadmap_agent.py)<br/>• 4-Week Study Plan<br/>• Topic Prioritization<br/>• Daily Action Items"]
        Coord --> InterviewAg["InterviewAgent<br/>(agents/interview_agent.py)<br/>• Tailored Question Bank<br/>• STAR Behavioral Prompts<br/>• Technical Deep Dives"]
        Coord --> BulletAg["BulletAgent<br/>(agents/bullet_agent.py)<br/>• Action-Verb Rewrites<br/>• Metric & Impact Boosts"]
    end

    ResumeAg --> Aggregator["Result Aggregator & Validator<br/>(agents/coordinator_schema.py)"]
    RolePrepAg --> Aggregator
    RoadmapAg --> Aggregator
    InterviewAg --> Aggregator
    BulletAg --> Aggregator

    Aggregator --> Output["Structured Assessment JSON<br/>(Persisted to analyses table)"]
```

---

## 4. Mock Interview Session Lifecycle

Mock interviews allow students to test their readiness against company-tailored questions with real-time STAR evaluation and session resumption.

```mermaid
stateDiagram-v2
    [*] --> Initialized: Start / Resume Interview (/interview/<analysis_id>)
    
    Initialized --> InProgress: Load Questions & Set Timer
    
    state InProgress {
        [*] --> Answering: Display Question & Record Audio/Text
        Answering --> CheckpointSaved: Auto-save draft (/api/interview/recovery/checkpoint)
        CheckpointSaved --> Answering: Continue Editing
        Answering --> Submitting: Submit Answer (/interview/<analysis_id>/submit)
        Submitting --> Evaluating: InterviewAgent STAR Evaluation
        Evaluating --> FeedbackDisplayed: Score, Strengths & Improvements Shown
        FeedbackDisplayed --> NextQuestion: Advance to Next Question
        NextQuestion --> Answering: More Questions Exist
    }

    InProgress --> Paused: Student pauses (/api/interview/<session_id>/pause)
    Paused --> InProgress: Student resumes (/api/interview/<session_id>/resume)

    InProgress --> Completed: All Questions Answered & Evaluated
    Completed --> Archived: Saved to interviews table
    Archived --> Exported: Download PDF Transcript (/download/interview-transcript/<id>)
    Archived --> [*]
```

---

## 5. Main Database Tables & Schema Relationships

All application state is maintained in SQLite via `utils/database.py` and versioned migrations in `db/migrations.py`.

```mermaid
erDiagram
    users ||--o{ auth_sessions : "has active sessions"
    users ||--o{ analyses : "owns resume analyses"
    users ||--o{ job_applications : "tracks job pipeline"
    users ||--o{ student_profiles : "maintains academic profile"
    users ||--o{ student_streaks : "accumulates prep streak"
    
    analyses ||--o| interviews : "generates mock interview"
    analyses ||--o{ analysis_annotations : "receives annotations"
    analyses ||--o{ cohort_benchmarks : "benchmarks peer score"

    users {
        string id PK
        string name
        string email UK
        string password_hash
        integer is_active
        string role
        integer is_verified
        timestamp created_at
    }

    auth_sessions {
        string id PK
        string user_id FK
        string token_hash UK
        string client_label
        real created_at
        real last_seen_at
        real revoked_at
    }

    analyses {
        string id PK
        string student_id FK
        string resume_filename
        string company_name
        string target_role
        integer version_number
        text results
        timestamp created_at
    }

    interviews {
        string id PK
        string analysis_id FK
        text questions_json
        text user_answers
        text evaluations
        integer completed
        timestamp created_at
    }

    job_applications {
        string id PK
        string student_id FK
        string company_name
        string role_title
        string status
        string application_date
        text notes
    }

    student_profiles {
        string student_id PK
        string full_name
        real cgpa
        integer backlogs
        string branch
        string college
        string target_role
        string target_company
    }

    admin_user_audit_logs {
        string id PK
        string admin_id
        string action
        string target_user_id
        string target_email
        text details
        string ip_address
        timestamp created_at
    }

    feature_flags {
        string key PK
        string description
        integer is_enabled
        integer rollout_percentage
        timestamp updated_at
    }
```

---

## 6. Directory Structure & Key Modules

| Path | Primary Responsibility |
| :--- | :--- |
| `app.py` | Application factory and server entrypoint (`create_app()`). |
| `routes/` | Modular Flask Blueprints: `auth.py`, `analysis.py`, `interview.py`, `tracker.py`, `admin.py`, `jobs.py`, `reports.py`. |
| `agents/` | Multi-agent AI core: `coordinator.py`, `resume_agent.py`, `interview_agent.py`, `coding_agent.py`, `roadmap_agent.py`. |
| `utils/` | Shared utilities: `gemini.py`, `database.py`, `feature_flags.py`, `pii_redactor.py`, `csrf.py`, `rate_limiter.py`. |
| `db/` | Database migration engine: `migrations.py` with versioned schema tracking. |
| `data/` | Static reference datasets: `companies.json`, `interview_questions.json`, `role_templates.json`, `schemas/`. |
| `templates/` | Jinja2 templates: `dashboard.html`, `interview.html`, `admin_users.html`, `admin_feature_flags.html`. |
| `static/` | Frontend assets: CSS, modular JavaScript (`static/js/modules/`), and icons. |
| `tests/` | Pytest automated test suites covering all routes, agents, schemas, and security controls. |
