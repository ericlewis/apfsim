#!/usr/bin/env python3
"""Build a machine-readable source contract for APF bring-up intake."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core_discovery import find_slot_objects, inspect_core, read_json
from profile_generator import (
    filter_hdl_paths,
    hdl_paths,
    normalize_profile_name,
    parse_qsf_project,
    qsf_report,
    select_qsf,
)
from wrapper_synthesizer import (
    ModuleInfo,
    build_synthesis_report,
    choose_top,
    module_score,
    norm,
    parse_modules,
)

SCHEMA = "apfsim.source_contract.v1"

PORT_GROUPS: dict[str, list[str]] = {
    "clock": ["clk_74a", "clk_74b", "clk", "clock", "refclk", "pclk", "pixel_clk", "video_clk"],
    "reset": ["reset", "reset_n", "rst", "rst_n", "reset_l", "rst_l"],
    "bridge": ["bridge_addr", "bridge_rd", "bridge_wr", "bridge_wr_data", "bridge_rd_data", "ioctl_download", "ioctl_wr"],
    "video": ["video_rgb", "vid_rgb", "vga_r", "vga_g", "vga_b", "hblank", "vblank", "lhbl", "lvbl", "hsync", "vsync", "de"],
    "audio": ["audio_mclk", "audio_lrck", "audio_dac", "aud_mclk", "aud_lrck", "aud_dac", "audio_l", "audio_r"],
    "input": ["cont1_key", "cont2_key", "joystick", "buttons", "coin", "start", "p1", "p2"],
    "memory": ["sdram", "sram", "psram", "cram", "ddr", "dram"],
}


def build_source_contract(
    root: Path,
    *,
    output_dir: Path | None = None,
    profile_name: str | None = None,
    source_top: str | None = None,
) -> dict[str, Any]:
    root = root.expanduser().resolve()
    name = profile_name or normalize_profile_name(root.name)
    inv = inspect_core(root, source_root=str(root.parent), profile_by_root={})
    qsf_project = parse_qsf_project(select_qsf(root, inv))
    sources = qsf_project.sources if qsf_project.sources else hdl_paths(root)
    sources, skipped_sources = filter_hdl_paths(sources)
    modules = parse_modules(sources)
    selected = choose_top(modules, explicit=source_top, qsf_top=qsf_project.top_level_entity)
    synthesis = build_synthesis_report(selected, modules)
    blockers = intake_blockers(inv, qsf_project, modules, selected, synthesis)
    classification = classify_source(inv, selected, synthesis, blockers)

    contract: dict[str, Any] = {
        "schema": SCHEMA,
        "profile": name,
        "root": str(root),
        "classification": classification,
        "top": top_report(root, modules, selected, source_top, qsf_project.top_level_entity),
        "ports": port_report(selected, synthesis, inv),
        "sources": source_report(root, inv, qsf_project, sources, skipped_sources),
        "metadata": metadata_report(root, inv),
        "memory": inv.memory,
        "blockers": blockers,
        "recommendations": recommendations(classification, blockers),
        "qsf": qsf_report(qsf_project),
    }
    if output_dir:
        output_dir = output_dir.expanduser().resolve()
        contract["paths"] = {
            "contract": str(output_dir / "source_contract.json"),
            "markdown": str(output_dir / "source_contract.md"),
        }
    return contract


def write_source_contract(contract: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "source_contract.json"
    md_path = output_dir / "source_contract.md"
    contract = dict(contract)
    contract["paths"] = {
        "contract": str(json_path),
        "markdown": str(md_path),
    }
    json_path.write_text(json.dumps(contract, indent=2) + "\n")
    md_path.write_text(render_markdown(contract))
    return json_path, md_path


def intake_blockers(inv: Any, qsf_project: Any, modules: dict[str, ModuleInfo], selected: ModuleInfo | None, synthesis: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if selected is None:
        blockers.append(blocker("SOURCE_TOP_MISSING", "No Verilog/SystemVerilog module could be selected for APF wrapper or profile generation.", "error"))
    elif qsf_project.top_level_entity and qsf_project.top_level_entity not in modules:
        blockers.append(blocker("TOP_LEVEL_ENTITY_MISSING", f"QSF top {qsf_project.top_level_entity} was not found in parsed Verilog/SystemVerilog sources.", "error"))
    elif qsf_project.top_level_entity and selected.name != qsf_project.top_level_entity:
        blockers.append(blocker(
            "TOP_LEVEL_ENTITY_NOT_SELECTED",
            f"QSF top is {qsf_project.top_level_entity}, but intake selected {selected.name}.",
            "warning",
            evidence={"qsf_top": qsf_project.top_level_entity, "selected_top": selected.name},
        ))
    for path in qsf_project.missing_sources[:20]:
        blockers.append(blocker("SOURCE_FILE_MISSING", "QSF references a source file that does not exist.", "error", evidence={"path": str(path)}))
    if qsf_project.vhdl_files or inv.vhdl_files:
        blockers.append(blocker(
            "VHDL_ENTITY_PRESENT",
            "VHDL sources are present; public Verilator bring-up needs a translation, faithful model, or explicitly marked stub.",
            "error",
            evidence={"qsf_vhdl_files": [str(path) for path in qsf_project.vhdl_files[:20]], "vhdl_file_count": inv.vhdl_files},
        ))
    for risk in inv.memory.get("risks", []):
        code = str(risk.get("code") or "MEMORY_MODEL_REQUIRED")
        severity = str(risk.get("severity") or "error")
        if severity == "error":
            blockers.append(blocker("MEMORY_MODEL_REQUIRED", str(risk.get("message") or "External memory model is required."), severity, evidence={"specific_code": code}))
        blockers.append(blocker(code, str(risk.get("message") or code), severity))
    if inv.uses_pll or inv.uses_altsyncram or inv.uses_dcfifo or inv.qip_files:
        evidence = {
            "uses_pll": inv.uses_pll,
            "uses_altsyncram": inv.uses_altsyncram,
            "uses_dcfifo": inv.uses_dcfifo,
            "qip_files": inv.qip_files,
        }
        blockers.append(blocker("SHIM_REQUIRED", "Vendor/IP primitives or QIP-managed sources are present; shim catalog resolution is required.", "warning", evidence=evidence))
    for item in synthesis.get("blockers", []):
        blockers.append(blocker(str(item.get("code")), str(item.get("message")), "error"))
    if not inv.core_jsons:
        blockers.append(blocker("PACKAGE_METADATA_MISSING", "No core.json was found under a recognized APF package tree.", "warning", evidence={"file": "core.json"}))
    if not inv.video_jsons:
        blockers.append(blocker("PACKAGE_METADATA_MISSING", "No video.json was found under a recognized APF package tree.", "warning", evidence={"file": "video.json"}))
    if inv.data_slot_count and inv.asset_file_count == 0:
        blockers.append(blocker("DATA_SLOT_PAYLOAD_MISSING", "data.json declares slots but no local dist/Assets payloads were found.", "warning"))
    return dedupe_blockers(blockers)


def blocker(code: str, message: str, severity: str = "error", *, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if evidence:
        out["evidence"] = evidence
    return out


def dedupe_blockers(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (str(item.get("code")), str(item.get("message")))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def classify_source(inv: Any, selected: ModuleInfo | None, synthesis: dict[str, Any], blockers: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: list[str] = []
    severe = {str(item.get("code")) for item in blockers if item.get("severity") == "error"}
    has_bridge = any(item.get("apf_signal") == "bridge_rd_data" for item in synthesis.get("mappings", []))
    has_video = not any(str(item.get("code", "")).startswith("VIDEO_") for item in synthesis.get("blockers", []))
    has_apf_top = len(inv.missing_apf_ports) <= 4
    if selected is None:
        mode = "architecture-block"
        confidence = 0.05
        reasons.append("No selectable Verilog/SystemVerilog top was found.")
    elif has_apf_top and has_bridge and has_video:
        mode = "direct-mode"
        confidence = 0.85
        reasons.append("Selected top already exposes most APF-facing ports.")
    elif "VHDL_ENTITY_PRESENT" in severe or "MEMORY_MODEL_REQUIRED" in severe:
        mode = "family-specific"
        confidence = 0.68
        reasons.append("Core depends on family/device behavior that should be modeled rather than stubbed.")
    elif has_video:
        mode = "shell-mode"
        confidence = 0.72
        reasons.append("Selected top exposes video-like outputs but needs an APF shell/wrapper.")
    else:
        mode = "architecture-block"
        confidence = 0.35
        reasons.append("Selected top is present, but APF video/bridge surfaces are not inferable.")
    if inv.vhdl_files:
        reasons.append(f"{inv.vhdl_files} VHDL source file(s) present.")
    if inv.memory.get("external_classes"):
        reasons.append("External memory classes detected: " + ", ".join(inv.memory.get("external_classes", [])))
    return {
        "mode": mode,
        "confidence": round(confidence, 3),
        "status": "blocked" if any(item.get("severity") == "error" for item in blockers) else "ready",
        "reasons": reasons,
    }


def top_report(root: Path, modules: dict[str, ModuleInfo], selected: ModuleInfo | None, explicit: str | None, qsf_top: str | None) -> dict[str, Any]:
    candidates = sorted(modules.values(), key=lambda module: (-module_score(module), module.name))[:25]
    return {
        "selected": selected.name if selected else "",
        "selected_source": rel(root, selected.path) if selected else "",
        "explicit": explicit or "",
        "qsf_top": qsf_top or "",
        "module_count": len(modules),
        "candidates": [
            {
                "module": module.name,
                "source": rel(root, module.path),
                "score": module_score(module),
                "port_count": len(module.ports),
                "signals": module_signal_groups(module),
            }
            for module in candidates
        ],
    }


def module_signal_groups(module: ModuleInfo) -> list[str]:
    names = {norm(name) for name in module.ports}
    groups = []
    for group, candidates in PORT_GROUPS.items():
        if any(norm(candidate) in names or any(norm(candidate) in name for name in names) for candidate in candidates):
            groups.append(group)
    return groups


def port_report(selected: ModuleInfo | None, synthesis: dict[str, Any], inv: Any) -> dict[str, Any]:
    source_ports = synthesis.get("source_ports", [])
    return {
        "apf_ports_present": inv.apf_ports,
        "apf_ports_missing": inv.missing_apf_ports,
        "source_ports": source_ports,
        "source_port_count": len(source_ports),
        "candidates": collect_port_candidates(selected),
        "wrapper_mappings": synthesis.get("mappings", []),
        "wrapper_blockers": synthesis.get("blockers", []),
    }


def collect_port_candidates(selected: ModuleInfo | None) -> dict[str, list[dict[str, str]]]:
    if selected is None:
        return {group: [] for group in PORT_GROUPS}
    out: dict[str, list[dict[str, str]]] = {}
    for group, candidates in PORT_GROUPS.items():
        group_items = []
        candidate_norms = [norm(item) for item in candidates]
        for port in selected.ports.values():
            port_norm = norm(port.name)
            if any(candidate in port_norm or port_norm in candidate for candidate in candidate_norms):
                group_items.append({"name": port.name, "direction": port.direction, "width": port.width})
        out[group] = group_items
    return out


def source_report(root: Path, inv: Any, qsf_project: Any, sources: list[Path], skipped_sources: list[Path]) -> dict[str, Any]:
    return {
        "counts": {
            "sv": inv.sv_files,
            "v": inv.v_files,
            "vhdl": inv.vhdl_files,
            "qip": inv.qip_files,
        },
        "source_files": [rel(root, path) for path in sources[:300]],
        "source_file_count": len(sources),
        "skipped_sources": [rel(root, path) for path in skipped_sources[:100]],
        "missing_sources": [str(path) for path in qsf_project.missing_sources[:100]],
        "vhdl_files": [rel(root, path) for path in qsf_project.vhdl_files[:100]],
        "qip_files": [rel(root, path) for path in qsf_project.qip_files[:100]],
    }


def metadata_report(root: Path, inv: Any) -> dict[str, Any]:
    slots: list[dict[str, Any]] = []
    for data_json in inv.data_jsons:
        data = read_json(root / data_json)
        for slot in find_slot_objects(data):
            slots.append({
                "id": int_value(slot.get("id") if "id" in slot else slot.get("slot")),
                "name": str(slot.get("name") or ""),
                "filename": str(slot.get("filename") or ""),
                "address": string_or_none(slot.get("address") if "address" in slot else slot.get("loadaddress")),
                "required": bool(slot.get("required", True)),
                "nonvolatile": bool(slot.get("nonvolatile") or slot.get("save") or slot.get("savefile")),
                "deferload": bool(slot.get("deferload") or slot.get("deferred") or slot.get("defer")),
                "parameters": string_or_none(slot.get("parameters")),
            })
    return {
        "core_ids": inv.core_ids,
        "core_jsons": inv.core_jsons,
        "data_jsons": inv.data_jsons,
        "input_jsons": inv.input_jsons,
        "interact_jsons": inv.interact_jsons,
        "video_jsons": inv.video_jsons,
        "asset_dirs": inv.asset_dirs,
        "asset_file_count": inv.asset_file_count,
        "video_modes": inv.video_modes,
        "data_slots": slots,
        "data_slot_count": inv.data_slot_count,
        "required_slot_count": inv.required_slot_count,
        "nonvolatile_slot_count": inv.nonvolatile_slot_count,
        "deferred_slot_count": inv.deferred_slot_count,
    }


def recommendations(classification: dict[str, Any], blockers: list[dict[str, Any]]) -> list[dict[str, str]]:
    codes = {str(item.get("code")) for item in blockers}
    out: list[dict[str, str]] = []
    mode = str(classification.get("mode"))
    if mode == "shell-mode":
        out.append({"action": "synth-wrapper", "message": "Run or review apfsim synth-wrapper; selected top appears wrapper-adaptable."})
    if "MEMORY_MODEL_REQUIRED" in codes:
        out.append({"action": "memory-model", "message": "Select or implement an external RAM model before interpreting ROM/video failures."})
    if "VHDL_ENTITY_PRESENT" in codes:
        out.append({"action": "vhdl-strategy", "message": "Choose a public Verilator-compatible translation/model strategy for VHDL entities."})
    if "BRIDGE_MAPPING_MISSING" in codes:
        out.append({"action": "bridge-adapter", "message": "Add or synthesize an APF bridge adapter; boot lifecycle cannot be certified without bridge read/write behavior."})
    if "VIDEO_DE_MAPPING_MISSING" in codes or "VIDEO_RGB_MAPPING_MISSING" in codes:
        out.append({"action": "video-adapter", "message": "Map source blanking/RGB signals to APF video_de/video_rgb before video-shape discovery."})
    if not out:
        out.append({"action": "generate-profile", "message": "Generate a profile and run lint/build preflight."})
    return out


def render_markdown(contract: dict[str, Any]) -> str:
    classification = contract.get("classification", {})
    lines = [
        f"# APFSIM Source Contract: {contract.get('profile', '')}",
        "",
        f"- Root: `{contract.get('root', '')}`",
        f"- Mode: `{classification.get('mode', '')}`",
        f"- Status: `{classification.get('status', '')}`",
        f"- Confidence: `{classification.get('confidence', 0)}`",
        f"- Selected top: `{contract.get('top', {}).get('selected', '')}`",
        "",
        "## Reasons",
        "",
    ]
    for reason in classification.get("reasons", []):
        lines.append(f"- {reason}")
    lines.extend(["", "## Blocking / Risk Codes", ""])
    for item in contract.get("blockers", []):
        lines.append(f"- `{item.get('severity', '')}` `{item.get('code', '')}`: {item.get('message', '')}")
    lines.extend(["", "## Recommendations", ""])
    for item in contract.get("recommendations", []):
        lines.append(f"- `{item.get('action', '')}`: {item.get('message', '')}")
    lines.extend(["", "## Source Summary", ""])
    sources = contract.get("sources", {})
    counts = sources.get("counts", {})
    lines.append(f"- HDL counts: sv={counts.get('sv', 0)} v={counts.get('v', 0)} vhdl={counts.get('vhdl', 0)} qip={counts.get('qip', 0)}")
    memory = contract.get("memory", {})
    lines.append(f"- Memory classes: {', '.join(memory.get('classes', [])) or '-'}")
    metadata = contract.get("metadata", {})
    lines.append(f"- Core IDs: {', '.join(metadata.get('core_ids', [])) or '-'}")
    lines.append(f"- Video modes: {', '.join(metadata.get('video_modes', [])) or '-'}")
    lines.append(f"- Data slots: {metadata.get('data_slot_count', 0)}")
    lines.append("")
    return "\n".join(lines)


def int_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return None
    return None


def string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.expanduser().resolve().relative_to(root.expanduser().resolve()))
    except ValueError:
        return str(path)
