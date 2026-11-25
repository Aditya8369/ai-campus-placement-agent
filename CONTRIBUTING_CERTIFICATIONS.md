# Contributing Verified Certifications and Courses (#757)

Thank you for helping campus students bridge their skill gaps with high-quality, verified certifications and courses!

## How It Works
Students who see missing skills on their placement analysis receive up to three curated certification and course recommendations.
All recommendations are loaded directly from [`data/skill_certifications.json`](data/skill_certifications.json).

**No code changes are required to add or update recommendations. Simply edit the JSON data file.**

---

## Contribution Criteria
1. **Verified Links Only**: Verify that every URL resolves directly to the course or certification landing page (no broken links, paywalls behind deceptive ads, or link shorteners).
2. **Quality Providers**: Prefer industry-recognized providers such as:
   - Official cloud/vendor certifications (AWS, Google Cloud, Microsoft Azure, Oracle, Docker, CNCF, HashiCorp, Linux Foundation, MongoDB, Apollo).
   - University/Industry platforms (Coursera, edX, Harvard CS50, freeCodeCamp, DeepLearning.AI, Stanford Online).
   - High-quality open educational resources.
3. **Up to Three Options**: Provide 1 to 3 high-impact options per skill (e.g., combining a free tutorial, a comprehensive course, and a formal certification).
4. **Required Attributes**:
   - `title`: Complete title of the course or credential.
   - `provider`: Organization or platform offering it.
   - `level`: `Beginner`, `Intermediate`, or `Advanced`.
   - `type`: `Free`, `Paid`, or `Free to Audit`.
   - `duration`: Approximate completion time (e.g. `20 hours`, `3 months (10 hrs/week)`).
   - `url`: Direct, verified link.
   - `last_verified`: Date formatted as `YYYY-MM-DD` when you checked the link and validity.

---

## Example Entry in `data/skill_certifications.json`
```json
"Rust": [
  {
    "title": "Learn Rust by Building Real-World Applications",
    "provider": "freeCodeCamp",
    "level": "Beginner",
    "type": "Free",
    "duration": "14 hours",
    "url": "https://www.freecodecamp.org/news/rust-crash-course-for-beginners/",
    "last_verified": "2026-11-25"
  }
]
```

See [`data/certification_contribution_template.json`](data/certification_contribution_template.json) for the full schema and template.
