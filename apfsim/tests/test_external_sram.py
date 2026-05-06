import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "apfsim"


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_mock_external_sram_rom_readback_passes_and_reports_activity(tmp_path):
    artifacts = tmp_path / "external-sram"
    r = subprocess.run([
        str(CLI),
        "run",
        "--profile", "mock_external_sram",
        "--artifacts", str(artifacts),
    ], cwd=ROOT, text=True, capture_output=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr

    result = json.loads((artifacts / "result.json").read_text())
    slot = result["data"]["slots"][0]
    assert slot["readback_attempted"] is True
    assert slot["readback_matches"] is True
    assert slot["readback_mismatch_count"] == 0
    counters = {item["name"]: item["value"] for item in result["memory_activity"]["counters"]}
    assert counters["sram_write_count"] > 0
    assert counters["sram_read_count"] > 0

    memory = json.loads((artifacts / "memory_activity.json").read_text())
    assert memory["observed"] is True
    assert memory["counter_status"] == "observed"
    assert not memory["errors"]


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_mock_external_sram_corrupt_byte_lane_fails_with_readback_diagnostic(tmp_path):
    artifacts = tmp_path / "external-sram-corrupt"
    r = subprocess.run([
        str(CLI),
        "run",
        "--profile", "mock_external_sram_corrupt",
        "--artifacts", str(artifacts),
    ], cwd=ROOT, text=True, capture_output=True, timeout=180)
    assert r.returncode == 1, r.stdout + r.stderr

    result = json.loads((artifacts / "result.json").read_text())
    slot = result["data"]["slots"][0]
    assert slot["readback_attempted"] is True
    assert slot["readback_matches"] is False
    assert slot["readback_mismatch_count"] > 0
    assert slot["readback_first_mismatch_offset"] == 0

    diagnostics = json.loads((artifacts / "diagnostics.json").read_text())
    codes = {item["code"] for item in diagnostics["diagnostics"]}
    assert "DATA_SLOT_READBACK_MISMATCH" in codes
    readback = next(item for item in diagnostics["diagnostics"] if item["code"] == "DATA_SLOT_READBACK_MISMATCH")
    assert readback["phase"] == "data"
    assert "external RAM write path corrupted ROM bytes" in readback["likely_causes"]

    memory = json.loads((artifacts / "memory_activity.json").read_text())
    assert memory["observed"] is True
    counters = {item["name"]: item["value"] for item in memory["counters"]}
    assert counters["sram_write_count"] > 0
    assert counters["sram_read_count"] > 0
