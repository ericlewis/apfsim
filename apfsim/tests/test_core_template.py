import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = Path("/Users/ericlewis/Developer/openfpga-arcade-cores/ref-pocket-cores/agg23/template")


def test_agg23_core_template_boot():
    if shutil.which("verilator") is None:
        import pytest
        pytest.skip("verilator not installed")
    if not TEMPLATE_ROOT.exists():
        import pytest
        pytest.skip("agg23 core template checkout not present")
    r = subprocess.run([
        "make", "-C", str(ROOT), "run-template", "FRAMES=2"
    ], text=True, capture_output=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS boot: reached running" in r.stdout
    assert "PASS video: 2 frames, 320x240 active" in r.stdout
    assert "PASS audio:" in r.stdout
    assert "STATUS running" in r.stdout
