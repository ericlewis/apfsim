import json
import struct
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from artifact_validator import ArtifactValidationError, derive_phase_statuses, validate_artifacts


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def write_wav(path: Path, frames: list[tuple[int, int]], sample_rate: int = 48000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        payload = b"".join(struct.pack("<hh", left, right) for left, right in frames)
        wav.writeframes(payload)


def base_result(tmp_path: Path):
    save_path = tmp_path / "artifacts" / "saves" / "slot_4.bin"
    return {
        "ok": True,
        "failed_phase": "",
        "status": "running",
        "boot": {
            "ok": True,
            "reset_enter_cycle": 10,
            "target_ready_cycle": 20,
            "reset_exit_cycle": 30,
            "running_cycle": 40,
        },
        "data": {
            "slots": [
                {"id": 1, "loaded_size": 1024, "nonvolatile": False},
                {"id": 4, "loaded_size": 4, "nonvolatile": True},
            ]
        },
        "video": {"frames_completed": 1, "active_width": 256, "active_height": 224, "errors": 0},
        "video_shape": {
            "active_width": 256,
            "active_height": 224,
            "total_width_min": 341,
            "total_width_max": 341,
            "hs_to_de_gap_min": 1,
            "de_to_hs_gap_min": 1,
            "vs_to_first_de_lines": 0,
            "de_errors": 0,
            "pulse_width_errors": 0,
            "skip_errors": 0,
            "stable_dimensions": True,
            "protocol_valid": True,
        },
        "audio": {"sample_rate": 48000, "samples": 3},
        "bridge": {
            "endian": "little",
            "reads": 10,
            "writes": 20,
            "host_commands": 4,
            "target_commands": 1,
            "slot_table_writes": 64,
            "data_payload_writes": 256,
        },
        "interact": {"persistent_writes": 1},
        "input": {"scripted_events": 1, "delivered_events": 1, "ever_active": True},
        "save": {"reports": [{"id": 4, "bytes": 4, "path": str(save_path), "matches_input": True}]},
        "failures": [],
    }


def write_valid_artifacts(root: Path):
    write_json(
        root / "video" / "frame_000001.json",
        {"active_width": 256, "active_width_min": 256, "active_height": 224, "de_errors": 0},
    )
    write_json(
        root / "audio" / "stats.json",
        {
            "sample_rate": 48000,
            "channels": 2,
            "samples": 3,
            "min_l": 0,
            "max_l": 2,
            "min_r": -2,
            "max_r": 2,
            "peak_to_peak_l": 2,
            "peak_to_peak_r": 4,
            "dc_offset_l": 1,
            "dc_offset_r": 0,
            "clipped_samples": 0,
        },
    )
    write_json(
        root / "video_shape.json",
        {
            "schema": "apfsim.video_shape.v1",
            "source_result": str(root / "result.json"),
            "result_ok": True,
            "video_shape": {
                "active_width": 256,
                "active_height": 224,
                "total_width_min": 341,
                "total_width_max": 341,
                "hs_to_de_gap_min": 1,
                "de_to_hs_gap_min": 1,
                "vs_to_first_de_lines": 0,
                "de_errors": 0,
                "pulse_width_errors": 0,
                "skip_errors": 0,
                "stable_dimensions": True,
                "protocol_valid": True,
            },
        },
    )
    write_wav(root / "audio" / "out.wav", [(0, -2), (1, 0), (2, 2)])
    write_json(
        root / "bridge_summary.json",
        {
            "endian": "little",
            "reads": 10,
            "writes": 20,
            "host_commands": 4,
            "target_commands": 1,
            "slot_table_writes": 64,
            "data_payload_writes": 256,
            "commands": [],
        },
    )
    save_path = root / "saves" / "slot_4.bin"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(b"save")


def test_validate_artifacts_hydrates_phase_statuses_and_accepts_valid_outputs(tmp_path):
    artifacts = tmp_path / "artifacts"
    result = base_result(tmp_path)
    write_json(artifacts / "result.json", result)
    write_valid_artifacts(artifacts)
    video_metadata = tmp_path / "video.json"
    write_json(video_metadata, {"expected_width": 256, "expected_height": 224})

    validated = validate_artifacts(artifacts, video_metadata_path=video_metadata, update_result=True)

    assert sorted(validated["phases"]) == ["audio", "boot", "data", "input", "interact", "reset", "save", "video"]
    assert {phase["status"] for phase in validated["phases"].values()} == {"pass"}
    assert {phase["ok"] for phase in validated["phases"].values()} == {True}
    persisted = json.loads((artifacts / "result.json").read_text())
    assert persisted["phases"]["save"]["status"] == "pass"
    assert persisted["lifecycle"]["cycles"]["reset_enter"] == 10
    assert persisted["lifecycle"]["durations"]["boot_to_running_cycles"] == 40
    lifecycle = json.loads((artifacts / "lifecycle.json").read_text())
    assert lifecycle["schema"] == "apfsim.lifecycle.v1"
    assert lifecycle["lifecycle"] == persisted["lifecycle"]


def test_validate_artifacts_requires_existing_phase_statuses_without_update(tmp_path):
    artifacts = tmp_path / "artifacts"
    write_json(artifacts / "result.json", base_result(tmp_path))
    write_valid_artifacts(artifacts)

    with pytest.raises(ArtifactValidationError, match="missing phases object"):
        validate_artifacts(artifacts, update_result=False)


def test_validate_artifacts_rejects_video_dimension_mismatch(tmp_path):
    artifacts = tmp_path / "artifacts"
    result = base_result(tmp_path)
    result["phases"] = derive_phase_statuses(result)
    write_json(artifacts / "result.json", result)
    write_valid_artifacts(artifacts)
    write_json(artifacts / "video" / "frame_000001.json", {"active_width": 320, "active_height": 224})

    with pytest.raises(ArtifactValidationError, match="active_width 320"):
        validate_artifacts(artifacts)


def test_validate_artifacts_rejects_wav_stats_mismatch(tmp_path):
    artifacts = tmp_path / "artifacts"
    result = base_result(tmp_path)
    result["phases"] = derive_phase_statuses(result)
    write_json(artifacts / "result.json", result)
    write_valid_artifacts(artifacts)
    write_wav(artifacts / "audio" / "out.wav", [(0, 0), (1, 1)])

    with pytest.raises(ArtifactValidationError, match="WAV frames 2 do not match stats samples 3"):
        validate_artifacts(artifacts)


def test_validate_artifacts_requires_save_report_for_nonvolatile_slot(tmp_path):
    artifacts = tmp_path / "artifacts"
    result = base_result(tmp_path)
    result["save"] = {"reports": []}
    result["phases"] = derive_phase_statuses(result)
    write_json(artifacts / "result.json", result)
    write_valid_artifacts(artifacts)

    with pytest.raises(ArtifactValidationError, match="missing save report for nonvolatile slot 4"):
        validate_artifacts(artifacts)


def test_public_schema_files_are_valid_json():
    schema_dir = ROOT / "schemas"
    expected = {
        "bridge_summary.schema.json",
        "corpus_summary.schema.json",
        "diagnostic.schema.json",
        "generated_profile.schema.json",
        "lifecycle.schema.json",
        "memory_activity.schema.json",
        "memory_dependencies.schema.json",
        "package_check.schema.json",
        "profile.schema.json",
        "repair_plan.schema.json",
        "result.schema.json",
        "run_summary.schema.json",
        "shim_catalog.schema.json",
        "source_provenance.schema.json",
        "video_apply.schema.json",
        "video_activity.schema.json",
        "video_compare.schema.json",
        "video_shape.schema.json",
    }
    found = {path.name for path in schema_dir.glob("*.schema.json")}
    assert expected <= found
    for name in expected:
        data = json.loads((schema_dir / name).read_text())
        assert data["$schema"].startswith("https://json-schema.org/")
        assert data["type"] == "object"
