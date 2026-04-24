import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "apfsim"


def run_cli(*args, timeout=180):
    return subprocess.run([str(CLI), *args], cwd=ROOT, text=True, capture_output=True, timeout=timeout)


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_strict_port_gate_reports_all_core_port_checks(tmp_path):
    artifacts = tmp_path / "strict"
    r = run_cli("run", "--profile", "mock_port_gate", "--artifacts", str(artifacts), timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr

    result = json.loads((artifacts / "result.json").read_text())
    assert result["ok"] is True
    assert result["boot"]["ok"] is True
    assert result["boot"]["reset_enter_cycle"] < result["boot"]["reset_exit_cycle"] <= result["boot"]["running_cycle"]

    assert result["data"]["slots"][0]["id"] == 1
    assert result["data"]["slots"][0]["loaded_size"] == 1024
    assert result["readbacks"][0]["name"] == "mock_rom_write_count"
    assert result["readbacks"][0]["ok"] is True

    assert result["video"]["active_width"] == 256
    assert result["video"]["active_height"] == 224
    assert result["video"]["pulse_width_errors"] == 0
    assert result["video"]["rgb_when_de_low_errors"] == 0
    assert result["video"]["hs_after_vs_gap_min"] >= 3
    assert result["video"]["hs_to_de_gap_min"] >= 1
    assert result["video"]["de_to_hs_gap_min"] >= 1
    assert result["video"]["unique_colors"] >= 2
    assert result["video"]["nonzero_pixels"] >= 1

    assert result["audio"]["samples"] >= 64
    assert result["audio"]["peak_to_peak_l"] >= 32 or result["audio"]["peak_to_peak_r"] >= 32
    assert result["audio"]["clipped_samples"] == 0

    assert result["interact"]["persistent_writes"] >= 1
    assert result["input"]["ever_active"] is True
    assert result["failures"] == []


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_failed_correctness_gate_writes_actionable_result(tmp_path):
    artifacts = tmp_path / "fail-video"
    r = run_cli(
        "run",
        "--profile", "mock",
        "--scenario", "scenarios/port_gate_fail_video.yml",
        "--frames", "2",
        "--artifacts", str(artifacts),
        timeout=180,
    )
    assert r.returncode == 1
    result = json.loads((artifacts / "result.json").read_text())
    assert result["ok"] is False
    assert result["failed_phase"] == "assert"
    assert "video: active width mismatch" in result["failures"]
    assert result["video"]["active_width"] == 256


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_failed_video_content_gate_writes_actionable_result(tmp_path):
    artifacts = tmp_path / "fail-video-content"
    r = run_cli(
        "run",
        "--profile", "mock",
        "--scenario", "scenarios/port_gate_fail_video_content.yml",
        "--frames", "2",
        "--artifacts", str(artifacts),
        timeout=180,
    )
    assert r.returncode == 1
    result = json.loads((artifacts / "result.json").read_text())
    assert result["ok"] is False
    assert result["failed_phase"] == "assert"
    assert "video: unique color count below expectation" in result["failures"]
    assert result["video"]["unique_colors"] > 0
