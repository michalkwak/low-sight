"""Runs the JavaScript tests for the HUD's voice tools (tests/js/, Node's built-in runner),
so `pytest` covers them too. Skipped when Node isn't installed."""

import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = Path(__file__).parent / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_webmcp_tools_js():
    files = sorted(str(p) for p in JS_TESTS.glob("*.test.js"))
    assert files, "no JS tests found"
    proc = subprocess.run(["node", "--test", *files], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
