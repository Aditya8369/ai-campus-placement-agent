# Deployment & Vercel Configuration Guide

This guide details how to deploy the **AI Campus Placement Agent** to Vercel and other cloud environments, lists all required settings and environment variables, explains the root cause investigation for serverless function errors, and documents how to run lightweight pre-flight deployment checks.

---

## 1. Vercel Architecture Overview

The AI Campus Placement Agent is a Python Flask WSGI application configured to run seamlessly as a Serverless Function on Vercel:

- **WSGI Entrypoint (`api/index.py`)**: Exposes the Flask application instance (`app`) to Vercel's Python Serverless Runtime.
- **Routing Configuration (`vercel.json`)**: Employs URL rewrites to route all incoming HTTP requests (`/(.*)`) to the serverless entrypoint `/api/index.py`. Static assets in `/static` are automatically served with high-performance caching.
- **Serverless Ephemeral Storage**: When deployed on Vercel (`VERCEL=1`), all persistent file operations (SQLite database, file uploads, PDF reports, database backups) are automatically directed to `/tmp`, which provides 512 MB of writable scratch space per function instance.

---

## 2. Root Cause Investigation & Fixes (Vercel 500 FUNCTION_INVOCATION_FAILED)

### What Happened
During deployment review, the live site returned HTTP 500 `FUNCTION_INVOCATION_FAILED`. In Vercel serverless functions, this status code indicates that the Python runtime crashed upon function invocation before returning an HTTP response.

### Root Cause Analysis
1. **Missing Typing Import (`utils/database.py`)**:
   - Function type annotations in `utils/database.py` referenced `Union[...]`, but `Union` was omitted from `from typing import Optional, List, Dict, Any`.
   - Because `app.py` imports `utils.database` at module load time, the unhandled `NameError: name 'Union' is not defined` crashed the process immediately on import.
2. **Missing CSRF Module Imports (`app.py`)**:
   - During merge resolution of structured logging (#301), the import statement `from utils.csrf import csrf, CSRFError, generate_csrf` was inadvertently wiped from `app.py`.
   - When the WSGI app initialized, line 288 (`csrf.init_app(app)`) raised `NameError: name 'csrf' is not defined`, crashing the serverless container.
3. **Incomplete Public Endpoints Set (`app.py`)**:
   - Several public endpoints (`privacy_policy`, `forgot_password`, `reset_password`, `get_company_profile`) were missing from `public_endpoints` in `require_login()`, causing unauthenticated visitors to trigger unwanted 302 redirects or 401 errors.
4. **Strict Secret Key Requirement Fallback (`config.py`)**:
   - If `FLASK_ENV=production` was configured without setting `FLASK_SECRET_KEY`, `config.py` threw an unhandled `RuntimeError`, killing the function.
5. **Missing Vercel Serverless Entrypoint & Config**:
   - Without `vercel.json` rewrites and `api/index.py`, Vercel could not determine how to map incoming web traffic to the Flask application.

### Solutions Applied
- Added `Union` to imports in `utils/database.py`.
- Restored `from utils.csrf import csrf, CSRFError, generate_csrf` in `app.py`.
- Added missing public routes (`"privacy_policy"`, `"forgot_password"`, `"reset_password"`, `"get_company_profile"`) to `public_endpoints` in `app.py`.
- Updated `config.py` with multi-OS temporary storage fallbacks and safe serverless secret key handling with clear warnings.
- Created `api/index.py` and `vercel.json` for proper Vercel routing.
- Created `utils/deployment_check.py` and `tests/test_deployment.py` to prevent future regressions.

---

## 3. Required & Recommended Environment Settings

Configure these variables in your **Vercel Project Settings > Environment Variables** (or in your `.env` file for local development):

| Variable Name | Required? | Default Value | Description |
|---|---|---|---|
| `FLASK_SECRET_KEY` | **Required (Prod)** | `dev-secret-key-12345` | Cryptographic key used to sign session cookies and CSRF tokens. Must be a long random string in production. |
| `GEMINI_API_KEY` | **Required (AI)** | `""` | Google Gemini API key used for resume evaluation, ATS scoring, and interview generation. |
| `ADMIN_SECRET_KEY` | Optional | `admin-default-secret-key-2026` | Key required for accessing administrative backup and migration endpoints. |
| `FLASK_ENV` | Optional | `production` | Set to `production` on live deployments; enables secure cookie attributes (`Secure`, `HttpOnly`, `SameSite=Lax`). |
| `RATE_LIMIT_ENABLED` | Optional | `true` | Enables in-memory endpoint rate limiting to prevent abuse. |
| `RATE_LIMIT_ANALYZE` | Optional | `5/hour` | Quota limit for computationally expensive resume analysis calls. |
| `MAX_UPLOAD_SIZE_MB` | Optional | `5` | Maximum allowed file size for resume uploads in megabytes. |
| `LOG_LEVEL` | Optional | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `SESSION_TIMEOUT_MINUTES` | Optional | `30` | Inactivity duration in minutes before user session automatically expires. |

---

## 4. How to Deploy to Vercel

### Option A: Via GitHub Integration (Recommended)
1. Push your repository to GitHub.
2. Go to the [Vercel Dashboard](https://vercel.com/dashboard) and click **"Add New..." > "Project"**.
3. Select your GitHub repository.
4. Under **Environment Variables**, add:
   - `FLASK_SECRET_KEY`: `<your-random-secret-key>`
   - `GEMINI_API_KEY`: `<your-google-gemini-api-key>`
5. Leave Build & Output Settings as default (Vercel automatically detects `vercel.json` and `requirements.txt`).
6. Click **Deploy**.

### Option B: Via Vercel CLI
```bash
# Install Vercel CLI globally
npm install -g vercel

# Link and deploy to production
vercel --prod
```

---

## 5. Lightweight Pre-Flight Deployment Check

To prevent broken releases from ever reaching production, a lightweight pre-flight deployment check is included:

### Running the Check Locally
```bash
python utils/deployment_check.py
```

Expected output:
```text
======================================================================
  AI Campus Placement Agent - Deployment Pre-Flight Smoke Check
======================================================================
[PASS] Configuration Files: vercel.json, api/index.py, requirements.txt verified.
[PASS] App WSGI Initialization: Module imports clean without runtime NameErrors.

--- Public Routes Probe ---
  [PASS] /                      200    59.3ms - Home landing page
  [PASS] /healthz               200    10.3ms - Health probe / readiness endpoint
  [PASS] /health                200    10.5ms - Health alias endpoint
  [PASS] /api/health            200    11.0ms - API health check
  [PASS] /login                 200    16.4ms - Authentication login page
  [PASS] /register              200    10.9ms - Student registration page
  [PASS] /privacy               200     8.5ms - Privacy policy page
  [PASS] /forgot-password       200    11.1ms - Password recovery page
  [PASS] /api/company/Google    200    10.0ms - Company hiring guide profile API
======================================================================
  RESULT: DEPLOYMENT CHECK PASSED (Release ready for Vercel)
======================================================================
```

### Running via Pytest
```bash
pytest tests/test_deployment.py -v --no-cov
```

### CI/CD Integration
The check is automatically run as part of the GitHub Actions CI workflow (`.github/workflows/ci.yml`) under the `environment-diagnostics` job before tests or builds proceed.

