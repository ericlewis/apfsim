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


def test_play_command_is_exposed():
    r = run_cli("play", "--help")
    assert r.returncode == 0
    assert "--scale" in r.stdout
    assert "--speed-percent" in r.stdout


def test_video_shape_extracts_stable_contract(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "result.json").write_text(json.dumps({
        "ok": True,
        "status": "running",
        "phases": {"video": {"status": "pass", "ok": True}},
        "video": {
            "frames_completed": 3,
            "validated_frames": 2,
            "active_width": 256,
            "active_height": 224,
            "active_width_frame_min": 256,
            "active_width_frame_max": 256,
            "active_height_frame_min": 224,
            "active_height_frame_max": 224,
            "pixels_per_line_min": 341,
            "pixels_per_line_max": 341,
            "hs_after_vs_gap_min": 3,
            "hs_to_de_gap_min": 1,
            "de_to_hs_gap_min": 1,
            "unstable_dimension_frames": 0,
            "errors": 0,
            "raw_errors": 1,
            "ignored_startup_frames": 1,
            "unique_colors": 16,
        },
    }))

    r = run_cli("video-shape", str(artifacts))
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(r.stdout)
    assert doc["schema"] == "apfsim.video_shape.v1"
    assert doc["result_ok"] is True
    assert doc["video_phase_status"] == "pass"
    shape = doc["video_shape"]
    assert shape["active_width"] == 256
    assert shape["active_height"] == 224
    assert shape["total_width_min"] == 341
    assert shape["pixels_per_line_min"] == 341
    assert shape["ignored_startup_frames"] == 1
    assert shape["stable_dimensions"] is True
    assert shape["protocol_valid"] is True
    assert "unique_colors" not in shape


def test_compare_video_json_passes_and_flags_mismatch(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "video_shape.json").write_text(json.dumps({
        "schema": "apfsim.video_shape.v1",
        "source_result": str(artifacts / "result.json"),
        "result_ok": True,
        "video_shape": {
            "active_width": 256,
            "active_height": 224,
            "total_width_min": 320,
            "total_width_max": 320,
            "hs_to_de_gap_min": 1,
            "de_to_hs_gap_min": 1,
            "vs_to_first_de_lines": 0,
            "de_errors": 0,
            "pulse_width_errors": 0,
            "skip_errors": 0,
            "errors": 0,
            "stable_dimensions": True,
            "protocol_valid": True,
        },
    }))
    video_json = tmp_path / "video.json"
    video_json.write_text(json.dumps({
        "video": {
            "magic": "APF_VER_1",
            "scaler_modes": [
                {"width": 256, "height": 224, "rotation": 0},
                {"width": 256, "height": 224, "rotation": 180},
            ],
        }
    }))

    r = run_cli("compare-video-json", "--shape", str(artifacts), "--video-json", str(video_json))
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(r.stdout)
    assert report["schema"] == "apfsim.video_compare.v1"
    assert report["ok"] is True
    assert report["matched_modes"][0]["width"] == 256

    bad_video_json = tmp_path / "bad_video.json"
    bad_video_json.write_text(json.dumps({"video": {"scaler_modes": [{"width": 256, "height": 225}]}}))
    r = run_cli("compare-video-json", "--shape", str(artifacts), "--video-json", str(bad_video_json))
    assert r.returncode == 1
    bad_report = json.loads(r.stdout)
    assert bad_report["ok"] is False
    assert "256x225" in bad_report["failures"][0]
    assert "256x224" in bad_report["failures"][0]


def test_validate_artifacts_reports_clean_cli_error(tmp_path):
    missing = tmp_path / "missing-run"
    r = run_cli("validate-artifacts", str(missing))
    assert r.returncode == 2
    assert "apfsim artifact error" in r.stderr
    assert "missing result.json" in r.stderr
    assert "Traceback" not in r.stderr


def test_shim_catalog_lists_public_catalog():
    r = run_cli("shim-catalog", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(r.stdout)
    assert doc["schema"] == "apfsim.shim_catalog.v1"
    names = {entry["name"] for entry in doc["entries"]}
    assert "intel_bram_shims" in names
    assert "sdram_ideal_transactional" in names
    assert "external_sram_pin_model" in names
    sram = next(entry for entry in doc["entries"] if entry["name"] == "external_sram_pin_model")
    assert sram["kind"] == "behavioral_model_library"
    assert "sram" in sram["memory_classes"]


def test_shim_catalog_profile_expands_runtime_cwd_and_verilator_flags(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({
        "schema": "apfsim.shim_catalog.v1",
        "entries": [
            {
                "name": "runtime_assets",
                "verilator_flags": ["-Wno-BLKANDNBLK"],
                "runtime_cwd": "{root}/hdl",
            }
        ],
    }))
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({
        "name": "profile",
        "root": str(tmp_path),
        "top": "core_top",
        "filelist": "filelist.f",
        "scenario": "scenario.yml",
        "shim_catalog": ["runtime_assets"],
    }))

    r = run_cli("shim-catalog", "--profile", str(profile), "--catalog", str(catalog), "--json")

    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(r.stdout)
    assert doc["runtime_cwd"] == str(tmp_path / "hdl")
    assert "-Wno-BLKANDNBLK" in doc["verilator_flags"]


def test_apply_video_shape_patches_scaler_modes_and_hints(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "video_shape.json").write_text(json.dumps({
        "schema": "apfsim.video_shape.v1",
        "source_result": str(artifacts / "result.json"),
        "result_ok": True,
        "video_shape": {
            "active_width": 256,
            "active_height": 224,
            "total_width_min": 320,
            "total_width_max": 320,
            "hs_to_de_gap_min": 2,
            "de_to_hs_gap_min": 62,
            "vs_to_first_de_lines": 0,
            "de_errors": 0,
            "pulse_width_errors": 0,
            "skip_errors": 0,
            "errors": 0,
            "stable_dimensions": True,
            "protocol_valid": True,
        },
    }))
    video_json = tmp_path / "video.json"
    video_json.write_text(json.dumps({
        "video": {
            "magic": "APF_VER_1",
            "scaler_modes": [
                {"width": 256, "height": 225, "rotation": 0},
                {"width": 256, "height": 225, "rotation": 180},
            ],
        }
    }))
    patched = tmp_path / "patched_video.json"
    r = run_cli(
        "apply-video-shape",
        "--shape", str(artifacts),
        "--video-json", str(video_json),
        "--out", str(patched),
        "--timing-hints",
        "--pretty",
    )
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(r.stdout)
    assert report["schema"] == "apfsim.video_apply.v1"
    assert report["changed"] is True
    out = json.loads(patched.read_text())
    assert [mode["height"] for mode in out["video"]["scaler_modes"]] == [224, 224]
    assert out["video"]["_apfsim_video_shape"]["total_width_min"] == 320

    r = run_cli("compare-video-json", "--shape", str(artifacts), "--video-json", str(patched))
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_video_shape_can_run_profile_and_write_json_out(tmp_path):
    artifacts = tmp_path / "shape-run"
    json_out = tmp_path / "shape.json"
    r = run_cli(
        "video-shape",
        "--profile", "mock_port_gate",
        "--frames", "4",
        "--artifacts", str(artifacts),
        "--json-out", str(json_out),
        "--pretty",
        timeout=180,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(json_out.read_text())
    assert doc["schema"] == "apfsim.video_shape.v1"
    assert doc["video_shape"]["active_width"] == 256
    assert doc["video_shape"]["active_height"] == 224
    assert doc["video_shape"]["total_width_min"] == 320
    assert doc["video_shape"]["total_width_max"] == 320
    assert doc["video_shape"]["vs_to_first_de_lines"] == 0
    assert doc["video_shape"]["de_errors"] == 0
    assert doc["video_shape"]["pulse_width_errors"] == 0
    assert doc["video_shape"]["skip_errors"] == 0
    assert doc["video_shape"]["stable_dimensions"] is True
    assert (artifacts / "video_shape.json").exists()
    assert (artifacts / "lifecycle.json").exists()
    result = json.loads((artifacts / "result.json").read_text())
    assert result["video_shape"] == doc["video_shape"]
    assert result["lifecycle"]["running"] is True


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


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_mock_profile_reports_frame_change_after_input(tmp_path):
    artifacts = tmp_path / "input-response"
    r = run_cli(
        "run",
        "--profile", "mock",
        "--scenario", "scenarios/input_response_smoke.yml",
        "--artifacts", str(artifacts),
        timeout=180,
    )
    assert r.returncode == 0, r.stdout + r.stderr

    result = json.loads((artifacts / "result.json").read_text())
    assert result["input_video_effect_seen"] is True
    assert result["input_video_response"]["changed"] is True
    assert result["input_video_response"]["changed_frames"] >= 1
    phases = {phase["name"]: phase for phase in result["video_activity"]["phases"]}
    assert phases["gameplay"]["pass"] is True
    assert phases["gameplay"]["changed"] is True
