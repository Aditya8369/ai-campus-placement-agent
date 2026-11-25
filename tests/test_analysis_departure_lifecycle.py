"""Run portable JavaScript cancellation regressions with the standard Node test runner."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_analysis_departure_lifecycle():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the JavaScript lifecycle contract tests")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--test", "tests/js/analysis_lifecycle.test.mjs"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
