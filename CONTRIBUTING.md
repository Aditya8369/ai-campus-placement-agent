# Contributing to AI Campus Placement Agent

Thank you for your interest in contributing to the AI Campus Placement Agent! We welcome contributions from the community to help improve this open-source project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Contributing Guidelines](#contributing-guidelines)
- [Contributing Company Interview Preparation Guides](#contributing-company-interview-preparation-guides)
- [Pull Request Process](#pull-request-process)
- [Reporting Issues](#reporting-issues)

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting Started

### Prerequisites

- Python 3.9 or higher
- pip (Python package manager)
- Git

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/deepikagandla74/ai-campus-placement-agent.git
   cd ai-campus-placement-agent
   ```

## Development Setup

1. Install dependencies (including testing and linting tools):
   ```bash
   pip install -r requirements.txt
   pip install flake8 black isort pytest pytest-cov
   ```

2. Set up environment variables:
   - Copy `.env.example` (if available) or create a `.env` file
   - Add your Gemini API key:
     ```
     FLASK_SECRET_KEY=replace_with_a_long_random_secret
     GEMINI_API_KEY=your_gemini_api_key_here
     ```

3. Populate Synthetic Local Development Data (Optional but Recommended):
   Contributors can populate safe synthetic data to test dashboards, job applications, mock interviews, and reports without creating data manually or needing API keys:
   ```bash
   # Seed an isolated local development database
   python utils/seed_data.py
   # or
   flask seed run

   # Test logins:
   # Student: contributor.demo@seed.local / Password123!
   # Admin:   admin.demo@seed.local / AdminPassword123!
   ```

4. Run the application:
   ```bash
   # To use the seeded development database:
   # Linux / macOS:
   export DATABASE_PATH="placement_agent_dev.db" && python app.py
   # Windows (PowerShell):
   $env:DATABASE_PATH="placement_agent_dev.db"; python app.py
   ```

5. Visit `http://127.0.0.1:5000/` in your browser

6. Verify local tests and lint checks (matching CI workflow):
   ```bash
   # Run flake8 critical syntax and undefined name checks
   flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics

   # Run automated pytest test suite
   pytest

   # Run pre-flight diagnostic validators
   python utils/ci_pipeline_validator.py
   python utils/deployment_check.py
   ```

## Contributing Guidelines

### What Can I Contribute?

We welcome contributions in the following areas:

- **Bug fixes**: Help us squash bugs and improve stability
- **New features**: Propose and implement new placement-related features
- **Documentation**: Improve documentation, add examples, or write tutorials
- **UI/UX improvements**: Enhance the user interface and experience
- **Performance optimizations**: Make the application faster and more efficient
- **Test coverage**: Add tests to improve code reliability

### Working on an Issue

Before starting a substantial change, open or claim an issue and confirm the proposed approach with the maintainers. This helps avoid duplicate work and keeps contributions aligned with the project.

Issues intended for new contributors should explain the problem, expected outcome, relevant files or routes, reproduction steps where applicable, and how the change can be verified. Maintainers should label issues by scope and difficulty only when those labels are meaningful and the task is ready to work on.

For NSoC Project Kernel consideration, the project maintainer is responsible for keeping real, well-scoped issues for different experience levels, reviewing pull requests, and helping contributors understand the codebase. These are responsibilities described on the [official NSoC site](https://www.nsoc.in/); they are not a promise of acceptance into the program.

### Development Workflow

1. Create a new branch for your feature or bugfix:
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/your-bugfix-name
   ```

2. Make your changes following our coding standards:
   - Follow PEP 8 style guidelines
   - Write clear, descriptive commit messages
   - Add comments for complex logic
   - Update relevant documentation

3. Test your changes thoroughly:
   - Run linter: `flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics`
   - Run tests: `pytest`
   - Run diagnostics: `python utils/ci_pipeline_validator.py` and `python utils/deployment_check.py`
   - Ensure the automated CI workflow will pass without lint errors or test failures
   - Test the specific feature you modified and check for regressions

4. Commit your changes:
   ```bash
   git add .
   git commit -m "Short description of your changes"
   ```

### Coding Standards

- **Python**: Follow PEP 8 style guide
- **HTML/CSS/JS**: Follow modern best practices
- **Comments**: Add docstrings to functions and classes
- **Variable naming**: Use descriptive, meaningful names
- **Error handling**: Include proper error handling and logging

### Subresource Integrity (SRI) for Frontend Libraries (#648)

To protect users against Content Delivery Network (CDN) tampering or malicious resource manipulation, **all external scripts and stylesheets loaded in `templates/` must use Subresource Integrity (SRI)**.

#### Requirements for External Resources:
1. **Pinned Version**: URLs must reference an exact semantic version (e.g. `@5.3.0` or `@4.6.1`). Floating tags such as `latest`, major-only specifiers like `@5/`, or unversioned URLs are prohibited.
2. **Integrity Attribute**: Tags must define `integrity="sha384-..."` (or `sha256-` / `sha512-`).
3. **Crossorigin Attribute**: Tags must specify `crossorigin="anonymous"`.
4. **CSP Compatibility**: External hostnames must already be permitted in the Content-Security-Policy (CSP) headers in `routes/__init__.py`. Currently allowed origins include `cdn.jsdelivr.net` and `cdnjs.cloudflare.com`.

#### How to Compute an SRI Hash for a New Library:

When introducing a new library or upgrading an existing one, compute the cryptographic SHA-384 digest of the exact file:

- **Using cURL and OpenSSL (Linux / macOS / Git Bash)**:
  ```bash
  curl -sSL "https://cdn.jsdelivr.net/npm/package@1.2.3/dist/file.min.js" | openssl dgst -sha384 -binary | openssl base64 -A
  ```

- **Using Python**:
  ```bash
  python -c "import urllib.request, hashlib, base64; d = urllib.request.urlopen('https://cdn.jsdelivr.net/npm/package@1.2.3/dist/file.min.js').read(); print('sha384-' + base64.b64encode(hashlib.sha384(d).digest()).decode())"
  ```

- **Using Online Generators**:
  You can also use tools like [SRI Hash Generator](https://www.srihash.org/) or the integrity string provided on [cdnjs.com](https://cdnjs.com/).

#### Example Tag Usage:
```html
<!-- Script -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"
        integrity="sha384-geWF76RCwLtnZ8qwWowPQNguL3RmwHVBC9FhGdlKrxdiJJigb/j/68SIy3Te4Bkz"
        crossorigin="anonymous"></script>

<!-- Stylesheet -->
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
      rel="stylesheet"
      integrity="sha384-9ndCyUaIbzAi2FUVXJi0CjmCapSmO7SnpJef0486qhLnuZ2cdeRhO02iuK6FUUVM"
      crossorigin="anonymous">
```

Run the validator locally to confirm compliance:
```bash
python utils/sri_validator.py
```

### Property-Based Testing with Hypothesis (#692)

To ensure pure functions in the platform (parsers, sanitizers, validators, regional formatters, and scoring engines) handle arbitrary user inputs, Unicode artifacts, boundary values, and extreme numbers without crashing or returning invalid results, we use **[Hypothesis](https://hypothesis.readthedocs.io/)** for property-based testing.

Unlike example-based tests that only check inputs anticipated by developers, property-based tests randomly generate hundreds of permutations (including empty strings, unusual Unicode symbols, ligature characters, extreme numeric values, and special file paths) and automatically shrink any failing input down to the minimal reproducible case.

#### Running Property-Based Tests Locally:
```bash
# Run the complete property-based test suite
pytest tests/test_property_based.py -v

# Run with custom verbosity or statistics
pytest tests/test_property_based.py -v --hypothesis-show-statistics
```

#### How to Add or Extend a Property-Based Test:

When writing or modifying pure utility functions, validators, or calculation logic:

1. **Target Pure Functions**: Focus on functions that take inputs and produce outputs without side-effects (e.g. database transactions or network/API calls).
2. **Define Invariants / Properties**: Identify properties that must hold true for *all* valid or arbitrary inputs:
   - **No Unhandled Crashes**: Function always returns the expected type (`str`, `dict`, `int`) without raising unhandled exceptions on arbitrary strings.
   - **Score Bounds**: Numeric scores (e.g. ATS score, match score, bullet impact) must strictly stay within bounds (e.g. `0 <= score <= 100`).
   - **Determinism**: Repeating the function on the exact same input produces identical output.
   - **Idempotence**: `fn(fn(x)) == fn(x)` (e.g. text normalization, filename sanitization, skill canonicalization).
   - **Length & Security Contracts**: Outputs respect maximum length constraints and strip path traversal / injection markers.
3. **Keep Examples Fast for CI**: Use `@settings(max_examples=40, deadline=None)` or `@settings(max_examples=50, deadline=None)` so the full suite runs in under 10 seconds without slowing down CI.
4. **Capture Failing Examples as Regression Tests**: Whenever Hypothesis identifies an edge case bug (such as `decimals=0` or `NaN`/`Infinity` floats in formatters), fix the underlying function and commit the minimal failing example to `TestHypothesisDiscoveredRegressions` in `tests/test_property_based.py`.

#### Example Property-Based Test Pattern:
```python
from hypothesis import given, settings, strategies as st
from utils.file_validation_service import sanitize_filename

@settings(max_examples=50, deadline=None)
@given(
    raw_name=st.one_of(st.text(max_size=300), st.none()),
    max_length=st.integers(min_value=10, max_value=200)
)
def test_prop_sanitize_filename_invariants(raw_name: str | None, max_length: int):
    clean = sanitize_filename(raw_name, max_length=max_length)
    assert isinstance(clean, str)
    assert 0 < len(clean) <= max_length
    assert "/" not in clean and "\\" not in clean and "\x00" not in clean
    # Idempotent
    assert sanitize_filename(clean, max_length=max_length) == clean
```

### Route Organization & Where to Add New Routes (#553)

The application has been refactored from a monolithic `app.py` into modular Flask Blueprints grouped by feature area inside the `routes/` package. **`app.py` is a thin entry point** exporting `app = create_app()` and should not have new routes added to it directly.

When adding or modifying routes, place them in the corresponding Blueprint module:

- **`routes/auth.py`**: Authentication, login/logout, registration, two-factor auth (2FA), session lifecycle, password recovery.
- **`routes/analysis.py`**: Resume uploads, ATS evaluation, resume diff/comparisons, dashboards, role skill gaps.
- **`routes/interview.py`**: Mock interviews, speech & STAR evaluation, aptitude practice, group discussions, and interview preparation notes.
- **`routes/coding_practice.py`**: Coding problems, sandbox execution, problem bookmarks, submission tracking.
- **`routes/tracker.py`**: Job application tracking pipelines, placement milestones, calendar deadlines, and reminder preferences.
- **`routes/jobs.py`**: Job recommendations, company profiles, internship feeds, GitHub/LinkedIn profile analyzers.
- **`routes/reports.py`**: PDF reports, certificates, skills gap downloads, watermarking, and read-only report sharing.
- **`routes/admin.py`**: Administrative AI metrics, Gemini usage tracking, database backups, and moderation queue.
- **`routes/api.py`**: Shared/utility endpoints (health checks, system status, i18n translations, walkthroughs).
- **`routes/common.py`**: Shared constants (`APPLICATION_STAGES`, `WALKTHROUGH_STEPS_CATALOG`, caches), agent instances, and helper functions.

Use the Blueprint decorator for your area (e.g. `@interview_bp.route("/path")` rather than `@app.route(...)`). URL endpoints remain backwards-compatible across templates and tests with automatic alias mapping.

## Pull Request Process

1. **Update Documentation**: If your changes affect functionality, update the README or relevant documentation

2. **Commit Messages**: Use clear, descriptive commit messages:
   - `feat: add new interview evaluation feature`
   - `fix: resolve PDF parsing error for certain formats`
   - `docs: update installation instructions`
   - `refactor: simplify database initialization`

3. **Push to Your Fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

4. **Create Pull Request**:
   - Go to the original repository on GitHub
   - Click "New Pull Request"
   - Select your branch
   - Fill out the PR template with details about your changes
   - Link related issues using `#issue-number`

5. **Review Process**:
   - Maintainers will review your PR
   - Address any feedback or requested changes
   - Once approved, your PR will be merged

### PR Checklist

Before submitting your PR, ensure:

- [ ] Code follows the project's style guidelines
- [ ] Changes are tested; PR describes what was run and any checks not run
- [ ] Documentation is updated if needed
- [ ] Commit messages are clear and descriptive
- [ ] No merge conflicts with the main branch
- [ ] PR description explains the "why" and "what" of changes
- [ ] PR is linked to a relevant issue or explains why no issue was needed

## Reporting Issues

### Bug Reports

When reporting a bug, please include:

- **Title**: Clear, descriptive bug title
- **Description**: Detailed explanation of the bug
- **Steps to Reproduce**: Clear steps to reproduce the issue
- **Expected Behavior**: What you expected to happen
- **Actual Behavior**: What actually happened
- **Screenshots**: If applicable, add screenshots

### Feature Requests

For feature requests, please include:

- **Title**: Clear feature title
- **Description**: Detailed description of the feature
- **Use Case**: Why this feature would be useful
- **Proposed Solution**: How you envision the feature working
- **Alternatives**: Any alternative solutions considered

## Questions

If you have questions about contributing:

- Check existing [Issues](https://github.com/deepikagandla74/ai-campus-placement-agent/issues)
- Open an [Issue](https://github.com/deepikagandla74/ai-campus-placement-agent/issues) with your question
- Contact maintainers through the repository

## Recognition

Contributors will be recognized in the project's CONTRIBUTORS file.

Thank you for contributing to AI Campus Placement Agent! 🚀
