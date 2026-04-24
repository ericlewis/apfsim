import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "apfsim"
MRJONG_ROOT = Path("/Users/ericlewis/Developer/openfpga-arcade-cores/our-pocket-cores/openFPGA-MrJong")


def ppm_unique_colors(path: Path) -> int:
    with path.open("rb") as f:
        assert f.readline().strip() == b"P6"
        dims = f.readline().strip()
        while dims.startswith(b"#"):
            dims = f.readline().strip()
        width, height = [int(v) for v in dims.split()]
        assert (width, height) == (240, 224)
        assert int(f.readline()) == 255
        data = f.read()
    return len(Counter(bytes(data[i:i + 3]) for i in range(0, len(data), 3)))


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_mrjong_real_verilog_produces_nonblack_frames(tmp_path):
    if not MRJONG_ROOT.exists():
        pytest.skip("MrJong core checkout not present")

    artifacts = tmp_path / "mrjong"
    r = subprocess.run([
        str(CLI),
        "run",
        "--profile", "mrjong",
        "--artifacts", str(artifacts),
    ], cwd=ROOT, text=True, capture_output=True, timeout=240)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS data: slot 1 loaded 41248 bytes" in r.stdout
    assert "PASS boot: reached running" in r.stdout
    assert "PASS video: 12 frames, 240x224 active" in r.stdout
    assert "PASS input: scripted pulses delivered" in r.stdout

    result = json.loads((artifacts / "result.json").read_text())
    assert result["ok"] is True
    assert result["data"]["slots"][0]["loaded_size"] == 41248
    assert result["video"]["active_width"] == 240
    assert result["video"]["active_height"] == 224
    assert result["video"]["errors"] == 0
    assert result["input"]["ever_active"] is True
    assert ppm_unique_colors(artifacts / "video" / "frame_000012.ppm") > 1
