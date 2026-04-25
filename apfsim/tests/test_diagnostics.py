import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from diagnostics import diagnose_artifacts, write_diagnostics


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def passing_result(width=256, height=224):
    return {
        "ok": True,
        "failed_phase": "",
        "message": "",
        "status": "running",
        "artifact_dir": "",
        "boot": {
            "ok": True,
            "reset_enter_cycle": 10,
            "target_ready_cycle": 20,
            "reset_exit_cycle": 30,
            "running_cycle": 40,
        },
        "bridge": {
            "host_timeouts": 0,
            "slot_table_ok": True,
            "slot_table_writes": 64,
        },
        "data": {"slots": [{"id": 1, "loaded_size": 4, "loaded_words": 1, "observed_write_words": 1}]},
        "interact": {"persistent_writes": 1},
        "input": {"scripted_events": 1, "delivered_events": 1},
        "save": {"reports": []},
        "video": {
            "frames_completed": 3,
            "active_width": width,
            "active_height": height,
            "errors": 0,
            "unique_colors": 8,
            "nonzero_pixels": 100,
            "changed_frames": 2,
        },
        "video_shape": {
            "active_width": width,
            "active_height": height,
            "total_width_min": 384,
            "total_width_max": 384,
            "hs_to_de_gap_min": 1,
            "de_to_hs_gap_min": 1,
            "vs_to_first_de_lines": 0,
            "de_errors": 0,
            "pulse_width_errors": 0,
            "skip_errors": 0,
            "stable_dimensions": True,
            "protocol_valid": True,
        },
        "audio": {
            "sample_rate": 48000,
            "samples": 128,
            "mclk_edges": 4096,
            "lrck_edges": 32,
            "min_l": -4,
            "max_l": 4,
            "min_r": -2,
            "max_r": 2,
        },
        "failures": [],
    }


def diagnostic_codes(doc):
    return [item["code"] for item in doc["diagnostics"]]


def test_diagnostics_detect_video_extra_active_pixel(tmp_path):
    artifacts = tmp_path / "run"
    write_json(artifacts / "result.json", passing_result(width=289, height=224))
    video_json = tmp_path / "video.json"
    write_json(video_json, {"video": {"scaler_modes": [{"width": 288, "height": 224}]}})

    doc = diagnose_artifacts(artifacts, video_metadata_path=video_json)

    assert doc["status"] == "fail"
    assert "VIDEO_EXTRA_ACTIVE_PIXEL" in diagnostic_codes(doc)
    item = next(item for item in doc["diagnostics"] if item["code"] == "VIDEO_EXTRA_ACTIVE_PIXEL")
    assert item["observed"]["active_width"] == 289
    assert item["expected"]["active_width"] == 288
    assert item["repairs"][0]["kind"] == "wrapper_patch"


def test_diagnostics_detect_missing_post_input_video_change(tmp_path):
    artifacts = tmp_path / "run"
    result = passing_result()
    result["ok"] = False
    result["failed_phase"] = "assert"
    result["message"] = "video: no frame changed after input"
    result["input_video_response"] = {
        "name": "after_input",
        "available": True,
        "start_frame": 2,
        "end_frame": 4,
        "frames_considered": 3,
        "changed_frames": 0,
        "max_changed_pixels": 0,
        "required": True,
        "min_changed_frames": 1,
        "min_changed_pixels": 1,
        "changed": False,
        "pass": False,
    }
    write_json(artifacts / "result.json", result)

    doc = diagnose_artifacts(artifacts)

    assert "VIDEO_NO_POST_INPUT_CHANGE" in diagnostic_codes(doc)
    assert "VIDEO_FRAME_COUNT_MISMATCH" not in diagnostic_codes(doc)


def test_diagnostics_suppress_static_frame_when_input_changes_video(tmp_path):
    artifacts = tmp_path / "run"
    result = passing_result()
    result["video"]["unique_colors"] = 1
    result["video"]["nonzero_pixels"] = 0
    result["video"]["changed_frames"] = 0
    result["input_video_response"] = {
        "name": "after_input",
        "changed": True,
        "changed_frames": 1,
        "max_changed_pixels": 128,
        "required": True,
        "pass": True,
    }
    write_json(artifacts / "result.json", result)

    doc = diagnose_artifacts(artifacts)

    assert "VIDEO_STATIC_FRAME" not in diagnostic_codes(doc)
    assert "VIDEO_NO_POST_INPUT_CHANGE" not in diagnostic_codes(doc)


def test_diagnostics_detect_missing_post_input_audio_activity(tmp_path):
    artifacts = tmp_path / "run"
    result = passing_result()
    result["ok"] = False
    result["failed_phase"] = "assert"
    result["message"] = "audio: no activity after input"
    result["input_audio_response"] = {
        "name": "after_input",
        "available": True,
        "start_frame": 2,
        "end_frame": 4,
        "start_sample": 10,
        "end_sample": 10,
        "samples": 0,
        "nonzero_samples": 0,
        "peak": 0,
        "activity": "no_samples",
        "required": True,
        "min_samples": 1,
        "min_nonzero_samples": 1,
        "min_peak": 1,
        "active": False,
        "pass": False,
    }
    write_json(artifacts / "result.json", result)

    doc = diagnose_artifacts(artifacts)

    assert "AUDIO_NO_POST_INPUT_ACTIVITY" in diagnostic_codes(doc)


def test_write_diagnostics_emits_json_and_markdown_report(tmp_path):
    artifacts = tmp_path / "run"
    write_json(artifacts / "result.json", passing_result())

    doc = write_diagnostics(artifacts)

    assert doc["schema"] == "apfsim.diagnostics.v1"
    assert doc["status"] == "pass"
    assert (artifacts / "diagnostics.json").exists()
    report = (artifacts / "bringup-report.md").read_text()
    assert "Status: PASS" in report
    assert "Blocking: none" in report


def test_diagnostics_detect_data_slot_short_write(tmp_path):
    artifacts = tmp_path / "run"
    result = passing_result()
    result["data"]["slots"][0]["loaded_words"] = 8
    result["data"]["slots"][0]["observed_write_words"] = 3
    write_json(artifacts / "result.json", result)

    doc = diagnose_artifacts(artifacts)

    assert "DATA_SLOT_LOAD_SHORT" in diagnostic_codes(doc)


def test_diagnostics_detect_required_data_slot_without_payload(tmp_path):
    artifacts = tmp_path / "run"
    result = passing_result()
    result["ok"] = False
    result["failed_phase"] = "assert"
    result["message"] = "data: required slot 4 was not loaded"
    result["data_load"] = {
        "slots": [
            {
                "id": 4,
                "name": "Cartridge",
                "required": True,
                "has_address": True,
                "loaded_bytes": 0,
                "path": "",
                "load_status": "required_file_unspecified",
            }
        ]
    }
    write_json(artifacts / "result.json", result)

    doc = diagnose_artifacts(artifacts)

    assert "DATA_SLOT_REQUIRED_MISSING" in diagnostic_codes(doc)
    item = next(item for item in doc["diagnostics"] if item["code"] == "DATA_SLOT_REQUIRED_MISSING")
    assert item["phase"] == "data"
    assert item["observed"]["slot"] == 4
    assert item["evidence"][0]["json_pointer"] == "/data_load/slots/0"


def test_diagnostics_detect_required_data_slot_missing_file(tmp_path):
    artifacts = tmp_path / "run"
    result = passing_result()
    result["ok"] = False
    result["failed_phase"] = "startup"
    result["message"] = "required slot 4 file not found"
    result["data_load"] = {
        "slots": [
            {
                "id": 4,
                "name": "Cartridge",
                "required": True,
                "has_address": True,
                "loaded_bytes": 0,
                "path": str(tmp_path / "missing.ngp"),
                "file_exists": False,
                "load_status": "required_file_missing",
                "load_error": "required slot 4 file not found",
            }
        ]
    }
    write_json(artifacts / "result.json", result)

    doc = diagnose_artifacts(artifacts)

    assert "DATA_SLOT_FILE_MISSING" in diagnostic_codes(doc)
    item = next(item for item in doc["diagnostics"] if item["code"] == "DATA_SLOT_FILE_MISSING")
    assert item["observed"]["slot"] == 4
    assert item["observed"]["file_exists"] is False


def test_diagnostics_allow_setup_slot_without_address(tmp_path):
    artifacts = tmp_path / "run"
    result = passing_result()
    result["data_load"] = {
        "slots": [
            {
                "id": 0,
                "name": "Game JSON Setup",
                "required": True,
                "has_address": False,
                "loaded_bytes": 0,
                "path": "setup.json",
                "file_exists": True,
                "load_status": "no_address",
            }
        ]
    }
    write_json(artifacts / "result.json", result)

    doc = diagnose_artifacts(artifacts)

    assert "DATA_SLOT_ADDRESS_INVALID" not in diagnostic_codes(doc)
    assert "DATA_SLOT_REQUIRED_MISSING" not in diagnostic_codes(doc)


def test_diagnostics_detect_target_data_slot_id_mismatch(tmp_path):
    artifacts = tmp_path / "run"
    result = passing_result()
    result["bridge"]["target_slot_errors"] = 1
    result["bridge"]["target_dataslot_reads"] = 2
    write_json(artifacts / "result.json", result)

    doc = diagnose_artifacts(artifacts)

    assert "DATA_SLOT_ID_MISMATCH" in diagnostic_codes(doc)
    item = next(item for item in doc["diagnostics"] if item["code"] == "DATA_SLOT_ID_MISMATCH")
    assert item["observed"]["target_slot_errors"] == 1


def test_diagnostics_detect_data_slot_readback_mismatch(tmp_path):
    artifacts = tmp_path / "run"
    result = passing_result()
    result["ok"] = False
    result["failed_phase"] = "assert"
    result["message"] = "data: slot 1 readback mismatch"
    result["data"]["slots"][0].update({
        "loaded_size": 4,
        "loaded_crc32": "0x12345678",
        "loaded_checksum": "0xAAAAAAAAAAAAAAAA",
        "verify_readback": True,
        "readback_attempted": True,
        "readback_matches": False,
        "readback_bytes": 4,
        "readback_crc32": "0xDEADBEEF",
        "readback_checksum": "0xBBBBBBBBBBBBBBBB",
        "readback_mismatch_count": 1,
        "readback_first_mismatch_offset": 2,
        "readback_expected_byte": 17,
        "readback_observed_byte": 34,
    })
    write_json(artifacts / "result.json", result)

    doc = diagnose_artifacts(artifacts)

    assert "DATA_SLOT_READBACK_MISMATCH" in diagnostic_codes(doc)
    item = next(item for item in doc["diagnostics"] if item["code"] == "DATA_SLOT_READBACK_MISMATCH")
    assert item["observed"]["first_mismatch_offset"] == 2
    assert "external RAM write path corrupted ROM bytes" in item["likely_causes"]


def test_diagnostics_surface_memory_model_profile_risk(tmp_path):
    artifacts = tmp_path / "run"
    write_json(artifacts / "result.json", passing_result())

    doc = diagnose_artifacts(artifacts, profile={
        "memory": {
            "schema": "apfsim.memory_dependencies.v1",
            "classes": ["sram"],
            "external_classes": ["sram"],
            "risks": [
                {
                    "code": "SRAM_MODEL_REQUIRED",
                    "severity": "error",
                    "message": "Async external SRAM dependency detected; pin/bus model is required.",
                }
            ],
        }
    })

    assert "SRAM_MODEL_REQUIRED" in diagnostic_codes(doc)
    assert doc["status"] == "fail"


def test_diagnostics_surface_live_memory_counter_errors(tmp_path):
    artifacts = tmp_path / "run"
    write_json(artifacts / "result.json", passing_result())
    write_json(artifacts / "memory_activity.json", {
        "schema": "apfsim.memory_activity.v1",
        "observed": True,
        "counter_status": "observed",
        "counters": [
            {"name": "sram_read_count", "class": "sram", "value": 12, "error": False},
            {
                "name": "sram_byte_enable_error",
                "class": "sram",
                "value": 1,
                "error": True,
                "error_code": "MEMORY_BYTE_ENABLE_MISMATCH",
            },
        ],
        "errors": [
            {
                "code": "MEMORY_BYTE_ENABLE_MISMATCH",
                "severity": "error",
                "counter": "sram_byte_enable_error",
                "class": "sram",
                "value": 1,
                "observed": True,
            }
        ],
    })

    doc = diagnose_artifacts(artifacts)

    assert "MEMORY_BYTE_ENABLE_MISMATCH" in diagnostic_codes(doc)
    item = next(item for item in doc["diagnostics"] if item["code"] == "MEMORY_BYTE_ENABLE_MISMATCH")
    assert item["phase"] == "memory"
    assert item["observed"]["counter"] == "sram_byte_enable_error"
    assert item["evidence"][0]["artifact"] == "memory_activity.json"


def test_diagnostics_explain_sdram_rom_write_mismatch(tmp_path):
    artifacts = tmp_path / "run"
    result = passing_result()
    result["data_load"] = {
        "total_loaded_bytes": 4096,
        "slots": [{
            "id": 1,
            "name": "ROM",
            "path": "game.rom",
            "address": "0x10000000",
            "has_address": True,
            "loaded_bytes": 4096,
            "crc": "0x12345678",
        }],
    }
    write_json(artifacts / "result.json", result)
    write_json(artifacts / "memory_activity.json", {
        "schema": "apfsim.memory_activity.v1",
        "observed": True,
        "counter_status": "observed",
        "counters": [
            {
                "name": "sdram_rom_mismatch_count",
                "class": "sdram",
                "value": 1,
                "error": True,
                "error_code": "MEMORY_ROM_WRITE_MISMATCH",
            },
            {"name": "sdram_first_rom_mismatch_addr", "class": "sdram", "value": 4660, "error": False},
            {"name": "sdram_first_rom_mismatch_expected", "class": "sdram", "value": 43690, "error": False},
            {"name": "sdram_first_rom_mismatch_actual", "class": "sdram", "value": 21845, "error": False},
            {"name": "sdram_first_rom_mismatch_dqm", "class": "sdram", "value": 2, "error": False},
        ],
        "errors": [
            {
                "code": "MEMORY_ROM_WRITE_MISMATCH",
                "severity": "error",
                "counter": "sdram_rom_mismatch_count",
                "class": "sdram",
                "value": 1,
                "observed": True,
            }
        ],
    })

    doc = diagnose_artifacts(artifacts)

    item = next(item for item in doc["diagnostics"] if item["code"] == "MEMORY_ROM_WRITE_MISMATCH")
    assert item["phase"] == "memory"
    assert item["observed"]["expected_word"] == 43690
    assert item["observed"]["actual_word"] == 21845
    assert item["observed"]["byte_lanes_checked"] == {"low": True, "high": False}
    assert item["observed"]["source"]["matched"] is False
    assert "external SDRAM write path corrupted ROM-backed bytes" in item["likely_causes"]
    assert "bank/address packing" in item["repairs"][0]["description"]


def test_diagnostics_attribute_sdram_rom_mismatch_to_source_slot(tmp_path):
    artifacts = tmp_path / "run"
    result = passing_result()
    result["data_load"] = {
        "total_loaded_bytes": 4096,
        "slots": [{
            "id": 1,
            "name": "ROM",
            "path": "game.rom",
            "address": "0x10000000",
            "has_address": True,
            "loaded_bytes": 4096,
            "crc": "0x12345678",
        }],
    }
    write_json(artifacts / "result.json", result)
    write_json(artifacts / "memory_activity.json", {
        "schema": "apfsim.memory_activity.v1",
        "observed": True,
        "counter_status": "observed",
        "counters": [
            {"name": "sdram_rom_mismatch_count", "class": "sdram", "value": 1, "error": True, "error_code": "MEMORY_ROM_WRITE_MISMATCH"},
            {"name": "sdram_first_rom_mismatch_addr", "class": "sdram", "value": 4, "error": False},
            {"name": "sdram_first_rom_mismatch_expected", "class": "sdram", "value": 0x1122, "error": False},
            {"name": "sdram_first_rom_mismatch_actual", "class": "sdram", "value": 0x3344, "error": False},
            {"name": "sdram_first_rom_mismatch_dqm", "class": "sdram", "value": 1, "error": False},
        ],
        "errors": [
            {"code": "MEMORY_ROM_WRITE_MISMATCH", "severity": "error", "counter": "sdram_rom_mismatch_count", "class": "sdram", "value": 1, "observed": True},
        ],
    })

    doc = diagnose_artifacts(artifacts)

    item = next(item for item in doc["diagnostics"] if item["code"] == "MEMORY_ROM_WRITE_MISMATCH")
    assert item["observed"]["slot_id"] == 1
    assert item["observed"]["source_file"] == "game.rom"
    assert item["observed"]["source_offset"] == 8
    assert item["observed"]["byte_lanes"]["names"] == ["high"]


def test_diagnostics_warn_on_sdram_rom_coverage_gap(tmp_path):
    artifacts = tmp_path / "run"
    write_json(artifacts / "result.json", passing_result())
    write_json(artifacts / "memory_activity.json", {
        "schema": "apfsim.memory_activity.v1",
        "observed": True,
        "counter_status": "observed",
        "counters": [
            {"name": "sdram_rom_coverage_gap_count", "class": "sdram", "value": 3, "error": False},
            {"name": "sdram_first_coverage_gap_addr", "class": "sdram", "value": 12582912, "error": False},
        ],
        "errors": [],
    })

    doc = diagnose_artifacts(artifacts)

    item = next(item for item in doc["diagnostics"] if item["code"] == "MEMORY_ROM_COVERAGE_GAP")
    assert item["severity"] == "warning"
    assert item["observed"]["first_addr"] == 12582912
    assert any("setup or message asset" in cause for cause in item["likely_causes"])


def test_diagnostics_warn_when_observed_memory_counters_stay_idle_during_load(tmp_path):
    artifacts = tmp_path / "run"
    result = passing_result()
    result["data_load"] = {"total_loaded_bytes": 1024}
    write_json(artifacts / "result.json", result)
    write_json(artifacts / "memory_activity.json", {
        "schema": "apfsim.memory_activity.v1",
        "observed": True,
        "counter_status": "observed",
        "counters": [
            {"name": "sram_read_count", "class": "sram", "value": 0, "error": False},
            {"name": "sram_write_count", "class": "sram", "value": 0, "error": False},
        ],
        "errors": [],
    })

    doc = diagnose_artifacts(artifacts)

    assert "MEMORY_NO_ACTIVITY" in diagnostic_codes(doc)
    item = next(item for item in doc["diagnostics"] if item["code"] == "MEMORY_NO_ACTIVITY")
    assert item["severity"] == "warning"
    assert item["observed"]["loaded_bytes"] == 1024


def test_diagnostics_do_not_require_save_roundtrip_when_only_unload_was_expected(tmp_path):
    artifacts = tmp_path / "run"
    result = passing_result()
    result["data"]["slots"].append({"id": 4, "nonvolatile": True, "loaded_size": 43, "file": "mock.hi"})
    result["save"] = {"reports": [{"id": 4, "bytes": 43, "matches_input": False}]}
    write_json(artifacts / "result.json", result)

    doc = diagnose_artifacts(artifacts)

    assert "SAVE_ROUNDTRIP_MISMATCH" not in diagnostic_codes(doc)


def test_diagnostics_report_save_roundtrip_when_scenario_failed_on_roundtrip(tmp_path):
    artifacts = tmp_path / "run"
    result = passing_result()
    result["ok"] = False
    result["failed_phase"] = "save"
    result["message"] = "save: unloaded slot 4 did not match input"
    result["data"]["slots"].append({"id": 4, "nonvolatile": True, "loaded_size": 43, "file": "mock.hi"})
    result["save"] = {"reports": [{"id": 4, "bytes": 43, "matches_input": False}]}
    write_json(artifacts / "result.json", result)

    doc = diagnose_artifacts(artifacts)

    assert "SAVE_ROUNDTRIP_MISMATCH" in diagnostic_codes(doc)
