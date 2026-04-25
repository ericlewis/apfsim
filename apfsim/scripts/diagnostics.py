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
    "DATA_SLOT_REQUIRED_MISSING",
    "DATA_SLOT_FILE_MISSING",
    "DATA_SLOT_ID_MISMATCH",
    "DATA_SLOT_PAYLOAD_MISSING",
    "DATA_SLOT_LOAD_SHORT",
    "DATA_SLOT_READBACK_UNAVAILABLE",
    "DATA_SLOT_READBACK_MISMATCH",
    "INSTANCE_JSON_INVALID",
    "INTERACT_WRITE_MISSING",
    "VIDEO_NO_CLOCK",
    "VIDEO_NO_DE",
    "VIDEO_STATIC_FRAME",
    "VIDEO_NO_POST_INPUT_CHANGE",
    "VIDEO_WIDTH_MISMATCH",
    "VIDEO_HEIGHT_MISMATCH",
    "VIDEO_PROTOCOL_ERROR",
    "VIDEO_EXTRA_ACTIVE_PIXEL",
    "VIDEO_FRAME_COUNT_MISMATCH",
    "VIDEO_UNSTABLE_DIMENSIONS",
    "AUDIO_NO_MCLK",
    "AUDIO_NO_LRCK",
    "AUDIO_NO_DAC_ACTIVITY",
    "AUDIO_NO_POST_INPUT_ACTIVITY",
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
    "MEMORY_ROM_WRITE_MISMATCH",
    "MEMORY_ROM_COVERAGE_GAP",
    "MEMORY_OUT_OF_RANGE",
    "MEMORY_BUS_CONTENTION",
    "MEMORY_NO_ACTIVITY",
    "MEMORY_STALL_TIMEOUT",
    "SDRAM_COMMAND_ERROR",
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


def _counter_value(counters: list[dict[str, Any]], name: str, default: int = 0) -> int:
    for item in counters:
        if isinstance(item, dict) and str(item.get("name") or "") == name:
            return _as_int(item.get("value"), default)
    return default


def _data_slots(result: dict[str, Any]) -> list[dict[str, Any]]:
    data_load_slots = _list(_obj(result.get("data_load")).get("slots"))
    data_slots = _list(_obj(result.get("data")).get("slots"))
    slots = data_load_slots or data_slots
    return [slot for slot in slots if isinstance(slot, dict)]


def _loaded_slot_candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    for slot in _data_slots(result):
        loaded = _as_int(slot.get("loaded_bytes"), _as_int(slot.get("loaded_size"), 0))
        if loaded <= 0:
            continue
        candidates.append({
            "id": slot.get("id"),
            "name": slot.get("name", ""),
            "path": slot.get("path", slot.get("file", "")),
            "loaded_bytes": loaded,
            "crc": slot.get("crc", slot.get("loaded_crc32")),
        })
    return candidates


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


def _diagnostic_priority(item: dict[str, Any], index: int) -> tuple[int, int, int]:
    severity_rank = {"error": 0, "warning": 1, "info": 2}.get(str(item.get("severity")), 2)
    code = str(item.get("code") or "")
    phase = str(item.get("phase") or "")
    if code.startswith("DATA_SLOT") or code.startswith("INSTANCE_JSON"):
        domain_rank = 0
    elif code.startswith("MEMORY_ROM") or code == "MEMORY_UNINITIALIZED_READ":
        domain_rank = 1
    elif phase == "bridge" or code.startswith("BRIDGE"):
        domain_rank = 2
    elif phase == "reset" or code.startswith("RESET") or code == "READY_TO_RUN_MISSING":
        domain_rank = 3
    elif code == "BOOT_TIMEOUT":
        domain_rank = 9
    elif phase == "video" or code.startswith("VIDEO"):
        domain_rank = 4
    elif phase == "audio" or code.startswith("AUDIO"):
        domain_rank = 5
    else:
        domain_rank = 6
    return (severity_rank, domain_rank, index)


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
    memory_activity = load_optional_json_object(artifact_root / "memory_activity.json")
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
    if not memory_activity:
        memory_activity = _obj(result.get("memory_activity"))

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

    slots = _data_slots(result)
    slot_pointer_base = "/data_load/slots" if _list(_obj(result.get("data_load")).get("slots")) else "/data/slots"
    for index, slot in enumerate(slots):
        slot_id = slot.get("id")
        required = _as_bool(slot.get("required"), False)
        deferload = _as_bool(slot.get("deferload"), False)
        has_address = _as_bool(slot.get("has_address"), True)
        loaded_bytes = _as_int(slot.get("loaded_bytes"), _as_int(slot.get("loaded_size"), 0))
        path = str(slot.get("path") or slot.get("file") or "")
        file_exists = _as_bool(slot.get("file_exists"), bool(path))
        load_status = str(slot.get("load_status") or "")
        load_error = str(slot.get("load_error") or "")

        if required and not deferload and has_address and loaded_bytes <= 0:
            if not path or load_status == "required_file_unspecified":
                _diag(
                    items,
                    code="DATA_SLOT_REQUIRED_MISSING",
                    phase="data",
                    severity="error",
                    summary=f"Required dataslot {slot_id} has no payload path.",
                    observed={"slot": slot_id, "path": path, "load_status": load_status},
                    expected={"required_slot_payload": "configured"},
                    evidence=[{"artifact": "result.json", "json_pointer": f"{slot_pointer_base}/{index}"}],
                    likely_causes=[
                        "scenario did not provide --slot for a required ROM/cart asset",
                        "generated data.json defines a required loadable slot without a filename",
                        "instance JSON did not resolve the required slot payload",
                    ],
                    repairs=[
                        {
                            "kind": "scenario_or_package_patch",
                            "confidence": 0.84,
                            "description": "Provide the required slot payload or fix the generated instance/data slot mapping before interpreting boot/video failures.",
                        }
                    ],
                )
            elif not file_exists or load_status == "required_file_missing":
                _diag(
                    items,
                    code="DATA_SLOT_FILE_MISSING",
                    phase="data",
                    severity="error",
                    summary=f"Required dataslot {slot_id} payload file is missing.",
                    observed={"slot": slot_id, "path": path, "file_exists": file_exists, "load_error": load_error},
                    expected={"file_exists": True},
                    evidence=[{"artifact": "result.json", "json_pointer": f"{slot_pointer_base}/{index}"}],
                    likely_causes=[
                        "profile or scenario points at the wrong ROM path",
                        "instance JSON selected an asset that is not present in the package tree",
                        "core URL/path was generated without the required game/cart payload",
                    ],
                    repairs=[
                        {
                            "kind": "scenario_or_package_patch",
                            "confidence": 0.86,
                            "description": "Fix the slot file path or generated package asset mapping; rerun before debugging reset/video.",
                        }
                    ],
                )
            else:
                _diag(
                    items,
                    code="DATA_SLOT_PAYLOAD_MISSING",
                    phase="data",
                    severity="error",
                    summary=f"Required dataslot {slot_id} did not load any bytes.",
                    observed={"slot": slot_id, "path": path, "load_status": load_status, "load_error": load_error},
                    expected={"loaded_bytes": "> 0"},
                    evidence=[{"artifact": "result.json", "json_pointer": f"{slot_pointer_base}/{index}"}],
                    likely_causes=[
                        "data-slot request-write was rejected or never reached the target",
                        "payload size validation failed before bridge writes started",
                        "required ROM/cart slot was mistaken for setup-only metadata",
                    ],
                    repairs=[
                        {
                            "kind": "profile_or_package_patch",
                            "confidence": 0.74,
                            "description": "Check data.json slot id/address/size constraints and the bridge command transcript for this slot.",
                        }
                    ],
                )

        if load_status in {"size_exact_mismatch", "size_maximum_exceeded"}:
            _diag(
                items,
                code="DATA_SLOT_LOAD_SHORT",
                phase="data",
                severity="error",
                summary=f"Dataslot {slot_id} payload failed size validation.",
                observed={"slot": slot_id, "path": path, "load_status": load_status, "load_error": load_error},
                expected={"size": "data.json size_exact/size_maximum constraints"},
                evidence=[{"artifact": "result.json", "json_pointer": f"{slot_pointer_base}/{index}"}],
                likely_causes=[
                    "wrong ROM/archive file selected for this slot",
                    "generated size_exact/size_maximum metadata does not match the assembled payload",
                    "instance JSON points at a setup file instead of the actual game data",
                ],
                repairs=[
                    {
                        "kind": "package_or_scenario_patch",
                        "confidence": 0.82,
                        "description": "Select the correct payload or regenerate data.json size constraints from the assembled ROM.",
                    }
                ],
            )

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
                evidence=[{"artifact": "result.json", "json_pointer": f"{slot_pointer_base}/{index}"}],
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
                evidence=[{"artifact": "result.json", "json_pointer": f"{slot_pointer_base}/{index}"}],
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
                evidence=[{"artifact": "result.json", "json_pointer": f"{slot_pointer_base}/{index}"}],
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
                evidence=[{"artifact": "result.json", "json_pointer": f"{slot_pointer_base}/{index}"}],
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

    if _as_int(bridge.get("target_slot_errors"), 0) > 0:
        _diag(
            items,
            code="DATA_SLOT_ID_MISMATCH",
            phase="data",
            severity="error",
            summary="Target requested one or more undefined data-slot IDs.",
            observed={
                "target_slot_errors": _as_int(bridge.get("target_slot_errors"), 0),
                "target_dataslot_reads": _as_int(bridge.get("target_dataslot_reads"), 0),
                "target_dataslot_writes": _as_int(bridge.get("target_dataslot_writes"), 0),
            },
            expected={"target_slot_errors": 0},
            evidence=[{"artifact": "result.json", "json_pointer": "/bridge/target_slot_errors"}],
            likely_causes=[
                "generated data.json uses different slot IDs than the HDL expects",
                "instance JSON remapped or omitted a secondary ROM slot",
                "deferload target-command slots were not included in the scenario/profile",
            ],
            repairs=[
                {
                    "kind": "metadata_or_scenario_patch",
                    "confidence": 0.78,
                    "description": "Compare target data-slot command IDs in bridge.log with data.json and generated scenario slots.",
                }
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
    _diagnose_audio(items, result, audio, failed_phase, message)
    _diagnose_input(items, input_doc)
    _diagnose_saves(items, data, save, failed_phase, message, _as_bool(result.get("ok"), False))
    _diagnose_memory_activity(items, memory_activity, result)

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
    activity = _obj(result.get("video_activity"))
    input_response = _obj(result.get("input_video_response")) or _obj(activity.get("input_response"))
    input_response_changed = _as_bool(input_response.get("changed"), False)
    named_phase_changed = any(
        isinstance(phase, dict) and _as_bool(phase.get("changed"), False)
        for phase in _list(activity.get("phases"))
    )
    if input_response and _as_bool(input_response.get("required", input_response.get("require_changed")), False) and not _as_bool(input_response.get("pass"), True):
        _diag(
            items,
            code="VIDEO_NO_POST_INPUT_CHANGE",
            phase="video",
            severity="error",
            summary="No frame changed inside the configured post-input response window.",
            observed={
                "name": input_response.get("name"),
                "available": input_response.get("available"),
                "start_frame": input_response.get("start_frame"),
                "end_frame": input_response.get("end_frame"),
                "frames_considered": input_response.get("frames_considered"),
                "changed_frames": input_response.get("changed_frames"),
                "max_changed_pixels": input_response.get("max_changed_pixels"),
            },
            expected={
                "min_changed_frames": input_response.get("min_changed_frames"),
                "min_changed_pixels": input_response.get("min_changed_pixels"),
            },
            evidence=[{"artifact": "result.json", "json_pointer": "/input_video_response"}],
            likely_causes=[
                "coin/start input did not reach the gameplay core",
                "core remained in attract/static mode after input",
                "ROM or CPU path is running but gameplay state did not advance",
            ],
            repairs=[
                {
                    "kind": "wrapper_or_scenario_patch",
                    "confidence": 0.67,
                    "description": "Verify controller bit mapping and extend the post-input response window if this game changes later than the current scenario allows.",
                }
            ],
        )

    for index, phase in enumerate(_list(activity.get("phases"))):
        if not isinstance(phase, dict):
            continue
        if _as_bool(phase.get("required", phase.get("require_changed")), False) and not _as_bool(phase.get("pass"), True):
            _diag(
                items,
                code="VIDEO_NO_POST_INPUT_CHANGE",
                phase="video",
                severity="error",
                summary=f"Required video activity phase did not change: {phase.get('name') or index}.",
                observed={
                    "name": phase.get("name"),
                    "available": phase.get("available"),
                    "start_frame": phase.get("start_frame"),
                    "end_frame": phase.get("end_frame"),
                    "frames_considered": phase.get("frames_considered"),
                    "changed_frames": phase.get("changed_frames"),
                    "max_changed_pixels": phase.get("max_changed_pixels"),
                },
                expected={
                    "min_changed_frames": phase.get("min_changed_frames"),
                    "min_changed_pixels": phase.get("min_changed_pixels"),
                },
                evidence=[{"artifact": "result.json", "json_pointer": f"/video_activity/phases/{index}"}],
                likely_causes=[
                    "named scenario phase starts before the input effect is visible",
                    "scripted input did not transition the core out of its static state",
                    "gameplay/video state is blocked by data-load, reset, or input mapping",
                ],
                repairs=[
                    {
                        "kind": "wrapper_or_scenario_patch",
                        "confidence": 0.64,
                        "description": "Check controller mapping and tune the named phase start/window after confirming real gameplay timing.",
                    }
                ],
            )

    if frames >= 2 and width > 0 and height > 0 and not (input_response_changed or named_phase_changed) and (unique_colors <= 1 or nonzero_pixels <= 0):
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
    lower = message.lower()
    if failed_phase != "assert":
        return
    if "video" in lower and ("frame count" in lower or "required frame" in lower):
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
    elif "audio" in lower and "after input" in lower:
        _diag(
            items,
            code="AUDIO_NO_POST_INPUT_ACTIVITY",
            phase="audio",
            severity="error",
            summary=message or "Scenario post-input audio expectation failed.",
            observed={"message": message},
            expected={"audio_activity_after_input": True},
            evidence=[{"artifact": "result.json", "json_pointer": "/input_audio_response"}],
            likely_causes=["coin/start input did not reach the core", "gameplay has not started yet", "audio is intentionally silent until a later gameplay phase"],
            repairs=[{"kind": "wrapper_or_scenario_patch", "confidence": 0.58, "description": "Verify controller mapping and extend the audio post-input response window if the game starts sound later."}],
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
    items: list[dict[str, Any]], result: dict[str, Any], audio: dict[str, Any], failed_phase: str, message: str) -> None:
    mclk_edges = _as_int(audio.get("mclk_edges"), 0)
    lrck_edges = _as_int(audio.get("lrck_edges"), 0)
    samples = _as_int(audio.get("samples"), 0)
    peak_l = abs(_as_int(audio.get("min_l"), 0)) + abs(_as_int(audio.get("max_l"), 0))
    peak_r = abs(_as_int(audio.get("min_r"), 0)) + abs(_as_int(audio.get("max_r"), 0))
    activity = _obj(result.get("audio_activity"))
    input_response = _obj(result.get("input_audio_response")) or _obj(activity.get("input_response"))
    if failed_phase == "audio" or "audio" in message.lower():
        severity = "error"
    else:
        severity = "warning"
    if input_response and _as_bool(input_response.get("required", input_response.get("require_activity")), False) and not _as_bool(input_response.get("pass"), True):
        _diag(
            items,
            code="AUDIO_NO_POST_INPUT_ACTIVITY",
            phase="audio",
            severity="error",
            summary="No audio activity was observed inside the configured post-input response window.",
            observed={
                "name": input_response.get("name"),
                "available": input_response.get("available"),
                "start_frame": input_response.get("start_frame"),
                "end_frame": input_response.get("end_frame"),
                "samples": input_response.get("samples"),
                "nonzero_samples": input_response.get("nonzero_samples"),
                "peak": input_response.get("peak"),
                "activity": input_response.get("activity"),
            },
            expected={
                "min_samples": input_response.get("min_samples"),
                "min_nonzero_samples": input_response.get("min_nonzero_samples"),
                "min_peak": input_response.get("min_peak"),
            },
            evidence=[{"artifact": "result.json", "json_pointer": "/input_audio_response"}],
            likely_causes=[
                "input did not transition the core into a sound-producing state",
                "audio pins are mapped but DAC data remains silent after gameplay input",
                "scenario response window is too short for this game's first sound",
            ],
            repairs=[
                {
                    "kind": "wrapper_or_scenario_patch",
                    "confidence": 0.62,
                    "description": "Verify input mapping and tune the post-input audio window after confirming expected gameplay timing.",
                }
            ],
        )
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
    roundtrip_was_expected = failed_phase == "save" and (
        "roundtrip" in message.lower()
        or "match input" in message.lower()
        or "did not match" in message.lower()
    )
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
            if not roundtrip_was_expected:
                continue
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


def _memory_counter_error_code(counter: dict[str, Any]) -> str:
    explicit = str(counter.get("error_code") or "")
    if explicit in KNOWN_CODES:
        return explicit
    name = str(counter.get("name") or "").lower()
    if "bus_contention" in name:
        return "MEMORY_BUS_CONTENTION"
    if "byte_enable" in name:
        return "MEMORY_BYTE_ENABLE_MISMATCH"
    if "overrun" in name or "stall" in name:
        return "MEMORY_STALL_TIMEOUT"
    return "MEMORY_MODEL_REQUIRED"


def _memory_error_likely_causes(code: str) -> list[str]:
    if code == "MEMORY_ROM_WRITE_MISMATCH":
        return [
            "external SDRAM write path corrupted ROM-backed bytes",
            "SDRAM address, bank, or byte-lane mapping differs from the JTFRAME programming sideband",
            "download byte swapping or data mask handling is wrong",
        ]
    if code == "MEMORY_UNINITIALIZED_READ":
        return [
            "core read a ROM-backed SDRAM address before the physical SDRAM write landed",
            "data-slot payload did not cover a region the core expects to execute or render from",
            "SDRAM address mapping dropped or shifted a programmed ROM word",
        ]
    if code == "SDRAM_COMMAND_ERROR":
        return [
            "SDRAM controller issued READ/WRITE without an active row",
            "generated wrapper connected SDRAM command pins with wrong polarity",
            "pin-level model does not match this controller's command sequencing",
        ]
    return [
        "external RAM byte lanes, address bits, or control strobes are miswired",
        "memory controller accepted a request while busy or stalled",
        "wrapper exposes a memory model error flag from SRAM/PSRAM/CRAM/SDRAM",
    ]


def _memory_error_repair_description(code: str) -> str:
    if code == "MEMORY_ROM_WRITE_MISMATCH":
        return "Compare the SDRAM ROM preload sideband against physical SDRAM writes; inspect bank/address packing, byte-lane masks, and download byte swapping."
    if code == "MEMORY_UNINITIALIZED_READ":
        return "Check whether the ROM/data-slot image is complete, then trace the first ROM-backed unwritten read address through the SDRAM programming and address mapper."
    if code == "SDRAM_COMMAND_ERROR":
        return "Inspect SDRAM command pin polarity and row/bank activation timing in the generated wrapper and pin-level model."
    return "Trace the named counter back to the memory model and inspect address, byte-enable, OE/WE, and request/ack timing."


def _memory_error_observed(
    code: str,
    counter_name: str,
    value: int,
    class_name: Any,
    observed: Any,
    counters: list[dict[str, Any]],
    result: dict[str, Any],
) -> dict[str, Any]:
    doc = {
        "counter": counter_name,
        "class": class_name,
        "value": value,
        "observed": observed,
    }
    if code == "MEMORY_ROM_WRITE_MISMATCH":
        addr = _counter_value(counters, "sdram_first_rom_mismatch_addr")
        dqm = _counter_value(counters, "sdram_first_rom_mismatch_dqm", 3)
        doc.update({
            "first_addr": addr,
            "bank": addr >> 22,
            "expected_word": _counter_value(counters, "sdram_first_rom_mismatch_expected"),
            "actual_word": _counter_value(counters, "sdram_first_rom_mismatch_actual"),
            "dqm": dqm,
            "byte_lanes_checked": {
                "low": (dqm & 0x1) == 0,
                "high": (dqm & 0x2) == 0,
            },
            "source_slot_candidates": _loaded_slot_candidates(result),
        })
    elif code == "MEMORY_UNINITIALIZED_READ":
        addr = _counter_value(counters, "sdram_first_rom_unwritten_read_addr")
        dqm = _counter_value(counters, "sdram_first_rom_unwritten_dqm", 3)
        doc.update({
            "first_addr": addr,
            "bank": addr >> 22,
            "expected_word": _counter_value(counters, "sdram_first_rom_unwritten_expected"),
            "dqm": dqm,
            "byte_lanes_checked": {
                "low": (dqm & 0x1) == 0,
                "high": (dqm & 0x2) == 0,
            },
            "source_slot_candidates": _loaded_slot_candidates(result),
        })
    return doc


def _diagnose_memory_activity(items: list[dict[str, Any]], memory_activity: dict[str, Any], result: dict[str, Any]) -> None:
    if not memory_activity:
        return
    counters = [item for item in _list(memory_activity.get("counters")) if isinstance(item, dict)]
    emitted: set[tuple[str, str]] = set()
    for index, error in enumerate(_list(memory_activity.get("errors"))):
        if not isinstance(error, dict):
            continue
        code = str(error.get("code") or "MEMORY_MODEL_REQUIRED")
        if code not in KNOWN_CODES:
            code = "MEMORY_MODEL_REQUIRED"
        counter_name = str(error.get("counter") or error.get("name") or "")
        key = (code, counter_name)
        if key in emitted:
            continue
        emitted.add(key)
        _diag(
            items,
            code=code,
            phase="memory",
            severity=str(error.get("severity") or "error"),
            summary=f"Memory activity counter reported {code}.",
            observed=_memory_error_observed(
                code,
                counter_name,
                _as_int(error.get("value"), 0),
                error.get("class"),
                error.get("observed", memory_activity.get("observed")),
                counters,
                result,
            ),
            expected={"memory_error_counters": 0},
            evidence=[{"artifact": "memory_activity.json", "json_pointer": f"/errors/{index}"}],
            likely_causes=_memory_error_likely_causes(code),
            repairs=[
                {
                    "kind": "wrapper_patch",
                    "confidence": 0.73,
                    "description": _memory_error_repair_description(code),
                }
            ],
        )
    for index, counter in enumerate(counters):
        if not _as_bool(counter.get("error"), False):
            continue
        code = _memory_counter_error_code(counter)
        counter_name = str(counter.get("name") or "")
        key = (code, counter_name)
        if key in emitted:
            continue
        emitted.add(key)
        _diag(
            items,
            code=code,
            phase="memory",
            severity="error",
            summary=f"Memory counter {counter_name or '<unnamed>'} reported an error.",
            observed=_memory_error_observed(
                code,
                counter_name,
                _as_int(counter.get("value"), 0),
                counter.get("class"),
                memory_activity.get("observed"),
                counters,
                result,
            ),
            expected={"counter_value": 0},
            evidence=[{"artifact": "memory_activity.json", "json_pointer": f"/counters/{index}"}],
            likely_causes=_memory_error_likely_causes(code),
            repairs=[
                {
                    "kind": "memory_model",
                    "confidence": 0.76,
                    "description": _memory_error_repair_description(code),
                }
            ],
        )

    for index, counter in enumerate(counters):
        name = str(counter.get("name") or "")
        if name != "sdram_rom_coverage_gap_count":
            continue
        value = _as_int(counter.get("value"), 0)
        if value <= 0:
            continue
        first_addr = next(
            (
                _as_int(item.get("value"), 0)
                for item in counters
                if isinstance(item, dict) and str(item.get("name") or "") == "sdram_first_coverage_gap_addr"
            ),
            0,
        )
        _diag(
            items,
            code="MEMORY_ROM_COVERAGE_GAP",
            phase="memory",
            severity="warning",
            summary="SDRAM model observed reads outside ROM-backed coverage.",
            observed={
                "counter": name,
                "class": counter.get("class"),
                "value": value,
                "first_addr": first_addr,
                "bank": first_addr >> 22,
                "source_slot_candidates": _loaded_slot_candidates(result),
            },
            expected={"coverage_gap_count": 0},
            evidence=[{"artifact": "memory_activity.json", "json_pointer": f"/counters/{index}"}],
            likely_causes=[
                "ROM/data-slot payload is incomplete for this core",
                "scenario selected a setup or message asset instead of the full game ROM",
                "JTFRAME programming address-to-SDRAM mapping needs a stronger family rule",
            ],
            repairs=[
                {
                    "kind": "scenario_or_profile_fix",
                    "confidence": 0.72,
                    "description": "Use the full expected ROM payload or add a family-specific ROM coverage mapping before treating SDRAM reads as fully verified.",
                }
            ],
        )

    if not _as_bool(memory_activity.get("observed"), False):
        return
    data_load = _obj(result.get("data_load"))
    loaded_bytes = _as_int(data_load.get("total_loaded_bytes"), 0)
    if loaded_bytes <= 0:
        return
    activity_by_class: dict[str, int] = {}
    for counter in counters:
        name = str(counter.get("name") or "").lower()
        if not (name.endswith("_read_count") or name.endswith("_write_count")):
            continue
        cls = str(counter.get("class") or "memory")
        activity_by_class[cls] = activity_by_class.get(cls, 0) + _as_int(counter.get("value"), 0)
    for cls, total in sorted(activity_by_class.items()):
        if total > 0:
            continue
        _diag(
            items,
            code="MEMORY_NO_ACTIVITY",
            phase="memory",
            severity="warning",
            summary=f"Memory counters for {cls} were observed but stayed at zero during data-loaded run.",
            observed={"class": cls, "counter_total": total, "loaded_bytes": loaded_bytes},
            expected={"counter_total": "> 0 when this memory path is used"},
            evidence=[{"artifact": "memory_activity.json", "json_pointer": "/counters"}],
            likely_causes=[
                "standard memory counter ports are wired to the wrong model instance",
                "data slot loaded into a different memory path than the observed counters",
                "core did not reach the memory controller despite APF data loading",
            ],
            repairs=[
                {
                    "kind": "wrapper_patch",
                    "confidence": 0.55,
                    "description": "Check whether the data-slot address range should increment the observed memory model's read/write counters.",
                }
            ],
        )


def _diagnostic_doc(artifact_root: Path, result: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    items = [
        item for _, item in sorted(
            enumerate(items),
            key=lambda indexed: _diagnostic_priority(indexed[1], indexed[0]),
        )
    ]
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
