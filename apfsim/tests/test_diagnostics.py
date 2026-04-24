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
