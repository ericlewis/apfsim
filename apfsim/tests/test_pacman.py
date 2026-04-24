import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACMAN_ROOT = Path("/Users/ericlewis/Developer/openfpga-arcade-cores/our-pocket-cores/openFPGA-PacMan")


def test_pacman_apf_shell_boot():
    if shutil.which("verilator") is None:
        import pytest
        pytest.skip("verilator not installed")
    if not PACMAN_ROOT.exists():
        import pytest
        pytest.skip("Pac-Man core checkout not present")
    r = subprocess.run([
        "make", "-C", str(ROOT), "run-pacman", "FRAMES=2"
    ], text=True, capture_output=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS data: slot 1 loaded 54048 bytes" in r.stdout
    assert "PASS boot: reached running" in r.stdout
    assert "PASS video: 2 frames, 288x224 active" in r.stdout
    assert "PASS audio:" in r.stdout
    assert "PASS input: scripted pulses delivered" in r.stdout
