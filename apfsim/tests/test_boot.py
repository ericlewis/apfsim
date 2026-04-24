import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require_verilator():
    if shutil.which("verilator") is None:
        import pytest
        pytest.skip("verilator not installed")


def run_make(*args):
    require_verilator()
    return subprocess.run(["make", "-C", str(ROOT), *args], text=True, capture_output=True, timeout=120)


def test_boot_mock():
    r = run_make("clean", "run-mock", "FRAMES=4")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS boot: reached running" in r.stdout
    assert "PASS data: slot 1 loaded 1024 bytes" in r.stdout
    assert "PASS video: 4 frames, 256x224 active" in r.stdout
    assert "PASS audio:" in r.stdout
    assert "STATUS running" in r.stdout
