"""
Tests for Account-Based Failed Login Attempt Tracking and Lockout (#851).
========================================================================
Acceptance Criteria:
1. Repeated failures trigger a delay or lockout and then recover.
2. Responses do not reveal whether an account exists (anti-enumeration).
3. Counters reset after success.
4. Tests use a fixed clock.
5. Notification email sent to account owner on lockout.
6. Table growth capped with cleanup.
"""

import time
import uuid
import pytest
from unittest.mock import MagicMock, patch
from werkzeug.security import generate_password_hash

from app import app
from utils.database import get_db_connection
from utils.account_lockout_service import (
    AccountLockoutService,
    lockout_service,
)
from utils.email_service import EmailNotificationService


@pytest.fixture
def test_user():
    """Creates a unique test user in the database."""
    unique_id = str(uuid.uuid4())[:8]
    email = f"user_{unique_id}@example.com"
    raw_password = "Password123!"
    pw_hash = generate_password_hash(raw_password)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO users (id, name, email, password_hash, is_verified)
        VALUES (?, ?, ?, ?, 1)
        """,
        (f"user_{unique_id}", f"Test User {unique_id}", email, pw_hash),
    )
    conn.commit()
    conn.close()

    return {
        "id": f"user_{unique_id}",
        "name": f"Test User {unique_id}",
        "email": email,
        "password": raw_password,
    }


class FixedClock:
    """Helper class providing a controllable, deterministic fixed clock for testing."""

    def __init__(self, start_time: float = 1700000000.0):
        self._current_time = start_time

    def time(self) -> float:
        return self._current_time

    def advance(self, seconds: float) -> None:
        self._current_time += seconds

    def set_time(self, new_time: float) -> None:
        self._current_time = new_time


def test_repeated_failures_trigger_progressive_delay_and_lockout_with_fixed_clock():
    """
    Criterion 1 & 4: Repeated failures trigger progressive delays, then lockout,
    and then recover once the clock advances past the lockout duration.
    """
    clock = FixedClock(start_time=1700000000.0)
    service = AccountLockoutService(
        lockout_threshold=5,
        lockout_duration_seconds=900,  # 15 minutes
        window_seconds=900,
    )
    test_ident = f"target_{uuid.uuid4()}@example.com"
    test_ip = "192.168.1.100"

    # 1st failure: count=1, no delay, not locked
    is_locked, count = service.record_failed_attempt(test_ident, test_ip, current_time=clock.time())
    assert not is_locked
    assert count == 1
    locked, remaining, delay = service.check_lockout(test_ident, test_ip, current_time=clock.time())
    assert not locked
    assert delay == 0.0

    # 2nd failure: count=2, no delay, not locked
    clock.advance(10.0)
    is_locked, count = service.record_failed_attempt(test_ident, test_ip, current_time=clock.time())
    assert not is_locked
    assert count == 2
    locked, remaining, delay = service.check_lockout(test_ident, test_ip, current_time=clock.time())
    assert not locked
    assert delay == 0.0

    # 3rd failure: count=3, progressive delay = 1.0s
    clock.advance(10.0)
    is_locked, count = service.record_failed_attempt(test_ident, test_ip, current_time=clock.time())
    assert not is_locked
    assert count == 3
    locked, remaining, delay = service.check_lockout(test_ident, test_ip, current_time=clock.time())
    assert not locked
    assert delay == 1.0

    # 4th failure: count=4, progressive delay = 2.0s
    clock.advance(10.0)
    is_locked, count = service.record_failed_attempt(test_ident, test_ip, current_time=clock.time())
    assert not is_locked
    assert count == 4
    locked, remaining, delay = service.check_lockout(test_ident, test_ip, current_time=clock.time())
    assert not locked
    assert delay == 2.0

    # 5th failure: triggers 15-minute temporary lockout!
    clock.advance(10.0)
    is_locked, count = service.record_failed_attempt(test_ident, test_ip, current_time=clock.time())
    assert is_locked
    assert count == 5

    # During lockout (e.g. 1 minute later): must be strictly locked out
    clock.advance(60.0)
    locked, remaining, delay = service.check_lockout(test_ident, test_ip, current_time=clock.time())
    assert locked
    assert remaining > 0.0
    assert service.is_locked_out(test_ident, current_time=clock.time())

    # After 15 minutes + 1 second (recovery): must recover!
    clock.advance(850.0)  # total elapsed: 10+10+10+10+60+850 = 950s > 900s
    locked, remaining, delay = service.check_lockout(test_ident, test_ip, current_time=clock.time())
    assert not locked
    assert remaining == 0.0
    assert not service.is_locked_out(test_ident, current_time=clock.time())


def test_responses_do_not_reveal_whether_account_exists(test_user):
    """
    Criterion 2: Responses do not reveal whether an account exists (anti-enumeration).
    Verifies that unknown accounts and real accounts receive 100% identical flash messages
    and status codes for both single failures and after reaching lockout.
    """
    real_email = test_user["email"]
    unknown_email = f"nonexistent_{uuid.uuid4()}@example.com"
    app.config["TESTING"] = True

    with app.test_client() as client:
        # Failure 1: Real account vs Unknown account
        res_real_1 = client.post(
            "/login",
            data={"email": real_email, "password": "wrongpassword1"},
            follow_redirects=True,
        )
        res_unknown_1 = client.post(
            "/login",
            data={"email": unknown_email, "password": "wrongpassword1"},
            follow_redirects=True,
        )

        assert res_real_1.status_code == 200
        assert res_unknown_1.status_code == 200
        # Both must display the exact same message
        assert b"Invalid email or password" in res_real_1.data
        assert b"Invalid email or password" in res_unknown_1.data
        # Neither mentions whether the user was found
        assert b"user not found" not in res_unknown_1.data.lower()
        assert b"account does not exist" not in res_unknown_1.data.lower()

        # Trigger lockout (5 failures each)
        for i in range(2, 6):
            client.post("/login", data={"email": real_email, "password": f"wrong_{i}"}, follow_redirects=True)
            client.post("/login", data={"email": unknown_email, "password": f"wrong_{i}"}, follow_redirects=True)

        # 6th attempt while locked: Real account vs Unknown account
        res_real_locked = client.post(
            "/login",
            data={"email": real_email, "password": test_user["password"]},  # real password while locked
            follow_redirects=True,
        )
        res_unknown_locked = client.post(
            "/login",
            data={"email": unknown_email, "password": "anypassword"},
            follow_redirects=True,
        )

        assert res_real_locked.status_code == 200
        assert res_unknown_locked.status_code == 200
        # Both return the exact same lockout response
        assert b"Too many failed login attempts. Please try again later." in res_real_locked.data
        assert b"Too many failed login attempts. Please try again later." in res_unknown_locked.data


def test_counters_reset_after_successful_login(test_user):
    """
    Criterion 3: Counters reset after success.
    Verifies that after several failed attempts, a successful login completely
    clears the failed attempts, and subsequent failures start from count 1.
    """
    clock = FixedClock(start_time=1700000000.0)
    app.config["TESTING"] = True
    email = test_user["email"]

    # Record 3 failures in lockout service
    lockout_service.record_failed_attempt(email, "127.0.0.1", current_time=clock.time())
    lockout_service.record_failed_attempt(email, "127.0.0.1", current_time=clock.time())
    lockout_service.record_failed_attempt(email, "127.0.0.1", current_time=clock.time())

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM failed_login_attempts WHERE identifier = ?", (email,))
    assert cursor.fetchone()[0] == 3
    conn.close()

    with app.test_client() as client:
        # Successful login with correct password
        res = client.post(
            "/login",
            data={"email": email, "password": test_user["password"]},
            follow_redirects=True,
        )
        assert res.status_code == 200
        assert b"Login successful" in res.data

        # Counters must now be reset to 0
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM failed_login_attempts WHERE identifier = ?", (email,))
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT COUNT(*) FROM account_lockouts WHERE identifier = ?", (email,))
        assert cursor.fetchone()[0] == 0
        conn.close()

        # A subsequent single failure only registers 1 failure, NOT lockout
        client.get("/logout", follow_redirects=True)
        res_fail = client.post(
            "/login",
            data={"email": email, "password": "wrong_password_again"},
            follow_redirects=True,
        )
        assert b"Invalid email or password" in res_fail.data
        assert b"Too many failed login attempts" not in res_fail.data


def test_notification_email_sent_to_account_owner_on_lockout(test_user):
    """
    Criterion 5: Sends a notification email to the account owner when a lockout happens,
    and does not send to unknown accounts.
    """
    clock = FixedClock(start_time=1700000000.0)
    service = AccountLockoutService(lockout_threshold=5, lockout_duration_seconds=900)
    real_email = test_user["email"]
    unknown_email = f"unknown_{uuid.uuid4()}@example.com"

    with patch.object(EmailNotificationService, "send_account_lockout_notification", return_value=True) as mock_send:
        # 4 failures: no lockout, no email
        for _ in range(4):
            service.record_failed_attempt(real_email, "127.0.0.1", current_time=clock.time())
        assert mock_send.call_count == 0

        # 5th failure on real account: triggers lockout and sends email to account owner!
        service.record_failed_attempt(real_email, "127.0.0.1", current_time=clock.time())
        assert mock_send.call_count == 1
        assert mock_send.call_args[1]["recipient_email"] == real_email
        assert mock_send.call_args[1]["lockout_minutes"] == 15

        # Another attempt during the same lockout period: does NOT spam duplicate email
        service.record_failed_attempt(real_email, "127.0.0.1", current_time=clock.time())
        assert mock_send.call_count == 1

        # 5 failures on unknown account: triggers lockout state, but does NOT email anyone
        mock_send.reset_mock()
        for _ in range(5):
            service.record_failed_attempt(unknown_email, "127.0.0.1", current_time=clock.time())
        assert mock_send.call_count == 0


def test_distributed_brute_force_across_multiple_ips_triggers_account_lockout():
    """
    Problem statement test: IP-based rate limiting does not stop an attacker who tries
    many passwords for one account from many addresses.
    Verify that 5 failed attempts from 5 distinct IP addresses for the same account
    trigger an account-level lockout.
    """
    clock = FixedClock(start_time=1700000000.0)
    service = AccountLockoutService(lockout_threshold=5, lockout_duration_seconds=900)
    target_account = f"ceo_{uuid.uuid4()}@targetcorp.com"

    # Attacker tries from 5 different botnet / proxy IPs
    ips = ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4", "5.5.5.5"]
    for ip in ips[:4]:
        service.record_failed_attempt(target_account, ip, current_time=clock.time())

    # Not locked yet after 4
    locked, _, _ = service.check_lockout(target_account, "6.6.6.6", current_time=clock.time())
    assert not locked

    # 5th attempt from 5th IP
    is_locked, _ = service.record_failed_attempt(target_account, ips[4], current_time=clock.time())
    assert is_locked

    # Any new IP attempting to target this account is now blocked by account lockout!
    locked, remaining, _ = service.check_lockout(target_account, "7.7.7.7", current_time=clock.time())
    assert locked
    assert remaining > 0


def test_table_growth_capped_with_cleanup():
    """
    Criterion 6: Cap table growth with cleanup.
    Verifies that old records beyond retention cutoff are purged and total rows are capped.
    """
    clock = FixedClock(start_time=1700000000.0)
    service = AccountLockoutService(
        max_retention_seconds=3600,  # 1 hour retention
        max_table_rows=10,            # Cap at 10 rows
    )
    ident = f"user_{uuid.uuid4()}@example.com"

    # Add 15 records in the past
    for i in range(15):
        service.record_failed_attempt(ident, f"10.0.0.{i}", current_time=clock.time())
        clock.advance(1.0)

    # Table count should be capped at max_table_rows (10)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM failed_login_attempts WHERE identifier = ?", (ident,))
    count = int(cursor.fetchone()[0])
    assert count <= 10
    conn.close()

    # Advance clock past retention (2 hours later)
    clock.advance(7200.0)
    purged = service.cleanup_old_attempts(retention_seconds=3600, current_time=clock.time())
    assert purged > 0

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM failed_login_attempts WHERE identifier = ?", (ident,))
    assert cursor.fetchone()[0] == 0
    conn.close()
