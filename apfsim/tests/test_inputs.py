import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_input_smoke():
    if shutil.which("verilator") is None:
        import pytest
        pytest.skip("verilator not installed")
    r = subprocess.run([
        "make", "-C", str(ROOT), "run-mock", "FRAMES=8", "SCENARIO=scenarios/input_smoke.yml"
    ], text=True, capture_output=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS input: scripted pulses delivered" in r.stdout
