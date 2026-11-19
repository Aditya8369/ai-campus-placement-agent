import json
import pytest
from app import app
from utils.database import get_db_connection, create_user
from utils.recovery_code_service import AccountRecoveryCodeService, recovery_code_service
from werkzeug.security import generate_password_hash


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


@pytest.fixture
def test_user():
    user_id = "test_user_rec_406"
    email = "rec406@example.com"
    password = "SecurePassword123!"
    password_hash = generate_password_hash(password)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id = ? OR email = ?", (user_id, email))
    cursor.execute("DELETE FROM account_recovery_codes WHERE user_id = ?", (user_id,))
    cursor.execute(
        """
        INSERT INTO users (id, name, email, password_hash, two_factor_enabled)
        VALUES (?, ?, ?, ?, 1)
        """,
        (user_id, "Recovery Test User", email, password_hash)
    )
    conn.commit()
    conn.close()

    return {
        "id": user_id,
        "email": email,
        "password": password,
        "password_hash": password_hash
    }


def test_recovery_code_generation_and_hashing(test_user):
    service = AccountRecoveryCodeService(code_count=10)
    user_id = test_user["id"]

    # 1. Generate code set
    result = service.generate_new_code_set(user_id, count=10)
    assert result["total_count"] == 10
    assert len(result["recovery_codes"]) == 10
    first_set_codes = list(result["recovery_codes"])

    # Verify formatting (XXXX-XXXX-XXXX)
    for code in first_set_codes:
        parts = code.split("-")
        assert len(parts) == 3
        for part in parts:
            assert len(part) == 4

    # Check status
    status = service.get_recovery_codes_status(user_id)
    assert status["has_codes"] is True
    assert status["total_count"] == 10
    assert status["remaining_count"] == 10
    assert status["consumed_count"] == 0

    # Verify plaintext is not stored in DB
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT code_hash FROM account_recovery_codes WHERE user_id = ?", (user_id,))
    stored = cursor.fetchall()
    conn.close()
    for row in stored:
        assert row["code_hash"] not in first_set_codes
        assert len(row["code_hash"]) == 64  # SHA-256 hex length


def test_recovery_code_single_use_consumption(test_user):
    service = AccountRecoveryCodeService()
    user_id = test_user["id"]

    result = service.generate_new_code_set(user_id, count=5)
    codes = result["recovery_codes"]
    test_code = codes[0]

    # First consumption succeeds
    success, msg = service.verify_and_consume_code(user_id, test_code)
    assert success is True
    assert "accepted" in msg.lower()
    assert "4" in msg  # 4 remaining

    # Second consumption of same code MUST fail
    second_try, second_msg = service.verify_and_consume_code(user_id, test_code)
    assert second_try is False
    assert "already consumed" in second_msg.lower() or "invalid" in second_msg.lower()

    # Verify status reflects 1 consumed, 4 remaining
    status = service.get_recovery_codes_status(user_id)
    assert status["remaining_count"] == 4
    assert status["consumed_count"] == 1


def test_generating_new_set_invalidates_old_codes(test_user):
    service = AccountRecoveryCodeService()
    user_id = test_user["id"]

    # Generate Set A
    set_a = service.generate_new_code_set(user_id, count=4)
    code_a = set_a["recovery_codes"][0]

    # Generate Set B
    set_b = service.generate_new_code_set(user_id, count=4)
    code_b = set_b["recovery_codes"][0]

    # Verify code from Set A is now invalid
    valid_a, msg_a = service.verify_and_consume_code(user_id, code_a)
    assert valid_a is False

    # Verify code from Set B is valid
    valid_b, msg_b = service.verify_and_consume_code(user_id, code_b)
    assert valid_b is True


def test_generate_download_text(test_user):
    service = AccountRecoveryCodeService()
    codes = ["A1B2-C3D4-E5F6", "G7H8-J9K0-L1M2"]
    text = service.generate_download_text(test_user["email"], codes)

    assert "AI CAMPUS PLACEMENT AGENT" in text
    assert test_user["email"] in text
    assert "A1B2-C3D4-E5F6" in text
    assert "G7H8-J9K0-L1M2" in text
    assert "Single-use" in text or "ONCE" in text


def test_api_status_and_generate(client, test_user):
    with client.session_transaction() as sess:
        sess["user_id"] = test_user["id"]

    # 1. Check initial status
    res = client.get("/api/account/recovery-codes/status")
    assert res.status_code == 200
    assert res.get_json()["success"] is True

    # 2. Generate with wrong password
    bad_gen = client.post("/api/account/recovery-codes/generate", json={"password": "WrongPassword"})
    assert bad_gen.status_code == 403
    assert bad_gen.get_json()["success"] is False

    # 3. Generate with correct password
    good_gen = client.post("/api/account/recovery-codes/generate", json={"password": test_user["password"]})
    assert good_gen.status_code == 201
    gen_data = good_gen.get_json()
    assert gen_data["success"] is True
    assert len(gen_data["recovery_codes"]) == 10
    active_code = gen_data["recovery_codes"][0]

    # 4. Verify code via API
    ver_res = client.post("/api/account/recovery-codes/verify", json={
        "user_id": test_user["id"],
        "code": active_code
    })
    assert ver_res.status_code == 200
    assert ver_res.get_json()["success"] is True

    # 5. Re-verifying same code fails
    repeat_res = client.post("/api/account/recovery-codes/verify", json={
        "user_id": test_user["id"],
        "code": active_code
    })
    assert repeat_res.status_code == 400
    assert repeat_res.get_json()["success"] is False


def test_ui_routes_and_download(client, test_user):
    with client.session_transaction() as sess:
        sess["user_id"] = test_user["id"]

    # Dashboard page
    dash_res = client.get("/account/recovery-codes")
    assert dash_res.status_code == 200
    assert b"Account Recovery Codes" in dash_res.data

    # Generate POST route
    gen_res = client.post("/account/recovery-codes/generate", data={"password": test_user["password"]})
    assert gen_res.status_code == 200
    assert b"Your Account Recovery Codes" in gen_res.data
    assert b"Save these codes right now" in gen_res.data

    # Download route
    down_res = client.get("/account/recovery-codes/download")
    assert down_res.status_code == 200
    assert down_res.headers["Content-Disposition"].startswith("attachment;")
    assert b"AI CAMPUS PLACEMENT AGENT" in down_res.data
