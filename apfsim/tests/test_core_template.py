import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = os.environ.get("CORE_TEMPLATE_ROOT") or os.environ.get("TEMPLATE_ROOT")
TEMPLATE_ROOT_PATH = Path(TEMPLATE_ROOT) if TEMPLATE_ROOT else None


def test_core_template_boot():
    if shutil.which("verilator") is None:
        import pytest
        pytest.skip("verilator not installed")
    if TEMPLATE_ROOT_PATH is None or not TEMPLATE_ROOT_PATH.exists():
        import pytest
        pytest.skip("core template checkout not present")
    r = subprocess.run([
        "make", "-C", str(ROOT), "run-template", "FRAMES=2"
    ], text=True, capture_output=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS boot: reached running" in r.stdout
    assert "PASS video: 2 frames, 320x240 active" in r.stdout
    assert "PASS audio:" in r.stdout
    assert "STATUS running" in r.stdout
