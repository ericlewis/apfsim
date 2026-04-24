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
    assert result["phases"]["boot"]["status"] == "pass"
    assert result["phases"]["reset"]["status"] == "pass"
    assert result["phases"]["data"]["status"] == "pass"
    assert result["phases"]["video"]["status"] == "pass"
    assert result["phases"]["audio"]["status"] == "pass"
    assert result["phases"]["interact"]["status"] == "pass"
    assert result["phases"]["input"]["status"] == "pass"
    assert result["phases"]["save"]["status"] == "pass"
    assert result["bridge"]["endian"] == "little"
    assert result["bridge"]["read_latency_cycles"] == 2
    assert result["bridge"]["write_strobe_cycles"] == 1
    assert result["bridge"]["host_commands"] >= 6
    assert result["bridge"]["target_commands"] >= 1
    assert result["bridge"]["slot_table_ok"] is True
    assert result["bridge"]["data_payload_writes"] == 256
    bridge_summary = json.loads((artifacts / "bridge_summary.json").read_text())
    assert bridge_summary["writes"] == result["bridge"]["writes"]
    assert bridge_summary["reads"] == result["bridge"]["reads"]
    assert any(item["direction"] == "target" and item["command"] == "0x00000140" for item in bridge_summary["commands"])
    assert result["boot"]["ok"] is True
    assert result["boot"]["reset_enter_cycle"] < result["boot"]["reset_exit_cycle"] <= result["boot"]["running_cycle"]
    assert result["boot"]["data_all_complete_cycle"] < result["boot"]["target_ready_cycle"]
    assert result["boot"]["reset_hold_cycles"] >= 500
    assert result["boot"]["reset_exit_to_running_cycles"] <= 2000
    assert result["boot"]["events"] == [
        "boot_start",
        "status_setup",
        "reset_enter",
        "slot_table_populated",
        "data_load_complete",
        "data_slot_all_complete",
        "rtc_sent",
        "target_ready_to_run",
        "before_reset_exit",
        "reset_exit",
        "status_running",
    ]

    assert result["data"]["slots"][0]["id"] == 1
    assert result["data"]["slots"][0]["loaded_size"] == 1024
    assert result["data"]["slots"][0]["loaded_words"] == 256
    assert result["data"]["slots"][0]["observed_write_words"] == 256
    assert result["data"]["slots"][0]["observed_first_write_address"] == "0x10000000"
    assert result["data"]["slots"][0]["observed_last_write_address"] == "0x100003FC"
    assert result["data"]["slots"][0]["observed_write_address_errors"] == 0
    assert result["data"]["slots"][0]["loaded_checksum"] == "0x86EA4CAF14129F83"
    assert result["data"]["slots"][0]["expected_checksum"] == "0x86EA4CAF14129F83"
    assert result["data"]["slots"][0]["verify_readback"] is True
    assert result["data"]["slots"][0]["readback_attempted"] is True
    assert result["data"]["slots"][0]["readback_matches"] is True
    assert result["data"]["slots"][0]["readback_bytes"] == 1024
    assert result["data"]["slots"][0]["readback_crc32"] == result["data"]["slots"][0]["loaded_crc32"]
    assert result["data"]["slots"][0]["readback_checksum"] == result["data"]["slots"][0]["loaded_checksum"]
    assert result["data"]["slots"][0]["readback_mismatch_count"] == 0
    assert result["readbacks"][0]["name"] == "mock_rom_write_count"
    assert result["readbacks"][0]["ok"] is True

    assert result["video"]["active_width"] == 256
    assert result["video"]["active_height"] == 224
    assert result["video"]["active_width_frame_min"] == 256
    assert result["video"]["active_width_frame_max"] == 256
    assert result["video"]["unstable_dimension_frames"] == 0
    assert result["video"]["hs_under_active_height_frames"] == 0
    assert result["video"]["pulse_width_errors"] == 0
    assert result["video"]["rgb_when_de_low_errors"] == 0
    assert result["video"]["hs_after_vs_gap_min"] >= 3
    assert result["video"]["hs_to_de_gap_min"] >= 1
    assert result["video"]["de_to_hs_gap_min"] >= 1
    assert result["video"]["unique_colors"] >= 2
    assert result["video"]["nonzero_pixels"] >= 1
    assert result["video_shape"]["active_width"] == 256
    assert result["video_shape"]["active_height"] == 224
    assert result["video_shape"]["total_width_min"] == 320
    assert result["video_shape"]["total_width_max"] == 320
    assert result["video_shape"]["vs_to_first_de_lines"] == 0
    assert result["video_shape"]["de_errors"] == 0
    assert result["video_shape"]["pulse_width_errors"] == 0
    assert result["video_shape"]["skip_errors"] == 0
    assert result["video_shape"]["stable_dimensions"] is True
    assert result["video_shape"]["protocol_valid"] is True
    shape_doc = json.loads((artifacts / "video_shape.json").read_text())
    assert shape_doc["schema"] == "apfsim.video_shape.v1"
    assert shape_doc["video_shape"] == result["video_shape"]

    assert result["audio"]["samples"] >= 64
    assert result["audio"]["peak_to_peak_l"] >= 32 or result["audio"]["peak_to_peak_r"] >= 32
    assert result["audio"]["clipped_samples"] == 0
    assert result["audio"]["lrck_half_period_mclk_min"] == result["audio"]["lrck_half_period_mclk_max"]
    assert result["audio"]["estimated_mclk_lrck_ratio"] > 0

    assert result["interact"]["persistent_writes"] >= 1
    assert result["input"]["ever_active"] is True
    assert result["failures"] == []


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_target_command_service_covers_runtime_dataslot_and_filename_paths(tmp_path):
    artifacts = tmp_path / "target-commands"
    r = run_cli("run", "--profile", "mock_target_commands", "--artifacts", str(artifacts), "--bridge-trace", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr

    result = json.loads((artifacts / "result.json").read_text())
    assert result["ok"] is True
    assert result["bridge"]["target_commands"] == 9
    assert result["bridge"]["target_dataslot_reads"] == 2
    assert result["bridge"]["target_dataslot_read_bytes"] == 32
    assert result["bridge"]["target_dataslot_writes"] == 2
    assert result["bridge"]["target_dataslot_write_bytes"] == 16
    assert result["bridge"]["target_dataslot_flushes"] == 1
    assert result["bridge"]["target_filename_requests"] == 1
    assert result["bridge"]["target_open_file_requests"] == 1
    assert result["bridge"]["target_debug_events"] == 1
    assert result["bridge"]["target_unsupported_commands"] == 0
    assert result["bridge"]["target_slot_errors"] == 0
    assert result["bridge"]["target_range_errors"] == 0
    assert result["bridge"]["slot_table_ok"] is True

    slots = {slot["id"]: slot for slot in result["data"]["slots"]}
    assert slots[1]["target_read_requests"] == 2
    assert slots[1]["target_read_bytes"] == 32
    assert slots[1]["target_filename_requests"] == 1
    assert slots[1]["target_open_requests"] == 1
    assert slots[4]["target_write_requests"] == 2
    assert slots[4]["target_write_bytes"] == 16
    assert slots[4]["target_flush_requests"] == 1
    assert (artifacts / "saves" / "slot_4.bin").read_bytes() == bytes.fromhex("CCBBAA9900FFEEDD")

    readbacks = {item["name"]: item for item in result["readbacks"]}
    assert readbacks["target_read_payload_count"]["ok"] is True
    assert readbacks["target_read_first_word"]["ok"] is True
    assert readbacks["target_filename_struct_bytes"]["ok"] is True

    bridge_summary = json.loads((artifacts / "bridge_summary.json").read_text())
    target_commands = [item["command"] for item in bridge_summary["commands"] if item["direction"] == "target"]
    assert target_commands == [
        "0x00000140",
        "0x00000180",
        "0x00000184",
        "0x00000188",
        "0x00000190",
        "0x00000152",
        "0x00000181",
        "0x00000185",
        "0x00000192",
    ]
    assert (artifacts / "bridge_transactions.jsonl").exists()


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_lifecycle_injection_covers_os_notify_reload_and_savestate(tmp_path):
    artifacts = tmp_path / "lifecycle"
    r = run_cli("run", "--profile", "mock_lifecycle", "--artifacts", str(artifacts), timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr

    result = json.loads((artifacts / "result.json").read_text())
    assert result["ok"] is True
    assert result["bridge"]["runtime_dataslot_updates"] == 1
    assert result["bridge"]["savestate_save_requests"] == 1
    assert result["bridge"]["savestate_save_bytes"] == 16
    assert result["bridge"]["host_commands"] >= 13
    assert result["host_commands"][0]["command"] == "0x000000B1"
    assert all(item["executed"] for item in result["host_commands"])

    host_events = {item["name"]: item for item in result["host_commands"]}
    assert host_events["runtime_reload_slot_1"]["result"] == "0x00000000"
    assert host_events["runtime_reload_slot_1"]["bytes"] == 1024
    assert host_events["savestate_save"]["result"] == "0x00000002"
    assert host_events["savestate_save"]["bytes"] == 16
    assert host_events["savestate_save"]["response1"] == "0x20001000"
    assert host_events["savestate_save"]["response2"] == "0x00000010"

    savestate = result["savestate"]["reports"][0]
    assert savestate["supported"] is True
    assert savestate["ready"] is True
    assert savestate["address"] == "0x20001000"
    assert savestate["bytes"] == 16
    assert (artifacts / "savestates" / "mock_state.sta").read_bytes() == bytes.fromhex("DDCCBBAA44332211887766555AA5A599")

    readbacks = {item["name"]: item for item in result["readbacks"]}
    assert readbacks["menu_state_last"]["ok"] is True
    assert readbacks["display_mode_last"]["ok"] is True
    assert readbacks["runtime_update_count"]["ok"] is True
    assert readbacks["runtime_update_slot"]["ok"] is True
    assert readbacks["runtime_update_size"]["ok"] is True
    assert readbacks["savestate_start_count"]["ok"] is True
    assert readbacks["cart_notify_last"]["ok"] is True

    bridge_summary = json.loads((artifacts / "bridge_summary.json").read_text())
    host_commands = [item["command"] for item in bridge_summary["commands"] if item["direction"] == "host"]
    assert "0x000000B0" in host_commands
    assert "0x000000B1" in host_commands
    assert "0x000000B2" in host_commands
    assert "0x000000B8" in host_commands
    assert "0x0000008A" in host_commands
    assert host_commands.count("0x000000A0") >= 3


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


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_failed_reset_timing_gate_writes_actionable_result(tmp_path):
    artifacts = tmp_path / "fail-reset-timing"
    r = run_cli(
        "run",
        "--profile", "mock",
        "--scenario", "scenarios/port_gate_fail_reset_timing.yml",
        "--frames", "2",
        "--artifacts", str(artifacts),
        timeout=180,
    )
    assert r.returncode == 1
    result = json.loads((artifacts / "result.json").read_text())
    assert result["ok"] is False
    assert result["failed_phase"] == "assert"
    assert "reset: reset hold time below expectation" in result["failures"]
    assert 0 < result["boot"]["reset_hold_cycles"] < 1000000


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_failed_data_checksum_gate_writes_actionable_result(tmp_path):
    artifacts = tmp_path / "fail-data-checksum"
    r = run_cli(
        "run",
        "--profile", "mock",
        "--scenario", "scenarios/port_gate_fail_data_checksum.yml",
        "--frames", "2",
        "--artifacts", str(artifacts),
        timeout=180,
    )
    assert r.returncode == 1
    result = json.loads((artifacts / "result.json").read_text())
    assert result["ok"] is False
    assert result["failed_phase"] == "assert"
    assert "data: slot 1 checksum mismatch" in result["failures"]
    assert result["data"]["slots"][0]["loaded_checksum"] == "0x86EA4CAF14129F83"
    assert result["data"]["slots"][0]["expected_checksum"] == "0x0000000000000001"


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_failed_audio_timing_gate_writes_actionable_result(tmp_path):
    artifacts = tmp_path / "fail-audio-timing"
    r = run_cli(
        "run",
        "--profile", "mock",
        "--scenario", "scenarios/port_gate_fail_audio_timing.yml",
        "--frames", "2",
        "--artifacts", str(artifacts),
        timeout=180,
    )
    assert r.returncode == 1
    result = json.loads((artifacts / "result.json").read_text())
    assert result["ok"] is False
    assert result["phases"]["audio"]["status"] == "fail"
    assert "audio: MCLK/LRCK ratio outside expectation" in result["failures"]
    assert result["audio"]["estimated_mclk_lrck_ratio"] == 64


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_failed_bridge_endian_gate_writes_actionable_result(tmp_path):
    artifacts = tmp_path / "fail-bridge-endian"
    r = run_cli(
        "run",
        "--profile", "mock_port_gate",
        "--bridge-endian", "big",
        "--artifacts", str(artifacts),
        timeout=180,
    )
    assert r.returncode == 1
    result = json.loads((artifacts / "result.json").read_text())
    assert result["ok"] is False
    assert result["bridge"]["endian"] == "big"
    assert "bridge: endian mode was not little-endian" in result["failures"]
