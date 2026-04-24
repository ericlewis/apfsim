import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASICASSETS_ROOT = os.environ.get("CORE_EXAMPLE_BASICASSETS_ROOT") or os.environ.get("BASICASSETS_ROOT")
BASICASSETS_ROOT_PATH = Path(BASICASSETS_ROOT) if BASICASSETS_ROOT else None


def test_basicassets_boot_data_video_audio():
    if shutil.which("verilator") is None:
        import pytest
        pytest.skip("verilator not installed")
    if BASICASSETS_ROOT_PATH is None or not BASICASSETS_ROOT_PATH.exists():
        import pytest
        pytest.skip("BasicAssets checkout not present")
    r = subprocess.run([
        "make", "-C", str(ROOT), "run-basicassets", "FRAMES=2"
    ], text=True, capture_output=True, timeout=240)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS data: slot 1 loaded 184320 bytes" in r.stdout
    assert "PASS data: slot 99 loaded 1343824 bytes" in r.stdout
    assert "PASS boot: reached running" in r.stdout
    assert "PASS interact: 1 persistent writes verified" in r.stdout
    assert "PASS video: 2 frames, 320x288 active" in r.stdout
    assert "PASS audio:" in r.stdout
    assert "STATUS running" in r.stdout
