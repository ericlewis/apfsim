#!/usr/bin/env python3
"""Runtime artifact validation for apfsim profile runs."""

from __future__ import annotations

import json
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_PHASES = ("boot", "reset", "data", "video", "audio", "interact", "input", "save")
PASS = "pass"
FAIL = "fail"
MISSING = "missing"
LIFECYCLE_SCHEMA = "apfsim.lifecycle.v1"
LIFECYCLE_PHASES = (
    ("boot_start", "start_cycle"),
    ("status_setup", "setup_cycle"),
    ("reset_enter", "reset_enter_cycle"),
    ("slot_table_populated", "slot_table_cycle"),
    ("data_load_complete", "data_load_complete_cycle"),
    ("data_slot_all_complete", "data_all_complete_cycle"),
    ("rtc_sent", "rtc_cycle"),
    ("target_ready_to_run", "target_ready_cycle"),
    ("before_reset_exit", "before_reset_exit_cycle"),
    ("reset_exit", "reset_exit_cycle"),
    ("status_running", "running_cycle"),
)


@dataclass(frozen=True)
class ArtifactIssue:
    path: Path
    message: str


class ArtifactValidationError(RuntimeError):
    def __init__(self, issues: list[ArtifactIssue]):
        self.issues = issues
        super().__init__(format_issues(issues))


def format_issues(issues: list[ArtifactIssue]) -> str:
    return "artifact validation failed:\n" + "\n".join(f"  - {issue.path}: {issue.message}" for issue in issues)


def validate_artifacts(
    artifact_root: Path,
    *,
    video_metadata_path: Path | None = None,
    update_result: bool = False,
) -> dict[str, Any]:
    """Validate a runtime artifact directory and optionally annotate result.json.

    The validator is intentionally additive: with update_result=True it writes a
    derived `phases` block into result.json before validating that block.
    """

    artifact_root = Path(artifact_root)
    result_path = artifact_root / "result.json"
    issues: list[ArtifactIssue] = []
    result = _load_json_object(result_path, issues, "result.json")
    if result is None:
        raise ArtifactValidationError(issues)

    if update_result:
        phases = derive_phase_statuses(result)
        lifecycle_doc = derive_lifecycle_document(result, result_path)
        lifecycle = lifecycle_doc["lifecycle"]
        dirty = False
        if result.get("phases") != phases:
            result["phases"] = phases
            dirty = True
        if result.get("lifecycle") != lifecycle:
            result["lifecycle"] = lifecycle
            dirty = True
        if dirty:
            result_path.write_text(json.dumps(result, indent=2) + "\n")
        _write_lifecycle_document(artifact_root / "lifecycle.json", lifecycle_doc)

    _validate_phase_statuses(result_path, result, issues)
    _validate_video_artifacts(artifact_root, result, issues)
    _validate_video_shape_artifact(artifact_root, result, issues)
    _validate_lifecycle_artifact(artifact_root, result, issues)
    if video_metadata_path is not None:
        _validate_video_metadata(Path(video_metadata_path), result, issues)
    _validate_audio_artifacts(artifact_root, result, issues)
    _validate_bridge_artifacts(artifact_root, result, issues)
    _validate_save_artifacts(artifact_root, result, issues)

    if issues:
        raise ArtifactValidationError(issues)
    return result


def annotate_result_phases(artifact_root: Path) -> bool:
    """Best-effort phase annotation for failed runs without changing CLI status."""

    result_path = Path(artifact_root) / "result.json"
    try:
        with result_path.open() as fh:
            result = json.load(fh)
        if not isinstance(result, dict):
            return False
        phases = derive_phase_statuses(result)
        if result.get("phases") != phases:
            result["phases"] = phases
            result_path.write_text(json.dumps(result, indent=2) + "\n")
        return True
    except (OSError, json.JSONDecodeError):
        return False


def derive_phase_statuses(result: dict[str, Any]) -> dict[str, dict[str, str]]:
    failures = [str(item) for item in result.get("failures", []) if isinstance(item, str)]
    failed_phase = str(result.get("failed_phase") or "")
    phases: dict[str, dict[str, str]] = {}
    for phase in REQUIRED_PHASES:
        status = _phase_status(result, phase, failures, failed_phase)
        phases[phase] = {"status": status, "ok": status == PASS}
    return phases


def derive_lifecycle_document(result: dict[str, Any], source_result: Path | str) -> dict[str, Any]:
    lifecycle = derive_lifecycle(result)
    return {
        "schema": LIFECYCLE_SCHEMA,
        "source_result": str(source_result),
        "result_ok": bool(result.get("ok", False)),
        "lifecycle": lifecycle,
    }


def derive_lifecycle(result: dict[str, Any]) -> dict[str, Any]:
    boot = result.get("boot") if isinstance(result.get("boot"), dict) else {}
    video = result.get("video") if isinstance(result.get("video"), dict) else {}
    audio = result.get("audio") if isinstance(result.get("audio"), dict) else {}
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    slots = data.get("slots", []) if isinstance(data.get("slots"), list) else []

    cycles: dict[str, int] = {}
    events: list[dict[str, int | str]] = []
    for name, field in LIFECYCLE_PHASES:
        cycle = _optional_int(boot.get(field))
        if cycle is None:
            cycle = 0
        cycles[name] = cycle
        if cycle > 0 or name == "boot_start":
            events.append({"name": name, "cycle": cycle})

    loaded_slots = [slot for slot in slots if isinstance(slot, dict) and _number(slot.get("loaded_size"), 0) > 0]
    lifecycle = {
        "cycles_74a": _optional_int(result.get("cycles_74a")) or 0,
        "boot_ok": bool(boot.get("ok", False)),
        "running": (_optional_int(boot.get("running_cycle")) or 0) > 0,
        "cycles": cycles,
        "events": events,
        "durations": {
            "boot_to_running_cycles": _duration(cycles.get("boot_start"), cycles.get("status_running"), allow_zero_start=True),
            "reset_hold_cycles": _duration(cycles.get("reset_enter"), cycles.get("reset_exit")),
            "reset_exit_to_running_cycles": _duration(cycles.get("reset_exit"), cycles.get("status_running")),
            "data_load_cycles": _duration(cycles.get("slot_table_populated"), cycles.get("data_load_complete")),
        },
        "counters": {
            "frames_completed": _optional_int(video.get("frames_completed")) or 0,
            "frames_started": _optional_int(video.get("frames_started")) or 0,
            "audio_samples": _optional_int(audio.get("samples")) or 0,
            "loaded_slots": len(loaded_slots),
        },
    }
    return lifecycle


def _duration(start: int | None, end: int | None, *, allow_zero_start: bool = False) -> int:
    if start is None or end is None or end == 0 or end < start:
        return 0
    if start == 0 and not allow_zero_start:
        return 0
    return end - start


def _write_lifecycle_document(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")


def _phase_status(result: dict[str, Any], phase: str, failures: list[str], failed_phase: str) -> str:
    if any(item.startswith(f"{phase}:") for item in failures):
        return FAIL
    if failed_phase == phase:
        return FAIL

    value = result.get(phase)
    if phase == "boot":
        if isinstance(value, dict):
            return PASS if bool(value.get("ok")) else FAIL
        return MISSING
    if phase == "reset":
        boot = result.get("boot") if isinstance(result.get("boot"), dict) else {}
        if not boot:
            return MISSING
        required = ("reset_enter_cycle", "target_ready_cycle", "reset_exit_cycle", "running_cycle")
        return PASS if all(_number(boot.get(key), 0) > 0 for key in required) else FAIL
    if phase == "data":
        if isinstance(value, dict) and isinstance(value.get("slots", []), list):
            return PASS
        return MISSING
    if phase == "video":
        if isinstance(value, dict):
            return FAIL if _number(value.get("errors"), 0) > 0 else PASS
        return MISSING
    if phase == "audio":
        if isinstance(value, dict):
            return PASS if _number(value.get("sample_rate"), 0) > 0 else FAIL
        return MISSING
    if phase == "interact":
        if isinstance(value, dict):
            return PASS
        return MISSING
    if phase == "input":
        if isinstance(value, dict):
            delivered = _number(value.get("delivered_events"), 0)
            scripted = _number(value.get("scripted_events"), 0)
            return FAIL if delivered < scripted else PASS
        return MISSING
    if phase == "save":
        if isinstance(value, dict) and isinstance(value.get("reports", []), list):
            return PASS
        return MISSING
    return MISSING


def _validate_phase_statuses(path: Path, result: dict[str, Any], issues: list[ArtifactIssue]) -> None:
    phases = result.get("phases")
    if not isinstance(phases, dict):
        issues.append(ArtifactIssue(path, "missing phases object"))
        return
    for phase in REQUIRED_PHASES:
        entry = phases.get(phase)
        if not isinstance(entry, dict):
            issues.append(ArtifactIssue(path, f"missing phases.{phase} status"))
            continue
        status = entry.get("status")
        if status not in {PASS, FAIL, MISSING}:
            issues.append(ArtifactIssue(path, f"phases.{phase}.status must be pass, fail, or missing"))


def _validate_video_artifacts(artifact_root: Path, result: dict[str, Any], issues: list[ArtifactIssue]) -> None:
    video_dir = artifact_root / "video"
    if not video_dir.is_dir():
        return

    video = result.get("video") if isinstance(result.get("video"), dict) else {}
    expected_width = _optional_int(video.get("active_width"))
    expected_height = _optional_int(video.get("active_height"))

    for path in sorted(video_dir.glob("*.json")):
        meta = _load_json_object(path, issues, "video frame metadata")
        if meta is None:
            continue
        width = _optional_int(meta.get("active_width"))
        height = _optional_int(meta.get("active_height"))
        if width is None or width <= 0:
            issues.append(ArtifactIssue(path, "active_width must be a positive integer"))
        if height is None or height <= 0:
            issues.append(ArtifactIssue(path, "active_height must be a positive integer"))
        min_width = _optional_int(meta.get("active_width_min"))
        if min_width is not None and width is not None and (min_width <= 0 or min_width > width):
            issues.append(ArtifactIssue(path, "active_width_min must be positive and <= active_width"))
        if expected_width is not None and width is not None and width != expected_width:
            issues.append(ArtifactIssue(path, f"active_width {width} does not match result video width {expected_width}"))
        if expected_height is not None and height is not None and height != expected_height:
                issues.append(ArtifactIssue(path, f"active_height {height} does not match result video height {expected_height}"))


def _validate_video_shape_artifact(artifact_root: Path, result: dict[str, Any], issues: list[ArtifactIssue]) -> None:
    result_path = artifact_root / "result.json"
    shape = result.get("video_shape")
    if not isinstance(shape, dict):
        issues.append(ArtifactIssue(result_path, "missing video_shape object"))
        return

    required = (
        "active_width",
        "active_height",
        "total_width_min",
        "total_width_max",
        "hs_to_de_gap_min",
        "de_to_hs_gap_min",
        "vs_to_first_de_lines",
        "de_errors",
        "pulse_width_errors",
        "skip_errors",
        "stable_dimensions",
    )
    for key in required:
        if key not in shape:
            issues.append(ArtifactIssue(result_path, f"video_shape missing {key}"))

    width = _optional_int(shape.get("active_width"))
    height = _optional_int(shape.get("active_height"))
    total_min = _optional_int(shape.get("total_width_min"))
    total_max = _optional_int(shape.get("total_width_max"))
    if width is None or width <= 0:
        issues.append(ArtifactIssue(result_path, "video_shape.active_width must be positive"))
    if height is None or height <= 0:
        issues.append(ArtifactIssue(result_path, "video_shape.active_height must be positive"))
    if total_min is not None and total_max is not None and (total_min <= 0 or total_max < total_min):
        issues.append(ArtifactIssue(result_path, "video_shape total width min/max is invalid"))
    if not isinstance(shape.get("stable_dimensions"), bool):
        issues.append(ArtifactIssue(result_path, "video_shape.stable_dimensions must be boolean"))
    if "protocol_valid" in shape and not isinstance(shape.get("protocol_valid"), bool):
        issues.append(ArtifactIssue(result_path, "video_shape.protocol_valid must be boolean"))

    video = result.get("video") if isinstance(result.get("video"), dict) else {}
    video_width = _optional_int(video.get("active_width"))
    video_height = _optional_int(video.get("active_height"))
    if video_width is not None and width is not None and width != video_width:
        issues.append(ArtifactIssue(result_path, f"video_shape.active_width {width} does not match result video width {video_width}"))
    if video_height is not None and height is not None and height != video_height:
        issues.append(ArtifactIssue(result_path, f"video_shape.active_height {height} does not match result video height {video_height}"))

    shape_path = artifact_root / "video_shape.json"
    shape_doc = _load_json_object(shape_path, issues, "video_shape.json")
    if shape_doc is None:
        return
    if shape_doc.get("schema") != "apfsim.video_shape.v1":
        issues.append(ArtifactIssue(shape_path, "schema must be apfsim.video_shape.v1"))
    file_shape = shape_doc.get("video_shape")
    if not isinstance(file_shape, dict):
        issues.append(ArtifactIssue(shape_path, "missing video_shape object"))
        return
    file_width = _optional_int(file_shape.get("active_width"))
    file_height = _optional_int(file_shape.get("active_height"))
    if width is not None and file_width != width:
        issues.append(ArtifactIssue(shape_path, "video_shape.active_width does not match result.json"))
    if height is not None and file_height != height:
        issues.append(ArtifactIssue(shape_path, "video_shape.active_height does not match result.json"))


def _validate_lifecycle_artifact(artifact_root: Path, result: dict[str, Any], issues: list[ArtifactIssue]) -> None:
    result_path = artifact_root / "result.json"
    lifecycle = result.get("lifecycle")
    if not isinstance(lifecycle, dict):
        issues.append(ArtifactIssue(result_path, "missing lifecycle object"))
        return
    cycles = lifecycle.get("cycles")
    events = lifecycle.get("events")
    durations = lifecycle.get("durations")
    counters = lifecycle.get("counters")
    if not isinstance(cycles, dict):
        issues.append(ArtifactIssue(result_path, "lifecycle.cycles must be an object"))
        return
    if not isinstance(events, list):
        issues.append(ArtifactIssue(result_path, "lifecycle.events must be a list"))
    if not isinstance(durations, dict):
        issues.append(ArtifactIssue(result_path, "lifecycle.durations must be an object"))
    if not isinstance(counters, dict):
        issues.append(ArtifactIssue(result_path, "lifecycle.counters must be an object"))

    previous_name = ""
    previous_cycle = 0
    for name, _field in LIFECYCLE_PHASES:
        cycle = _optional_int(cycles.get(name))
        if cycle is None:
            issues.append(ArtifactIssue(result_path, f"lifecycle.cycles.{name} must be an integer"))
            continue
        if cycle < 0:
            issues.append(ArtifactIssue(result_path, f"lifecycle.cycles.{name} must be non-negative"))
        if cycle > 0 and previous_cycle > 0 and cycle < previous_cycle:
            issues.append(ArtifactIssue(result_path, f"lifecycle phase {name} occurs before {previous_name}"))
        if cycle > 0:
            previous_name = name
            previous_cycle = cycle

    for key in ("boot_to_running_cycles", "reset_hold_cycles", "reset_exit_to_running_cycles", "data_load_cycles"):
        if isinstance(durations, dict):
            value = _optional_int(durations.get(key))
            if value is None or value < 0:
                issues.append(ArtifactIssue(result_path, f"lifecycle.durations.{key} must be a non-negative integer"))
    for key in ("frames_completed", "frames_started", "audio_samples", "loaded_slots"):
        if isinstance(counters, dict):
            value = _optional_int(counters.get(key))
            if value is None or value < 0:
                issues.append(ArtifactIssue(result_path, f"lifecycle.counters.{key} must be a non-negative integer"))

    lifecycle_path = artifact_root / "lifecycle.json"
    lifecycle_doc = _load_json_object(lifecycle_path, issues, "lifecycle.json")
    if lifecycle_doc is None:
        return
    if lifecycle_doc.get("schema") != LIFECYCLE_SCHEMA:
        issues.append(ArtifactIssue(lifecycle_path, f"schema must be {LIFECYCLE_SCHEMA}"))
    file_lifecycle = lifecycle_doc.get("lifecycle")
    if not isinstance(file_lifecycle, dict):
        issues.append(ArtifactIssue(lifecycle_path, "missing lifecycle object"))
        return
    if file_lifecycle.get("cycles") != lifecycle.get("cycles"):
        issues.append(ArtifactIssue(lifecycle_path, "lifecycle.cycles does not match result.json"))
    if file_lifecycle.get("durations") != lifecycle.get("durations"):
        issues.append(ArtifactIssue(lifecycle_path, "lifecycle.durations does not match result.json"))


def _validate_video_metadata(path: Path, result: dict[str, Any], issues: list[ArtifactIssue]) -> None:
    if not path.exists():
        return
    metadata = _load_json_object(path, issues, "video metadata")
    if metadata is None:
        return

    dimensions = _extract_video_dimensions(metadata)
    for width, height in dimensions:
        if width <= 0 or height <= 0:
            issues.append(ArtifactIssue(path, f"video dimensions must be positive, got {width}x{height}"))

    if len(dimensions) == 1 and isinstance(result.get("video"), dict):
        result_video = result["video"]
        active_width = _optional_int(result_video.get("active_width"))
        active_height = _optional_int(result_video.get("active_height"))
        width, height = dimensions[0]
        if active_width is not None and active_width != width:
            issues.append(ArtifactIssue(path, f"metadata width {width} does not match result video width {active_width}"))
        if active_height is not None and active_height != height:
            issues.append(ArtifactIssue(path, f"metadata height {height} does not match result video height {active_height}"))


def _extract_video_dimensions(value: Any) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []
    if isinstance(value, dict):
        width = _optional_int(value.get("expected_width", value.get("width")))
        height = _optional_int(value.get("expected_height", value.get("height")))
        if width is not None and height is not None:
            found.append((width, height))
        for nested in value.values():
            found.extend(_extract_video_dimensions(nested))
    elif isinstance(value, list):
        for item in value:
            found.extend(_extract_video_dimensions(item))
    return _dedupe_dimensions(found)


def _dedupe_dimensions(values: list[tuple[int, int]]) -> list[tuple[int, int]]:
    deduped: list[tuple[int, int]] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def _validate_audio_artifacts(artifact_root: Path, result: dict[str, Any], issues: list[ArtifactIssue]) -> None:
    audio_dir = artifact_root / "audio"
    if not audio_dir.is_dir():
        return

    stats_path = audio_dir / "stats.json"
    stats: dict[str, Any] | None = None
    if stats_path.exists():
        stats = _load_json_object(stats_path, issues, "audio stats")
        if stats is not None:
            _validate_audio_stats(stats_path, stats, result, issues)

    wav_path = audio_dir / "out.wav"
    if wav_path.exists():
        _validate_wav(wav_path, stats, issues)


def _validate_bridge_artifacts(artifact_root: Path, result: dict[str, Any], issues: list[ArtifactIssue]) -> None:
    summary_path = artifact_root / "bridge_summary.json"
    if not summary_path.exists():
        return
    summary = _load_json_object(summary_path, issues, "bridge summary")
    if summary is None:
        return

    reads = _optional_int(summary.get("reads"))
    writes = _optional_int(summary.get("writes"))
    if reads is None or reads < 0:
        issues.append(ArtifactIssue(summary_path, "reads must be a non-negative integer"))
    if writes is None or writes < 0:
        issues.append(ArtifactIssue(summary_path, "writes must be a non-negative integer"))
    if summary.get("endian") not in {"little", "big"}:
        issues.append(ArtifactIssue(summary_path, "endian must be little or big"))
    if not isinstance(summary.get("commands", []), list):
        issues.append(ArtifactIssue(summary_path, "commands must be a list"))

    result_bridge = result.get("bridge") if isinstance(result.get("bridge"), dict) else None
    if result_bridge is not None:
        for key in ("reads", "writes", "host_commands", "target_commands", "slot_table_writes", "data_payload_writes"):
            left = _optional_int(summary.get(key))
            right = _optional_int(result_bridge.get(key))
            if left is not None and right is not None and left != right:
                issues.append(ArtifactIssue(summary_path, f"{key} {left} does not match result bridge {key} {right}"))


def _validate_audio_stats(path: Path, stats: dict[str, Any], result: dict[str, Any], issues: list[ArtifactIssue]) -> None:
    sample_rate = _optional_int(stats.get("sample_rate"))
    channels = _optional_int(stats.get("channels"))
    samples = _optional_int(stats.get("samples"))
    if sample_rate is None or sample_rate <= 0:
        issues.append(ArtifactIssue(path, "sample_rate must be a positive integer"))
    if channels is None or channels <= 0:
        issues.append(ArtifactIssue(path, "channels must be a positive integer"))
    if samples is None or samples < 0:
        issues.append(ArtifactIssue(path, "samples must be a non-negative integer"))

    for suffix in ("l", "r"):
        min_value = _optional_number(stats.get(f"min_{suffix}"))
        max_value = _optional_number(stats.get(f"max_{suffix}"))
        peak = _optional_number(stats.get(f"peak_to_peak_{suffix}"))
        if min_value is not None and max_value is not None and min_value > max_value:
            issues.append(ArtifactIssue(path, f"min_{suffix} must be <= max_{suffix}"))
        if peak is not None and peak < 0:
            issues.append(ArtifactIssue(path, f"peak_to_peak_{suffix} must be non-negative"))
        if min_value is not None and max_value is not None and peak is not None and abs((max_value - min_value) - peak) > 1:
            issues.append(ArtifactIssue(path, f"peak_to_peak_{suffix} does not match min/max range"))

    clipped = _optional_int(stats.get("clipped_samples"))
    if clipped is not None and clipped < 0:
        issues.append(ArtifactIssue(path, "clipped_samples must be non-negative"))
    if clipped is not None and samples is not None and channels is not None and clipped > samples * channels:
        issues.append(ArtifactIssue(path, "clipped_samples exceeds total channel samples"))

    result_audio = result.get("audio") if isinstance(result.get("audio"), dict) else None
    if result_audio is not None:
        result_samples = _optional_int(result_audio.get("samples"))
        result_rate = _optional_int(result_audio.get("sample_rate"))
        if samples is not None and result_samples is not None and samples != result_samples:
            issues.append(ArtifactIssue(path, f"samples {samples} does not match result audio samples {result_samples}"))
        if sample_rate is not None and result_rate is not None and sample_rate != result_rate:
            issues.append(ArtifactIssue(path, f"sample_rate {sample_rate} does not match result audio sample_rate {result_rate}"))


def _validate_wav(path: Path, stats: dict[str, Any] | None, issues: list[ArtifactIssue]) -> None:
    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_rate = wav.getframerate()
            sample_width = wav.getsampwidth()
            frames = wav.getnframes()
    except (OSError, EOFError, wave.Error) as exc:
        issues.append(ArtifactIssue(path, f"invalid WAV file: {exc}"))
        return

    if channels <= 0:
        issues.append(ArtifactIssue(path, "WAV channel count must be positive"))
    if sample_rate <= 0:
        issues.append(ArtifactIssue(path, "WAV sample rate must be positive"))
    if sample_width <= 0:
        issues.append(ArtifactIssue(path, "WAV sample width must be positive"))
    if frames < 0:
        issues.append(ArtifactIssue(path, "WAV frame count must be non-negative"))

    if stats is None:
        return
    stats_channels = _optional_int(stats.get("channels"))
    stats_rate = _optional_int(stats.get("sample_rate"))
    stats_samples = _optional_int(stats.get("samples"))
    if stats_channels is not None and channels != stats_channels:
        issues.append(ArtifactIssue(path, f"WAV channels {channels} do not match stats channels {stats_channels}"))
    if stats_rate is not None and sample_rate != stats_rate:
        issues.append(ArtifactIssue(path, f"WAV sample_rate {sample_rate} does not match stats sample_rate {stats_rate}"))
    if stats_samples is not None and frames != stats_samples:
        issues.append(ArtifactIssue(path, f"WAV frames {frames} do not match stats samples {stats_samples}"))


def _validate_save_artifacts(artifact_root: Path, result: dict[str, Any], issues: list[ArtifactIssue]) -> None:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    slots = data.get("slots", []) if isinstance(data.get("slots", []), list) else []
    nonvolatile_slots = [slot for slot in slots if isinstance(slot, dict) and bool(slot.get("nonvolatile")) and _number(slot.get("loaded_size"), 0) > 0]
    if not nonvolatile_slots:
        return

    save = result.get("save") if isinstance(result.get("save"), dict) else {}
    reports = save.get("reports", []) if isinstance(save.get("reports", []), list) else []
    reports_by_id = {str(report.get("id")): report for report in reports if isinstance(report, dict)}

    for slot in nonvolatile_slots:
        slot_id = str(slot.get("id"))
        loaded_size = int(_number(slot.get("loaded_size"), 0))
        report = reports_by_id.get(slot_id)
        if report is None:
            issues.append(ArtifactIssue(artifact_root / "result.json", f"missing save report for nonvolatile slot {slot_id}"))
            continue
        report_bytes = _optional_int(report.get("bytes"))
        if report_bytes is None or report_bytes <= 0:
            issues.append(ArtifactIssue(artifact_root / "result.json", f"save report for slot {slot_id} must have positive byte count"))
        elif report_bytes != loaded_size:
            issues.append(ArtifactIssue(artifact_root / "result.json", f"save report bytes {report_bytes} do not match loaded_size {loaded_size} for slot {slot_id}"))

        save_path_value = report.get("path")
        save_path = Path(str(save_path_value)) if save_path_value else artifact_root / "saves" / f"slot_{slot_id}.bin"
        if not save_path.is_absolute():
            save_path = artifact_root / save_path
        if not save_path.exists():
            issues.append(ArtifactIssue(save_path, f"missing save output for nonvolatile slot {slot_id}"))
            continue
        size = save_path.stat().st_size
        if report_bytes is not None and size != report_bytes:
            issues.append(ArtifactIssue(save_path, f"save file size {size} does not match report bytes {report_bytes}"))


def _load_json_object(path: Path, issues: list[ArtifactIssue], label: str) -> dict[str, Any] | None:
    try:
        with path.open() as fh:
            data = json.load(fh)
    except FileNotFoundError:
        issues.append(ArtifactIssue(path, f"missing {label}"))
        return None
    except json.JSONDecodeError as exc:
        issues.append(ArtifactIssue(path, f"invalid {label}: {exc}"))
        return None
    if not isinstance(data, dict):
        issues.append(ArtifactIssue(path, f"{label} must be a JSON object"))
        return None
    return data


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return None
    return None


def _optional_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _number(value: Any, default: float) -> float:
    parsed = _optional_number(value)
    return default if parsed is None else parsed
