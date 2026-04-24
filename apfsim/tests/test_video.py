import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_video_frame_metadata():
    if shutil.which("verilator") is None:
        import pytest
        pytest.skip("verilator not installed")
    r = subprocess.run([
        "make", "-C", str(ROOT), "run-mock", "FRAMES=3", "SCENARIO=scenarios/video_measure.yml"
    ], text=True, capture_output=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    meta_path = ROOT / "build/run/frames/frame_000001.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["active_width"] == 256
    assert meta["active_height"] == 224
    assert meta["vs_pulses"] == 1
    assert meta["de_errors"] == 0
