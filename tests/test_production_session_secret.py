"""Exercise the real config import without loading .env files or real secrets."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

CONFIG_SOURCE = Path(__file__).resolve().parents[1] / "config.py"
STRONG_KEY = "synthetic-only-7d49af208c5b6130f296eab84d19c067"


def import_config(tmp_path, **variables):
    """Import an isolated copy so storage setup stays inside the temporary path."""
    source = tmp_path / "config.py"
    source.write_bytes(CONFIG_SOURCE.read_bytes())
    env = os.environ.copy()
    for key in ("FLASK_SECRET_KEY", "SECRET_KEY", "DEFAULT_SECRET_KEY", "FLASK_ENV", "VERCEL"):
        env.pop(key, None)
    env.update(variables)
    program = (
        "import runpy, sys, types; "
        "sys.modules['dotenv'] = types.SimpleNamespace(load_dotenv=lambda: None); "
        "result = runpy.run_path('config.py'); "
        "assert result['FLASK_SECRET_KEY'] == " + repr(variables.get("EXPECTED", STRONG_KEY))
    )
    return subprocess.run(
        [sys.executable, "-c", program],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("production", [{"FLASK_ENV": "production"}, {"VERCEL": "1"}])
@pytest.mark.parametrize(
    "key",
    [
        None,
        "short",
        "x" * 40,
        "replace_with_a_secure_random_flask_secret_key",
        "change-this-to-a-random-secret-string",
        " " * 40,
    ],
)
def test_production_rejects_missing_or_weak_keys(tmp_path, production, key):
    variables = {**production, "DEFAULT_SECRET_KEY": STRONG_KEY}
    if key is not None:
        variables["FLASK_SECRET_KEY"] = key
    result = import_config(tmp_path, **variables)
    assert result.returncode != 0
    assert "Production requires" in result.stderr
    if key and key.strip():
        assert key not in result.stderr


@pytest.mark.parametrize(
    "production", [{"FLASK_ENV": "production"}, {"VERCEL": "1"}, {"FLASK_ENV": " Production "}]
)
@pytest.mark.parametrize("name", ["FLASK_SECRET_KEY", "SECRET_KEY"])
def test_production_accepts_strong_canonical_or_legacy_key(tmp_path, production, name):
    result = import_config(tmp_path, **production, **{name: STRONG_KEY})
    assert result.returncode == 0, result.stderr


def test_canonical_key_takes_precedence_and_is_not_trimmed(tmp_path):
    key = " " + STRONG_KEY + " "
    result = import_config(
        tmp_path,
        FLASK_ENV="production",
        FLASK_SECRET_KEY=key,
        SECRET_KEY="other-synthetic-key-123456789012345",
        EXPECTED=key,
    )
    assert result.returncode == 0, result.stderr


def test_invalid_canonical_key_cannot_be_hidden_by_valid_alias(tmp_path):
    result = import_config(tmp_path, VERCEL="1", FLASK_SECRET_KEY="short", SECRET_KEY=STRONG_KEY)
    assert result.returncode != 0
    assert "Production requires" in result.stderr


@pytest.mark.parametrize(
    "variables,expected",
    [
        ({}, "dev-secret-key-12345"),
        ({"FLASK_ENV": "development"}, "dev-secret-key-12345"),
        ({"FLASK_ENV": "development", "DEFAULT_SECRET_KEY": "local-only"}, "local-only"),
        ({"FLASK_ENV": "development", "FLASK_SECRET_KEY": "test-key"}, "test-key"),
    ],
)
def test_local_development_compatibility(tmp_path, variables, expected):
    result = import_config(tmp_path, **variables, EXPECTED=expected)
    assert result.returncode == 0, result.stderr
