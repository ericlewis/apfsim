"""Pocket/APF lifecycle log analyzer.

The parser is intentionally tolerant: Pocket debug logs and apfsim bridge logs do not
share one canonical line format, so detection uses APF command names, command IDs,
and common key/value fields rather than exact line templates.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

HOST_COMMANDS = {
    0x0000: "Request Status",
    0x0010: "Reset Enter",
    0x0011: "Reset Exit",
    0x0080: "Data slot request read",
    0x0082: "Data slot request write",
    0x008A: "Data slot update",
    0x008F: "Data slot access all complete",
    0x0090: "Real-time clock data",
    0x00B1: "OS notify cartridge adapter",
    0x00B8: "OS notify display mode",
}

TARGET_COMMANDS = {
    0x0140: "Ready to Run",
}

STATUS_CODES = {
    0x01: "booting",
    0x02: "setup",
    0x03: "idle",
    0x04: "running",
}

HOST_COMMAND_TO_KIND = {
    0x0000: "request_status",
    0x0010: "reset_enter",
    0x0011: "reset_exit",
    0x0080: "dataslot_request_read",
    0x0082: "dataslot_request_write",
    0x008A: "dataslot_update",
    0x008F: "dataslot_all_complete",
    0x0090: "rtc",
    0x00B1: "os_notify_cartridge_adapter",
    0x00B8: "os_notify_display_mode",
}

EXPECTED_LIFECYCLE = [
    "status_setup",
    "reset_enter",
    "dataslot_request_write",
    "dataslot_all_complete",
    "rtc",
    "target_ready_to_run",
    "reset_exit",
    "status_running",
]

HEX_RE = re.compile(r"0x([0-9a-fA-F]+)")
KEY_HEX_RE = re.compile(r"\b([A-Za-z0-9_]+)=0x([0-9a-fA-F]+)")
KEY_DEC_RE = re.compile(r"\b([A-Za-z0-9_]+)=([0-9]+)")


@dataclass
class LogEvent:
    kind: str
    line: int
    text: str
    name: str = ""
    value: int | None = None
    fields: dict[str, int] = field(default_factory=dict)


@dataclass
class DataSlotObservation:
    id: int | None = None
    bytes: int | None = None
    address: int | None = None
    writes32: int | None = None
    request_line: int | None = None
    done_line: int | None = None


@dataclass
class LifecycleSummary:
    path: str
    line_count: int = 0
    event_count: int = 0
    sequence_ok: bool = False
    phases: dict[str, int] = field(default_factory=dict)
    missing_phases: list[str] = field(default_factory=list)
    order_errors: list[str] = field(default_factory=list)
    statuses: list[dict[str, Any]] = field(default_factory=list)
    host_commands: list[dict[str, Any]] = field(default_factory=list)
    target_commands: list[dict[str, Any]] = field(default_factory=list)
    data_slots: list[dict[str, Any]] = field(default_factory=list)
    event_counts: dict[str, int] = field(default_factory=dict)


def _lower_words(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _parse_fields(text: str) -> dict[str, int]:
    fields: dict[str, int] = {key.lower(): int(value, 16) for key, value in KEY_HEX_RE.findall(text)}
    for key, value in KEY_DEC_RE.findall(text):
        fields.setdefault(key.lower(), int(value, 10))
    return fields


def _all_hex_values(text: str) -> list[int]:
    return [int(value, 16) for value in HEX_RE.findall(text)]


def _short_command_id(value: int) -> int:
    return value & 0xFFFF


def _event(kind: str, line_no: int, text: str, name: str = "", value: int | None = None, fields: dict[str, int] | None = None) -> LogEvent:
    return LogEvent(kind=kind, line=line_no, text=text.rstrip(), name=name, value=value, fields=fields or {})


def _detect_host_command(line_no: int, text: str, fields: dict[str, int], words: str) -> LogEvent | None:
    lower = text.lower()
    if "cmd" not in fields and "result" in fields and ("host ok" in lower or " ok " in f" {words} "):
        return None

    command: int | None = None
    if "cmd" in fields:
        command = _short_command_id(fields["cmd"])
    elif "result" not in fields and any(token in words for token in ("host", "command", "cmd")):
        for value in _all_hex_values(text):
            candidate = _short_command_id(value)
            if candidate in HOST_COMMANDS:
                command = candidate
                break

    if command is None:
        name_to_command = [
            ("request status", 0x0000),
            ("reset enter", 0x0010),
            ("reset exit", 0x0011),
            ("data slot request read", 0x0080),
            ("dataslot request read", 0x0080),
            ("data slot request write", 0x0082),
            ("dataslot request write", 0x0082),
            ("data slot update", 0x008A),
            ("data slot access all complete", 0x008F),
            ("dataslot all complete", 0x008F),
            ("real time clock data", 0x0090),
            ("real-time clock data", 0x0090),
            ("rtc", 0x0090),
        ]
        for needle, value in name_to_command:
            if needle in words or needle in lower:
                command = value
                break

    if command is None or command not in HOST_COMMANDS:
        return None

    return _event(HOST_COMMAND_TO_KIND[command], line_no, text, HOST_COMMANDS[command], command, fields)


def _detect_status(line_no: int, text: str, fields: dict[str, int], words: str) -> LogEvent | None:
    value: int | None = None
    if "result" in fields and ("request status" in text.lower() or fields.get("cmd") == 0):
        value = _short_command_id(fields["result"])
    elif "status" in fields:
        value = _short_command_id(fields["status"])
    elif "status" in words:
        for candidate, name in STATUS_CODES.items():
            if name in words:
                value = candidate
                break

    if value not in STATUS_CODES:
        return None
    name = STATUS_CODES[value]
    return _event(f"status_{name}", line_no, text, name, value, fields)


def _detect_target_command(line_no: int, text: str, fields: dict[str, int], words: str) -> LogEvent | None:
    lower = text.lower()
    if "target ok" in lower:
        return None

    command: int | None = None
    if "word" in fields:
        command = _short_command_id(fields["word"])
    elif "ready to run" in lower or "ready to run" in words:
        command = 0x0140
    else:
        for value in _all_hex_values(text):
            candidate = _short_command_id(value)
            if candidate in TARGET_COMMANDS:
                command = candidate
                break

    if command not in TARGET_COMMANDS:
        return None
    kind = "target_ready_to_run" if command == 0x0140 else "target_command"
    return _event(kind, line_no, text, TARGET_COMMANDS[command], command, fields)


def _detect_dataslot_line(line_no: int, text: str, fields: dict[str, int], words: str) -> LogEvent | None:
    if "dataslot table" in text.lower() or "data slot table" in text.lower():
        return _event("dataslot_table", line_no, text, "Data slot table", None, fields)
    if "dataslot load begin" in text.lower() or "data slot load begin" in text.lower():
        return _event("dataslot_load_begin", line_no, text, "Data slot load begin", None, fields)
    if "dataslot load done" in text.lower() or "data slot load done" in text.lower():
        return _event("dataslot_load_done", line_no, text, "Data slot load done", None, fields)
    if "slot" in words and "write" in words and "bytes" in fields:
        return _event("dataslot_load_begin", line_no, text, "Data slot load begin", None, fields)
    return None


def parse_log_events(path: Path) -> tuple[list[LogEvent], int]:
    events: list[LogEvent] = []
    line_count = 0
    with path.open(errors="replace") as fh:
        for line_count, line in enumerate(fh, start=1):
            fields = _parse_fields(line)
            words = _lower_words(line)
            detectors = [
                _detect_status,
                _detect_dataslot_line,
                _detect_target_command,
                _detect_host_command,
            ]
            seen: set[tuple[str, int | None]] = set()
            for detector in detectors:
                event = detector(line_count, line, fields, words)
                if not event:
                    continue
                key = (event.kind, event.value)
                if key in seen:
                    continue
                seen.add(key)
                events.append(event)
    return events, line_count


def _first_lines(events: list[LogEvent]) -> dict[str, int]:
    phases: dict[str, int] = {}
    for event in events:
        phases.setdefault(event.kind, event.line)
    return phases


def _data_slots(events: list[LogEvent]) -> list[dict[str, Any]]:
    slots: list[DataSlotObservation] = []
    by_id: dict[int, DataSlotObservation] = {}

    def first_field(fields: dict[str, int], *names: str) -> int | None:
        for name in names:
            if name in fields:
                return fields[name]
        return None

    def get_slot(slot_id: int | None) -> DataSlotObservation:
        if slot_id is None:
            slot = DataSlotObservation()
            slots.append(slot)
            return slot
        if slot_id not in by_id:
            by_id[slot_id] = DataSlotObservation(id=slot_id)
            slots.append(by_id[slot_id])
        return by_id[slot_id]

    for event in events:
        if event.kind == "dataslot_request_write":
            slot_id = first_field(event.fields, "p0", "id")
            slot = get_slot(slot_id)
            slot.bytes = event.fields.get("p1", slot.bytes)
            slot.address = event.fields.get("p2", slot.address)
            slot.request_line = event.line
        elif event.kind == "dataslot_load_begin":
            slot_id = first_field(event.fields, "id", "slot")
            slot = get_slot(slot_id)
            slot.bytes = event.fields.get("bytes", slot.bytes)
            slot.address = event.fields.get("address", slot.address)
            slot.request_line = slot.request_line or event.line
        elif event.kind == "dataslot_load_done":
            slot_id = first_field(event.fields, "id", "slot")
            slot = get_slot(slot_id)
            slot.writes32 = event.fields.get("writes32", slot.writes32)
            slot.done_line = event.line

    return [asdict(slot) for slot in slots]


def summarize_log(path: Path) -> LifecycleSummary:
    events, line_count = parse_log_events(path)
    phases = _first_lines(events)
    missing = [phase for phase in EXPECTED_LIFECYCLE if phase not in phases]
    order_errors: list[str] = []
    previous_phase = ""
    previous_line = -1
    for phase in EXPECTED_LIFECYCLE:
        if phase not in phases:
            continue
        line = phases[phase]
        if previous_line > line:
            order_errors.append(f"{phase} line {line} occurred before {previous_phase} line {previous_line}")
        previous_phase = phase
        previous_line = line

    counts: dict[str, int] = {}
    for event in events:
        counts[event.kind] = counts.get(event.kind, 0) + 1

    statuses = [
        {"line": event.line, "status": event.name, "value": event.value}
        for event in events
        if event.kind.startswith("status_")
    ]
    host_commands = [
        {"line": event.line, "command": event.name, "value": event.value, "fields": event.fields}
        for event in events
        if event.value in HOST_COMMANDS and event.kind in set(HOST_COMMAND_TO_KIND.values())
    ]
    target_commands = [
        {"line": event.line, "command": event.name, "value": event.value, "fields": event.fields}
        for event in events
        if event.value in TARGET_COMMANDS or event.kind.startswith("target_")
    ]

    return LifecycleSummary(
        path=str(path),
        line_count=line_count,
        event_count=len(events),
        sequence_ok=not missing and not order_errors,
        phases=phases,
        missing_phases=missing,
        order_errors=order_errors,
        statuses=statuses,
        host_commands=host_commands,
        target_commands=target_commands,
        data_slots=_data_slots(events),
        event_counts=counts,
    )


def analyze_logs(paths: list[Path]) -> dict[str, Any]:
    files = [asdict(summarize_log(path)) for path in paths]
    return {
        "ok": all(item["sequence_ok"] for item in files),
        "files": files,
    }


def write_json_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
