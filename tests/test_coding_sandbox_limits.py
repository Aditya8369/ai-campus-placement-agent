import pytest
from app import app
from utils.secure_coding_sandbox import (
    SecureCodingSandboxService,
    secure_coding_sandbox
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_safe_algorithm_execution():
    service = SecureCodingSandboxService()
    code = """
def two_sum(nums, target):
    seen = {}
    for i, n in enumerate(nums):
        diff = target - n
        if diff in seen:
            return [seen[diff], i]
        seen[n] = i
    return []

print(two_sum([2, 7, 11, 15], 9))
"""
    res = service.execute_code(code)
    assert res["status"] == "SUCCESS"
    assert "[0, 1]" in res["stdout"]
    assert res["execution_time_ms"] >= 0
    assert res["truncated"] is False


def test_disallowed_imports_blocked():
    service = SecureCodingSandboxService()
    malicious_codes = [
        "import os\nos.system('dir')",
        "import sys\nprint(sys.version)",
        "from subprocess import Popen",
        "import socket\ns = socket.socket()"
    ]
    for code in malicious_codes:
        res = service.execute_code(code)
        assert res["status"] == "SECURITY_VIOLATION"
        assert "is restricted" in res["stderr"]


def test_disallowed_calls_blocked():
    service = SecureCodingSandboxService()
    calls = [
        "eval('1 + 1')",
        "open('app.py', 'r')",
        "__import__('os')"
    ]
    for code in calls:
        res = service.execute_code(code)
        assert res["status"] == "SECURITY_VIOLATION"
        assert "is prohibited" in res["stderr"]


def test_runtime_error_handled():
    service = SecureCodingSandboxService()
    code = """
arr = [1, 2, 3]
print(arr[10])
"""
    res = service.execute_code(code)
    assert res["status"] == "RUNTIME_ERROR"
    assert "IndexError" in res["stderr"]


def test_output_length_truncation():
    service = SecureCodingSandboxService()
    code = """
for i in range(2000):
    print("Long repetitive output line for placement testing")
"""
    res = service.execute_code(code, max_output_chars=500)
    assert res["status"] == "SUCCESS"
    assert res["truncated"] is True
    assert "[OUTPUT TRUNCATED" in res["stdout"]
    assert len(res["stdout"]) < 1000


def test_api_execute_sandboxed_endpoint(client):
    res = client.post("/api/coding/execute-sandboxed", json={
        "code": "print('Hello from sandboxed placement engine!')"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "Hello from sandboxed" in data["result"]["stdout"]


def test_api_execute_sandboxed_empty_code(client):
    res = client.post("/api/coding/execute-sandboxed", json={"code": ""})
    assert res.status_code == 400
    assert res.get_json()["success"] is False
