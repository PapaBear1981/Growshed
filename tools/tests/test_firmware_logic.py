"""Compiles and runs the native C++ tests for the node control logic (firmware/common/control.h).

The same header is compiled into the ESP32 firmware, so this exercises the real
interlock code on a PC. Skipped where no C++ compiler is installed.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ not installed")
def test_node_control_logic(tmp_path):
    binary = tmp_path / "control_test"
    source = REPO_ROOT / "firmware" / "tests" / "control_test.cpp"
    build = subprocess.run(
        ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-o", str(binary), str(source)],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all tests passed" in result.stdout
