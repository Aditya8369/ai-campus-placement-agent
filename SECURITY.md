# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in the AI Campus Placement Agent, please report it responsibly.

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, report the issue privately using [GitHub Security Advisories](https://github.com/deepikagandla74/ai-campus-placement-agent/security/advisories/new).

Include the following information in your report:

- A description of the vulnerability
- Steps to reproduce the issue
- Potential impact of the vulnerability
- Any suggested fixes or mitigations (if available)

### What to Expect

- We will acknowledge receipt of your report within 48 hours
- We will provide a detailed response within 7 days
- We will work with you to understand and validate the issue
- We will coordinate a fix and release plan
- We will credit you in the security advisory (unless you prefer to remain anonymous)

### Security Best Practices

When using this application:

1. **Keep API Keys Secure**: Never commit `.env` files or API keys to version control
2. **Use Environment Variables**: Always use environment variables for sensitive configuration
3. **Regular Updates**: Keep dependencies updated to receive security patches
4. **Secure Deployment**: Use HTTPS in production and configure proper CORS policies
5. **Input Validation**: The application includes input validation, but ensure proper deployment security

### Known Security Considerations

- **API Key Management**: Users must provide their own Gemini API key via environment variables
- **File Uploads**: PDF uploads are validated and restricted to `.pdf` extensions
- **Database**: SQLite is used for development. For production, consider PostgreSQL or MySQL with proper authentication
- **Session Management**: Flask secret keys should be set to strong, random values in production

### Dependency Management & Automated Vulnerability Scanning

We actively audit and update dependencies across Python and JavaScript to remediate known security vulnerabilities:

- **Python Dependencies**: Audited using `pip-audit` against PyPI/OSV advisories.
- **JavaScript Dependencies**: Audited using `npm audit` against GitHub Security Advisories.
- **Automated Dependabot**: Weekly pull requests for `github-actions`, `pip`, and `npm` ecosystems.
- **Comprehensive Guide**: See [docs/DEPENDENCY_SECURITY.md](docs/DEPENDENCY_SECURITY.md) for step-by-step triage, remediation, and exemption instructions.

### Dependency Vulnerability Management & CI Audits (#649)

To ensure dependencies remain secure and reliable across environments:
1. **Automated Dual-Ecosystem Scanning in CI**: Pull requests, main-branch commits, and weekly scheduled workflows execute automated audits via `python utils/dependency_audit.py`. The runner audits both Python (`requirements.txt`) and JavaScript (`package.json`).
2. **Production Focus & Dev-Warning Policy**: To avoid failing builds on irrelevant development-only tools (e.g., test runners, linters, code formatters), the scan audits production dependencies (`--omit=dev`) and enforces high/critical thresholds (`--audit-level=high`). Any excluded dev-only warnings are logged informatively with clear explanations in the GitHub Step Summary.
3. **Automated Grouped Updates**: Dependabot (`.github/dependabot.yml`) checks weekly for updates to Python packages, JavaScript packages, and GitHub Actions, grouping minor and patch updates into batched pull requests.

#### Handling Unfixable or Deferred Security Advisories
When a vulnerability is detected in an upstream package where no immediate patch is available or where an upgrade would introduce breaking changes, maintainers may record a **time-limited exemption**:
- **Python**: In `.pip-audit-ignore.yml`
- **JavaScript**: In `.npm-audit-ignore.json`

Every ignored advisory in either file **strictly requires**:
- `id`: The vulnerability identifier (e.g., `PYSEC-2026-2151`, `CVE-2026-XXXX`, or `GHSA-xxxx-yyyy-zzzz`).
- `package`: The name of the affected library.
- `reason`: A clear, documented technical justification explaining why the advisory cannot be upgraded immediately and any mitigations in place.
- `expiry`: A strict expiration date in `YYYY-MM-DD` (maximum recommended window: 90 days).

**Enforcement Policy**:
- The CI audit runner (`utils/dependency_audit.py`) strictly validates both ignore files.
- Any exemption missing a `reason` or `expiry` date is immediately rejected, causing CI to fail.
- Once the expiration date passes (`expiry < today`), the exemption automatically expires and the CI build fails until the dependency is upgraded or a renewed justification with a new expiration date is reviewed and merged.

### Security Resources

- [OWASP Python Security](https://owasp.org/www-project-python-security/)
- [Flask Security Best Practices](https://flask.palletsprojects.com/en/latest/security/)
- [Python Security Documentation](https://docs.python.org/3/library/security_warnings.html)

Thank you for helping keep the AI Campus Placement Agent and its users safe!
