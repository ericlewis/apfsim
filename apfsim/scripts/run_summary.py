#!/usr/bin/env python3
"""Normalize apfsim run artifacts into one machine-readable per-core row."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

SCHEMA = "apfsim.run_summary.v1"
TSV_COLUMNS = [
    "ok",
    "first_error_code",
    "blocking_codes",
    "warning_codes",
    "package_ok",
    "package_error_count",
    "active_width",
    "active_height",
    "frames_considered",
    "video_protocol_valid",
    "audio_activity",
    "audio_samples",
    "audio_nonzero_samples",
    "loaded_bytes_total",
    "data_crc_list",
    "data_readback_verified_slots",
    "data_readback_mismatches",
    "data_readback_failed_slots",
    "input_effect_seen",
    "interact_readback_verified",
    "reset_action_seen",
    "shimmed_modules",
    "memory_classes",
    "memory_models",
    "memory_risks",
    "artifact_dir",
]


def load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def optional_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return load_json_object(path)


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on", "pass"}
    return default


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return default
    return default


def summarize_run(artifact_dir: Path, *, package_check_path: Path | None = None) -> dict[str, Any]:
    artifact_dir = artifact_dir.resolve()
    result = optional_json_object(artifact_dir / "result.json")
    diagnostics = optional_json_object(artifact_dir / "diagnostics.json")
    package = optional_json_object(package_check_path or (artifact_dir / "package_check.json"))
    provenance = optional_json_object(artifact_dir / "source_provenance.json")

    diag_items = [item for item in _list(diagnostics.get("diagnostics")) if isinstance(item, dict)]
    blocking_codes = [str(item.get("code")) for item in diag_items if item.get("severity") == "error"]
    warning_codes = [str(item.get("code")) for item in diag_items if item.get("severity") == "warning"]
    first_error_code = blocking_codes[0] if blocking_codes else ""

    video_shape = _obj(result.get("video_shape"))
    video_protocol = _obj(result.get("video_protocol"))
    audio = _obj(result.get("audio"))
    data_load = _obj(result.get("data_load"))
    input_doc = _obj(result.get("input"))
    interact_readback = _obj(result.get("interact_readback"))
    shimmed = [str(item.get("name")) for item in _list(provenance.get("shimmed_modules")) if isinstance(item, dict) and item.get("name")]
    memory_doc = _obj(provenance.get("memory_dependencies"))
    memory_models_doc = [item for item in _list(provenance.get("memory_models")) if isinstance(item, dict)]
    memory_classes = [str(item) for item in _list(memory_doc.get("classes"))]
    memory_models = [
        f"{item.get('class')}:{item.get('model')}"
        for item in memory_models_doc
        if item.get("class") and item.get("model")
    ]
    memory_risks = [
        str(item.get("code"))
        for item in _list(memory_doc.get("risks"))
        if isinstance(item, dict) and item.get("code")
    ]
    data_slots = [slot for slot in _list(data_load.get("slots")) if isinstance(slot, dict)]
    data_crc_list = [str(slot.get("crc")) for slot in data_slots if slot.get("crc")]
    data_readback_verified_slots = sum(1 for slot in data_slots if _as_bool(slot.get("readback_attempted"), False))
    data_readback_mismatches = sum(_as_int(slot.get("readback_mismatch_count"), 0) for slot in data_slots)
    data_readback_failed_slots = [
        str(slot.get("id"))
        for slot in data_slots
        if _as_bool(slot.get("readback_attempted"), False) and not _as_bool(slot.get("readback_matches"), True)
    ]

    package_errors = _list(package.get("package_errors"))
    package_warnings = _list(package.get("package_warnings"))
    package_known = bool(package)
    package_ok = _as_bool(package.get("ok"), True) if package_known else None
    result_ok = _as_bool(result.get("ok"), False)
    diagnostics_ok = not blocking_codes
    ok = result_ok and diagnostics_ok and (package_ok is not False)

    row = {
        "ok": ok,
        "first_error_code": first_error_code,
        "blocking_codes": blocking_codes,
        "warning_codes": warning_codes,
        "package_ok": package_ok,
        "package_error_count": len(package_errors),
        "package_warning_count": len(package_warnings),
        "active_width": _as_int(video_shape.get("active_width"), 0),
        "active_height": _as_int(video_shape.get("active_height"), 0),
        "frames_considered": _as_int(video_shape.get("frames_considered", video_shape.get("frames_measured")), 0),
        "startup_frames_ignored": _as_int(video_shape.get("startup_frames_ignored", video_shape.get("ignored_startup_frames")), 0),
        "video_protocol_valid": _as_bool(video_protocol.get("valid", video_shape.get("protocol_valid")), False),
        "video_first_error_cycle": _as_int(video_protocol.get("first_error_cycle", video_shape.get("first_error_cycle")), 0),
        "audio_activity": str(audio.get("activity") or "unknown"),
        "audio_samples": _as_int(audio.get("samples"), 0),
        "audio_nonzero_samples": _as_int(audio.get("nonzero_samples"), 0),
        "audio_peak": _as_int(audio.get("peak"), 0),
        "loaded_bytes_total": _as_int(data_load.get("total_loaded_bytes"), 0),
        "data_crc_list": data_crc_list,
        "data_readback_verified_slots": data_readback_verified_slots,
        "data_readback_mismatches": data_readback_mismatches,
        "data_readback_failed_slots": data_readback_failed_slots,
        "input_effect_seen": _as_bool(result.get("input_effect_seen", input_doc.get("input_effect_seen")), False),
        "interact_readback_verified": _as_bool(interact_readback.get("verified"), False),
        "reset_action_seen": _as_bool(result.get("reset_action_seen"), False),
        "shimmed_modules": shimmed,
        "memory_classes": memory_classes,
        "memory_models": memory_models,
        "memory_risks": memory_risks,
        "artifact_dir": str(artifact_dir),
    }
    return {
        "schema": SCHEMA,
        "artifact_dir": str(artifact_dir),
        "ok": ok,
        "row": row,
        "diagnostics": {
            "first_error_code": first_error_code,
            "blocking_codes": blocking_codes,
            "warning_codes": warning_codes,
        },
        "package": {
            "known": package_known,
            "ok": package_ok,
            "errors": package_errors,
            "warnings": package_warnings,
        },
        "video": {
            "active_width": row["active_width"],
            "active_height": row["active_height"],
            "frames_considered": row["frames_considered"],
            "startup_frames_ignored": row["startup_frames_ignored"],
            "protocol_valid": row["video_protocol_valid"],
            "first_error_cycle": row["video_first_error_cycle"],
        },
        "audio": {
            "activity": row["audio_activity"],
            "samples": row["audio_samples"],
            "nonzero_samples": row["audio_nonzero_samples"],
            "peak": row["audio_peak"],
        },
        "data": {
            "loaded_bytes_total": row["loaded_bytes_total"],
            "crc_list": data_crc_list,
            "readback_verified_slots": data_readback_verified_slots,
            "readback_mismatches": data_readback_mismatches,
            "readback_failed_slots": data_readback_failed_slots,
        },
        "source_provenance": {
            "shimmed_modules": shimmed,
            "memory_dependencies": memory_doc,
            "memory_models": memory_models_doc,
        },
    }


def write_summary(
    artifact_dir: Path,
    *,
    json_out: Path | None = None,
    tsv_out: Path | None = None,
    package_check_path: Path | None = None,
) -> dict[str, Any]:
    doc = summarize_run(artifact_dir, package_check_path=package_check_path)
    if json_out is None:
        json_out = artifact_dir / "summary.json"
    if tsv_out is None:
        tsv_out = artifact_dir / "summary.tsv"
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    write_summary_tsv(doc, tsv_out)
    return doc


def write_summary_tsv(doc: dict[str, Any], path: Path) -> None:
    row = _obj(doc.get("row"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TSV_COLUMNS, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerow({key: _tsv_value(row.get(key)) for key in TSV_COLUMNS})


def _tsv_value(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
