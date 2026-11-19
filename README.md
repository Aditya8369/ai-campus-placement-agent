# AI Campus Placement Agent

# This project is a part of Nexus Spring of Code (NSoC) 2026 - Winter Edition
> 
[![CI](https://github.com/deepikagandla74/ai-campus-placement-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/deepikagandla74/ai-campus-placement-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI Workflow](https://github.com/deepikagandla74/ai-campus-placement-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/deepikagandla74/ai-campus-placement-agent/actions/workflows/ci.yml)
[![Open Source](https://img.shields.io/badge/Open%20Source-Yes-success.svg)](https://github.com/deepikagandla74/ai-campus-placement-agent)
[![Contributors](https://img.shields.io/badge/contributors-welcome-orange.svg)](CONTRIBUTING.md)

An AI-powered multi-agent assistant that helps students prepare for campus placements through resume analysis, job matching, personalized learning roadmaps, skill gap analysis, and interactive mock interviews.

This is an independently developed open-source application.

---

## Why is this an AI Agent System (and NOT a Chatbot)?

A typical chatbot operates as a single-turn or multi-turn conversational loop, where a single large language model (LLM) responds directly to user queries. 

In contrast, the **AI Campus Placement Agent** implements a **Coordinated Multi-Agent Architecture**:
1. **Orchestrated Workflow**: A single, central `CoordinatorAgent` receives the initial workspace context (resume, target job description, target company profiles).
2. **Task Delegation**: The coordinator executes a single structured LLM call to save token costs and prevent rate-limiting, and then delegates the resulting data subsets to specialized sub-agents.
3. **Dedicated Domain Responsibilities**: Each specialized agent is modeled as an independent Python class focusing on a single task:
   * **ResumeAgent**: Evaluates ATS formatting, experiences, strengths, and suggests grammar improvements.
   * **JobMatchAgent**: Performs keyword extraction and evaluates match percentages against the target role.
   * **SkillGapAgent**: Maps missing skills into an actionable table showing learning times, importance, and priority.
   * **RoadmapAgent**: Generates a custom 6-week curriculum with topic deep-dives and estimated study hours.
   * **InterviewAgent**: Generates tailored interview questions and handles dynamic, real-time responses scoring technical accuracy and communication.

---

## System Architecture & Workflow

```mermaid
graph TD
    User([Student User]) -->|Uploads PDF Resume / Pastes Job Desc / Selects Company| FlaskApp[Flask Web Server]
    FlaskApp -->|Launches Analysis| Coord[CoordinatorAgent]
    Coord -->|Infects static profiles| StaticData[(data/companies.json)]
    Coord -->|Single Structured JSON Request| GeminiAPI[Gemini 3.5 / 2.5 API]
    GeminiAPI -->|Structured JSON Response| Coord
    
    %% Coordinator delegation
    Coord -->|Resume Block| ResumeAgent[ResumeAgent]
    Coord -->|Job Match Block| JobMatchAgent[JobMatchAgent]
    Coord -->|Skill Gap Block| SkillGapAgent[SkillGapAgent]
    Coord -->|Roadmap Block| RoadmapAgent[RoadmapAgent]
    Coord -->|Interview Questions Block| InterviewAgent[InterviewAgent]
    
    %% Outputs
    ResumeAgent -->|Validated ATS Feedback| CombinedResult[Coordinated Payloads]
    JobMatchAgent -->|Match Percentage & Top 5 Changes| CombinedResult
    SkillGapAgent -->|Structured Missing Skills Table| CombinedResult
    RoadmapAgent -->|6-Week Syllabus Accordion| CombinedResult
    InterviewAgent -->|15 Dynamic Practice Questions| CombinedResult
    
    CombinedResult -->|Store Results| Database[(SQLite DB)]
    Database -->|Render UI Views| DashUI[Dashboard View]
    
    %% Dynamic Interview Flow
    User -->|Submits Answer| LiveInterview[Live Interview Simulator]
    LiveInterview -->|Evaluates Answer & Next Q| InterviewAgent
    InterviewAgent -->|API Evaluation Call| GeminiAPI
    
    %% Report Download
    User -->|Request PDF Download| PDFReport[ReportLab PDF Compiler]
    PDFReport -->|Generates Report| User
```

### Architectural Highlights

The system is engineered as a modular, decoupled pipeline designed for efficiency, resilience, and privacy:

1. **Coordinator Multi-Agent Pattern**:
   Instead of launching fragmented, repetitive LLM calls for each capability, the `CoordinatorAgent` compiles the candidate's resume text, target role requirements, and recruiter profiles into a single structured prompt. It performs one optimized call to the Gemini model, validates the payload schema, and safely decomposes the structured response into specialized sub-agents:
   - **ResumeAgent**: Evaluates ATS formatting, experiences, strengths, grammar issues, and computes an objective placement score.
   - **JobMatchAgent**: Extracts technical and domain skills, cross-referencing candidate profile keywords against job descriptions to identify matches and critical omissions.
   - **SkillGapAgent**: Prioritizes missing competencies, estimating required study hours and mapping learning resources.
   - **RoadmapAgent**: Constructs an adaptive 6-week week-by-week placement syllabus with concrete milestones.
   - **InterviewAgent**: Generates technical and behavioral question banks and powers the real-time dynamic interview evaluator.

2. **Resilient AI Gateway (`utils/gemini.py`)**:
   - Outbound API calls are wrapped in an automated retry handler with exponential backoff and randomized jitter to mitigate HTTP 429 quota exhaustion and transient 5xx server errors.
   - Strict schema validation and defensive JSON parsing prevent malformed model responses from crashing downstream agents.

3. **Privacy-First Data Flow**:
   - **Automated PII Redaction**: Strips sensitive personal identifiers (phone numbers, email addresses, street addresses) before sending resume content to external AI models.
   - **Local Persistence Only**: Analyses and practice sessions are stored locally in SQLite (`data/campus_agent.db`); uploaded resumes are stored temporarily in `uploads/` and can be cleaned up on demand.

4. **Document Validation & Security Controls**:
   - True byte-level magic signature checks (`%PDF-` for PDF, `PK\x03\x04` for Word `.docx`) reject disguised binaries and corrupted uploads.
   - In-memory sliding-window rate limiting prevents API quota exhaustion.
   - Cryptographic CSRF tokens and hardened session cookies (`HttpOnly`, `SameSite=Lax`) safeguard student sessions.

---

## Features

1. **Resume Analysis & ATS Scoring**: Extract text from PDF resumes, run grammar & style checks, identify weaknesses, and calculate a grounded ATS Score.
2. **Job Description Matching & In-Context Resume Keyword Highlighter**: Paste a Job Description to compare candidate metrics against corporate requirements, listing the exact changes needed to pass initial screenings. Inspect in-context keyword highlights across extracted resume text with whole-word matching, toggleable highlight styling, and a separate breakdown of missing keywords mapped to suggested resume sections (Skills, Projects, Experience).
3. **Skill Gap Remediation Table**: Get a prioritizing list of missing skills detailing estimated learning times, resource links, and custom project suggestions.
4. **6-Week Study Roadmap**: Access a weekly preparation calendar mapping theoretical topics, coding challenges, and revision items.
5. **Interactive Mock Interview Simulator & Timed Answer Mode**: Engage in a live, conversational chat with the Interview Agent. Answers are evaluated dynamically on technical accuracy, communication style, verbal clarity, and STAR story structure. Practice under realistic exam conditions with optional **Timed Answer Mode** featuring per-question countdowns, configurable time limits (Technical, Behavioral, HR), last-15-second visual and screen-reader accessible warnings (`aria-live`), automatic submission on expiration, and pacing telemetry included in feedback and transcripts. Keep untimed mode by default.
6. **Static Company Profiles**: Contains pre-cached interview processes, hiring guidelines, eligibility patterns, and preparation advice for 15 top campus recruiters: Google, Microsoft, Amazon, Adobe, Flipkart, Zoho, TCS, Infosys, Accenture, Capgemini, Wipro, Cognizant, Deloitte, HCLTech, and Tech Mahindra.
7. **Comprehensive PDF Reports**: Generates and compiles a formatted, multi-page PDF document summarizing placement analysis and roadmaps using ReportLab.
8. **Dark / Light Theme Toggle**: Seamless single-click switching between light and dark modes with zero page reload, browser persistence (`localStorage`), default system preference detection (`prefers-color-scheme`), and high-contrast readability across dashboards, tables, interview chat, and study roadmaps.
9. **Placement Analysis History & Data Management**: Browse past evaluations ordered newest first, view target company, target role, and ATS scores, reopen past analyses in the dashboard view without running new AI calls, and delete stored analyses and personal data with confirmation.
10. **Privacy Notice & Consent Protection**: Transparent plain-language privacy notice (`/privacy`), required candidate consent before processing resume text via the Gemini API, optional PII redaction (masking emails, phones, and addresses), local SQLite storage, and complete account deletion options.
11. **'Try with a Sample Resume' Demo Mode**: Explore the full platform capabilities instantly without registration, login, or a Gemini API key. Loads a bundled, fictional candidate profile (Alex Chen, BS in CS from UC Berkeley) targeting a Google Software Development Engineer (SDE 1) position with pre-calculated ATS scoring, skill evidence mapping, and a 6-week preparation roadmap. A prominent "Demo data" banner marks all demo content, and demo results are never persisted to any user history or real database records.
12. **'Tell Me About Yourself' Introduction Builder & Practice Coach**: Generates tailored elevator pitch scripts from verified resume projects and target role/company context in three standard durations: 30 seconds (~65-85 words), 60 seconds (~130-160 words), and 90 seconds (~190-230 words) based on a 140 wpm conversational speaking rate. Features live-updating speaking time estimation as the text is edited, Present &rarr; Past &rarr; Future framework guidance, strict integrity enforcement against fabricating achievements not present in the resume, and an interactive practice coach that scores structure, clarity, and pacing.
13. **Timed Aptitude Practice Module**: Prepare for online campus recruitment screening tests with timed practice sets (`/aptitude`). Features a curated, original question bank (`data/aptitude_questions.json`) spanning **Quantitative Aptitude**, **Logical Reasoning**, and **Verbal Ability**. Supports full 15-minute comprehensive tests and 10-minute sectional drills, visible countdown timers with accessible time warnings, automatic submission upon timeout, and complete scorecards featuring per-topic accuracy, step-by-step mathematical/logical explanations, and weak topic identification (<60% accuracy) displayed on the student dashboard.
14. **Campus Group Discussion (GD) Practice & AI Feedback Coach**: Master high-stakes campus placement GD rounds with an interactive practice module (`/group-discussion`). Access curated topics across **Current Affairs**, **Technology**, and **Abstract** categories, spin for random topics, write 150–250 word contributions (Opening Statement, Rebuttal, or Conclusion), and receive comprehensive multi-criteria AI feedback scoring **Content**, **Structure**, **Balance**, and **Clarity** (0–100 each). Includes high-impact alternative opening statements, key missed counter-points / blind spots, concrete strengths and improvement areas, resilient deterministic fallback evaluation, and longitudinal practice history tracking in SQLite.
15. **CTC to In-Hand Salary & Offer Comparison Calculator**: Demystifies multi-component campus placement offers by breaking down headline CTC figures into guaranteed monthly take-home pay. Evaluates fixed pay, variable incentives, joining bonuses, and employer PF across up to three offers side-by-side. Deductions are calculated using a clearly labeled, configurable assumption set stored in `data/salary_calculator_assumptions.json` (EPF @ 12% of basic, professional tax @ ₹200/mo, standard deduction of ₹75,000, and New Tax Regime slabs with Section 87A rebate and 4% cess). Highlights the Highest Monthly In-Hand Pay and Highest Guaranteed Pay to prevent students from being misled by inflated variable bonuses, rejects negative/invalid inputs, and includes a prominent disclaimer that calculations are estimates and not certified tax advice.

---

## Feature Walkthrough & Screenshots

Here is a visual walkthrough of the core placement preparation modules:

### 1. AI Resume Dashboard & ATS Scoring
Comprehensive placement readiness dashboard displaying overall ATS match score, keyword match percentage, detected strengths, and actionable resume formatting suggestions.
![AI Resume Dashboard & ATS Scoring](docs/screenshots/dashboard-ats-analysis.svg)

#### ATS Resume Scoring Rules & Section-Wise Breakdown (#494)

The platform evaluates resumes using a **100% deterministic recruitment scoring model** out of a fixed **100-point total**. By relying on objective parsing rules rather than variable LLM temperatures, **the same resume always receives the exact same score**, while AI is reserved strictly for targeted bullet rewrites and fix suggestions.

##### Section Weights (100 Points Total)

| Section | Max Points | Evaluation Criteria |
| :--- | :---: | :--- |
| **Contact Information** | 15 pts | Valid email (+4), phone number (+4), LinkedIn profile link (+4), and GitHub / portfolio link (+3). |
| **Professional Summary** | 10 pts | Section presence (+3), ideal length of 20–120 words (+3), role intent & career focus (+2), and key technology highlights (+2). |
| **Technical Skills** | 20 pts | Section presence (+4), technical breadth (&ge;10 skills: +8; &ge;6 skills: +6; &ge;3 skills: +4), structured categorization into Languages, Frameworks, and Tools (+4), and tech stack diversity (+4). |
| **Work Experience & Internships** | 20 pts | Section presence (+4), explicit role titles (+4), dynamic action verbs in bullets (+5), quantified achievements & scale metrics (+4), and duration timelines (+3). |
| **Projects & Portfolio** | 20 pts | Section presence (+4), multiple distinct projects (&ge;2 projects: +5), explicit tech stack per project (+4), implementation action verbs (+4), and live links or measurable outcomes (+3). |
| **Education & Qualifications** | 15 pts | Section presence (+4), degree title specified (+4), recognized university or institution (+4), and graduation year / CGPA (+3). |

##### Core Resume Basics Hygiene Checks

In addition to section scores, the engine checks four fundamental resume hygiene basics:
- **Action Verbs**: Verifies that experience and project bullet points lead with dynamic power verbs (e.g. *Architected*, *Engineered*, *Optimized*, *Spearheaded*) rather than passive phrasing (*Responsible for*, *Helped with*). Passing requires at least 4 unique action verbs.
- **Quantified Achievements**: Scans for numbers, percentages, latency improvements, user scale (e.g. *improved throughput by 25%*, *5,000+ jobs/min*), and business outcomes. Passing requires at least 2 quantified metrics.
- **Consistent Dates**: Evaluates timeline formatting consistency across education and experience (e.g., standardizing on *Month Year – Month Year* or *Year – Year*) without mixing conflicting notation styles.
- **Resume Length**: Measures word count against optimal campus placement formats. The optimal single-page campus resume is **250 to 850 words**. Under 150 words is flagged as too brief; over 1,200 words is flagged as overly verbose.

##### Identifying Which Section Hurts the Resume Most ("Hurts Most")

The scoring engine calculates the point deficit (`max_score - earned_score`) across all sections. The section with the highest lost points is prominently highlighted as the **Biggest Score Drag** alongside a tailored, actionable fix suggestion so students immediately know where to invest effort to see the largest score improvement.

---

### 2. Interactive Mock Interview Simulator
Real-time conversational practice simulator with dynamic question generation, live answer evaluation, STAR technique analysis, and an optional timed countdown mode.
![Interactive Mock Interview Simulator](docs/screenshots/mock-interview-simulator.svg)

---

### 3. Personalized 6-Week Study Roadmap
Custom weekly preparation curriculum tailored to the candidate's target company and role, mapping daily study topics, coding problems, and mock tests.
![Personalized 6-Week Study Roadmap](docs/screenshots/study-roadmap.svg)

---

### 4. Skill Gap Remediation Matrix
Detailed breakdown of identified skill gaps, detailing importance priority, estimated learning hours, project ideas, and curated documentation links.
![Skill Gap Remediation Matrix](docs/screenshots/skill-gap-analysis.svg)

---

### 5. CTC to In-Hand Salary & Offer Comparison Calculator
Transparent financial planning tool demystifying campus CTC offers by calculating monthly take-home pay, EPF contributions, and tax deductions with side-by-side offer comparison.
![CTC to In-Hand Salary Calculator](docs/screenshots/ctc-salary-calculator.svg)

>>>>>>> upstream/main

---

## Tech Stack

* **Frontend**: HTML5, CSS3, JavaScript, Bootstrap 5 (Material/Glassmorphism theme)
* **Backend**: Python, Flask, SQLite (for persistence of analyses & interview sessions)
* **AI Core**: Google Gen AI Python SDK (`google-genai`), Gemini API (Central model selection: `gemini-2.5-flash`)
* **Utilities**: PyPDF2 (PDF parsing), ReportLab (PDF compiling), python-dotenv (environment variables)

---

## Folder Structure

```
AI-Campus-Placement-Agent/
│   app.py                  # Flask Application Server
│   config.py               # Path configurations & Model settings
│   prompts.py              # Central prompt registry
│   requirements.txt        # Project dependencies
│   .env                    # Environment key file (GitIgnored)
│   README.md               # Project documentation
│
├───agents/                 # Independent AI Agent classes
│       coordinator.py
│       resume_agent.py
│       job_match_agent.py
│       skill_gap_agent.py
│       roadmap_agent.py
│       interview_agent.py
│
├───data/                   # Pre-cached static profile files
│       companies.json
│
├───static/                 # Styles and JS scripts
│   ├───css/
│   │       style.css
│   └───js/
│           script.js
│
├───templates/              # HTML layout templates
│       index.html
│       dashboard.html
│       interview.html
│
├───utils/                  # Backend support utilities
│       database.py
│       gemini.py
│       pdf_reader.py
│       report_generator.py
│
├───uploads/                # Uploaded resumes (Created on runtime)
└───reports/                # Generated report PDFs (Created on runtime)
```

---

## Prerequisites & Step-by-Step Setup Guide

Follow this guide to get the application running locally on your workstation.

### Prerequisites

Ensure the following tools and accounts are set up before beginning:

| Prerequisite | Minimum Version | Verification Command | Purpose |
|--------------|:---------------:|:--------------------:|---------|
| **Python** | `3.9+` (`3.9`–`3.12` recommended) | `python --version` or `python3 --version` | Core application runtime |
| **pip** | `21.0+` | `pip --version` or `python -m pip --version` | Python package installer |
| **Git** | `2.20+` | `git --version` | Source code version control |
| **Google Gemini API Key** | Free or Paid Tier | *N/A* | Powers LLM agents ([Get a free key from Google AI Studio](https://aistudio.google.com/)) *(Optional for Demo mode)* |
| **Web Browser** | Any modern browser | *N/A* | Google Chrome, Mozilla Firefox, Microsoft Edge, Safari |

---

### Step-by-Step Installation

#### 1. Clone the Repository
Clone the project repository to your local machine:
```bash
git clone https://github.com/deepikagandla74/ai-campus-placement-agent.git
cd ai-campus-placement-agent
```

#### 2. Create a Virtual Environment
Isolate dependencies using Python's built-in `venv` module:

- **macOS / Linux**:
  ```bash
  python3 -m venv venv
  ```
- **Windows (PowerShell / Command Prompt)**:
  ```powershell
  python -m venv venv
  ```

#### 3. Activate the Virtual Environment
Activate your newly created virtual environment before installing packages:

- **macOS / Linux**:
  ```bash
  source venv/bin/activate
  ```
- **Windows (PowerShell)**:
  ```powershell
  .\venv\Scripts\Activate.ps1
  ```
  *(If you encounter execution policy restrictions on PowerShell, run `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` first)*
- **Windows (Command Prompt)**:
  ```cmd
  venv\Scripts\activate.bat
  ```

Your terminal prompt will now display `(venv)`.

#### 4. Upgrade pip and Install Dependencies
Install all required libraries specified in `requirements.txt`:
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

#### 5. Configure Environment Variables
Create your local `.env` configuration file from the provided safe template:

- **macOS / Linux**:
  ```bash
  cp .env.example .env
  ```
- **Windows (Command Prompt / PowerShell)**:
  ```cmd
  copy .env.example .env
  ```

Open `.env` in your text editor and supply your Gemini API key:
```env
FLASK_SECRET_KEY=change-this-to-a-random-secret-string
GEMINI_API_KEY=AIzaSy...your-gemini-api-key-here
```
> **Security Note**: Never commit your real `.env` file or credentials to version control. All values in `.env.example` are safe placeholders, and `.env` is ignored by Git.

#### 6. Start the Flask Application
Run the main server script:
```bash
python app.py
```
On initial startup, the SQLite database at `data/campus_agent.db` is initialized automatically if it does not already exist.

#### 7. Access the Application
Open your web browser and navigate to:
```
http://127.0.0.1:5000/
```
or
```
http://localhost:5000/
```

---

### Running in Demo Mode (No API Key Required)
Want to explore all dashboard and evaluation features immediately without configuring a Gemini API key?
1. Start the app as shown above (`python app.py`).
2. Visit `http://127.0.0.1:5000/` and click the **"Try with a Sample Resume"** button on the homepage, or navigate directly to `http://127.0.0.1:5000/demo`.
3. The platform instantly loads a complete candidate profile targeting Google SDE-1 with realistic ATS scoring, skill gap matrices, and interview simulations.

---

### Running Automated Tests & Linting
Verify your local setup by running the test suite and code quality checks:
```bash
# Run all unit and integration tests
pytest

# Run tests with verbose output
pytest -v

# Run linting checks
flake8 .
black --check .
```

---

### Deployment & Cloud Hosting (Vercel)
The project is configured for deployment on Vercel using Python Serverless Functions (`api/index.py` and `vercel.json`):
- **Deployment Guide & Required Settings**: Refer to [docs/DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md) for environment variables, architectural notes, and step-by-step instructions.
- **Pre-Flight Smoke Check**: Run `python utils/deployment_check.py` to verify deployment integrity, configuration files, and critical public routes before releasing.

### 6. Run Resume Parser & Layout Tests
Verify resume text extraction and structured section parsing across all supported layouts (single column, two column, tables, and no section headings) with one command:
```bash
pytest tests/test_resume_parser.py
```

---

## Rate Limiting & Security Quotas

To protect quota-limited AI endpoints (Gemini API calls) from accidental exhaustion or abuse, the application includes a sliding-window in-memory rate limiter with configurable thresholds.

### Endpoint Quotas

| Endpoint / Scope | Default Limit | Purpose |
|------------------|---------------|---------|
| `/analyze` & `/api/analysis/start` (`analyze`) | `5/hour` | Resume extraction and multi-agent coordination |
| `/interview/.../submit` (`interview_eval`) | `30/hour` | Dynamic mock interview evaluations |
| `/api/interview/evaluate-star` (`star_eval`) | `30/hour` | STAR behavioral response evaluation |
| `/batch-compare` (`batch_compare`) | `10/hour` | Concurrent multi-company placement evaluation |
| `/api/generate-outreach` (`generate_outreach`) | `20/hour` | Personalized cover letter & email generation |
| Default / Other Routes (`default`) | `100/minute` | General API and UI browsing |

### Throttling Behavior

- **HTTP Status 429**: When a user or client exceeds the allowed quota, the server returns an `HTTP 429 Too Many Requests` status code with `Retry-After`, `X-RateLimit-Limit`, and `X-RateLimit-Remaining: 0` headers.
- **Friendly UI & Hints**: Browser submissions render a dedicated `429.html` cooldown page displaying a clear explanation and dynamic "try again in X minutes" (or seconds) hint with a real-time countdown.
- **JSON API Responses**: REST/AJAX endpoints return a structured JSON response:
  ```json
  {
    "success": false,
    "error": "Too Many Requests",
    "message": "You have temporarily exceeded the request rate limit for this action. Please try again in 59 minutes.",
    "retry_after_seconds": 3540,
    "retry_after_hint": "try again in 59 minutes"
  }
  ```

### Configuration (Without Modifying Route Code)

Quotas can be adjusted centrally via `.env` or in `config.py` using standard `<count>/<unit>` format strings (`second`, `minute`, `hour`, `day`):

```env
# Enable or disable rate limiting globally (true / false)
RATE_LIMIT_ENABLED=true

# Custom quotas
RATE_LIMIT_ANALYZE=5/hour
RATE_LIMIT_INTERVIEW=30/hour
RATE_LIMIT_BATCH=10/hour
RATE_LIMIT_OUTREACH=20/hour
RATE_LIMIT_STAR=30/hour
RATE_LIMIT_DEFAULT=100/minute
```

---

## Resume Upload Validation & Friendly Error Handling (#493)

To prevent application crashes, denial-of-service, blank analyses, and confusing failures from malformed uploads, comprehensive validation is enforced across client and server layers (`static/js/script.js`, `app.py`, and `utils/pdf_reader.py`) before parsing occurs:

- **Supported Formats Only**: Accepts strictly genuine PDF (`.pdf`) and Microsoft Word (`.docx`) files. Files with invalid extensions or non-matching magic byte signatures are rejected immediately.
- **Configurable File Size Boundary**: Uploads exceeding the maximum allowed size (default: **5 MB**, configurable via `MAX_UPLOAD_SIZE_MB`) are intercepted before parsing or storing to disk.
- **Scanned Image & Empty Content Detection**: Detects documents containing no extractable text (image scans, screenshots, empty pages) across both PDF and DOCX formats, explicitly explaining that scanned images are not supported and directing students to upload text-based files with selectable text or paste resume text directly.
- **Robustness Against Crashes**: Bad files, corrupt documents, or password locks never trigger uncaught 500 errors, crashes, or blank dashboards. All failure paths return clean HTTP 400 responses or helpful flash notices, and all temporary upload files are guaranteed to be cleaned up on failure.

### Upload Failure Cases & Error Messages

| Failure Case | HTTP Status | User Message |
| :--- | :---: | :--- |
| **Unsupported File Type** (e.g. `.png`, `.jpg`, `.txt`, `.exe`, no ext) | 400 / Flash | `"Unsupported file format (Invalid file format '<ext>'). Only PDF (.pdf) and Word (.docx) resumes are supported."` |
| **Oversized Upload** (> 5 MB) | 400 / 413 / Flash | `"The uploaded file exceeds the maximum allowed size of 5 MB. Please upload a smaller file."` |
| **Empty File** (0 Bytes) | 400 / Flash | `"The uploaded file is empty. Please upload a valid resume."` |
| **Scanned / Image-Only PDF** (0 text or < 100 chars) | 400 / Flash | `"The uploaded PDF appears to be scanned or image-based with no readable text. Scanned images are not supported. PyPDF2 could not extract text from this document. Please upload a text-based PDF resume or paste your resume text directly."` |
| **Blank / Image-Only Word Document** (.docx) | 400 / Flash | `"Could not extract sufficient text from DOCX document: No extractable text found. Scanned images and image-only documents are not supported. Please upload a text-based resume (PDF or DOCX) with selectable text, or paste your resume text directly."` |
| **Corrupted Document** | 400 / Flash | `"The uploaded file is not a valid PDF document. Please upload a genuine PDF resume (.pdf)."` / `"The uploaded PDF is corrupted or unreadable. Please check the file and try again."` |
| **Password-Protected PDF** | 400 / Flash | `"This PDF is password-protected. Please upload an unlocked copy of your resume or save/export the PDF without password protection, then try again."` |
| **Missing Upload & Pasted Text** | 400 / Flash | `"Please upload a supported resume file (.pdf or .docx) or paste your resume text."` |

### Configuration
```env
# Maximum allowed resume upload file size in megabytes (default: 5 MB)
MAX_UPLOAD_SIZE_MB=5
```

## Scanned & Image-Only PDF Detection

To prevent wasted AI quota and misleading evaluations from non-extractable resumes, `utils/pdf_reader.py` detects scanned or image-only PDF documents:

- **Early Halting & Quota Protection**: When an uploaded PDF yields empty text or fewer than the required characters (default: 100 characters), the analysis stops immediately before calling any Gemini LLM endpoints.
- **Actionable User Guidance**: Displays a clear notification informing the user that the document appears scanned or image-based, prompting them to upload a text-based PDF or paste resume text directly.
- **Configurable Thresholds**:
  ```env
  # Minimum extractable text characters required from a PDF resume (default: 100)
  MIN_PDF_TEXT_CHARS=100

  # Optional local OCR fallback (pytesseract). Disabled by default to avoid external dependencies.
  ENABLE_OCR_FALLBACK=false
  ```
## Gemini API Retry & Resilience

To prevent transient network glitches, 429 rate limits, and temporary 5xx server errors from failing an ongoing analysis or interview session, all outbound Gemini LLM calls in `utils/gemini.py` are protected with an automatic exponential backoff retry mechanism.

### Key Capabilities
- **Automatic Retry on Transient Errors**: Automatically retries HTTP 429 (rate limits/quota exhaustion), HTTP 500/502/503/504 (server overload/downtime), and socket/connection timeouts.
- **Fail Fast on Permanent Errors**: Non-transient errors such as HTTP 400 (bad requests), HTTP 401/403 (invalid API key or permissions), and formatting failures fail immediately without waiting or retrying.
- **Exponential Backoff with Full Jitter**: Delays scale progressively (e.g., 1s, 2s, 4s) up to a configurable maximum cap, with randomized jitter to prevent thundering herd spikes.
- **Friendly Error Messages**: When all retries are exhausted, the server logs the full error server-side and surfaces a clean, friendly message to the student (e.g., *"The AI service is busy, please try again in a minute."*). Raw tracebacks and API internals are never exposed to the user.

### Retry Configuration

Retry attempts and backoff intervals can be tuned in `config.py` or `.env`:

```env
# Maximum retry attempts before giving up (default: 3)
GEMINI_RETRY_ATTEMPTS=3

# Initial delay in seconds before the first retry (default: 1.0)
GEMINI_RETRY_INITIAL_DELAY=1.0

# Multiplier for subsequent backoff intervals (default: 2.0 -> 1s, 2s, 4s)
GEMINI_RETRY_BACKOFF_FACTOR=2.0

# Maximum upper bound delay cap in seconds (default: 10.0)
GEMINI_RETRY_MAX_DELAY=10.0

# Enable randomized jitter to avoid synchronized bursts (default: true)
GEMINI_RETRY_JITTER=true

# Request timeout in seconds on every AI call to prevent hanging (default: 30.0)
GEMINI_REQUEST_TIMEOUT=30.0
```

---

## CSRF Protection & Session Cookie Security (#300)

To safeguard student accounts, mock interview sessions, and personal career preparation records against Cross-Site Request Forgery (CSRF) and unauthorized cross-origin requests, state-changing HTTP endpoints require a per-session verification token:

### Key Capabilities
- **Per-Session CSRF Verification**: All state-changing requests (`POST`, `PUT`, `DELETE`, `PATCH`) must provide a valid CSRF token, either via the `X-CSRFToken` / `X-CSRF-Token` HTTP headers or as a `csrf_token` hidden form parameter.
- **Frontend Interceptor**: A global `fetch()` wrapper in `static/js/script.js` extracts the session token from `<meta name="csrf-token">` and automatically injects it into all AJAX / fetch requests.
- **Actionable 400 Error Handling**: Requests lacking a valid token are rejected with HTTP 400. Browser requests display a styled, informative `templates/csrf_error.html` page with clear instructions to refresh, while AJAX / API requests receive a structured JSON 400 response.
- **Hardened Session Cookies**:
  - `SESSION_COOKIE_HTTPONLY=True`: Protects session cookies from cross-site scripting (XSS) client-side reads.
  - `SESSION_COOKIE_SAMESITE="Lax"`: Restricts cross-site cookie transmission to mitigate CSRF attacks.
  - `SESSION_COOKIE_SECURE`: Automatically set to `True` when running in production (`FLASK_ENV=production` or `SESSION_COOKIE_SECURE=true`), ensuring session cookies are only transmitted over HTTPS.

### Configuration
```env
# Enable or disable CSRF protection (default: true)
WTF_CSRF_ENABLED=true

# CSRF token expiration in seconds (default: 3600 = 1 hour)
WTF_CSRF_TIME_LIMIT=3600

# Session cookie SameSite policy (default: Lax)
SESSION_COOKIE_SAMESITE=Lax

# Force secure cookies regardless of environment (default: auto-detected from FLASK_ENV)
SESSION_COOKIE_SECURE=false
```

---

## Future Scope

The following features are being considered:
* **GitHub Profile Analyzer**: Scrape repositories to grade coding quality and contribution frequency.
* **LinkedIn Profile Review**: Sync profile sections to suggest bio keywords and networking adjustments.
* **Voice Mock Interviews**: Support voice-to-text and speech analysis to grade interview tone and pace.
* **Resume Version Comparison**: Compare formatting changes across iterations to track improvement.
* **LeetCode Progress Tracking**: Import solved problem counts and display targeted coding challenges.
* **Recruiter Email Generator**: Compose cold outreach emails tailored to hiring managers.
* **Placement Calendar Integration**: Log preparation milestones directly to Google Calendar.
* **Internship Recommendation Agent**: Suggest live job posts matching analyzed skill sets.

---

## Project Status

- ✅ **Multi-Agent Architecture**: Coordinated agent system with specialized sub-agents
- ✅ **Web Interface**: Responsive Flask-based UI with Bootstrap 5
- ✅ **Resume Analysis**: ATS scoring, grammar checks, and improvement suggestions
- ✅ **Job Matching**: Keyword extraction and match percentage calculation
- ✅ **Skill Gap Analysis**: Prioritized learning paths with time estimates
- ✅ **Study Roadmaps**: 6-week customized curriculum generation
- ✅ **Mock Interviews**: Interactive interview simulator with real-time evaluation
- ✅ **PDF Reports**: Comprehensive placement readiness reports
- ✅ **CI/CD Pipeline**: GitHub Actions for automated testing and validation

---

## Company Interview Cheat Sheet (One-Page Revision PDF)

To help candidates quickly revise on the way to campus drives, a downloadable one-page printable cheat sheet is available for every recruiter in `data/companies.json`:
- **One-Page Layout Guarantee**: Compact ReportLab formatting with defensive text truncation ensuring all company details fit strictly onto a single printed page.
- **Drive-Focused Content**: Includes company overview, recruitment workflow, technical and HR interview rounds, key interview topics, top required skills, and drive-day revision tips.
- **Personalized Skill Gap Targeting**: Seamlessly integrates the student's top 3 identified skill gaps for that company when previous analyses exist; skips the section cleanly and gracefully when the candidate has no analysis.
- **XML/HTML Entity Escaping**: Robust escaping prevents rendering errors and parser crashes on special symbols such as `&`, `<`, `>`, quotes, and `C++`.
- **Direct Downloads**: Accessible from the Company Explorer modal, the Companies Directory (`/companies`), and the Preparation Checklist (`/company-checklist`).

---

## Privacy & Data Protection

The AI Campus Placement Agent is committed to transparent, student-friendly data practices:
* **Plain-Language Privacy Notice**: Available at [`/privacy`](templates/privacy.html) (and linked in the application footer and upload form), detailing what data is collected, where it is sent, how long it is kept, and how to delete it.
* **Mandatory AI Processing Consent**: Every resume upload requires explicit consent before any resume text is submitted to third-party AI models.
* **Third-Party AI Service**: Resume text and target role details are sent securely over HTTPS to the Google Gemini API (`gemini-1.5-flash`) solely for immediate placement evaluation and roadmap generation.
* **Optional PII Redaction**: Students can toggle automated PII masking on the upload form to strip emails, phone numbers, addresses, and government IDs prior to transmission.
* **Local Storage & Retention**: Generated analyses, ATS scores, and interview records are stored in the host's local SQLite database (`data/campus_agent.db`). Uploaded files in `uploads/` are temporary.
* **Data Erasure & Control**: Candidates can permanently delete individual past analyses on the [History](/history) page or trigger complete profile erasure via [Delete Account](/delete-account).

---

## Troubleshooting & FAQ

Here are solutions to the most common setup and runtime issues:

### 1. Port 5000 Already in Use (`OSError: [Errno 98] Address already in use` or `WinError 10048`)
- **Cause**: Another service or previous Flask instance is already running on port 5000. On macOS Monterey and later, Apple's **AirPlay Receiver** uses port 5000 by default.
- **Solution**:
  - **Option A (Run on a different port)**: Pass a custom port flag or set the `PORT` environment variable:
    ```bash
    # Run on port 5001
    python app.py --port 5001
    ```
    or via environment variable:
    ```bash
    # Linux / macOS
    PORT=5001 python app.py

    # Windows (PowerShell)
    $env:PORT="5001"; python app.py
    ```
  - **Option B (Disable macOS AirPlay Receiver)**: Go to **System Settings > General > AirDrop & AirPlay**, and turn off **AirPlay Receiver**.
  - **Option C (Terminate occupying process)**:
    - *Windows*: Run `netstat -ano | findstr :5000` to find the process ID (`<PID>`), then `taskkill /PID <PID> /F`.
    - *Linux / macOS*: Run `lsof -i :5000` to find the process ID (`<PID>`), then `kill -9 <PID>`.

---

### 2. Gemini API Key Not Detected (`GEMINI_API_KEY is not set` or `401 Unauthorized`)
- **Cause**: Flask cannot find your Gemini API key in the environment or `.env` file.
- **Solution**:
  1. Confirm your `.env` file is located in the project root directory alongside `app.py` (not inside a subfolder).
  2. Ensure the key has no enclosing quotes, extra whitespace, or brackets:
     ```env
     GEMINI_API_KEY=AIzaSy...your-actual-key-here
     ```
  3. Verify the key is enabled in [Google AI Studio](https://aistudio.google.com/).
  4. **No API key?** You can test all UI features and agent outputs instantly using **Demo Mode** (`/demo` or clicking **"Try with a Sample Resume"** on the homepage).

---

### 3. Rate Limit Exceeded (HTTP 429 Too Many Requests)
- **Cause**: You exceeded the sliding-window request limit (by default, 5 resume analyses per hour to preserve AI quota).
- **Solution**:
  - Wait for the cooldown countdown on the friendly `429` error screen.
  - For local development and testing, increase the quotas in your `.env`:
    ```env
    RATE_LIMIT_ANALYZE=100/hour
    RATE_LIMIT_INTERVIEW=100/hour
    ```
  - Or disable rate limiting completely for automated test suites:
    ```env
    RATE_LIMIT_ENABLED=false
    ```

---

### 4. Scanned or Image-Based PDF Rejected ("Unable to extract sufficient text")
- **Cause**: The uploaded resume PDF contains rasterized scans or flattened images with fewer than `MIN_PDF_TEXT_CHARS` extractable characters.
- **Solution**:
  - Export your resume directly to a text-based PDF from Google Docs, Microsoft Word, or LaTeX ("Save as PDF" / "Print to PDF").
  - Or use the **Direct Text Input** tab on the upload screen and paste your resume text directly into the form.

---

### 5. `ModuleNotFoundError` or Missing Dependencies
- **Cause**: Python packages were installed into the global Python environment instead of the project virtual environment.
- **Solution**:
  - Ensure your virtual environment is active (your prompt should show `(venv)`).
  - Reinstall requirements:
    ```bash
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    ```

---

### 6. SQLite Database Errors or Corrupted State (`sqlite3.OperationalError`)
- **Cause**: A schema migration conflict or partially locked database file during local testing.
- **Solution**:
  - The SQLite database is stored locally at `data/campus_agent.db`.
  - Stop the Flask server (`Ctrl+C`), back up or delete `data/campus_agent.db`:
    ```bash
    # Linux / macOS
    rm data/campus_agent.db

    # Windows
    del data\campus_agent.db
    ```
  - Restart `python app.py`. The database and all necessary tables will be automatically recreated.

---

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Quick Start for Contributors

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## Community & Support

- 🆘 [Support Guide](SUPPORT.md) - Get help and common solutions
- 🐛 [Issue Tracker](https://github.com/deepikagandla74/ai-campus-placement-agent/issues)

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---
<div align='center'>
  
### If you find this repo helpful, please consider giving it a ⭐ star on GitHub!

</div>
