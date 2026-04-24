import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASICASSETS_ROOT = Path("/Users/ericlewis/Developer/core-example-basicassets")


def test_basicassets_boot_data_video_audio():
    if shutil.which("verilator") is None:
        import pytest
        pytest.skip("verilator not installed")
    if not BASICASSETS_ROOT.exists():
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
