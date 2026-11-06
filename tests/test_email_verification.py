import pytest
import uuid
from app import app
from utils.database import (
    init_db,
    create_user,
    get_user_by_email,
    generate_email_verification_token,
    verify_user_email_token,
    is_user_email_verified,
    get_db_connection
)
from werkzeug.security import generate_password_hash


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    yield


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["TESTING_BYPASS_VERIFICATION"] = False
    with app.test_client() as client:
        yield client


class TestEmailVerificationDatabase:
    """Unit tests for email verification token storage and verification lifecycle (#206)."""

    def test_generate_and_verify_token_success(self):
        user_id = str(uuid.uuid4())
        email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        create_user(user_id, "Verification Test Student", email, generate_password_hash("password123"))

        # Verify initial status is unverified (0)
        assert is_user_email_verified(user_id) is False

        # Generate verification token
        token = generate_email_verification_token(user_id)
        assert token is not None
        assert token.startswith("verify_")

        # Verify with valid token
        verified_user = verify_user_email_token(token)
        assert verified_user is not None
        assert verified_user["id"] == user_id
        assert verified_user["email"] == email
        assert verified_user["is_verified"] == 1

        # Check in DB
        assert is_user_email_verified(user_id) is True

        # Token should be consumed/cleared; reuse should fail
        assert verify_user_email_token(token) is None

    def test_verify_invalid_or_empty_token(self):
        assert verify_user_email_token("") is None
        assert verify_user_email_token("   ") is None
        assert verify_user_email_token("nonexistent_token_12345") is None

    def test_check_nonexistent_user_verified(self):
        assert is_user_email_verified("nonexistent-user-id") is False


class TestEmailVerificationRoutes:
    """Integration tests for web authentication flow with email verification (#206)."""

    def test_register_creates_unverified_user_and_token(self, client):
        email = f"student_{uuid.uuid4().hex[:8]}@example.com"
        password = "strong_password_123"

        response = client.post("/register", data={
            "name": "Jane Doe",
            "email": email,
            "password": password
        }, follow_redirects=True)

        assert response.status_code == 200
        # Should redirect to login with verification notification
        assert b"Registration successful" in response.data or b"verification link" in response.data

        # Check DB user status
        user = get_user_by_email(email)
        assert user is not None
        assert user["is_verified"] == 0
        assert user["verification_token"] is not None
        assert user["verification_token"].startswith("verify_")

    def test_unverified_user_cannot_login(self, client):
        email = f"unverified_{uuid.uuid4().hex[:8]}@example.com"
        password = "password12345"
        user_id = str(uuid.uuid4())
        create_user(user_id, "Unverified User", email, generate_password_hash(password))

        # Attempt login before verification
        response = client.post("/login", data={
            "email": email,
            "password": password
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b"Please verify your email address before logging in" in response.data
        assert b"Resend Verification Email" in response.data


    def test_verify_email_endpoint_activates_account(self, client):
        email = f"verify_route_{uuid.uuid4().hex[:8]}@example.com"
        password = "password12345"
        user_id = str(uuid.uuid4())
        create_user(user_id, "Route Verifier", email, generate_password_hash(password))
        token = generate_email_verification_token(user_id)

        # Hit the verification endpoint
        verify_resp = client.get(f"/verify-email/{token}", follow_redirects=True)
        assert verify_resp.status_code == 200
        assert b"Your email has been verified" in verify_resp.data

        # Now login should succeed
        login_resp = client.post("/login", data={
            "email": email,
            "password": password
        }, follow_redirects=True)

        assert login_resp.status_code == 200
        assert b"Login successful" in login_resp.data
        with client.session_transaction() as session:
            assert session.get("user_id") == user_id

    def test_verify_with_invalid_token_redirects_to_resend(self, client):
        resp = client.get("/verify-email/completely-invalid-token", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Invalid or expired verification link" in resp.data
        assert b"Verify Your Account" in resp.data

    def test_resend_verification_get_and_post(self, client):
        email = f"resend_user_{uuid.uuid4().hex[:8]}@example.com"
        user_id = str(uuid.uuid4())
        create_user(user_id, "Resend User", email, generate_password_hash("password12345"))
        old_token = generate_email_verification_token(user_id)

        # GET page
        get_resp = client.get(f"/resend-verification?email={email}")
        assert get_resp.status_code == 200
        assert b"Verify Your Account" in get_resp.data
        assert email.encode() in get_resp.data

        # POST resend
        post_resp = client.post("/resend-verification", data={"email": email}, follow_redirects=True)
        assert post_resp.status_code == 200
        assert b"new verification link has been sent" in post_resp.data

        # Verify old token changed
        updated_user = get_user_by_email(email)
        assert updated_user["verification_token"] != old_token
        assert updated_user["verification_token"] is not None

    def test_resend_verification_already_verified(self, client):
        email = f"already_verified_{uuid.uuid4().hex[:8]}@example.com"
        user_id = str(uuid.uuid4())
        create_user(user_id, "Already Verified", email, generate_password_hash("password12345"))
        token = generate_email_verification_token(user_id)
        verify_user_email_token(token)

        resp = client.post("/resend-verification", data={"email": email}, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Your email is already verified" in resp.data
