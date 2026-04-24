import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "apfsim"


def run_cli(*args, timeout=120):
    return subprocess.run([str(CLI), *args], cwd=ROOT, text=True, capture_output=True, timeout=timeout)


def test_invalid_profile_fails_before_verilator():
    r = run_cli("build", "--profile", "tests/fixtures/invalid_missing_top.json", "--preflight-only")
    assert r.returncode == 2
    assert "missing required key" in r.stderr


def test_missing_external_checkout_returns_skip(tmp_path):
    profile = tmp_path / "missing_external.json"
    profile.write_text(json.dumps({
        "name": "missing_external",
        "external": True,
        "root": str(tmp_path / "does-not-exist"),
        "top": "core_top",
        "filelist": "examples/mock/filelist.f",
        "scenario": "scenarios/boot_rom.yml",
    }))
    r = run_cli("build", "--profile", str(profile), "--preflight-only")
    assert r.returncode == 77
    assert "external root missing" in r.stdout


def test_missing_scenario_asset_is_preflight_error(tmp_path):
    scenario = tmp_path / "missing_asset.yml"
    missing = tmp_path / "missing.rom"
    scenario.write_text(f"""
name: missing_asset
data_slots:
  - id: 1
    name: ROM
    file: {missing}
    address: 0x10000000
run:
  until_frames: 1
expect:
  video:
    active_width: 256
    active_height: 224
""")
    profile = tmp_path / "missing_asset_profile.json"
    profile.write_text(json.dumps({
        "name": "missing_asset_profile",
        "top": "core_top",
        "filelist": "examples/mock/filelist.f",
        "scenario": str(scenario),
    }))
    r = run_cli("build", "--profile", str(profile), "--preflight-only")
    assert r.returncode == 2
    assert "scenario data slot file" in r.stderr
    assert str(missing) in r.stderr


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_mock_profile_run_writes_structured_artifacts(tmp_path):
    artifacts = tmp_path / "mock-run"
    r = run_cli("run", "--profile", "mock", "--frames", "2", "--artifacts", str(artifacts), timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr

    result = json.loads((artifacts / "result.json").read_text())
    assert result["ok"] is True
    assert result["status"] == "running"
    assert result["data"]["slots"][0]["loaded_size"] == 1024
    assert result["video"]["frames_completed"] == 2
    assert result["video"]["active_width"] == 256
    assert result["video"]["active_height"] == 224
    assert result["audio"]["samples"] > 0

    frame_meta = json.loads((artifacts / "video" / "frame_000001.json").read_text())
    assert frame_meta["active_width"] == 256
    assert frame_meta["active_height"] == 224
    assert frame_meta["de_errors"] == 0

    audio_stats = json.loads((artifacts / "audio" / "stats.json").read_text())
    assert audio_stats["channels"] == 2
    assert audio_stats["samples"] > 0
    assert (artifacts / "audio" / "out.wav").exists()

    bridge_log = (artifacts / "bridge.log").read_text()
    assert "HOST CM Request Status" in bridge_log
    assert "DATASLOT load done id=1" in bridge_log
