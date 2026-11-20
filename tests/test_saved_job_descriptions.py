"""
Tests for Saved Job Descriptions Library (#560).
Covers:
- Acceptance Criterion 1: A saved description can be selected and used in a new analysis.
- Acceptance Criterion 2: Rename, edit and delete work and ask for confirmation on delete.
- Acceptance Criterion 3: Limits are enforced with clear messages (count limit and text length).
- Acceptance Criterion 4: Tests cover permissions (another user's entries are never visible).
- Text escaping and XSS prevention.
"""

from unittest.mock import patch
import html
import pytest
from app import app
import config
from utils.database import (
    init_db,
    create_saved_job_description,
    get_saved_job_descriptions,
    get_saved_job_description_by_id,
    update_saved_job_description,
    delete_saved_job_description,
    count_saved_job_descriptions,
    rename_saved_job_description,
)


@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_saved_jd.db"
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    with patch.object(config, "DATABASE_PATH", str(test_db)), \
         patch.object(config, "REPORT_FOLDER", str(report_dir)):
        init_db()
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        app.config["ENFORCE_LOGIN_IN_TESTS"] = False
        with app.test_client() as test_client:
            with app.app_context():
                yield test_client


def test_saved_job_description_permissions_isolation(client):
    """
    Acceptance Criterion: Tests cover permissions (another user's entries are never visible).
    User B should never see, edit, rename, or delete User A's saved job descriptions.
    """
    # 1. Create a saved job description for Alice
    alice_jd = create_saved_job_description(
        student_id="student_alice",
        company_name="Google",
        role_title="Software Engineer - Backend",
        source="https://careers.google.com/jobs/123",
        description="Build scalable microservices in Python and Go.",
        notes="Alice's confidential referral note"
    )
    assert alice_jd["id"].startswith("saved-jd-")

    # 2. Bob visits the saved job descriptions web page
    with client.session_transaction() as sess:
        sess["user_id"] = "student_bob"
        sess["user_name"] = "Bob"

    res_bob_page = client.get("/saved-job-descriptions")
    assert res_bob_page.status_code == 200
    assert b"Software Engineer - Backend" not in res_bob_page.data
    assert b"Alice's confidential referral note" not in res_bob_page.data

    # 3. Bob checks the index dropdown on the home page
    res_bob_home = client.get("/")
    assert res_bob_home.status_code == 200
    assert b"Software Engineer - Backend" not in res_bob_home.data
    assert alice_jd["id"].encode() not in res_bob_home.data

    # 4. Bob calls the API list endpoint
    res_bob_api = client.get("/api/saved-job-descriptions")
    assert res_bob_api.status_code == 200
    bob_data = res_bob_api.get_json()
    assert bob_data["success"] is True
    assert len(bob_data["saved_job_descriptions"]) == 0

    # 5. Bob tries to access Alice's item via API GET
    res_bob_get = client.get(f"/api/saved-job-descriptions/{alice_jd['id']}")
    assert res_bob_get.status_code == 404

    # 6. Bob tries to edit Alice's item via web route
    res_bob_edit_view = client.get(f"/saved-job-descriptions/{alice_jd['id']}/edit")
    assert res_bob_edit_view.status_code == 302  # redirected with error message

    res_bob_edit_post = client.post(
        f"/saved-job-descriptions/{alice_jd['id']}/edit",
        data={
            "company_name": "Tampered",
            "role_title": "Tampered",
            "source": "",
            "description": "Tampered text",
            "notes": ""
        }
    )
    assert res_bob_edit_post.status_code == 302
    # Verify Alice's original record was NOT changed
    assert get_saved_job_description_by_id(alice_jd["id"], "student_alice")["company_name"] == "Google"

    # 7. Bob tries to rename Alice's item via web and API
    res_bob_rename_post = client.post(
        f"/saved-job-descriptions/{alice_jd['id']}/rename",
        data={"role_title": "Hacked Title"}
    )
    assert res_bob_rename_post.status_code == 302
    assert get_saved_job_description_by_id(alice_jd["id"], "student_alice")["role_title"] == "Software Engineer - Backend"

    res_bob_rename_api = client.post(
        f"/api/saved-job-descriptions/{alice_jd['id']}/rename",
        json={"role_title": "Hacked Title"}
    )
    assert res_bob_rename_api.status_code == 404

    # 8. Bob tries to delete Alice's item via web and API
    res_bob_delete_post = client.post(f"/saved-job-descriptions/{alice_jd['id']}/delete")
    assert res_bob_delete_post.status_code == 302
    assert get_saved_job_description_by_id(alice_jd["id"], "student_alice") is not None

    res_bob_delete_api = client.delete(f"/api/saved-job-descriptions/{alice_jd['id']}")
    assert res_bob_delete_api.status_code == 404
    assert get_saved_job_description_by_id(alice_jd["id"], "student_alice") is not None

    # 9. Now Alice visits her own page and verifies her data is present
    with client.session_transaction() as sess:
        sess["user_id"] = "student_alice"
        sess["user_name"] = "Alice"

    res_alice_page = client.get("/saved-job-descriptions")
    assert res_alice_page.status_code == 200
    assert b"Software Engineer - Backend" in res_alice_page.data
    assert b"Google" in res_alice_page.data

    res_alice_home = client.get("/")
    assert res_alice_home.status_code == 200
    assert b"Software Engineer - Backend" in res_alice_home.data
    assert alice_jd["id"].encode() in res_alice_home.data


def test_saved_job_description_crud_web_and_api(client):
    """
    Acceptance Criterion: Rename, edit and delete work and ask for confirmation on delete.
    """
    with client.session_transaction() as sess:
        sess["user_id"] = "student_carol"
        sess["user_name"] = "Carol"

    # 1. Create a saved job description via web POST
    res_create = client.post(
        "/saved-job-descriptions",
        data={
            "company_name": "Microsoft",
            "role_title": "Software Engineer II",
            "source": "https://careers.microsoft.com/job/456",
            "description": "Develop cloud services on Azure with C# and Python.",
            "notes": "Follow up with recruiter on Friday"
        },
        follow_redirects=True
    )
    assert res_create.status_code == 200
    assert b"Job description saved to your private library." in res_create.data
    assert b"Software Engineer II" in res_create.data

    descriptions = get_saved_job_descriptions("student_carol")
    assert len(descriptions) == 1
    jd_id = descriptions[0]["id"]

    # 2. Rename via web POST
    res_rename = client.post(
        f"/saved-job-descriptions/{jd_id}/rename",
        data={
            "role_title": "Senior Cloud Engineer",
            "company_name": "Microsoft Azure"
        },
        follow_redirects=True
    )
    assert res_rename.status_code == 200
    assert b"Job description renamed successfully." in res_rename.data
    updated_rec = get_saved_job_description_by_id(jd_id, "student_carol")
    assert updated_rec["role_title"] == "Senior Cloud Engineer"
    assert updated_rec["company_name"] == "Microsoft Azure"

    # 3. Rename via API
    res_api_rename = client.post(
        f"/api/saved-job-descriptions/{jd_id}/rename",
        json={"role_title": "Principal Cloud Architect"}
    )
    assert res_api_rename.status_code == 200
    assert res_api_rename.get_json()["saved_job_description"]["role_title"] == "Principal Cloud Architect"

    # 4. Edit via web POST
    res_edit = client.post(
        f"/saved-job-descriptions/{jd_id}/edit",
        data={
            "company_name": "Microsoft Cloud",
            "role_title": "Principal Architect",
            "source": "",  # Optional link
            "description": "Lead multi-region distributed system architectures.",
            "notes": "Final interview scheduled"
        },
        follow_redirects=True
    )
    assert res_edit.status_code == 200
    assert b"Saved job description updated." in res_edit.data
    edited_rec = get_saved_job_description_by_id(jd_id, "student_carol")
    assert edited_rec["description"] == "Lead multi-region distributed system architectures."
    assert edited_rec["source"] == ""

    # 5. Edit via API PATCH
    res_api_patch = client.patch(
        f"/api/saved-job-descriptions/{jd_id}",
        json={"notes": "Offer letter received!"}
    )
    assert res_api_patch.status_code == 200
    assert res_api_patch.get_json()["saved_job_description"]["notes"] == "Offer letter received!"

    # 6. Verify confirmation on delete in template
    res_view = client.get("/saved-job-descriptions")
    assert res_view.status_code == 200
    assert b"confirm(" in res_view.data
    assert b"Are you sure you want to delete this saved job description?" in res_view.data

    # 7. Delete via web POST
    res_delete = client.post(
        f"/saved-job-descriptions/{jd_id}/delete",
        follow_redirects=True
    )
    assert res_delete.status_code == 200
    assert b"Saved job description deleted." in res_delete.data
    assert get_saved_job_description_by_id(jd_id, "student_carol") is None


def test_saved_job_description_limits_enforced(client):
    """
    Acceptance Criterion: Limits are enforced with clear messages.
    - Text length limit (> 15,000 chars rejected with clear error message)
    - Missing required fields (title, company, description)
    - Per-user limit (exceeding MAX_SAVED_JOB_DESCRIPTIONS_PER_USER is rejected with clear error message)
    """
    with client.session_transaction() as sess:
        sess["user_id"] = "student_david"
        sess["user_name"] = "David"

    # 1. Text length limit enforcement (> 15,000 chars)
    long_desc = "A" * 15001
    res_long = client.post(
        "/api/saved-job-descriptions",
        json={
            "role_title": "Engineer",
            "company_name": "Acme Corp",
            "description": long_desc
        }
    )
    assert res_long.status_code == 400
    assert "15,000 characters or fewer" in res_long.get_json()["error"]

    # 2. Missing title enforcement
    res_no_title = client.post(
        "/api/saved-job-descriptions",
        json={
            "role_title": "",
            "company_name": "Acme Corp",
            "description": "Valid job description text."
        }
    )
    assert res_no_title.status_code == 400
    assert "Job title is required" in res_no_title.get_json()["error"]

    # 3. Missing company enforcement
    res_no_comp = client.post(
        "/api/saved-job-descriptions",
        json={
            "role_title": "Developer",
            "company_name": "",
            "description": "Valid job description text."
        }
    )
    assert res_no_comp.status_code == 400
    assert "Company name is required" in res_no_comp.get_json()["error"]

    # 4. Missing description enforcement
    res_no_desc = client.post(
        "/api/saved-job-descriptions",
        json={
            "role_title": "Developer",
            "company_name": "Acme",
            "description": ""
        }
    )
    assert res_no_desc.status_code == 400
    assert "Job description text is required" in res_no_desc.get_json()["error"]

    # 5. Optional link: saving without link/source succeeds!
    res_optional_link = client.post(
        "/api/saved-job-descriptions",
        json={
            "role_title": "DevOps Engineer",
            "company_name": "Acme Cloud",
            "description": "Docker and Kubernetes CI/CD setup."
            # source/link omitted
        }
    )
    assert res_optional_link.status_code == 201
    assert res_optional_link.get_json()["success"] is True

    # 6. Per-user limit enforcement
    # Save up to MAX_SAVED_JOB_DESCRIPTIONS_PER_USER (25)
    current_count = count_saved_job_descriptions("student_david")
    max_limit = getattr(config, "MAX_SAVED_JOB_DESCRIPTIONS_PER_USER", 25)

    for i in range(current_count, max_limit):
        create_saved_job_description(
            student_id="student_david",
            company_name=f"Company {i}",
            role_title=f"Role {i}",
            description=f"Job description content for role {i}."
        )

    assert count_saved_job_descriptions("student_david") == max_limit

    # Attempting to add one more via API should fail with clear limit message
    res_exceed_api = client.post(
        "/api/saved-job-descriptions",
        json={
            "role_title": "One Too Many",
            "company_name": "Over Limit Corp",
            "description": "Exceeding limit description."
        }
    )
    assert res_exceed_api.status_code == 400
    error_msg = res_exceed_api.get_json()["error"]
    assert "Limit reached" in error_msg
    assert str(max_limit) in error_msg

    # Attempting to add one more via web form should redirect with clear flashed message
    res_exceed_web = client.post(
        "/saved-job-descriptions",
        data={
            "role_title": "One Too Many Web",
            "company_name": "Over Limit Corp",
            "description": "Exceeding limit description."
        },
        follow_redirects=True
    )
    assert res_exceed_web.status_code == 200
    assert b"Limit reached" in res_exceed_web.data
    assert str(max_limit).encode() in res_exceed_web.data


def test_saved_job_description_selection_and_analysis_use(client):
    """
    Acceptance Criterion: A saved description can be selected and used in a new analysis.
    Verifies that the dropdown option contains the saved description and
    that passing saved_job_description or submitting it to the form works.
    """
    with client.session_transaction() as sess:
        sess["user_id"] = "student_eva"
        sess["user_name"] = "Eva"

    saved = create_saved_job_description(
        student_id="student_eva",
        company_name="Amazon",
        role_title="SDE Intern",
        source="https://amazon.jobs/123",
        description="Write Java code, work on AWS Lambdas, design DynamoDB tables."
    )

    # 1. Verify that the saved item appears in the dropdown on the index page
    res_home = client.get("/")
    assert res_home.status_code == 200
    assert b"Amazon - SDE Intern" in res_home.data
    assert b"data-description=" in res_home.data
    assert b"Write Java code, work on AWS Lambdas" in res_home.data
    assert b'id="btnSaveJobDescription"' in res_home.data

    # 2. Verify that clicking "Use for Analysis" loads index with saved_job_description param
    res_with_param = client.get(f"/?saved_job_description={saved['id']}")
    assert res_with_param.status_code == 200
    assert saved["id"].encode() in res_with_param.data


def test_saved_job_description_escaping_and_xss_prevention(client):
    """
    Acceptance Criterion: Escape all saved text when displaying it.
    Verifies that potential script injection and HTML payloads are properly escaped.
    """
    with client.session_transaction() as sess:
        sess["user_id"] = "student_security"
        sess["user_name"] = "SecurityTester"

    xss_payload = "<script>alert('xss')</script>"
    xss_company = "Hacker & Co <img src=x onerror=alert(1)>"
    xss_notes = "<b>Bold</b> & \"quotes\""

    saved = create_saved_job_description(
        student_id="student_security",
        company_name=xss_company,
        role_title=xss_payload,
        source="https://example.com/job?q=1&v=2",
        description=xss_payload + " Looking for secure developer.",
        notes=xss_notes
    )

    # Check on management page
    res_page = client.get("/saved-job-descriptions")
    assert res_page.status_code == 200
    # Must NOT contain raw unescaped script tags
    assert b"<script>alert('xss')</script>" not in res_page.data
    assert b"<img src=x onerror=alert(1)>" not in res_page.data
    # Must contain HTML escaped versions
    assert b"&lt;script&gt;alert(" in res_page.data
    assert b"&lt;/script&gt;" in res_page.data
    assert b"Hacker &amp; Co" in res_page.data

    # Check on index page dropdown
    res_home = client.get("/")
    assert res_home.status_code == 200
    assert b"<script>alert('xss')</script>" not in res_home.data
    assert b"&lt;script&gt;alert(" in res_home.data


def test_unauthenticated_access_is_blocked(client):
    """
    Acceptance Criterion: Keep the library private to the user.
    Unauthenticated users cannot access or tamper with saved job descriptions.
    """
    app.config["ENFORCE_LOGIN_IN_TESTS"] = True
    try:
        # 1. UI route redirects to login
        res_web = client.get("/saved-job-descriptions")
        assert res_web.status_code == 302
        assert "/login" in res_web.headers["Location"]

        # 2. API list returns 401
        res_api = client.get("/api/saved-job-descriptions")
        assert res_api.status_code == 401

        # 3. API create returns 401
        res_post = client.post(
            "/api/saved-job-descriptions",
            json={"role_title": "Test", "company_name": "Test", "description": "Test description"}
        )
        assert res_post.status_code == 401
    finally:
        app.config["ENFORCE_LOGIN_IN_TESTS"] = False
