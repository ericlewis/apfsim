#!/usr/bin/env python3
"""APF run artifact diagnosis and bring-up reporting."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DIAGNOSTICS_SCHEMA = "apfsim.diagnostics.v1"
DIAGNOSTIC_SCHEMA = "apfsim.diagnostic.v1"

KNOWN_CODES = (
    "PORT_MISSING",
    "PORT_WIDTH_MISMATCH",
    "CLOCK_NOT_TOGGLING",
    "RESET_NEVER_EXITED",
    "READY_TO_RUN_MISSING",
    "BOOT_TIMEOUT",
    "HOST_COMMAND_UNACKED",
    "TARGET_COMMAND_STUCK_BUSY",
    "BRIDGE_ENDIAN_MISMATCH",
    "BRIDGE_READBACK_MISMATCH",
    "DATA_SLOT_TABLE_MISSING",
    "DATA_SLOT_ADDRESS_INVALID",
    "DATA_SLOT_LOAD_SHORT",
    "DATA_SLOT_READBACK_UNAVAILABLE",
    "DATA_SLOT_READBACK_MISMATCH",
    "INTERACT_WRITE_MISSING",
    "VIDEO_NO_CLOCK",
    "VIDEO_NO_DE",
    "VIDEO_STATIC_FRAME",
    "VIDEO_WIDTH_MISMATCH",
    "VIDEO_HEIGHT_MISMATCH",
    "VIDEO_PROTOCOL_ERROR",
    "VIDEO_EXTRA_ACTIVE_PIXEL",
    "VIDEO_FRAME_COUNT_MISMATCH",
    "VIDEO_UNSTABLE_DIMENSIONS",
    "AUDIO_NO_MCLK",
    "AUDIO_NO_LRCK",
    "AUDIO_NO_DAC_ACTIVITY",
    "AUDIO_RATIO_MISMATCH",
    "INPUT_NOT_OBSERVED",
    "SAVE_SLOT_NOT_UNLOADED",
    "SAVE_ROUNDTRIP_MISMATCH",
    "SHIM_REQUIRED",
    "VHDL_ENTITY_STUBBED",
    "MEMORY_MODEL_REQUIRED",
    "MEMORY_WIDTH_MISMATCH",
    "MEMORY_BYTE_ENABLE_MISMATCH",
    "MEMORY_UNINITIALIZED_READ",
    "MEMORY_OUT_OF_RANGE",
    "MEMORY_NO_ACTIVITY",
    "MEMORY_STALL_TIMEOUT",
    "SDRAM_INIT_TIMEOUT",
    "SDRAM_REFRESH_MISSING",
    "CRAM_MODEL_REQUIRED",
    "PSRAM_MODEL_REQUIRED",
    "SRAM_MODEL_REQUIRED",
    "SRAM_BUS_CONTENTION",
)


def load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def load_optional_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return load_json_object(path)


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text, 0)
        except ValueError:
            return default
    return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return default


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _severity_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"errors": 0, "warnings": 0, "infos": 0}
    for item in items:
        severity = item.get("severity")
        if severity == "error":
            counts["errors"] += 1
        elif severity == "warning":
            counts["warnings"] += 1
        else:
            counts["infos"] += 1
    return counts


def _diag(
    items: list[dict[str, Any]],
    *,
    code: str,
    phase: str,
    severity: str,
    summary: str,
    observed: dict[str, Any] | None = None,
    expected: dict[str, Any] | None = None,
    evidence: list[dict[str, str]] | None = None,
    likely_causes: list[str] | None = None,
    repairs: list[dict[str, Any]] | None = None,
) -> None:
    if code not in KNOWN_CODES:
        raise ValueError(f"Unknown diagnostic code: {code}")
    item: dict[str, Any] = {
        "schema": DIAGNOSTIC_SCHEMA,
        "code": code,
        "phase": phase,
        "severity": severity,
        "summary": summary,
        "observed": observed or {},
        "expected": expected or {},
        "evidence": evidence or [],
        "likely_causes": likely_causes or [],
        "repairs": repairs or [],
    }
    items.append(item)


def _video_json_dimensions(video_metadata_path: Path | None) -> tuple[int | None, int | None]:
    if video_metadata_path is None or not video_metadata_path.exists():
        return (None, None)
    try:
        data = load_json_object(video_metadata_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return (None, None)
    video = _obj(data.get("video"))
    modes = _list(video.get("scaler_modes"))
    if not modes:
        modes = _list(data.get("scaler_modes"))
    for mode in modes:
        if not isinstance(mode, dict):
            continue
        width = _as_int(mode.get("width"), 0)
        height = _as_int(mode.get("height"), 0)
        if width > 0 and height > 0:
            return (width, height)
    return (None, None)


def _profile_expected_video(profile: dict[str, Any] | None) -> tuple[int | None, int | None]:
    if not profile:
        return (None, None)
    video = _obj(profile.get("video"))
    width = _as_int(video.get("expected_width"), 0)
    height = _as_int(video.get("expected_height"), 0)
    return (width or None, height or None)


def _profile_metadata_video(profile: dict[str, Any] | None) -> Path | None:
    if not profile:
        return None
    metadata = _obj(profile.get("metadata_jsons"))
    raw = metadata.get("video")
    if not raw:
        return None
    root_raw = profile.get("root")
    path = Path(str(raw)).expanduser()
    if path.is_absolute():
        return path
    if root_raw:
        return Path(str(root_raw)).expanduser() / path
    return path


def diagnose_artifacts(
    artifact_root: Path,
    *,
    profile: dict[str, Any] | None = None,
    video_metadata_path: Path | None = None,
) -> dict[str, Any]:
    """Classify APF contract failures from a run artifact directory."""
    artifact_root = artifact_root.resolve()
    result_path = artifact_root / "result.json"
    result = load_optional_json_object(result_path)
    video_shape_path = artifact_root / "video_shape.json"
    video_shape_doc = load_optional_json_object(video_shape_path)
    video_shape = _obj(video_shape_doc.get("video_shape")) if "video_shape" in video_shape_doc else video_shape_doc
    items: list[dict[str, Any]] = []

    if not result:
        _diag(
            items,
            code="BOOT_TIMEOUT",
            phase="preflight",
            severity="error",
            summary="Run did not produce result.json.",
            observed={"artifact_dir": str(artifact_root)},
            expected={"artifact": "result.json"},
            likely_causes=[
                "Verilated executable did not start",
                "simulation terminated before artifact emission",
                "profile artifact path is incorrect",
            ],
            repairs=[
                {
                    "kind": "profile_patch",
                    "confidence": 0.45,
                    "description": "Check the profile executable and artifact output directory.",
                }
            ],
        )
        return _diagnostic_doc(artifact_root, result, items)

    failed_phase = str(result.get("failed_phase") or "")
    message = str(result.get("message") or "")
    boot = _obj(result.get("boot"))
    bridge = _obj(result.get("bridge"))
    data = _obj(result.get("data"))
    video = _obj(result.get("video"))
    audio = _obj(result.get("audio"))
    interact = _obj(result.get("interact"))
    input_doc = _obj(result.get("input"))
    save = _obj(result.get("save"))

    if failed_phase == "boot" or (not _as_bool(result.get("ok"), False) and not failed_phase):
        _diag(
            items,
            code="BOOT_TIMEOUT",
            phase="boot",
            severity="error",
            summary=message or "Simulation did not complete the requested APF run.",
            observed={"failed_phase": failed_phase, "message": message},
            expected={"status": "running"},
            evidence=[{"artifact": "result.json", "json_pointer": "/failed_phase"}],
            likely_causes=[
                "host command sequence did not complete",
                "core never reached APF running state",
                "timeout is too short for this core",
            ],
            repairs=[
                {
                    "kind": "profile_patch",
                    "confidence": 0.52,
                    "description": "Increase timeout or inspect bridge.log for the last unacknowledged APF command.",
                }
            ],
        )

    if _as_int(boot.get("reset_exit_cycle"), 0) <= 0 and not _as_bool(boot.get("ok"), False):
        _diag(
            items,
            code="RESET_NEVER_EXITED",
            phase="reset",
            severity="error",
            summary="APF reset exit was not observed before the run failed.",
            observed={"reset_exit_cycle": _as_int(boot.get("reset_exit_cycle"), 0)},
            expected={"reset_exit_cycle": "> 0"},
            evidence=[{"artifact": "result.json", "json_pointer": "/boot/reset_exit_cycle"}],
            likely_causes=[
                "target never reported ready-to-run",
                "host command reset-exit was not acknowledged",
                "reset polarity or wrapper reset wiring is wrong",
            ],
            repairs=[
                {
                    "kind": "wrapper_patch",
                    "confidence": 0.56,
                    "description": "Verify reset polarity and APF reset-enter/reset-exit wiring in the generated wrapper.",
                }
            ],
        )

    if _as_int(boot.get("target_ready_cycle"), 0) <= 0 and failed_phase in {"boot", "reset", ""}:
        _diag(
            items,
            code="READY_TO_RUN_MISSING",
            phase="boot",
            severity="error",
            summary="Target Ready-to-Run command was not observed.",
            observed={"target_ready_cycle": _as_int(boot.get("target_ready_cycle"), 0)},
            expected={"target_command": "0x0140"},
            evidence=[{"artifact": "result.json", "json_pointer": "/boot/target_ready_cycle"}],
            likely_causes=[
                "APF command engine is not instantiated or not clocked",
                "core is stuck in setup after data loading",
                "host did not complete a required data-slot or RTC command",
            ],
            repairs=[
                {
                    "kind": "wrapper_patch",
                    "confidence": 0.5,
                    "description": "Check APF command bus wiring and target command/status register visibility.",
                }
            ],
        )

    if _as_int(bridge.get("host_timeouts"), 0) > 0 or "timed out" in message.lower():
        _diag(
            items,
            code="HOST_COMMAND_UNACKED",
            phase="bridge",
            severity="error",
            summary="At least one host command did not complete with an OK response.",
            observed={
                "host_timeouts": _as_int(bridge.get("host_timeouts"), 0),
                "last_host_command": boot.get("last_host_command"),
                "last_host_status_word": boot.get("last_host_status_word"),
            },
            expected={"host_command_status": "OK"},
            evidence=[{"artifact": "bridge.log", "json_pointer": ""}],
            likely_causes=[
                "bridge read latency is wrong for this core",
                "command/status register map is not APF-compatible",
                "core clock or reset prevented command processing",
            ],
            repairs=[
                {
                    "kind": "profile_patch",
                    "confidence": 0.62,
                    "description": "Adjust bridge read/write latency and inspect the command/status words in bridge.log.",
                }
            ],
        )

    _diagnose_assert_failure(items, failed_phase, message, video, audio, input_doc, save)

    if bridge and not _as_bool(bridge.get("slot_table_ok"), True):
        _diag(
            items,
            code="DATA_SLOT_TABLE_MISSING",
            phase="data",
            severity="error",
            summary="Dataslot ID/size table verification failed.",
            observed={
                "slot_table_writes": _as_int(bridge.get("slot_table_writes"), 0),
                "slot_table_ok": bridge.get("slot_table_ok"),
            },
            expected={"slot_table_ok": True},
            evidence=[{"artifact": "result.json", "json_pointer": "/bridge/slot_table_ok"}],
            likely_causes=[
                "bridge writes to 0xF8002000 are not reaching the APF framework",
                "slot table address is remapped or hidden behind a custom bridge adapter",
                "bridge endian configuration is wrong",
            ],
            repairs=[
                {
                    "kind": "wrapper_patch",
                    "confidence": 0.58,
                    "description": "Verify APF framework command RAM and dataslot table address mapping.",
                }
            ],
        )

    for index, slot in enumerate(_list(data.get("slots"))):
        if not isinstance(slot, dict):
            continue
        loaded_words = _as_int(slot.get("loaded_words"), 0)
        observed_words = _as_int(slot.get("observed_write_words"), loaded_words)
        if loaded_words > 0 and observed_words < loaded_words:
            _diag(
                items,
                code="DATA_SLOT_LOAD_SHORT",
                phase="data",
                severity="error",
                summary=f"Dataslot {slot.get('id')} received fewer bridge writes than expected.",
                observed={"slot": slot.get("id"), "observed_write_words": observed_words},
                expected={"loaded_words": loaded_words},
                evidence=[{"artifact": "result.json", "json_pointer": f"/data/slots/{index}"}],
                likely_causes=[
                    "bridge write strobe timing is too short",
                    "slot load address is wrong",
                    "core rejected the data-slot request-write command",
                ],
                repairs=[
                    {
                        "kind": "profile_patch",
                        "confidence": 0.68,
                        "description": "Increase bridge write idle cycles and verify the data.json load address.",
                    }
                ],
            )
        if _as_int(slot.get("observed_write_address_errors"), 0) > 0:
            _diag(
                items,
                code="DATA_SLOT_ADDRESS_INVALID",
                phase="data",
                severity="error",
                summary=f"Dataslot {slot.get('id')} saw bridge writes outside its expected address range.",
                observed={
                    "slot": slot.get("id"),
                    "address_errors": _as_int(slot.get("observed_write_address_errors"), 0),
                },
                expected={"address": slot.get("address")},
                evidence=[{"artifact": "result.json", "json_pointer": f"/data/slots/{index}"}],
                likely_causes=[
                    "data.json address does not match the wrapper memory map",
                    "bridge address bits are truncated or remapped",
                    "generated profile selected the wrong slot address",
                ],
                repairs=[
                    {
                        "kind": "metadata_patch",
                        "confidence": 0.66,
                        "description": "Patch data.json or the profile slot address to match the APF bridge-visible loader window.",
                    }
                ],
            )
        if _as_bool(slot.get("verify_readback"), False) and loaded_words > 0 and not _as_bool(slot.get("readback_attempted"), False):
            _diag(
                items,
                code="DATA_SLOT_READBACK_UNAVAILABLE",
                phase="data",
                severity="error",
                summary=f"Dataslot {slot.get('id')} required bridge readback verification, but no readback was attempted.",
                observed={"slot": slot.get("id"), "readback_attempted": slot.get("readback_attempted")},
                expected={"readback_attempted": True},
                evidence=[{"artifact": "result.json", "json_pointer": f"/data/slots/{index}"}],
                likely_causes=[
                    "scenario requested readback after the slot was skipped or defer-loaded",
                    "profile generated a readback requirement for a write-only load window",
                    "data slot metadata and scenario slot IDs do not refer to the same slot",
                ],
                repairs=[
                    {
                        "kind": "scenario_patch",
                        "confidence": 0.57,
                        "description": "Enable readback only for boot-loaded slots with a bridge-readable memory window, or make the wrapper expose that window.",
                    }
                ],
            )
        if _as_bool(slot.get("readback_attempted"), False) and not _as_bool(slot.get("readback_matches"), True):
            _diag(
                items,
                code="DATA_SLOT_READBACK_MISMATCH",
                phase="data",
                severity="error",
                summary=f"Dataslot {slot.get('id')} bridge readback did not match the loaded file.",
                observed={
                    "slot": slot.get("id"),
                    "readback_bytes": _as_int(slot.get("readback_bytes"), 0),
                    "readback_crc32": slot.get("readback_crc32"),
                    "readback_checksum": slot.get("readback_checksum"),
                    "first_mismatch_offset": slot.get("readback_first_mismatch_offset"),
                    "observed_byte": slot.get("readback_observed_byte"),
                },
                expected={
                    "loaded_size": _as_int(slot.get("loaded_size"), 0),
                    "loaded_crc32": slot.get("loaded_crc32"),
                    "loaded_checksum": slot.get("loaded_checksum"),
                    "expected_byte": slot.get("readback_expected_byte"),
                },
                evidence=[{"artifact": "result.json", "json_pointer": f"/data/slots/{index}"}],
                likely_causes=[
                    "external RAM write path corrupted ROM bytes",
                    "bridge byte lane or endian mapping is wrong",
                    "load address does not match the core's external RAM address decode",
                    "write strobe or idle timing is too short for the memory controller",
                    "bridge readback is mapped to a different memory window than bridge writes",
                ],
                repairs=[
                    {
                        "kind": "wrapper_patch",
                        "confidence": 0.78,
                        "description": "Inspect external RAM write byte enables, address bits, endian packing, and bridge readback mapping for this slot.",
                    },
                    {
                        "kind": "profile_patch",
                        "confidence": 0.62,
                        "description": "Increase bridge write idle/strobe cycles or select an external memory model with realistic write acceptance timing.",
                    },
                ],
            )

    persistent_writes = _as_int(interact.get("persistent_writes"), 0)
    if failed_phase == "interact" or ("interact" in message.lower() and persistent_writes <= 0):
        _diag(
            items,
            code="INTERACT_WRITE_MISSING",
            phase="interact",
            severity="error",
            summary="Expected persistent interact writes were not observed.",
            observed={"persistent_writes": persistent_writes, "message": message},
            expected={"persistent_writes": "> 0 when interact.json declares persistent variables"},
            evidence=[{"artifact": "result.json", "json_pointer": "/interact"}],
            likely_causes=[
                "interact.json was not loaded by the profile",
                "writeonly/mask handling did not produce a bridge write",
                "interact address is not bridge-visible",
            ],
            repairs=[
                {
                    "kind": "metadata_patch",
                    "confidence": 0.55,
                    "description": "Verify interact.json path, persistent flags, masks, and target bridge addresses.",
                }
            ],
        )

    _diagnose_video(items, result, video, video_shape, profile, video_metadata_path)
    _diagnose_audio(items, audio, failed_phase, message)
    _diagnose_input(items, input_doc)
    _diagnose_saves(items, data, save, failed_phase, message, _as_bool(result.get("ok"), False))

    _diagnose_profile_risks(items, profile)
    if not _as_bool(result.get("ok"), False) and not any(item.get("severity") == "error" for item in items):
        _diag(
            items,
            code="BOOT_TIMEOUT",
            phase=failed_phase or "runtime",
            severity="error",
            summary=message or "Run failed before a more specific APF diagnostic matched.",
            observed={"failed_phase": failed_phase, "message": message},
            expected={"result_ok": True},
            evidence=[{"artifact": "result.json", "json_pointer": "/ok"}],
            likely_causes=[
                "scenario expectation failed without a specific classifier",
                "simulation timed out before contract checks completed",
                "profile or wrapper needs a more specific diagnostic rule",
            ],
            repairs=[
                {
                    "kind": "diagnostic_followup",
                    "confidence": 0.35,
                    "description": "Inspect result.json and bridge.log, then add a narrower diagnostic rule for this failure mode.",
                }
            ],
        )
    return _diagnostic_doc(artifact_root, result, items)


def _diagnose_video(
    items: list[dict[str, Any]],
    result: dict[str, Any],
    video: dict[str, Any],
    video_shape: dict[str, Any],
    profile: dict[str, Any] | None,
    video_metadata_path: Path | None,
) -> None:
    frames = _as_int(video.get("frames_completed"), _as_int(video_shape.get("frames"), 0))
    width = _as_int(video_shape.get("active_width"), _as_int(video.get("active_width"), 0))
    height = _as_int(video_shape.get("active_height"), _as_int(video.get("active_height"), 0))
    if frames <= 0:
        _diag(
            items,
            code="VIDEO_NO_DE",
            phase="video",
            severity="error",
            summary="No complete APF video frames were captured.",
            observed={"frames_completed": frames, "active_width": width, "active_height": height},
            expected={"frames_completed": "> 0"},
            evidence=[{"artifact": "result.json", "json_pointer": "/video/frames_completed"}],
            likely_causes=[
                "video_rgb_clock is not toggling",
                "video_de is never asserted",
                "core is still held in reset or setup",
            ],
            repairs=[
                {
                    "kind": "wrapper_patch",
                    "confidence": 0.58,
                    "description": "Verify video clock mapping, DE polarity, and reset release wiring.",
                }
            ],
        )
    elif width <= 0 or height <= 0:
        _diag(
            items,
            code="VIDEO_NO_DE",
            phase="video",
            severity="error",
            summary="Frames were seen, but no active video area was measured.",
            observed={"frames_completed": frames, "active_width": width, "active_height": height},
            expected={"active_width": "> 0", "active_height": "> 0"},
            evidence=[{"artifact": "video_shape.json", "json_pointer": "/video_shape/active_width"}],
            likely_causes=[
                "DE polarity is inverted",
                "active-video gate is stuck inactive",
                "wrapper is exporting blanking instead of data-enable",
            ],
            repairs=[
                {
                    "kind": "wrapper_patch",
                    "confidence": 0.72,
                    "description": "Invert or remap video_de from the upstream blanking signal.",
                }
            ],
        )

    expected_width, expected_height = _video_json_dimensions(video_metadata_path)
    if expected_width is None or expected_height is None:
        profile_width, profile_height = _profile_expected_video(profile)
        expected_width = expected_width or profile_width
        expected_height = expected_height or profile_height

    if width > 0 and expected_width and width != expected_width:
        code = "VIDEO_EXTRA_ACTIVE_PIXEL" if width == expected_width + 1 else "VIDEO_WIDTH_MISMATCH"
        likely_causes = [
            "video_de asserted one cycle too early or too late",
            "upstream HBLK polarity or edge convention is mismatched",
            "generated wrapper does not trim border pixels",
        ]
        repairs = [
            {
                "kind": "wrapper_patch",
                "confidence": 0.82 if code == "VIDEO_EXTRA_ACTIVE_PIXEL" else 0.65,
                "description": "Gate or delay video_de so the APF active width matches the scaler metadata before patching video.json.",
            },
            {
                "kind": "metadata_patch",
                "confidence": 0.44,
                "description": "Patch video.json only if the simulated active area is confirmed to be the intended visible area.",
            },
        ]
        _diag(
            items,
            code=code,
            phase="video",
            severity="error",
            summary="Simulated active width does not match video metadata.",
            observed={"active_width": width, "active_height": height},
            expected={"active_width": expected_width, "active_height": expected_height},
            evidence=[
                {"artifact": "video_shape.json", "json_pointer": "/video_shape/active_width"},
                {"artifact": "result.json", "json_pointer": "/video_shape/active_width"},
            ],
            likely_causes=likely_causes,
            repairs=repairs,
        )

    if height > 0 and expected_height and height != expected_height:
        _diag(
            items,
            code="VIDEO_HEIGHT_MISMATCH",
            phase="video",
            severity="error",
            summary="Simulated active height does not match video metadata.",
            observed={"active_width": width, "active_height": height},
            expected={"active_width": expected_width, "active_height": expected_height},
            evidence=[
                {"artifact": "video_shape.json", "json_pointer": "/video_shape/active_height"},
                {"artifact": "result.json", "json_pointer": "/video_shape/active_height"},
            ],
            likely_causes=[
                "VBLK polarity or line counter trim is wrong",
                "wrapper exposes border or overscan lines",
                "video.json scaler height is stale",
            ],
            repairs=[
                {
                    "kind": "wrapper_patch",
                    "confidence": 0.7,
                    "description": "Gate video_de vertically so the active line count matches the intended APF scaler mode.",
                }
            ],
        )

    protocol_errors = (
        _as_int(video_shape.get("de_errors"), _as_int(video.get("de_errors"), 0))
        + _as_int(video_shape.get("pulse_width_errors"), _as_int(video.get("pulse_width_errors"), 0))
        + _as_int(video_shape.get("skip_errors"), _as_int(video.get("skip_errors"), 0))
        + _as_int(video_shape.get("errors"), 0)
    )
    if protocol_errors > 0 or not _as_bool(video_shape.get("protocol_valid"), True):
        _diag(
            items,
            code="VIDEO_PROTOCOL_ERROR",
            phase="video",
            severity="error",
            summary="APF video sync/DE protocol validation failed.",
            observed={
                "de_errors": _as_int(video_shape.get("de_errors"), _as_int(video.get("de_errors"), 0)),
                "pulse_width_errors": _as_int(video_shape.get("pulse_width_errors"), _as_int(video.get("pulse_width_errors"), 0)),
                "skip_errors": _as_int(video_shape.get("skip_errors"), _as_int(video.get("skip_errors"), 0)),
                "protocol_valid": video_shape.get("protocol_valid"),
            },
            expected={"protocol_valid": True},
            evidence=[{"artifact": "video_shape.json", "json_pointer": "/video_shape"}],
            likely_causes=[
                "HS/VS pulses are not one pixel-clock cycle wide",
                "DE is asserted more than once per line",
                "SKIP is asserted outside active video",
                "RGB metadata is present without APF-safe blanking behavior",
            ],
            repairs=[
                {
                    "kind": "wrapper_patch",
                    "confidence": 0.74,
                    "description": "Add APF video timing adaptation for HS/VS pulse width, DE gaps, and blank RGB policy.",
                }
            ],
        )

    if video_shape and not _as_bool(video_shape.get("stable_dimensions"), True):
        _diag(
            items,
            code="VIDEO_UNSTABLE_DIMENSIONS",
            phase="video",
            severity="error",
            summary="Measured active dimensions changed across captured frames.",
            observed={
                "active_width_min": video_shape.get("active_width_min"),
                "active_width_max": video_shape.get("active_width_max"),
                "active_height_min": video_shape.get("active_height_min"),
                "active_height_max": video_shape.get("active_height_max"),
            },
            expected={"stable_dimensions": True},
            evidence=[{"artifact": "video_shape.json", "json_pointer": "/video_shape/stable_dimensions"}],
            likely_causes=[
                "startup frames are included in the measurement",
                "core switches video modes without metadata update",
                "DE/HS/VS timing is unstable after reset",
            ],
            repairs=[
                {
                    "kind": "profile_patch",
                    "confidence": 0.61,
                    "description": "Increase startup_frame_ignore or model the core's runtime scaler-slot switch explicitly.",
                }
            ],
        )

    unique_colors = _as_int(video.get("unique_colors"), 0)
    changed_frames = _as_int(video.get("changed_frames"), 0)
    nonzero_pixels = _as_int(video.get("nonzero_pixels"), 0)
    if frames >= 2 and width > 0 and height > 0 and (unique_colors <= 1 or nonzero_pixels <= 0):
        _diag(
            items,
            code="VIDEO_STATIC_FRAME",
            phase="video",
            severity="warning",
            summary="Captured video appears blank or nearly static.",
            observed={
                "frames_completed": frames,
                "unique_colors": unique_colors,
                "changed_frames": changed_frames,
                "nonzero_pixels": nonzero_pixels,
            },
            expected={"visible_content": "nonblank or intentionally waived"},
            evidence=[{"artifact": "result.json", "json_pointer": "/video"}],
            likely_causes=[
                "ROM did not load into the gameplay core",
                "CPU is still held in reset",
                "palette/video RAM path is stubbed or not initialized",
            ],
            repairs=[
                {
                    "kind": "diagnostic_followup",
                    "confidence": 0.48,
                    "description": "Correlate with ROM/data-slot diagnostics and inspect the first dumped frame.",
                }
            ],
        )


def _diagnose_assert_failure(
    items: list[dict[str, Any]],
    failed_phase: str,
    message: str,
    video: dict[str, Any],
    audio: dict[str, Any],
    input_doc: dict[str, Any],
    save: dict[str, Any],
) -> None:
    if failed_phase != "assert":
        return
    lower = message.lower()
    if "video" in lower and "frame" in lower:
        _diag(
            items,
            code="VIDEO_FRAME_COUNT_MISMATCH",
            phase="video",
            severity="error",
            summary=message or "Scenario video frame-count expectation failed.",
            observed={"frames_completed": _as_int(video.get("frames_completed"), 0)},
            expected={"frames_completed": "scenario expectation"},
            evidence=[{"artifact": "result.json", "json_pointer": "/video/frames_completed"}],
            likely_causes=[
                "timeout or --frames value is shorter than the scenario expectation",
                "video frame cadence is slower than expected",
                "core did not start producing video soon enough after reset exit",
            ],
            repairs=[
                {
                    "kind": "scenario_patch",
                    "confidence": 0.64,
                    "description": "Increase run frames/timeout or adjust the scenario min_frames expectation after confirming video cadence.",
                }
            ],
        )
    elif "audio" in lower:
        _diag(
            items,
            code="AUDIO_NO_DAC_ACTIVITY",
            phase="audio",
            severity="error",
            summary=message or "Scenario audio expectation failed.",
            observed={"samples": _as_int(audio.get("samples"), 0)},
            expected={"audio": "scenario expectation"},
            evidence=[{"artifact": "result.json", "json_pointer": "/audio"}],
            likely_causes=["audio pins are not mapped", "I2S decoder saw silence or no LRCK", "scenario expects audio from a silent core"],
            repairs=[{"kind": "waiver_or_wrapper_patch", "confidence": 0.55, "description": "Fix audio pin mapping or add an explicit silence waiver."}],
        )
    elif "input" in lower:
        _diag(
            items,
            code="INPUT_NOT_OBSERVED",
            phase="input",
            severity="error",
            summary=message or "Scenario input expectation failed.",
            observed={"scripted_events": _as_int(input_doc.get("scripted_events"), 0), "delivered_events": _as_int(input_doc.get("delivered_events"), 0)},
            expected={"input": "scenario expectation"},
            evidence=[{"artifact": "result.json", "json_pointer": "/input"}],
            likely_causes=["input script ended before delivery", "controller mapping is wrong", "core ignored controller type bits"],
            repairs=[{"kind": "wrapper_patch", "confidence": 0.58, "description": "Verify cont*_key mappings and scenario input frame timing."}],
        )
    elif "save" in lower:
        _diag(
            items,
            code="SAVE_SLOT_NOT_UNLOADED",
            phase="save",
            severity="error",
            summary=message or "Scenario save expectation failed.",
            observed={"save_reports": len(_list(save.get("reports")))},
            expected={"save": "scenario expectation"},
            evidence=[{"artifact": "result.json", "json_pointer": "/save/reports"}],
            likely_causes=["nonvolatile slot was not unloaded", "save readback path is not bridge-visible", "scenario expected a save for a core without nonvolatile slots"],
            repairs=[{"kind": "profile_patch", "confidence": 0.56, "description": "Verify nonvolatile slot metadata and save unload expectations."}],
        )


def _diagnose_audio(
    items: list[dict[str, Any]], audio: dict[str, Any], failed_phase: str, message: str) -> None:
    mclk_edges = _as_int(audio.get("mclk_edges"), 0)
    lrck_edges = _as_int(audio.get("lrck_edges"), 0)
    samples = _as_int(audio.get("samples"), 0)
    peak_l = abs(_as_int(audio.get("min_l"), 0)) + abs(_as_int(audio.get("max_l"), 0))
    peak_r = abs(_as_int(audio.get("min_r"), 0)) + abs(_as_int(audio.get("max_r"), 0))
    if failed_phase == "audio" or "audio" in message.lower():
        severity = "error"
    else:
        severity = "warning"
    if mclk_edges <= 0:
        _diag(
            items,
            code="AUDIO_NO_MCLK",
            phase="audio",
            severity=severity,
            summary="No audio master clock edges were observed.",
            observed={"mclk_edges": mclk_edges},
            expected={"mclk_edges": "> 0"},
            evidence=[{"artifact": "result.json", "json_pointer": "/audio/mclk_edges"}],
            likely_causes=["audio_mclk is unmapped", "audio block is held in reset", "profile selected the wrong audio pins"],
            repairs=[{"kind": "wrapper_patch", "confidence": 0.66, "description": "Map or synthesize APF audio_mclk from the core's I2S clock."}],
        )
    if lrck_edges <= 0:
        _diag(
            items,
            code="AUDIO_NO_LRCK",
            phase="audio",
            severity=severity,
            summary="No audio LRCK edges were observed.",
            observed={"lrck_edges": lrck_edges},
            expected={"lrck_edges": "> 0"},
            evidence=[{"artifact": "result.json", "json_pointer": "/audio/lrck_edges"}],
            likely_causes=["I2S generator is not running", "audio_lrck is unmapped", "sample clock divider is wrong"],
            repairs=[{"kind": "wrapper_patch", "confidence": 0.63, "description": "Verify audio LRCK pin mapping and the I2S divider reset."}],
        )
    if samples <= 0 or (peak_l == 0 and peak_r == 0):
        _diag(
            items,
            code="AUDIO_NO_DAC_ACTIVITY",
            phase="audio",
            severity=severity,
            summary="Audio sample decoder saw no DAC activity.",
            observed={"samples": samples, "peak_l": peak_l, "peak_r": peak_r},
            expected={"samples": "> 0", "activity": "nonzero unless waived"},
            evidence=[{"artifact": "result.json", "json_pointer": "/audio"}],
            likely_causes=["audio_dac is stuck low", "core has intentional silence", "I2S bit alignment or pin mapping is wrong"],
            repairs=[{"kind": "waiver_or_wrapper_patch", "confidence": 0.5, "description": "Add an explicit audio silence waiver or correct I2S DAC pin mapping."}],
        )


def _diagnose_input(items: list[dict[str, Any]], input_doc: dict[str, Any]) -> None:
    scripted = _as_int(input_doc.get("scripted_events"), 0)
    delivered = _as_int(input_doc.get("delivered_events"), scripted)
    if scripted > delivered:
        _diag(
            items,
            code="INPUT_NOT_OBSERVED",
            phase="input",
            severity="error",
            summary="Scripted controller events were not delivered to the APF input pins.",
            observed={"scripted_events": scripted, "delivered_events": delivered},
            expected={"delivered_events": scripted},
            evidence=[{"artifact": "result.json", "json_pointer": "/input"}],
            likely_causes=["scenario input frame did not run", "controller port mapping is wrong", "core ignores the APF controller type bits"],
            repairs=[{"kind": "wrapper_patch", "confidence": 0.64, "description": "Verify cont*_key mapping and controller type bit handling."}],
        )


def _diagnose_saves(
    items: list[dict[str, Any]],
    data: dict[str, Any],
    save: dict[str, Any],
    failed_phase: str,
    message: str,
    result_ok: bool,
) -> None:
    slots = [slot for slot in _list(data.get("slots")) if isinstance(slot, dict)]
    nonvolatile_slots = [
        slot for slot in slots
        if _as_bool(slot.get("nonvolatile"), False)
        and (_as_int(slot.get("loaded_size"), 0) > 0 or bool(str(slot.get("file") or "")))
    ]
    reports = [report for report in _list(save.get("reports")) if isinstance(report, dict)]
    save_was_expected = result_ok or failed_phase == "save" or "save" in message.lower()
    if nonvolatile_slots and not reports:
        if not save_was_expected:
            return
        _diag(
            items,
            code="SAVE_SLOT_NOT_UNLOADED",
            phase="save",
            severity="error",
            summary="Nonvolatile data slot was declared but no save unload artifact was produced.",
            observed={"nonvolatile_slots": [slot.get("id") for slot in nonvolatile_slots], "save_reports": 0},
            expected={"save_reports": ">= 1"},
            evidence=[{"artifact": "result.json", "json_pointer": "/save/reports"}],
            likely_causes=["save unload flow did not run", "slot size table was not readable on shutdown", "nonvolatile slot address is not bridge-readable"],
            repairs=[{"kind": "profile_patch", "confidence": 0.61, "description": "Enable save unload in the scenario and verify nonvolatile slot size/address metadata."}],
        )
    for index, report in enumerate(reports):
        if report.get("matches_input") is False:
            _diag(
                items,
                code="SAVE_ROUNDTRIP_MISMATCH",
                phase="save",
                severity="error",
                summary=f"Save slot {report.get('slot_id')} did not roundtrip deterministically.",
                observed={"slot_id": report.get("slot_id"), "matches_input": False},
                expected={"matches_input": True},
                evidence=[{"artifact": "result.json", "json_pointer": f"/save/reports/{index}"}],
                likely_causes=["core mutated save RAM", "save unload size changed", "bridge readback path has stale or endian-swapped data"],
                repairs=[{"kind": "diagnostic_followup", "confidence": 0.57, "description": "Compare saves/slot_<id>.bin with the input save and inspect bridge readback ordering."}],
            )


def _diagnose_profile_risks(items: list[dict[str, Any]], profile: dict[str, Any] | None) -> None:
    if not profile:
        return
    memory = profile.get("memory") if isinstance(profile.get("memory"), dict) else {}
    for risk in _list(memory.get("risks")):
        if not isinstance(risk, dict):
            continue
        code = str(risk.get("code") or "MEMORY_MODEL_REQUIRED")
        if code not in KNOWN_CODES:
            code = "MEMORY_MODEL_REQUIRED"
        _diag(
            items,
            code=code,
            phase="preflight",
            severity=str(risk.get("severity") or "warning"),
            summary=str(risk.get("message") or "Memory dependency requires an explicit simulation model or waiver."),
            observed={"memory_classes": memory.get("classes", []), "external_classes": memory.get("external_classes", [])},
            expected={"memory_model": "selected, wired, or waived"},
            evidence=[{"artifact": "profile", "json_pointer": "/memory/risks"}],
            likely_causes=[
                "core depends on external RAM behavior that is not represented by the current profile",
                "generated wrapper has not selected a catalog memory model",
                "memory model is available but not wired to the core-specific controller",
            ],
            repairs=[
                {
                    "kind": "memory_model",
                    "confidence": 0.64,
                    "description": "Select or wire an explicit external RAM model and keep its confidence visible in source_provenance.json.",
                }
            ],
        )
    limitations = "\n".join(str(item) for item in _list(profile.get("limitations")))
    risks = json.dumps(profile.get("risks", []), sort_keys=True) if "risks" in profile else ""
    combined = f"{limitations}\n{risks}".lower()
    if "vhdl" in combined and ("stub" in combined or "entity" in combined):
        _diag(
            items,
            code="VHDL_ENTITY_STUBBED",
            phase="preflight",
            severity="warning",
            summary="Profile indicates VHDL gameplay/entity stubbing risk.",
            observed={"profile_risk": "vhdl"},
            expected={"real_gameplay_rtl": "Verilator-compatible"},
            evidence=[{"artifact": "profile", "json_pointer": "/risks"}],
            likely_causes=["Verilator does not compile VHDL directly", "generated shell uses a placeholder entity"],
            repairs=[{"kind": "shim_patch", "confidence": 0.49, "description": "Replace the stub with translated RTL, a public implementation, or a marked mixed-language strategy."}],
        )
    if "shim" in combined and "required" in combined:
        _diag(
            items,
            code="SHIM_REQUIRED",
            phase="preflight",
            severity="warning",
            summary="Profile indicates at least one unresolved shim requirement.",
            observed={"profile_risk": "shim_required"},
            expected={"shim_catalog": "complete for required vendor IP"},
            evidence=[{"artifact": "profile", "json_pointer": "/risks"}],
            likely_causes=["vendor IP was detected without a behavioral replacement", "filelist contains non-Verilator-friendly primitives"],
            repairs=[{"kind": "shim_patch", "confidence": 0.67, "description": "Add a deterministic simulation shim and filelist substitution entry."}],
        )
    if "memory" in combined and ("model" in combined or "sdram" in combined or "psram" in combined):
        _diag(
            items,
            code="MEMORY_MODEL_REQUIRED",
            phase="preflight",
            severity="warning",
            summary="Profile indicates an external memory model may be required.",
            observed={"profile_risk": "memory_model"},
            expected={"memory_model": "selected or waived"},
            evidence=[{"artifact": "profile", "json_pointer": "/risks"}],
            likely_causes=["core depends on SDRAM/PSRAM/CRAM behavior", "vendor memory controller was stubbed"],
            repairs=[{"kind": "memory_model", "confidence": 0.58, "description": "Select a transactional memory model matching the core's bridge-visible memory controller."}],
        )


def _diagnostic_doc(artifact_root: Path, result: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _severity_counts(items)
    result_ok = _as_bool(result.get("ok"), True)
    status = "fail" if summary["errors"] or not result_ok else "pass"
    return {
        "schema": DIAGNOSTICS_SCHEMA,
        "artifact_dir": str(artifact_root),
        "source_result": str(artifact_root / "result.json"),
        "ok": status == "pass" and result_ok,
        "status": status,
        "summary": summary,
        "diagnostics": items,
    }


def write_diagnostics(
    artifact_root: Path,
    *,
    profile: dict[str, Any] | None = None,
    video_metadata_path: Path | None = None,
) -> dict[str, Any]:
    if video_metadata_path is None:
        video_metadata_path = _profile_metadata_video(profile)
    doc = diagnose_artifacts(artifact_root, profile=profile, video_metadata_path=video_metadata_path)
    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "diagnostics.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    (artifact_root / "bringup-report.md").write_text(render_bringup_report(doc), encoding="utf-8")
    return doc


def render_bringup_report(doc: dict[str, Any]) -> str:
    diagnostics = [item for item in _list(doc.get("diagnostics")) if isinstance(item, dict)]
    errors = [item for item in diagnostics if item.get("severity") == "error"]
    warnings = [item for item in diagnostics if item.get("severity") == "warning"]
    title = Path(str(doc.get("artifact_dir", "run"))).name or "run"
    status = str(doc.get("status", "unknown")).upper()
    lines = [f"# Bring-Up Report: {title}", "", f"Status: {status}", ""]
    if errors:
        lines.append("Blocking:")
        for item in errors:
            lines.append(f"- {item.get('code')}: {item.get('summary')}")
        lines.append("")
    else:
        lines.append("Blocking: none")
        lines.append("")
    if warnings:
        lines.append("Non-blocking:")
        for item in warnings:
            lines.append(f"- {item.get('code')}: {item.get('summary')}")
        lines.append("")
    else:
        lines.append("Non-blocking: none")
        lines.append("")
    first_error = errors[0] if errors else None
    lines.append("Recommended next action:")
    if first_error:
        repairs = [repair for repair in _list(first_error.get("repairs")) if isinstance(repair, dict)]
        if repairs:
            lines.append(f"Apply or review: {repairs[0].get('description')}")
        else:
            lines.append(f"Investigate {first_error.get('code')} using the evidence artifacts below.")
    elif warnings:
        lines.append("Review warnings, add explicit waivers where intentional, then run the generated-core CI matrix.")
    else:
        lines.append("No APF contract diagnostics were emitted for this run.")
    lines.append("")
    lines.append("Artifacts:")
    for name in ("result.json", "diagnostics.json", "video_shape.json", "bridge.log", "bridge_summary.json", "lifecycle.json"):
        lines.append(f"- {name}")
    lines.append("")
    lines.append("Hardware confidence:")
    if errors:
        lines.append("Low until blocking APF contract diagnostics are resolved.")
    elif warnings:
        lines.append("Medium. Contract passed, but warnings should be waived or fixed before hardware validation.")
    else:
        lines.append("High for the simulated APF-facing contract. This does not prove FPGA timing closure or exact hardware behavior.")
    lines.append("")
    return "\n".join(lines)
