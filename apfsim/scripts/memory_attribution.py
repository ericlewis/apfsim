#!/usr/bin/env python3
"""Attribute external-memory ROM counter failures back to APF data slots."""
from __future__ import annotations

from typing import Any

ROM_EVENT_SCHEMA = "apfsim.memory_rom_validation.v1"


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip(), 0)
        except ValueError:
            return default
    return default


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def counter_value(counters: list[dict[str, Any]], name: str, default: int = 0) -> int:
    for item in counters:
        if isinstance(item, dict) and str(item.get("name") or "") == name:
            return _as_int(item.get("value"), default)
    return default


def loaded_slot_candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    data_load_slots = _list(_obj(result.get("data_load")).get("slots"))
    data_slots = _list(_obj(result.get("data")).get("slots"))
    candidates: list[dict[str, Any]] = []
    for slot in data_load_slots or data_slots:
        if not isinstance(slot, dict):
            continue
        loaded = _as_int(slot.get("loaded_bytes"), _as_int(slot.get("loaded_size"), 0))
        if loaded <= 0:
            continue
        candidates.append({
            "id": slot.get("id"),
            "name": slot.get("name", ""),
            "path": slot.get("path", slot.get("file", "")),
            "address": _as_int(slot.get("address"), 0),
            "has_address": bool(slot.get("has_address", "address" in slot)),
            "loaded_bytes": loaded,
            "crc": slot.get("crc", slot.get("loaded_crc32")),
            "checksum_fnv1a64": slot.get("checksum_fnv1a64", slot.get("loaded_checksum")),
        })
    return candidates


def byte_lanes_from_dqm(dqm: int, source_offset: int | None = None) -> dict[str, Any]:
    lanes: list[dict[str, Any]] = []
    checked = {"low": (dqm & 0x1) == 0, "high": (dqm & 0x2) == 0}
    if checked["low"]:
        lane: dict[str, Any] = {"name": "low", "index": 0}
        if source_offset is not None:
            lane["source_offset"] = source_offset
        lanes.append(lane)
    if checked["high"]:
        lane = {"name": "high", "index": 1}
        if source_offset is not None:
            lane["source_offset"] = source_offset + 1
        lanes.append(lane)
    return {
        "dqm": dqm,
        "checked": checked,
        "lanes": lanes,
        "names": [lane["name"] for lane in lanes],
    }


def _slot_match(slot: dict[str, Any], source_offset: int, rule: str, confidence: float, first_addr: int, byte_address: int) -> dict[str, Any] | None:
    loaded = _as_int(slot.get("loaded_bytes"), 0)
    if source_offset < 0 or source_offset >= loaded:
        return None
    return {
        "matched": True,
        "confidence": confidence,
        "rule": rule,
        "slot_id": slot.get("id"),
        "slot_name": slot.get("name", ""),
        "file": slot.get("path", ""),
        "slot_address": slot.get("address", 0),
        "slot_loaded_bytes": loaded,
        "slot_crc": slot.get("crc"),
        "slot_checksum_fnv1a64": slot.get("checksum_fnv1a64"),
        "source_offset": source_offset,
        "source_offset_hex": f"0x{source_offset:08x}",
        "first_addr": first_addr,
        "byte_address": byte_address,
    }


def attribute_memory_address(first_addr: int, result: dict[str, Any]) -> dict[str, Any]:
    """Best-effort mapping from a model address to a loaded data-slot offset.

    External RAM models often report controller word addresses while APF data
    slots report bridge byte addresses. The attribution therefore records the
    rule and confidence instead of pretending every family uses the same map.
    """
    slots = loaded_slot_candidates(result)
    matches: list[dict[str, Any]] = []
    for slot in slots:
        address = _as_int(slot.get("address"), 0)
        has_address = bool(slot.get("has_address"))
        if has_address:
            byte_address = first_addr
            match = _slot_match(slot, byte_address - address, "byte_address_matches_bridge_range", 0.9, first_addr, byte_address)
            if match:
                matches.append(match)
            byte_address = first_addr * 2
            match = _slot_match(slot, byte_address - address, "word_address_matches_bridge_range", 0.86, first_addr, byte_address)
            if match:
                matches.append(match)

        match = _slot_match(slot, first_addr * 2, "word_offset_from_slot_start", 0.74, first_addr, first_addr * 2)
        if match:
            matches.append(match)
        match = _slot_match(slot, first_addr, "byte_offset_from_slot_start", 0.64, first_addr, first_addr)
        if match:
            matches.append(match)

    if not matches:
        return {
            "matched": False,
            "first_addr": first_addr,
            "byte_address": first_addr * 2,
            "source_candidates": slots,
        }

    if len(slots) == 1:
        for match in matches:
            if match["rule"] == "word_offset_from_slot_start":
                match["confidence"] = max(match["confidence"], 0.84)
                match["rule"] += "_single_loaded_slot"
            elif match["rule"] == "byte_offset_from_slot_start":
                match["confidence"] = max(match["confidence"], 0.80)
                match["rule"] += "_single_loaded_slot"

    matches.sort(key=lambda item: (-float(item.get("confidence", 0.0)), str(item.get("slot_id")), int(item.get("source_offset", 0))))
    best = dict(matches[0])
    best["source_candidates"] = matches[:5]
    return best


def _event(
    *,
    code: str,
    counter: str,
    count: int,
    first_addr: int,
    class_name: str,
    result: dict[str, Any],
    severity: str,
    expected_word: int | None = None,
    actual_word: int | None = None,
    dqm: int | None = None,
) -> dict[str, Any]:
    source = attribute_memory_address(first_addr, result)
    source_offset = source.get("source_offset") if source.get("matched") else None
    lanes = byte_lanes_from_dqm(dqm if dqm is not None else 3, source_offset if isinstance(source_offset, int) else None)
    doc: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "counter": counter,
        "count": count,
        "class": class_name,
        "first_addr": first_addr,
        "first_addr_hex": f"0x{first_addr:08x}",
        "bank": first_addr >> 22,
        "byte_address": first_addr * 2,
        "byte_address_hex": f"0x{first_addr * 2:08x}",
        "address_unit": "word",
        "byte_lanes": lanes,
        "source": source,
        "source_slot_candidates": loaded_slot_candidates(result),
    }
    if expected_word is not None:
        doc["expected_word"] = expected_word
        doc["expected_word_hex"] = f"0x{expected_word & 0xffff:04x}"
    if actual_word is not None:
        doc["actual_word"] = actual_word
        doc["actual_word_hex"] = f"0x{actual_word & 0xffff:04x}"
    if dqm is not None:
        doc["dqm"] = dqm
    return doc


def build_rom_validation(memory_activity: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    counters = [item for item in _list(memory_activity.get("counters")) if isinstance(item, dict)]
    events: list[dict[str, Any]] = []

    mismatch_count = counter_value(counters, "sdram_rom_mismatch_count")
    if mismatch_count > 0:
        events.append(_event(
            code="MEMORY_ROM_WRITE_MISMATCH",
            counter="sdram_rom_mismatch_count",
            count=mismatch_count,
            first_addr=counter_value(counters, "sdram_first_rom_mismatch_addr"),
            class_name="sdram",
            result=result,
            severity="error",
            expected_word=counter_value(counters, "sdram_first_rom_mismatch_expected"),
            actual_word=counter_value(counters, "sdram_first_rom_mismatch_actual"),
            dqm=counter_value(counters, "sdram_first_rom_mismatch_dqm", 3),
        ))

    unwritten_count = counter_value(counters, "sdram_rom_unwritten_read_count")
    if unwritten_count > 0:
        events.append(_event(
            code="MEMORY_UNINITIALIZED_READ",
            counter="sdram_rom_unwritten_read_count",
            count=unwritten_count,
            first_addr=counter_value(counters, "sdram_first_rom_unwritten_read_addr"),
            class_name="sdram",
            result=result,
            severity="error",
            expected_word=counter_value(counters, "sdram_first_rom_unwritten_expected"),
            dqm=counter_value(counters, "sdram_first_rom_unwritten_dqm", 3),
        ))

    coverage_gap_count = counter_value(counters, "sdram_rom_coverage_gap_count")
    if coverage_gap_count > 0:
        events.append(_event(
            code="MEMORY_ROM_COVERAGE_GAP",
            counter="sdram_rom_coverage_gap_count",
            count=coverage_gap_count,
            first_addr=counter_value(counters, "sdram_first_coverage_gap_addr"),
            class_name="sdram",
            result=result,
            severity="warning",
        ))

    first_error = next((event for event in events if event.get("severity") == "error"), None)
    return {
        "schema": ROM_EVENT_SCHEMA,
        "events": events,
        "first_error": first_error or (events[0] if events else None),
    }


def event_for_code(memory_activity: dict[str, Any], result: dict[str, Any], code: str, counter: str = "") -> dict[str, Any]:
    validation = _obj(memory_activity.get("rom_validation"))
    if not validation:
        validation = build_rom_validation(memory_activity, result)
    for event in _list(validation.get("events")):
        if not isinstance(event, dict):
            continue
        if event.get("code") != code:
            continue
        if counter and event.get("counter") != counter:
            continue
        return event
    return {}
