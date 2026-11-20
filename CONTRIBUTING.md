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

3. Run the application:
   ```bash
   python app.py
   ```

4. Visit `http://127.0.0.1:5000/` in your browser

5. Verify local tests and lint checks (matching CI workflow):
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

## Contributing Company Interview Preparation Guides

We welcome community contributions to expand and update our company-specific interview preparation guides!

### How It Works

1. All company interview guides are stored in a single contributor-maintained JSON file: [`data/company_interview_prep.json`](data/company_interview_prep.json).
2. A contribution template with example structure is provided at [`data/company_contribution_template.json`](data/company_contribution_template.json).
3. **No code changes are required** — adding or updating a company in `data/company_interview_prep.json` immediately populates the company selector in the interview simulator and serves tips via the API.
4. If a student targets a company not yet in the data file, the system automatically falls back to general preparation tips.

### Guide Schema Requirements

Every company entry must contain the following fields:

| Field | Type | Description |
|---|---|---|
| `company_name` | `string` | Display name of the company (e.g. `"Google"`, `"Amazon"`). |
| `typical_rounds` | `list[string]` | Step-by-step recruitment stages (e.g. Online Assessment, Tech 1, Tech 2, HR). |
| `commonly_tested_topics` | `list[string]` | Key topics frequently asked (e.g. Dynamic Programming, Trees, System Design, SQL). |
| `preparation_tips` | `list[string]` | Actionable advice and strategic suggestions for students. |
| `last_updated` | `string (YYYY-MM-DD)` | Date of the latest verification or update (e.g. `"2026-11-18"`). |
| `community_contributed` | `boolean` | Set to `true` to indicate community contribution. |

### Example Entry

```json
{
  "Stripe": {
    "company_name": "Stripe",
    "typical_rounds": [
      "Round 1: Online Technical Assessment (Practical Coding / Bug Investigation)",
      "Round 2: Technical Phone Screen (API Integration or Data Structures)",
      "Round 3: Onsite Practical Coding (Working in a real codebase)",
      "Round 4: System Architecture & Design",
      "Round 5: Cultural Alignment & Teamwork"
    ],
    "commonly_tested_topics": [
      "API Design & HTTP Protocol",
      "Real-world Refactoring & Debugging",
      "Data Structures & Algorithmic Analysis",
      "System Scalability & Reliability",
      "Clean Code & Error Handling"
    ],
    "preparation_tips": [
      "Stripe tests practical development skills — be comfortable writing and reading real code.",
      "Get familiar with reading documentation and writing clean API calls.",
      "Explain your thought process continuously during coding rounds.",
      "Emphasize reliability, edge cases, and user experience in architectural questions."
    ],
    "last_updated": "2026-11-18",
    "community_contributed": true
  }
}
```

### Steps to Submit

1. Copy the structure from `data/company_contribution_template.json`.
2. Add your new company key to `data/company_interview_prep.json` (or update an existing entry with recent insights and an updated `last_updated` date).
3. Run the test suite:
   ```bash
   pytest tests/test_company_interview_prep.py
   ```
4. Submit a Pull Request titled `feat(data): add interview prep guide for <Company Name>`.

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
