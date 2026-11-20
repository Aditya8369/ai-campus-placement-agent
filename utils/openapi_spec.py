"""
OpenAPI 3.0.3 Specification Generator & Catalog for AI Campus Placement Agent (#410).

Provides complete OpenAPI 3.0.3 structured documentation for public and authenticated API routes,
including request schemas, query parameters, multipart form uploads, response models,
authentication mechanisms (session cookies, CSRF tokens), and HTTP error statuses.
"""

from typing import Dict, Any

OPENAPI_SPEC: Dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {
        "title": "AI Campus Placement Agent API",
        "version": "1.0.0",
        "description": (
            "Interactive OpenAPI documentation for the AI Campus Placement Agent platform. "
            "Enables students, institutional placement teams, and external developer integrations "
            "to perform AI-powered resume analysis, ATS scoring, mock interview evaluations, "
            "job application pipeline tracking, personalized preparation roadmaps, and account management."
        ),
        "contact": {
            "name": "AI Campus Placement Agent Support",
            "url": "https://github.com/deepikagandla74/ai-campus-placement-agent"
        },
        "license": {
            "name": "MIT License",
            "url": "https://opensource.org/licenses/MIT"
        }
    },
    "servers": [
        {
            "url": "/",
            "description": "Current Application Server"
        }
    ],
    "tags": [
        {
            "name": "Placement Analysis",
            "description": "Resume ATS evaluation, skill gap extraction, async pipeline tasks, and batch company comparison."
        },
        {
            "name": "Interview Practice & Evaluation",
            "description": "Dynamic mock interviews, coding challenges, algorithmic evaluation, STAR responses, and practice topics."
        },
        {
            "name": "Job Application Tracker",
            "description": "Manage recruitment applications across Applied, Assessment, Interview, Selected, and Rejected stages."
        },
        {
            "name": "Reports & Downloads",
            "description": "Downloadable evaluation reports (PDF), skills gap summaries, and interview transcripts."
        },
        {
            "name": "Preparation Notes",
            "description": "Personalized interview notes, categorized tips, and study concepts."
        },
        {
            "name": "Account & Security",
            "description": "Authentication, session keep-alive, active session registry, and password security."
        },
        {
            "name": "System & Utilities",
            "description": "System health probes, walkthrough catalog, and synthetic demo fixtures."
        }
    ],
    "paths": {
        "/api/analysis/start": {
            "post": {
                "tags": ["Placement Analysis"],
                "summary": "Start Asynchronous Resume Analysis",
                "description": (
                    "Initiates background AI placement evaluation for an uploaded resume or pasted text. "
                    "Returns a background task ID for polling or Server-Sent Events (SSE) streaming."
                ),
                "operationId": "startAnalysisAsync",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/x-www-form-urlencoded": {
                            "schema": {
                                "$ref": "#/components/schemas/AnalysisStartRequest"
                            }
                        },
                        "multipart/form-data": {
                            "schema": {
                                "$ref": "#/components/schemas/AnalysisStartMultipartRequest"
                            }
                        }
                    }
                },
                "responses": {
                    "202": {
                        "description": "Analysis task queued and started successfully.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/AnalysisTaskStartedResponse"
                                }
                            }
                        }
                    },
                    "400": {
                        "description": "Invalid input, missing resume, or privacy consent required.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/ErrorResponse"
                                }
                            }
                        }
                    },
                    "429": {
                        "description": "Rate limit exceeded.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/ErrorResponse"
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/analysis/status/{task_id}": {
            "get": {
                "tags": ["Placement Analysis"],
                "summary": "Get Analysis Task Progress",
                "description": "Poll the current progress and status of an asynchronous resume analysis task.",
                "operationId": "getAnalysisStatus",
                "parameters": [
                    {
                        "name": "task_id",
                        "in": "path",
                        "required": True,
                        "description": "Unique identifier of the queued analysis task.",
                        "schema": {
                            "type": "string"
                        }
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Task status and milestone progress details.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/AnalysisStatusResponse"
                                }
                            }
                        }
                    },
                    "404": {
                        "description": "Task not found or expired.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/ErrorResponse"
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/analysis/cancel/{task_id}": {
            "post": {
                "tags": ["Placement Analysis"],
                "summary": "Cancel Pending Analysis",
                "description": "Cancels an in-progress or queued background analysis task, aborting worker processing and cleaning up temporary files.",
                "operationId": "cancelAnalysisTask",
                "parameters": [
                    {
                        "name": "task_id",
                        "in": "path",
                        "required": True,
                        "description": "Unique identifier of the analysis task to cancel.",
                        "schema": {
                            "type": "string"
                        }
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Analysis task cancelled successfully.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean", "example": True},
                                        "message": {"type": "string", "example": "Analysis task cancelled successfully."},
                                        "task_id": {"type": "string", "example": "task-4f7b-91c2"},
                                        "status": {"type": "string", "example": "cancelled"}
                                    }
                                }
                            }
                        }
                    },
                    "400": {
                        "description": "Task already completed or invalid request.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/ErrorResponse"
                                }
                            }
                        }
                    },
                    "404": {
                        "description": "Task not found.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/ErrorResponse"
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/analysis/stream/{task_id}": {
            "get": {
                "tags": ["Placement Analysis"],
                "summary": "Stream Real-Time Analysis Progress (SSE)",
                "description": "Establishes a Server-Sent Events (SSE) connection streaming real-time milestones as sub-agents complete evaluation.",
                "operationId": "streamAnalysisProgress",
                "parameters": [
                    {
                        "name": "task_id",
                        "in": "path",
                        "required": True,
                        "description": "Unique task ID to stream events for.",
                        "schema": {
                            "type": "string"
                        }
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Event stream delivering JSON progress milestones.",
                        "content": {
                            "text/event-stream": {
                                "schema": {
                                    "type": "string",
                                    "example": "data: {\"status\": \"in_progress\", \"progress\": 45, \"message\": \"Evaluating ATS score...\"}\n\n"
                                }
                            }
                        }
                    }
                }
            }
        },
        "/analyze": {
            "post": {
                "tags": ["Placement Analysis"],
                "summary": "Submit Resume for Analysis (Form / Synchronous)",
                "description": "Primary submission endpoint for PDF/DOCX uploads or raw resume text. Redirects to candidate dashboard upon completion.",
                "operationId": "analyzeResume",
                "requestBody": {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "$ref": "#/components/schemas/AnalysisStartMultipartRequest"
                            }
                        }
                    }
                },
                "responses": {
                    "302": {
                        "description": "Redirects to /dashboard/{analysis_id} on success, or / on error."
                    },
                    "200": {
                        "description": "JSON response when requested with AJAX or ?async=true.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/AnalysisTaskStartedResponse"
                                }
                            }
                        }
                    },
                    "400": {
                        "description": "Validation error or missing required fields."
                    }
                }
            }
        },
        "/api/analysis/{analysis_id}/skill-evidence": {
            "get": {
                "tags": ["Placement Analysis"],
                "summary": "Get Skill Evidence Mapping",
                "description": "Inspect which skills detected in the candidate resume are backed by concrete project evidence versus unsupported.",
                "operationId": "getSkillEvidenceMapping",
                "parameters": [
                    {
                        "name": "analysis_id",
                        "in": "path",
                        "required": True,
                        "description": "Analysis ID of the candidate report.",
                        "schema": {
                            "type": "string"
                        }
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Skill evidence mapping breakdown.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/SkillEvidenceResponse"
                                }
                            }
                        }
                    },
                    "404": {
                        "description": "Analysis not found or unauthorized."
                    }
                }
            }
        },
        "/api/analysis/batch-compare": {
            "post": {
                "tags": ["Placement Analysis"],
                "summary": "Batch Multi-Company Comparison",
                "description": "Evaluates candidate resume against multiple recruiter benchmarks simultaneously (e.g. Google, Amazon, Microsoft, TCS).",
                "operationId": "batchCompareCompanies",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/BatchCompareRequest"
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Batch comparison matrix results.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/BatchCompareResponse"
                                }
                            }
                        }
                    }
                }
            }
        },
        "/interview/{analysis_id}/submit": {
            "post": {
                "tags": ["Interview Practice & Evaluation"],
                "summary": "Submit Live Mock Interview Answer",
                "description": "Evaluates candidate answer accuracy, technical depth, speech telemetry, and STAR structure for an interview question.",
                "operationId": "submitInterviewAnswer",
                "parameters": [
                    {
                        "name": "analysis_id",
                        "in": "path",
                        "required": True,
                        "schema": {
                            "type": "string"
                        }
                    }
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/InterviewAnswerSubmitRequest"
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "AI evaluation with accuracy score, feedback, and suggested STAR rewrite.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/InterviewAnswerEvaluationResponse"
                                }
                            }
                        }
                    },
                    "400": {
                        "description": "Invalid question index or missing answer payload."
                    }
                }
            }
        },
        "/api/interview/{analysis_id}/coding-problem": {
            "get": {
                "tags": ["Interview Practice & Evaluation"],
                "summary": "Get Dynamic Technical Coding Challenge",
                "description": "Fetches a tailored Data Structures & Algorithms coding challenge based on identified resume skill gaps.",
                "operationId": "getCodingProblem",
                "parameters": [
                    {
                        "name": "analysis_id",
                        "in": "path",
                        "required": True,
                        "schema": {
                            "type": "string"
                        }
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Coding problem description, starter code, and test cases.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/CodingProblemResponse"
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/interview/{analysis_id}/evaluate-code": {
            "post": {
                "tags": ["Interview Practice & Evaluation"],
                "summary": "Evaluate Submitted Code Solution",
                "description": "Executes solution against test cases, assesses algorithmic time/space complexity, and provides optimization suggestions.",
                "operationId": "evaluateCodeSolution",
                "parameters": [
                    {
                        "name": "analysis_id",
                        "in": "path",
                        "required": True,
                        "schema": {
                            "type": "string"
                        }
                    }
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/CodeEvaluationRequest"
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Code evaluation verdict, passed test counts, and complexity analysis.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/CodeEvaluationResponse"
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/interview/evaluate-star": {
            "post": {
                "tags": ["Interview Practice & Evaluation"],
                "summary": "Behavioral STAR Evaluation",
                "description": "Evaluates candidate behavioral response according to Situation, Task, Action, and Result dimensions.",
                "operationId": "evaluateStarMethod",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/StarEvaluationRequest"
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Detailed STAR scores, dimensional analysis, and model rewrite.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/StarEvaluationResponse"
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/interview/practice/topics": {
            "get": {
                "tags": ["Interview Practice & Evaluation"],
                "summary": "List Technical Practice Topics",
                "description": "Retrieves available technical subject categories (DSA, System Design, Operating Systems, Computer Networks).",
                "operationId": "getInterviewPracticeTopics",
                "responses": {
                    "200": {
                        "description": "List of practice topic descriptors.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean"},
                                        "topics": {
                                            "type": "array",
                                            "items": {"$ref": "#/components/schemas/PracticeTopicItem"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/interview/practice/generate": {
            "post": {
                "tags": ["Interview Practice & Evaluation"],
                "summary": "Generate Practice Challenge for Topic",
                "description": "Generates a customized technical interview question for a specific topic and difficulty level.",
                "operationId": "generateTopicPracticeChallenge",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["topic"],
                                "properties": {
                                    "topic": {"type": "string", "example": "dsa"},
                                    "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"], "default": "medium"}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Generated interview challenge payload.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean"},
                                        "challenge_id": {"type": "string"},
                                        "question": {"type": "string"},
                                        "difficulty": {"type": "string"},
                                        "hints": {"type": "array", "items": {"type": "string"}}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/interview/practice/evaluate": {
            "post": {
                "tags": ["Interview Practice & Evaluation"],
                "summary": "Evaluate Topic Practice Answer",
                "description": "Scores candidate response to a topic challenge and provides targeted guidance.",
                "operationId": "evaluateTopicPracticeAnswer",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["topic", "question", "answer"],
                                "properties": {
                                    "topic": {"type": "string"},
                                    "question": {"type": "string"},
                                    "answer": {"type": "string"},
                                    "difficulty": {"type": "string", "default": "medium"}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Practice evaluation verdict and suggestions.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean"},
                                        "verdict": {"type": "string", "example": "Correct"},
                                        "score": {"type": "integer", "example": 85},
                                        "feedback": {"type": "string"},
                                        "suggested_answer": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/interview-history": {
            "get": {
                "tags": ["Interview Practice & Evaluation"],
                "summary": "Get Candidate Interview History",
                "description": "Returns candidate's past mock interview sessions, performance trajectories, and round scores.",
                "operationId": "getInterviewHistory",
                "responses": {
                    "200": {
                        "description": "List of completed mock interview sessions.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean"},
                                        "sessions": {
                                            "type": "array",
                                            "items": {"$ref": "#/components/schemas/InterviewSessionSummary"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/applications": {
            "get": {
                "tags": ["Job Application Tracker"],
                "summary": "List Tracked Job Applications",
                "description": "Retrieves the authenticated candidate's job application records with optional stage or company filtering.",
                "operationId": "listJobApplications",
                "parameters": [
                    {
                        "name": "status",
                        "in": "query",
                        "required": False,
                        "description": "Filter by stage: Applied, Assessment, Interview, Selected, Rejected.",
                        "schema": {
                            "type": "string",
                            "enum": ["Applied", "Assessment", "Interview", "Selected", "Rejected"]
                        }
                    },
                    {
                        "name": "company",
                        "in": "query",
                        "required": False,
                        "description": "Filter by company name substring.",
                        "schema": {"type": "string"}
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Array of job application tracking records.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/JobApplicationListResponse"
                                }
                            }
                        }
                    }
                }
            },
            "post": {
                "tags": ["Job Application Tracker"],
                "summary": "Create Job Application Record",
                "description": "Records a new job application in the candidate's recruitment tracker.",
                "operationId": "createJobApplication",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/JobApplicationCreateRequest"
                            }
                        }
                    }
                },
                "responses": {
                    "201": {
                        "description": "Application tracked successfully.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/JobApplicationSingleResponse"
                                }
                            }
                        }
                    },
                    "400": {
                        "description": "Missing required fields (company_name or role_title)."
                    }
                }
            }
        },
        "/api/applications/{app_id}": {
            "get": {
                "tags": ["Job Application Tracker"],
                "summary": "Get Job Application Details",
                "description": "Retrieves detailed information for a single job application tracking record.",
                "operationId": "getJobApplication",
                "parameters": [
                    {"name": "app_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {
                    "200": {
                        "description": "Job application record.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/JobApplicationSingleResponse"
                                }
                            }
                        }
                    },
                    "404": {"description": "Application not found or unauthorized."}
                }
            },
            "put": {
                "tags": ["Job Application Tracker"],
                "summary": "Update Job Application Details",
                "description": "Updates company, role title, status, location, notes, or deadlines for an existing application.",
                "operationId": "updateJobApplication",
                "parameters": [
                    {"name": "app_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/JobApplicationCreateRequest"
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Application updated successfully.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/JobApplicationSingleResponse"
                                }
                            }
                        }
                    }
                }
            },
            "delete": {
                "tags": ["Job Application Tracker"],
                "summary": "Delete Job Application",
                "description": "Removes a tracked application from the candidate's pipeline.",
                "operationId": "deleteJobApplication",
                "parameters": [
                    {"name": "app_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {
                    "200": {
                        "description": "Application deleted successfully.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean"},
                                        "message": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/applications/{app_id}/status": {
            "post": {
                "tags": ["Job Application Tracker"],
                "summary": "Update Application Pipeline Stage",
                "description": "Quickly transitions an application between stages (Applied -> Assessment -> Interview -> Selected / Rejected).",
                "operationId": "updateApplicationStatus",
                "parameters": [
                    {"name": "app_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/ApplicationStatusUpdateRequest"
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Status updated successfully.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/JobApplicationSingleResponse"
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/applications/stats": {
            "get": {
                "tags": ["Job Application Tracker"],
                "summary": "Application Pipeline Analytics",
                "description": "Returns counts per recruitment stage and pipeline conversion rates.",
                "operationId": "getApplicationStats",
                "responses": {
                    "200": {
                        "description": "Funnel analytics and count metrics.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/ApplicationStatsResponse"
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/applications/export": {
            "get": {
                "tags": ["Job Application Tracker"],
                "summary": "Export Application Records",
                "description": "Exports tracked job applications as CSV or JSON file download.",
                "operationId": "exportApplications",
                "parameters": [
                    {
                        "name": "format",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string", "enum": ["csv", "json"], "default": "csv"}
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Export file download (text/csv or application/json)."
                    }
                }
            }
        },
        "/download/{analysis_id}": {
            "get": {
                "tags": ["Reports & Downloads"],
                "summary": "Download Full Placement Evaluation Report (PDF)",
                "description": "Generates and streams a professional, print-ready PDF containing the full candidate ATS evaluation, roadmap, and recommendations.",
                "operationId": "downloadFullReportPdf",
                "parameters": [
                    {"name": "analysis_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {
                    "200": {
                        "description": "Binary PDF document stream (application/pdf)."
                    },
                    "404": {"description": "Report not found."}
                }
            }
        },
        "/download/skills-gap/{analysis_id}": {
            "get": {
                "tags": ["Reports & Downloads"],
                "summary": "Download Skill Gap Analysis PDF",
                "description": "Generates a focused PDF outlining identified skill deficiencies, learning resources, and suggested micro-projects.",
                "operationId": "downloadSkillGapPdf",
                "parameters": [
                    {"name": "analysis_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {
                    "200": {
                        "description": "Binary PDF document stream (application/pdf)."
                    }
                }
            }
        },
        "/download/interview-transcript/{analysis_id}": {
            "get": {
                "tags": ["Reports & Downloads"],
                "summary": "Download Mock Interview Transcript",
                "description": "Downloads the complete transcript of questions, candidate answers, and AI evaluations.",
                "operationId": "downloadInterviewTranscript",
                "parameters": [
                    {"name": "analysis_id", "in": "path", "required": True, "schema": {"type": "string"}},
                    {"name": "format", "in": "query", "schema": {"type": "string", "enum": ["pdf", "markdown"], "default": "pdf"}}
                ],
                "responses": {
                    "200": {
                        "description": "Interview transcript stream."
                    }
                }
            }
        },
        "/download/preparation-summary": {
            "get": {
                "tags": ["Reports & Downloads"],
                "summary": "Download Preparation Roadmap Summary PDF",
                "description": "Generates a consolidated summary of the candidate's multi-week study milestones and checklist readiness.",
                "operationId": "downloadPreparationSummaryPdf",
                "responses": {
                    "200": {
                        "description": "Binary PDF document stream (application/pdf)."
                    }
                }
            }
        },
        "/api/notes": {
            "get": {
                "tags": ["Preparation Notes"],
                "summary": "List Preparation Notes",
                "description": "Retrieves the authenticated user's personal interview preparation notes.",
                "operationId": "listPreparationNotes",
                "responses": {
                    "200": {
                        "description": "List of candidate notes.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/PreparationNotesListResponse"
                                }
                            }
                        }
                    }
                }
            },
            "post": {
                "tags": ["Preparation Notes"],
                "summary": "Create Preparation Note",
                "description": "Creates a new personal study or interview preparation note.",
                "operationId": "createPreparationNote",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/PreparationNoteRequest"
                            }
                        }
                    }
                },
                "responses": {
                    "201": {
                        "description": "Note created successfully.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/PreparationNoteSingleResponse"
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/notes/{note_id}": {
            "get": {
                "tags": ["Preparation Notes"],
                "summary": "Get Preparation Note",
                "description": "Retrieves an individual note by ID.",
                "operationId": "getPreparationNote",
                "parameters": [
                    {"name": "note_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/PreparationNoteSingleResponse"}
                            }
                        }
                    }
                }
            },
            "put": {
                "tags": ["Preparation Notes"],
                "summary": "Update Preparation Note",
                "description": "Updates note title, content, or tags.",
                "operationId": "updatePreparationNote",
                "parameters": [
                    {"name": "note_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/PreparationNoteRequest"}
                        }
                    }
                },
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/PreparationNoteSingleResponse"}
                            }
                        }
                    }
                }
            },
            "delete": {
                "tags": ["Preparation Notes"],
                "summary": "Delete Preparation Note",
                "description": "Deletes an individual note.",
                "operationId": "deletePreparationNote",
                "parameters": [
                    {"name": "note_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean"},
                                        "message": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/login": {
            "post": {
                "tags": ["Account & Security"],
                "summary": "User Sign-In",
                "description": "Authenticates user with email and password, establishing an encrypted session cookie.",
                "operationId": "loginUser",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/x-www-form-urlencoded": {
                            "schema": {
                                "$ref": "#/components/schemas/LoginRequest"
                            }
                        }
                    }
                },
                "responses": {
                    "302": {"description": "Redirects to dashboard or next parameter on success."},
                    "200": {"description": "Renders login page with validation error if credentials invalid."}
                }
            }
        },
        "/register": {
            "post": {
                "tags": ["Account & Security"],
                "summary": "User Registration",
                "description": "Creates a new student account and initiates email verification.",
                "operationId": "registerUser",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/x-www-form-urlencoded": {
                            "schema": {
                                "$ref": "#/components/schemas/RegisterRequest"
                            }
                        }
                    }
                },
                "responses": {
                    "302": {"description": "Redirects to login page upon successful account creation."}
                }
            }
        },
        "/logout": {
            "post": {
                "tags": ["Account & Security"],
                "summary": "User Logout",
                "description": "Terminates active session and invalidates authentication cookies.",
                "operationId": "logoutUser",
                "responses": {
                    "302": {"description": "Redirects to home page."}
                }
            }
        },
        "/api/session/status": {
            "get": {
                "tags": ["Account & Security"],
                "summary": "Session Status & Expiration Countdown",
                "description": "Checks session validity, seconds until timeout, and warning threshold.",
                "operationId": "getSessionStatus",
                "responses": {
                    "200": {
                        "description": "Session active status.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/SessionStatusResponse"
                                }
                            }
                        }
                    },
                    "401": {
                        "description": "Session expired or unauthenticated."
                    }
                }
            }
        },
        "/api/session/keep-alive": {
            "post": {
                "tags": ["Account & Security"],
                "summary": "Refresh Session Activity Timestamp",
                "description": "Pings the server to reset inactivity timer when the user chooses to continue working.",
                "operationId": "keepSessionAlive",
                "responses": {
                    "200": {
                        "description": "Session refreshed.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string", "example": "active"},
                                        "message": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/session/logout": {
            "post": {
                "tags": ["Account & Security"],
                "summary": "Immediate Session Invalidation via API",
                "description": "Revokes current server-side session registry and deletes cookie.",
                "operationId": "apiSessionLogout",
                "responses": {
                    "200": {
                        "description": "Session revoked successfully."
                    }
                }
            }
        },
        "/api/auth/password-strength": {
            "post": {
                "tags": ["Account & Security"],
                "summary": "Evaluate Password Strength",
                "description": "Analyzes password complexity, entropy score (0-4), and returns helpful suggestions.",
                "operationId": "checkPasswordStrength",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["password"],
                                "properties": {
                                    "password": {"type": "string"}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "score": {"type": "integer", "minimum": 0, "maximum": 4},
                                        "label": {"type": "string", "example": "Strong"},
                                        "feedback": {"type": "array", "items": {"type": "string"}}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/health": {
            "get": {
                "tags": ["System & Utilities"],
                "summary": "System Health & Readiness Probe",
                "description": "Validates database connectivity, storage permissions, and service latency.",
                "operationId": "getHealthProbe",
                "responses": {
                    "200": {
                        "description": "Service is healthy and fully operational.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/HealthCheckResponse"
                                }
                            }
                        }
                    },
                    "503": {
                        "description": "Service degraded (e.g. database connection failed)."
                    }
                }
            }
        },
        "/api/walkthrough": {
            "get": {
                "tags": ["System & Utilities"],
                "summary": "First-Time User Walkthrough Catalog",
                "description": "Delivers structured steps introducing Resume Analysis, Interview Practice, Preparation Plans, and Application Tracker.",
                "operationId": "getWalkthroughCatalog",
                "responses": {
                    "200": {
                        "description": "Walkthrough catalog steps and dismissal state.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/WalkthroughResponse"
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/demo/sample-resume": {
            "get": {
                "tags": ["System & Utilities"],
                "summary": "Synthetic Sample Resume",
                "description": "Provides realistic synthetic candidate resume text for evaluator demonstrations without uploading personal data.",
                "operationId": "getDemoSampleResume",
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean"},
                                        "resume_text": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/demo/sample-job-description": {
            "get": {
                "tags": ["System & Utilities"],
                "summary": "Synthetic Sample Job Description",
                "description": "Provides synthetic role description for software engineering placement demonstrations.",
                "operationId": "getDemoSampleJobDescription",
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean"},
                                        "job_description": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/openapi.json": {
            "get": {
                "tags": ["System & Utilities"],
                "summary": "OpenAPI Specification JSON",
                "description": "Retrieves the complete OpenAPI 3.0.3 specification for the AI Campus Placement Agent platform.",
                "operationId": "getOpenApiSpecJson",
                "responses": {
                    "200": {
                        "description": "Full OpenAPI 3.0.3 specification document.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object"
                                }
                            }
                        }
                    }
                }
            }
        }
    },
    "components": {
        "securitySchemes": {
            "cookieAuth": {
                "type": "apiKey",
                "in": "cookie",
                "name": "session",
                "description": "Flask encrypted session cookie established upon login."
            },
            "csrfToken": {
                "type": "apiKey",
                "in": "header",
                "name": "X-CSRFToken",
                "description": "Cross-Site Request Forgery (CSRF) protection token."
            }
        },
        "schemas": {
            "ErrorResponse": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "example": False},
                    "error": {"type": "string", "example": "Invalid request parameter or missing field."},
                    "code": {"type": "string", "example": "VALIDATION_ERROR"}
                }
            },
            "AnalysisStartRequest": {
                "type": "object",
                "properties": {
                    "resume_text": {
                        "type": "string",
                        "description": "Raw text of the candidate resume."
                    },
                    "company": {
                        "type": "string",
                        "default": "General",
                        "description": "Target company name."
                    },
                    "job_description": {
                        "type": "string",
                        "description": "Target job description text to match against."
                    },
                    "privacy_consent": {
                        "type": "string",
                        "enum": ["true", "1", "on"],
                        "description": "Consent for AI processing of resume text."
                    },
                    "redact_pii": {
                        "type": "string",
                        "enum": ["true", "false"],
                        "default": "false",
                        "description": "Whether to sanitize emails, phone numbers, and addresses."
                    }
                }
            },
            "AnalysisStartMultipartRequest": {
                "type": "object",
                "properties": {
                    "resume": {
                        "type": "string",
                        "format": "binary",
                        "description": "PDF or DOCX resume document file."
                    },
                    "resume_text": {"type": "string"},
                    "company": {"type": "string", "default": "General"},
                    "job_description": {"type": "string"},
                    "privacy_consent": {"type": "string", "enum": ["true", "1", "on"]}
                }
            },
            "AnalysisTaskStartedResponse": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "example": True},
                    "status": {"type": "string", "example": "started"},
                    "task_id": {"type": "string", "example": "task-4f7b-91c2"},
                    "analysis_id": {"type": "string", "example": "aid-8d9e-11f4"},
                    "stream_url": {"type": "string", "example": "/api/analysis/stream/task-4f7b-91c2"},
                    "status_url": {"type": "string", "example": "/api/analysis/status/task-4f7b-91c2"}
                }
            },
            "AnalysisStatusResponse": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["queued", "in_progress", "completed", "error"]},
                    "progress": {"type": "integer", "minimum": 0, "maximum": 100},
                    "current_step": {"type": "string"},
                    "current_agent": {"type": "string"},
                    "analysis_id": {"type": "string"},
                    "redirect_url": {"type": "string"},
                    "error_message": {"type": "string"}
                }
            },
            "SkillEvidenceResponse": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "evidence_score": {"type": "integer", "example": 85},
                    "supported_skills_count": {"type": "integer", "example": 5},
                    "unsupported_skills_count": {"type": "integer", "example": 2},
                    "partial_skills_count": {"type": "integer", "example": 1},
                    "summary": {"type": "string"},
                    "skills": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "skill": {"type": "string"},
                                "status": {"type": "string", "enum": ["supported", "partial", "unsupported"]},
                                "source_section": {"type": "string"},
                                "snippet": {"type": "string"},
                                "suggestion": {"type": "string"}
                            }
                        }
                    }
                }
            },
            "BatchCompareRequest": {
                "type": "object",
                "required": ["resume_text", "companies"],
                "properties": {
                    "resume_text": {"type": "string"},
                    "companies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "example": ["Google", "Amazon", "Microsoft", "TCS"]
                    },
                    "job_description": {"type": "string"}
                }
            },
            "BatchCompareResponse": {
                "type": "object",
                "properties": {
                    "batch_id": {"type": "string"},
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "company": {"type": "string"},
                                "ats_score": {"type": "integer"},
                                "match_percentage": {"type": "integer"},
                                "verdict": {"type": "string"}
                            }
                        }
                    }
                }
            },
            "InterviewAnswerSubmitRequest": {
                "type": "object",
                "required": ["answer", "question_index"],
                "properties": {
                    "question_index": {"type": "integer", "example": 0},
                    "answer": {"type": "string", "example": "In a distributed system, I used Redis caching with LRU eviction to cut latency by 40%."},
                    "speech_metrics": {
                        "type": "object",
                        "properties": {
                            "speaking_rate_wpm": {"type": "number"},
                            "filler_words_count": {"type": "integer"},
                            "duration_seconds": {"type": "number"}
                        }
                    }
                }
            },
            "InterviewAnswerEvaluationResponse": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "score": {"type": "integer", "example": 88},
                    "strengths": {"type": "array", "items": {"type": "string"}},
                    "improvements": {"type": "array", "items": {"type": "string"}},
                    "follow_up": {"type": "string"},
                    "star_evaluation": {
                        "type": "object",
                        "properties": {
                            "star_score": {"type": "integer"},
                            "situation": {"type": "string"},
                            "task": {"type": "string"},
                            "action": {"type": "string"},
                            "result": {"type": "string"}
                        }
                    }
                }
            },
            "CodingProblemResponse": {
                "type": "object",
                "properties": {
                    "problem_id": {"type": "string"},
                    "title": {"type": "string", "example": "LRU Cache Implementation"},
                    "difficulty": {"type": "string", "example": "Medium"},
                    "description": {"type": "string"},
                    "starter_code": {"type": "string"},
                    "sample_test_cases": {"type": "array", "items": {"type": "object"}}
                }
            },
            "CodeEvaluationRequest": {
                "type": "object",
                "required": ["code", "language"],
                "properties": {
                    "code": {"type": "string"},
                    "language": {"type": "string", "enum": ["python", "javascript", "java", "cpp"], "default": "python"}
                }
            },
            "CodeEvaluationResponse": {
                "type": "object",
                "properties": {
                    "verdict": {"type": "string", "example": "Passed"},
                    "passed_tests": {"type": "integer", "example": 5},
                    "total_tests": {"type": "integer", "example": 5},
                    "time_complexity": {"type": "string", "example": "O(1)"},
                    "space_complexity": {"type": "string", "example": "O(N)"},
                    "feedback": {"type": "string"}
                }
            },
            "StarEvaluationRequest": {
                "type": "object",
                "required": ["question", "answer"],
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                    "question_type": {"type": "string", "default": "Behavioral"}
                }
            },
            "StarEvaluationResponse": {
                "type": "object",
                "properties": {
                    "star_score": {"type": "integer", "example": 84},
                    "situation_score": {"type": "integer"},
                    "task_score": {"type": "integer"},
                    "action_score": {"type": "integer"},
                    "result_score": {"type": "integer"},
                    "feedback": {"type": "string"},
                    "suggested_star_rewrite": {"type": "string"}
                }
            },
            "PracticeTopicItem": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "category": {"type": "string"},
                    "description": {"type": "string"}
                }
            },
            "InterviewSessionSummary": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "company_name": {"type": "string"},
                    "date": {"type": "string"},
                    "total_questions": {"type": "integer"},
                    "overall_score": {"type": "integer"}
                }
            },
            "JobApplicationCreateRequest": {
                "type": "object",
                "required": ["company_name", "role_title"],
                "properties": {
                    "company_name": {"type": "string", "example": "Google"},
                    "role_title": {"type": "string", "example": "Software Engineer"},
                    "status": {"type": "string", "enum": ["Applied", "Assessment", "Interview", "Selected", "Rejected"], "default": "Applied"},
                    "application_date": {"type": "string", "format": "date", "example": "2026-11-17"},
                    "location": {"type": "string", "example": "Mountain View, CA"},
                    "job_type": {"type": "string", "enum": ["Full-Time", "Internship", "Contract"], "default": "Full-Time"},
                    "notes": {"type": "string"}
                }
            },
            "JobApplicationSingleResponse": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "application": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "company_name": {"type": "string"},
                            "role_title": {"type": "string"},
                            "status": {"type": "string"},
                            "application_date": {"type": "string"},
                            "location": {"type": "string"},
                            "job_type": {"type": "string"}
                        }
                    }
                }
            },
            "JobApplicationListResponse": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "count": {"type": "integer"},
                    "applications": {
                        "type": "array",
                        "items": {"type": "object"}
                    }
                }
            },
            "ApplicationStatusUpdateRequest": {
                "type": "object",
                "required": ["status"],
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["Applied", "Assessment", "Interview", "Selected", "Rejected"]
                    }
                }
            },
            "ApplicationStatsResponse": {
                "type": "object",
                "properties": {
                    "total_applications": {"type": "integer"},
                    "applied": {"type": "integer"},
                    "assessment": {"type": "integer"},
                    "interview": {"type": "integer"},
                    "selected": {"type": "integer"},
                    "rejected": {"type": "integer"},
                    "interview_conversion_rate": {"type": "number"}
                }
            },
            "PreparationNoteRequest": {
                "type": "object",
                "required": ["title", "content"],
                "properties": {
                    "title": {"type": "string", "example": "Binary Search Invariants"},
                    "content": {"type": "string", "example": "Always check whether mid is inclusive or exclusive on boundaries."},
                    "category": {"type": "string", "example": "Algorithms"},
                    "tags": {"type": "array", "items": {"type": "string"}}
                }
            },
            "PreparationNoteSingleResponse": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "note": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "content": {"type": "string"},
                            "category": {"type": "string"},
                            "updated_at": {"type": "string"}
                        }
                    }
                }
            },
            "PreparationNotesListResponse": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "notes": {"type": "array", "items": {"type": "object"}}
                }
            },
            "LoginRequest": {
                "type": "object",
                "required": ["email", "password"],
                "properties": {
                    "email": {"type": "string", "format": "email", "example": "student@example.com"},
                    "password": {"type": "string", "format": "password", "example": "SecurePassword123!"}
                }
            },
            "RegisterRequest": {
                "type": "object",
                "required": ["name", "email", "password"],
                "properties": {
                    "name": {"type": "string", "example": "Jane Doe"},
                    "email": {"type": "string", "format": "email", "example": "jane@example.com"},
                    "password": {"type": "string", "format": "password"}
                }
            },
            "SessionStatusResponse": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["authenticated", "warning", "expired"]},
                    "authenticated": {"type": "boolean"},
                    "user_id": {"type": "string"},
                    "remaining_seconds": {"type": "number"},
                    "timeout_seconds": {"type": "integer"},
                    "warning_seconds": {"type": "integer"}
                }
            },
            "HealthCheckResponse": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "healthy"},
                    "service": {"type": "string", "example": "ai-campus-placement-agent"},
                    "latency_ms": {"type": "number"},
                    "timestamp": {"type": "string"},
                    "checks": {
                        "type": "object",
                        "properties": {
                            "database": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string", "example": "healthy"},
                                    "connection": {"type": "string", "example": "active"}
                                }
                            },
                            "storage": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string", "example": "healthy"},
                                    "writable": {"type": "boolean", "example": True}
                                }
                            }
                        }
                    }
                }
            },
            "WalkthroughResponse": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "dismissed": {"type": "boolean"},
                    "total_steps": {"type": "integer", "example": 4},
                    "recommended_next_step": {"type": "object"},
                    "steps": {"type": "array", "items": {"type": "object"}}
                }
            }
        }
    }
}


def get_openapi_spec() -> Dict[str, Any]:
    """Returns the full OpenAPI 3.0.3 specification dictionary."""
    import copy
    return copy.deepcopy(OPENAPI_SPEC)
