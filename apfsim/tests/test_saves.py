import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_save_roundtrip_mock():
    if shutil.which("verilator") is None:
        import pytest
        pytest.skip("verilator not installed")
    r = subprocess.run([
        "make", "-C", str(ROOT), "run-mock", "FRAMES=2", "SCENARIO=scenarios/boot_rom_save.yml"
    ], text=True, capture_output=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    save = ROOT / "build/run/saves/slot_4.bin"
    assert save.exists()
    assert save.read_bytes() == (ROOT / "examples/assets/mock.hi").read_bytes()
    assert "PASS save: slot 4 unloaded 43 bytes" in r.stdout
