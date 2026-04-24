#!/usr/bin/env python3
"""Generate reviewable apfsim profile candidates from a Pocket core checkout."""

from __future__ import annotations

import json
import os
import re
import shlex
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core_discovery import find_slot_objects, find_video_modes, inspect_core
from memory_wrapper import memory_wrapper_plan, render_memory_wrapper_sv

RTL_EXTS = {".v", ".sv"}
INCLUDE_EXTS = {".v", ".sv", ".vh", ".svh"}
COMMON_SHIMS = [
    "rtl_shims/mf_pllbase_sim.sv",
    "rtl_shims/altsyncram_sim.sv",
    "rtl_shims/dcfifo_sim.sv",
    "rtl_shims/vendor_ip_stubs.sv",
]
OPTIONAL_SHIMS = {
    "dpram": "rtl_shims/dpram_sim.sv",
    "sdram": "rtl_shims/sdram_sim.sv",
}
SKIP_FILE_RE = re.compile(
    r"(^|/)(apf_top|io_bridge_peripheral|io_pad_controller|pin_ddio_clk|mf_ddio|mf_pllbase|altpll|altsyncram|dcfifo)[^/]*\.(v|sv)$",
    re.IGNORECASE,
)
FRAMEWORK_PRIORITY = {
    "common.v": 0,
    "mf_datatable.v": 1,
    "core_bridge_cmd.v": 2,
    "data_loader.sv": 3,
    "data_unloader.sv": 4,
    "sync_fifo.sv": 5,
    "sound_i2s.sv": 6,
}
QSF_RTL_ASSIGNMENTS = {"VERILOG_FILE", "SYSTEMVERILOG_FILE"}
QSF_VHDL_ASSIGNMENTS = {"VHDL_FILE"}
QSF_INCLUDE_ASSIGNMENTS = {"SEARCH_PATH", "USER_LIBRARIES"}
QSF_DEFINE_ASSIGNMENTS = {
    "VERILOG_MACRO",
    "SYSTEMVERILOG_MACRO",
    "VERILOG_DEFINE",
    "SYSTEMVERILOG_DEFINE",
}
QSF_TOP_ASSIGNMENTS = {"TOP_LEVEL_ENTITY"}
MEMORY_REQUIRED_RISK_BY_CLASS = {
    "ddr": "MEMORY_MODEL_REQUIRED",
    "psram": "PSRAM_MODEL_REQUIRED",
    "cram": "CRAM_MODEL_REQUIRED",
    "sram": "SRAM_MODEL_REQUIRED",
}


@dataclass
class QsfProject:
    path: Path | None = None
    top_level_entity: str = ""
    sources: list[Path] = field(default_factory=list)
    include_dirs: list[Path] = field(default_factory=list)
    defines: list[str] = field(default_factory=list)
    vhdl_files: list[Path] = field(default_factory=list)
    qip_files: list[Path] = field(default_factory=list)
    missing_sources: list[Path] = field(default_factory=list)


@dataclass
class GeneratedProfile:
    profile_name: str
    root: Path
    output_dir: Path
    profile_path: Path
    filelist_path: Path
    scenario_path: Path
    notes_path: Path
    report_path: Path
    selected_shims: list[str] = field(default_factory=list)
    selected_shim_details: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    profile: dict[str, Any] = field(default_factory=dict)
    qsf: dict[str, Any] | None = None


def generate_profile_candidate(
    root: Path,
    output_dir: Path,
    *,
    apfsim_dir: Path,
    profile_name: str | None = None,
    catalog_path: Path | None = None,
    force: bool = False,
) -> GeneratedProfile:
    root = root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    inv = inspect_core(root, source_root=str(root.parent), profile_by_root={})
    name = profile_name or normalize_profile_name(root.name)
    profile_dir = output_dir / name
    profile_path = profile_dir / f"{name}.json"
    filelist_path = profile_dir / "filelist.f"
    scenario_path = profile_dir / "scenario.yml"
    notes_path = profile_dir / "NOTES.md"
    report_path = profile_dir / "candidate.json"
    if profile_dir.exists() and any(profile_dir.iterdir()) and not force:
        raise FileExistsError(f"output directory already exists: {profile_dir}")
    profile_dir.mkdir(parents=True, exist_ok=True)

    qsf_project = parse_qsf_project(select_qsf(root, inv))
    catalog = load_catalog(catalog_path or apfsim_dir / "catalogs" / "shims.json")
    selected_shims = select_shims(root, inv, catalog, qsf_project)
    selected_shim_details = shim_detail_records(selected_shims, catalog, root, apfsim_dir, name)
    generated_paths = generated_filelist_entries(selected_shims, catalog, root, apfsim_dir, name)
    memory = memory_with_catalog_models(inv.memory, selected_shims, catalog)
    memory_wrapper = memory_wrapper_plan(memory)
    wrapper_generation: dict[str, Any] = {}
    if memory_wrapper.get("generated"):
        generated_paths.append(str(memory_wrapper["path"]))
        wrapper_module = f"apfsim_{name}_memory_models"
        (profile_dir / "apfsim_memory_models.sv").write_text(
            render_memory_wrapper_sv(memory, module_name=wrapper_module)
        )
        memory_wrapper["module_name"] = wrapper_module
        wrapper_generation["memory_models"] = memory_wrapper
    excluded_sources = generated_source_paths(selected_shims, catalog, root, apfsim_dir, name)
    jtframe_wrapper = maybe_generate_jtframe_pocket_wrapper(qsf_project, profile_dir)
    if jtframe_wrapper:
        generated_paths.append(str(jtframe_wrapper["path"]))
        wrapper_generation["jtframe_pocket_logical_wrapper"] = jtframe_wrapper
        for source in jtframe_wrapper.get("replaced_sources", []):
            excluded_sources.add(Path(str(source)).expanduser().resolve())
    filelist_lines = build_filelist(root, inv, generated_paths, excluded_sources, qsf_project, apfsim_dir)
    filelist_path.write_text("\n".join(filelist_lines) + "\n")

    data_json = first_existing(root, inv.data_jsons)
    video_json = first_existing(root, inv.video_jsons)
    interact_json = first_existing(root, inv.interact_jsons)
    scenario, scenario_warnings = build_scenario(root, data_json, video_json, apfsim_dir, name)
    scenario_path.write_text(scenario)

    top_module = str(jtframe_wrapper.get("top", "")) if jtframe_wrapper else (qsf_project.top_level_entity or "core_top")
    required_paths = [placeholderize_path(root / rel, root, apfsim_dir) for rel in inv.top_files[:1]]
    top_source = find_module_source(qsf_project.sources, top_module)
    if top_source:
        required_paths.append(placeholderize_path(top_source, root, apfsim_dir))
    for metadata in [data_json, video_json, interact_json]:
        if metadata:
            required_paths.append(placeholderize_path(metadata, root, apfsim_dir))
    required_paths.extend(placeholderize_value(path, root, apfsim_dir) for path in required_paths_for_shims(selected_shims, catalog, root, apfsim_dir, name))
    if memory_wrapper.get("generated"):
        required_paths.append(str(memory_wrapper["path"]))
    if jtframe_wrapper:
        required_paths.append(str(jtframe_wrapper["path"]))
    required_paths = dedupe(required_paths)

    profile: dict[str, Any] = {
        "name": name,
        "description": f"Generated candidate profile for {root.name}; review before committing.",
        "external": True,
        "root_env": f"{env_prefix(name)}_ROOT",
        "top": top_module,
        "filelist": "{profile_dir}/filelist.f",
        "scenario": "{profile_dir}/scenario.yml",
        "metadata_jsons": {},
        "frames": 12,
        "timeout_cycles": 50000000,
        "write_idle_cycles": 64,
        "build_dir": f"build/generated-profiles/{name}/obj",
        "artifact_root": f"output/generated-profiles/{name}/run",
        "required_paths": required_paths,
        "expected_artifacts": [
            "result.json",
            "video_shape.json",
            "lifecycle.json",
            "bridge.log",
            "video/frame_000001.json",
            "audio/out.wav",
            "audio/stats.json",
        ],
    }
    if selected_shims:
        profile["shim_catalog"] = selected_shims
    if memory.get("required"):
        profile["memory"] = memory
    if wrapper_generation:
        profile["wrapper_generation"] = wrapper_generation
    risks = profile_risks(inv, selected_shims, qsf_project)
    if risks:
        profile["risks"] = risks
    profile_sources = qsf_project.sources if qsf_project.sources else hdl_paths(root)
    if any(path.suffix == ".sv" for path in profile_sources):
        profile["verilator_flags"] = ["--sv"]
    if data_json:
        profile["metadata_jsons"]["data"] = placeholderize_path(data_json, root, apfsim_dir)
    if video_json:
        profile["metadata_jsons"]["video"] = placeholderize_path(video_json, root, apfsim_dir)
    if interact_json:
        profile["metadata_jsons"]["interact"] = placeholderize_path(interact_json, root, apfsim_dir)
    if not profile["metadata_jsons"]:
        profile.pop("metadata_jsons")

    warnings = scenario_warnings + generation_warnings(inv, selected_shims, filelist_lines, qsf_project, excluded_sources, memory, top_module)
    profile_path.write_text(json.dumps(profile, indent=2) + "\n")
    notes_path.write_text(render_notes(inv, profile, selected_shim_details, warnings, profile_path, filelist_path, scenario_path, qsf_project, excluded_sources))
    qsf_payload = qsf_report(qsf_project, excluded_sources)
    report = {
        "schema": "apfsim.generated_profile.v1",
        "profile": name,
        "root": str(root),
        "status": inv.status,
        "action": inv.action,
        "selected_shims": selected_shims,
        "selected_shim_details": selected_shim_details,
        "wrapper_generation": wrapper_generation,
        "risks": risks,
        "paths": {
            "profile": str(profile_path),
            "filelist": str(filelist_path),
            "scenario": str(scenario_path),
            "notes": str(notes_path),
        },
        "warnings": warnings,
        "memory": memory,
        "qsf": qsf_payload,
        "inventory": inv.__dict__,
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return GeneratedProfile(
        profile_name=name,
        root=root,
        output_dir=profile_dir,
        profile_path=profile_path,
        filelist_path=filelist_path,
        scenario_path=scenario_path,
        notes_path=notes_path,
        report_path=report_path,
        selected_shims=selected_shims,
        selected_shim_details=selected_shim_details,
        risks=risks,
        warnings=warnings,
        profile=profile,
        qsf=qsf_payload,
    )


def normalize_profile_name(name: str) -> str:
    text = name
    text = re.sub(r"^openFPGA[-_]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text or "generated_core"


def env_prefix(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper() or "APFSIM_CORE"


def load_catalog(path: Path) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    entries = data.get("entries", []) if isinstance(data, dict) else []
    return {str(entry.get("name")): entry for entry in entries if isinstance(entry, dict) and entry.get("name")}


def select_shims(root: Path, inv: Any, catalog: dict[str, dict[str, Any]], qsf_project: QsfProject | None = None) -> list[str]:
    selected: list[str] = []
    source_paths = qsf_project.sources if qsf_project and qsf_project.sources else None
    for name, entry in catalog.items():
        if catalog_entry_matches(root, inv, entry, source_paths):
            selected.append(name)
    return dedupe(selected)


def catalog_entry_matches(root: Path, inv: Any, entry: dict[str, Any], source_paths: list[Path] | None = None) -> bool:
    detect = entry.get("detect", {})
    if not isinstance(detect, dict):
        return False

    for flag in detect.get("inventory_flags", []):
        if bool(getattr(inv, str(flag), False)):
            return True

    wanted_memory = {str(item) for item in detect.get("memory_classes", [])}
    if wanted_memory and wanted_memory.intersection(str(item) for item in getattr(inv, "memory_classes", [])):
        return True

    patterns = [str(item) for item in detect.get("source_patterns", [])]
    if patterns and source_patterns_match(root, patterns, source_paths):
        return True

    return False


def source_patterns_match(root: Path, patterns: list[str], source_paths: list[Path] | None = None) -> bool:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error:
            continue
    if not compiled:
        return False
    paths = source_paths if source_paths is not None else hdl_paths(root)
    for path in paths[:500]:
        try:
            text = path.read_text(errors="ignore")[:200000]
        except OSError:
            continue
        if any(pattern.search(text) for pattern in compiled):
            return True
    return False


def shim_detail_records(
    selected: list[str],
    catalog: dict[str, dict[str, Any]],
    root: Path,
    apfsim_dir: Path,
    profile_name: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for name in selected:
        entry = catalog.get(name, {})
        catalog_source = select_catalog_source(entry, root)
        fallback_used = not bool(catalog_source) and bool(entry.get("fallback_filelist_entries") or entry.get("fallback_required_paths"))
        context = {"catalog_source": catalog_source, "profile": profile_name}
        filelist_entries = [
            filelist_entry_text(expand_template(str(value), root, apfsim_dir, context), root, apfsim_dir)
            for value in selected_filelist_templates(entry, bool(catalog_source))
        ]
        records.append({
            "name": name,
            "description": str(entry.get("description", "")),
            "kind": str(entry.get("kind", "")),
            "confidence": str(entry.get("confidence", "")),
            "modules": [str(item) for item in entry.get("modules", [])],
            "memory_classes": [str(item) for item in entry.get("memory_classes", [])],
            "diagnostic_codes": [str(item) for item in entry.get("diagnostic_codes", [])],
            "catalog_source": catalog_source,
            "fallback_used": fallback_used,
            "filelist_entries": dedupe(filelist_entries),
        })
    return records


def generated_filelist_entries(selected: list[str], catalog: dict[str, dict[str, Any]], root: Path, apfsim_dir: Path, profile_name: str) -> list[str]:
    out: list[str] = []
    for name in selected:
        entry = catalog.get(name, {})
        catalog_source = select_catalog_source(entry, root)
        context = {"catalog_source": catalog_source, "profile": profile_name}
        for value in selected_filelist_templates(entry, bool(catalog_source)):
            expanded = expand_template(str(value), root, apfsim_dir, context)
            if expanded:
                out.append(filelist_entry_text(expanded, root, apfsim_dir))
        for item in entry.get("generated_files", []):
            if isinstance(item, dict) and item.get("dest"):
                out.append(relative_to_apfsim(expand_template(str(item["dest"]), root, apfsim_dir, context), apfsim_dir))
    return dedupe(out)


def generated_source_paths(selected: list[str], catalog: dict[str, dict[str, Any]], root: Path, apfsim_dir: Path, profile_name: str) -> set[Path]:
    out: set[Path] = set()
    for name in selected:
        entry = catalog.get(name, {})
        context = {"catalog_source": select_catalog_source(entry, root), "profile": profile_name}
        for item in entry.get("generated_files", []):
            if isinstance(item, dict) and item.get("source"):
                source = Path(expand_template(str(item["source"]), root, apfsim_dir, context))
                out.add(source.expanduser().resolve())
    return out


def required_paths_for_shims(selected: list[str], catalog: dict[str, dict[str, Any]], root: Path, apfsim_dir: Path, profile_name: str) -> list[str]:
    out: list[str] = []
    for name in selected:
        entry = catalog.get(name, {})
        catalog_source = select_catalog_source(entry, root)
        context = {"catalog_source": catalog_source, "profile": profile_name}
        for value in selected_required_path_templates(entry, bool(catalog_source)):
            expanded = expand_template(str(value), root, apfsim_dir, context)
            if expanded:
                out.append(expanded)
    return out


def select_catalog_source(entry: dict[str, Any], root: Path) -> str:
    for candidate in entry.get("source_candidates", []):
        candidate_text = str(candidate)
        text = os.path.expanduser(os.path.expandvars(candidate_text.replace("{root}", str(root))))
        path = Path(text)
        if path.exists():
            return candidate_text
    return ""


def selected_filelist_templates(entry: dict[str, Any], has_catalog_source: bool) -> list[str]:
    if not has_catalog_source and entry.get("fallback_filelist_entries"):
        return [str(item) for item in entry.get("fallback_filelist_entries", [])]
    return [str(item) for item in entry.get("filelist_entries", [])]


def selected_required_path_templates(entry: dict[str, Any], has_catalog_source: bool) -> list[str]:
    if not has_catalog_source and entry.get("fallback_required_paths"):
        return [str(item) for item in entry.get("fallback_required_paths", [])]
    return [str(item) for item in entry.get("required_paths", [])]


def memory_with_catalog_models(memory: dict[str, Any], selected_shims: list[str], catalog: dict[str, dict[str, Any]]) -> dict[str, Any]:
    doc = deepcopy(memory if isinstance(memory, dict) else {})
    if not doc:
        return doc
    classes = {str(item) for item in doc.get("classes", [])}
    selected_models: list[dict[str, str]] = []
    covered_classes: set[str] = set()
    models = doc.setdefault("models", {})
    available = doc.get("available_models", {})
    for name in selected_shims:
        entry = catalog.get(name, {})
        for cls in [str(item) for item in entry.get("memory_classes", [])]:
            if cls not in classes:
                continue
            covered_classes.add(cls)
            matching = [
                item for item in available.get(cls, [])
                if isinstance(item, dict) and item.get("catalog_entry") == name
            ]
            if matching:
                model = dict(matching[0])
                models[cls] = {
                    "selected": str(model.get("model") or name),
                    "confidence": str(model.get("confidence") or entry.get("confidence") or "sim_only"),
                    "source": str(model.get("source") or ""),
                    "notes": f"Selected by shim catalog entry {name}.",
                }
                selected_models.append({
                    "class": cls,
                    "catalog_entry": name,
                    "model": str(model.get("model") or name),
                    "confidence": str(model.get("confidence") or entry.get("confidence") or "sim_only"),
                    "source": str(model.get("source") or ""),
                })
    if covered_classes:
        doc["selected_model_classes"] = sorted(covered_classes)
        doc["selected_models"] = selected_models
        removable = {
            code for cls, code in MEMORY_REQUIRED_RISK_BY_CLASS.items()
            if cls in covered_classes
        }
        doc["risks"] = [
            item for item in doc.get("risks", [])
            if not (isinstance(item, dict) and item.get("code") in removable)
        ]
    return doc


def expand_template(value: str, root: Path, apfsim_dir: Path, context: dict[str, str]) -> str:
    text = value.replace("{root}", str(root)).replace("{apfsim}", str(apfsim_dir))
    for key, item in context.items():
        text = text.replace("{" + key + "}", str(item))
    return os.path.expanduser(os.path.expandvars(text))


def relative_to_apfsim(value: str, apfsim_dir: Path) -> str:
    path = Path(value)
    try:
        return path.resolve().relative_to(apfsim_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def filelist_entry_text(value: str, root: Path, apfsim_dir: Path) -> str:
    path = Path(value)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(apfsim_dir.resolve()).as_posix()
        except ValueError:
            return placeholderize_path(path, root, apfsim_dir)
    return value


def placeholderize_value(value: str | Path, root: Path, apfsim_dir: Path) -> str:
    text = str(value)
    if "$" in text or "{" in text:
        return text
    return placeholderize_path(Path(text), root, apfsim_dir)


def placeholderize_path(path: Path, root: Path, apfsim_dir: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    resolved = path.expanduser().resolve()
    root_resolved = root.expanduser().resolve()
    apfsim_resolved = apfsim_dir.expanduser().resolve()
    try:
        return "{root}/" + resolved.relative_to(root_resolved).as_posix()
    except ValueError:
        pass
    try:
        return "{apfsim}/" + resolved.relative_to(apfsim_resolved).as_posix()
    except ValueError:
        return str(resolved)


def hdl_paths(root: Path, excluded: set[Path] | None = None) -> list[Path]:
    source_roots = [path for path in [root / "src/fpga/apf", root / "src/fpga/core", root / "src/core", root / "target/pocket"] if path.exists()]
    paths: list[Path] = []
    for source_root in source_roots:
        for path in source_root.rglob("*"):
            if path.is_file() and path.suffix.lower() in RTL_EXTS:
                paths.append(path)
    filtered, _ = filter_hdl_paths(sorted(dict.fromkeys(paths), key=file_order_key), excluded)
    return filtered


def select_qsf(root: Path, inv: Any) -> Path | None:
    candidates: list[Path] = []
    for rel in getattr(inv, "qsf_files", []) or []:
        path = Path(rel)
        candidates.append(path if path.is_absolute() else root / rel)
    candidates.extend([
        root / "src/fpga/ap_core.qsf",
        root / "src/fpga/pocket.qsf",
        root / "src/fpga/core.qsf",
    ])
    candidates.extend(sorted(root.glob("**/*.qsf")))
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists():
            return resolved
    return None


def parse_qsf_project(qsf_path: Path | None) -> QsfProject:
    project = QsfProject(path=qsf_path)
    if not qsf_path:
        return project
    parse_qsf_like_file(qsf_path, qsf_path.parent, project, set())
    project.sources = dedupe(project.sources)
    project.include_dirs = dedupe(project.include_dirs)
    project.defines = dedupe(project.defines)
    project.vhdl_files = dedupe(project.vhdl_files)
    project.qip_files = dedupe(project.qip_files)
    project.missing_sources = dedupe(project.missing_sources)
    return project


def parse_qsf_like_file(path: Path, base: Path, project: QsfProject, seen_qips: set[Path]) -> None:
    try:
        lines = path.read_text(errors="ignore").splitlines()
    except OSError:
        return project
    for raw in lines:
        assignment = parse_qsf_assignment(raw)
        if not assignment:
            continue
        name, value = assignment
        if name in QSF_TOP_ASSIGNMENTS:
            project.top_level_entity = value.strip('"')
        elif name in QSF_RTL_ASSIGNMENTS:
            path = resolve_qsf_path(base, value)
            project.sources.append(path)
            if not path.exists():
                project.missing_sources.append(path)
        elif name in QSF_VHDL_ASSIGNMENTS:
            project.vhdl_files.append(resolve_qsf_path(base, value))
        elif name == "QIP_FILE":
            qip = resolve_qsf_path(base, value)
            project.qip_files.append(qip)
            if qip.exists() and qip not in seen_qips:
                seen_qips.add(qip)
                parse_qsf_like_file(qip, qip.parent, project, seen_qips)
        elif name in QSF_INCLUDE_ASSIGNMENTS:
            project.include_dirs.append(resolve_qsf_path(base, value))
        elif name in QSF_DEFINE_ASSIGNMENTS:
            define = normalize_qsf_define(value)
            if define:
                project.defines.append(define)


def parse_qsf_assignment(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    match = re.search(r'(^|\s)-name\s+("[^"]+"|\S+)\s+(.+)$', stripped)
    if match:
        name = match.group(2).strip('"').upper()
        value = parse_qsf_value(match.group(3))
        if value:
            return name, value
    try:
        parts = shlex.split(stripped, comments=True, posix=True)
    except ValueError:
        return None
    if len(parts) < 4 or parts[0] != "set_global_assignment":
        return None
    try:
        name_index = parts.index("-name")
    except ValueError:
        return None
    if name_index + 2 >= len(parts):
        return None
    return parts[name_index + 1].upper(), parts[name_index + 2]


def parse_qsf_value(text: str) -> str | None:
    value_text = text.strip()
    file_join = re.match(r'\[file\s+join\s+\$::quartus\(qip_path\)\s+(.+?)\]', value_text)
    if file_join:
        try:
            parts = shlex.split(file_join.group(1).strip(), comments=True, posix=True)
        except ValueError:
            parts = file_join.group(1).strip().split()
        parts = [part for part in parts if part and part != "]"]
        if parts:
            return str(Path(*parts))
    try:
        parts = shlex.split(value_text, comments=True, posix=True)
    except ValueError:
        parts = value_text.split()
    for part in parts:
        if part.startswith("-"):
            break
        return part
    return None


def resolve_qsf_path(base: Path, value: str) -> Path:
    expanded = os.path.expanduser(os.path.expandvars(value))
    path = Path(expanded)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def normalize_qsf_define(value: str) -> str:
    text = value.strip()
    if text.startswith("+define+"):
        text = text.removeprefix("+define+")
    return text


def filter_hdl_paths(paths: list[Path], excluded: set[Path] | None = None) -> tuple[list[Path], list[str]]:
    excluded = excluded or set()
    out: list[Path] = []
    skipped: list[str] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved in excluded:
            skipped.append(f"replaced:{resolved}")
            continue
        if path.suffix.lower() not in RTL_EXTS:
            skipped.append(f"unsupported:{resolved}")
            continue
        if SKIP_FILE_RE.search(resolved.as_posix()):
            skipped.append(f"vendor-or-apf-shell:{resolved}")
            continue
        out.append(resolved)
    return dedupe(out), dedupe(skipped)


def include_dirs(root: Path, qsf_project: QsfProject | None = None, sources: list[Path] | None = None) -> list[str]:
    dirs: set[Path] = set()
    if qsf_project:
        dirs.update(qsf_project.include_dirs)
    for path in sources or hdl_paths(root):
        dirs.add(path.parent)
    out = ["rtl_shims"]
    out.extend(str(path) for path in sorted(dirs))
    return out


def build_filelist(
    root: Path,
    inv: Any,
    generated_entries: list[str],
    excluded_sources: set[Path] | None = None,
    qsf_project: QsfProject | None = None,
    apfsim_dir: Path | None = None,
) -> list[str]:
    apfsim_dir = apfsim_dir or root
    lines: list[str] = []
    source_paths = qsf_project.sources if qsf_project and qsf_project.sources else hdl_paths(root, excluded_sources)
    source_paths, _ = filter_hdl_paths(source_paths, excluded_sources) if qsf_project and qsf_project.sources else (source_paths, [])
    for define in (qsf_project.defines if qsf_project else []):
        lines.append(f"+define+{define}")
    for inc in include_dirs(root, qsf_project, source_paths):
        inc_path = Path(inc)
        inc_text = placeholderize_path(inc_path, root, apfsim_dir) if inc_path.is_absolute() else inc
        lines.append(f"+incdir+{inc_text}")
    shims = list(COMMON_SHIMS)
    if inv.uses_sdram or inv.uses_ddr:
        shims.append(OPTIONAL_SHIMS["sdram"])
    if any("dpram" in path.name.lower() for path in source_paths):
        shims.append(OPTIONAL_SHIMS["dpram"])
    lines.extend(dedupe(shims))
    lines.extend(generated_entries)
    for path in source_paths:
        lines.append(placeholderize_path(path, root, apfsim_dir))
    return dedupe(lines)


def file_order_key(path: Path) -> tuple[int, str]:
    name = path.name
    if name in {"core_top.sv", "core_top.v", "pocket_top.sv", "pocket_top.v"}:
        return (9999, str(path))
    return (FRAMEWORK_PRIORITY.get(name, 100), str(path))


def find_module_source(sources: list[Path], module_name: str) -> Path | None:
    if not module_name:
        return None
    pattern = re.compile(r"\bmodule\s+" + re.escape(module_name) + r"\b")
    for path in sources:
        if path.suffix.lower() not in RTL_EXTS:
            continue
        try:
            if pattern.search(path.read_text(errors="ignore")[:500000]):
                return path
        except OSError:
            continue
    return None


def maybe_generate_jtframe_pocket_wrapper(qsf_project: QsfProject, profile_dir: Path) -> dict[str, Any] | None:
    if qsf_project.top_level_entity != "pocket_top":
        return None
    pocket_top = find_module_source(qsf_project.sources, "pocket_top")
    jtframe_pocket = find_module_source(qsf_project.sources, "jtframe_pocket")
    if not pocket_top or not jtframe_pocket:
        return None
    path = profile_dir / "apfsim_jtframe_pocket_wrapper.sv"
    path.write_text(render_jtframe_pocket_wrapper())
    return {
        "schema": "apfsim.jtframe_pocket_logical_wrapper.v1",
        "generated": True,
        "top": "core_top",
        "path": "{profile_dir}/apfsim_jtframe_pocket_wrapper.sv",
        "kind": "logical_apf_wrapper",
        "confidence": "public_jtframe_shell_bypass",
        "source": str(jtframe_pocket),
        "replaced_sources": [str(pocket_top)],
        "notes": (
            "Bypasses physical Pocket SPI/PAD/scaler DDR shell and instantiates "
            "jtframe_pocket on apfsim's logical APF bridge/controller/video/audio contract."
        ),
    }


def render_jtframe_pocket_wrapper() -> str:
    return r'''// Generated by apfsim generate-profile.
// Public JTFRAME logical APF wrapper for Verilator bring-up.
// This bypasses physical Pocket SPI/PAD/scaler DDR cells that are not part of
// apfsim's logical APF contract.
`timescale 1ns/1ps

module core_top (
    input  wire        clk_74a,
    input  wire        clk_74b,
    input  wire [31:0] bridge_addr,
    input  wire        bridge_rd,
    output wire [31:0] bridge_rd_data,
    input  wire        bridge_wr,
    input  wire [31:0] bridge_wr_data,
    output wire        bridge_endian_little,
    input  wire [31:0] cont1_key,
    input  wire [31:0] cont2_key,
    input  wire [31:0] cont3_key,
    input  wire [31:0] cont4_key,
    input  wire [31:0] cont1_joy,
    input  wire [31:0] cont2_joy,
    input  wire [31:0] cont3_joy,
    input  wire [31:0] cont4_joy,
    input  wire [15:0] cont1_trig,
    input  wire [15:0] cont2_trig,
    input  wire [15:0] cont3_trig,
    input  wire [15:0] cont4_trig,
    output reg         video_rgb_clock = 1'b0,
    output reg         video_rgb_clock_90 = 1'b0,
    output reg  [23:0] video_rgb,
    output reg         video_de,
    output reg         video_hs,
    output reg         video_vs,
    output wire        video_skip,
    output wire        audio_mclk,
    output wire        audio_lrck,
    output wire        audio_dac
);
`ifdef JTFRAME_COLORW
    localparam integer COLORW = `JTFRAME_COLORW;
`else
    localparam integer COLORW = 4;
`endif

    // JTFRAME's public bridge adapter swaps command/data words internally only
    // when this is asserted. apfsim drives command words in APF register order,
    // so keep the logical bridge big-endian here.
    assign bridge_endian_little = 1'b0;
    assign video_skip = 1'b0;

    wire [15:0] sdram_dq;
    wire [12:0] sdram_a;
    wire [1:0]  sdram_ba;
    wire        sdram_dqml;
    wire        sdram_dqmh;
    wire        sdram_nwe;
    wire        sdram_ncas;
    wire        sdram_nras;
    wire        sdram_ncs;
    wire        sdram_clk;
    wire        sdram_cke;

    wire [COLORW-1:0] core_r;
    wire [COLORW-1:0] core_g;
    wire [COLORW-1:0] core_b;
    wire              core_hs;
    wire              core_vs;
    wire              core_lhbl;
    wire              core_lvbl;
    wire              core_pxl_cen;
    wire              core_video_clk;
    wire              core_video_clk_90;
    wire              core_audio_clk;
    wire signed [15:0] core_audio_l;
    wire signed [15:0] core_audio_r;
    wire              core_led;
    wire [23:0]       core_debug_rgb;
    wire [7:0]        core_debug_flags;

    jtframe_pocket #(.COLORW(COLORW)) u_core (
        .clk_74a(clk_74a),
        .clk_74b(clk_74b),
        .reset_n(1'b1),
        .bridge_endian_little(bridge_endian_little),
        .bridge_addr(bridge_addr),
        .bridge_wr_data(bridge_wr_data),
        .bridge_wr(bridge_wr),
        .bridge_rd(bridge_rd),
        .bridge_rd_data(bridge_rd_data),
        .cont1_key(cont1_key),
        .cont2_key(cont2_key),
        .cont3_key(cont3_key),
        .cont4_key(cont4_key),
        .cont1_joy(cont1_joy),
        .cont2_joy(cont2_joy),
        .cont3_joy(cont3_joy),
        .cont4_joy(cont4_joy),
        .cont1_trig(cont1_trig),
        .cont2_trig(cont2_trig),
        .cont3_trig(cont3_trig),
        .cont4_trig(cont4_trig),
        .SDRAM_DQ(sdram_dq),
        .SDRAM_A(sdram_a),
        .SDRAM_BA(sdram_ba),
        .SDRAM_DQML(sdram_dqml),
        .SDRAM_DQMH(sdram_dqmh),
        .SDRAM_nWE(sdram_nwe),
        .SDRAM_nCAS(sdram_ncas),
        .SDRAM_nRAS(sdram_nras),
        .SDRAM_nCS(sdram_ncs),
        .SDRAM_CLK(sdram_clk),
        .SDRAM_CKE(sdram_cke),
        .video_r(core_r),
        .video_g(core_g),
        .video_b(core_b),
        .video_hs(core_hs),
        .video_vs(core_vs),
        .video_lhbl(core_lhbl),
        .video_lvbl(core_lvbl),
        .video_pxl_cen(core_pxl_cen),
        .video_rgb_clock(core_video_clk),
        .video_rgb_clock_90(core_video_clk_90),
        .audio_clk(core_audio_clk),
        .audio_l(core_audio_l),
        .audio_r(core_audio_r),
        .led(core_led),
        .pocket_debug_rgb(core_debug_rgb),
        .pocket_debug_flags(core_debug_flags)
    );

    function automatic [7:0] expand8;
        input [31:0] in;
        begin
            expand8 = 8'd0;
            case (COLORW)
                1: expand8 = {8{in[0]}};
                2: expand8 = {4{in[1:0]}};
                3: expand8 = {in[2:0], in[2:0], in[2:1]};
                4: expand8 = {2{in[3:0]}};
                5: expand8 = {in[4:0], in[4:2]};
                6: expand8 = {in[5:0], in[5:4]};
                7: expand8 = {in[6:0], in[6]};
                default: expand8 = in[7:0];
            endcase
        end
    endfunction

    wire [31:0] core_r_ext = 32'(core_r);
    wire [31:0] core_g_ext = 32'(core_g);
    wire [31:0] core_b_ext = 32'(core_b);
    wire [23:0] video_rgb_raw = {expand8(core_r_ext), expand8(core_g_ext), expand8(core_b_ext)};
    reg hs_prev = 1'b0;
    reg vs_prev = 1'b0;

    always @(posedge core_video_clk) begin
        // JTFRAME advances the visible stream on video_pxl_cen while the
        // physical Pocket shell forwards the faster PLL clock. For apfsim's
        // logical APF contract, present a pixel-clock pulse only when a new
        // pixel is valid so shape discovery observes the actual active area.
        video_rgb_clock <= core_pxl_cen;
        video_rgb_clock_90 <= core_pxl_cen;
        if (core_pxl_cen) begin
            video_de <= core_lhbl & core_lvbl;
            video_rgb <= (core_lhbl & core_lvbl) ? video_rgb_raw : 24'h0;
            video_hs <= ~hs_prev & core_hs;
            video_vs <= ~vs_prev & core_vs;
            hs_prev <= core_hs;
            vs_prev <= core_vs;
        end
    end

    jtframe_pocket_sound_i2s u_sound_i2s (
        .clk_74a(clk_74a),
        .clk_audio(core_audio_clk),
        .reset(1'b0),
        .audio_l(core_audio_l),
        .audio_r(core_audio_r),
        .audio_mclk(audio_mclk),
        .audio_lrck(audio_lrck),
        .audio_dac(audio_dac)
    );

    wire _unused = &{
        sdram_a, sdram_ba, sdram_dqml, sdram_dqmh, sdram_nwe, sdram_ncas,
        sdram_nras, sdram_ncs, sdram_clk, sdram_cke, sdram_dq, core_pxl_cen,
        core_led, core_debug_rgb, core_debug_flags
    };
endmodule
'''


def first_existing(root: Path, rels: list[str]) -> Path | None:
    for rel in rels:
        path = Path(rel)
        if not path.is_absolute():
            path = root / rel
        if path.exists():
            return path
    return None


def build_scenario(root: Path, data_json: Path | None, video_json: Path | None, apfsim_dir: Path, profile_name: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    slots = []
    total_loaded = 0
    if data_json:
        data = read_json(data_json)
        for slot in find_slot_objects(data):
            parsed = scenario_slot(root, slot, apfsim_dir)
            if parsed:
                slots.append(parsed)
                if parsed.get("file") and not parsed.get("nonvolatile") and not parsed.get("deferload"):
                    try:
                        total_loaded += Path(str(parsed["file"])).stat().st_size
                    except OSError:
                        pass
            else:
                warnings.append(f"could not translate data slot from {data_json}: {slot}")
    if not slots:
        warnings.append("no data slots were generated; add ROM/save slots manually")
    width, height = first_video_mode(video_json)
    if not width or not height:
        warnings.append("no video dimensions found; set expect.video.active_width/active_height manually")
    lines = [f"name: {profile_name}_generated_smoke"]
    if slots:
        lines.append("data_slots:")
        for slot in slots:
            lines.append(f"  - id: {slot['id']}")
            lines.append(f"    name: {quote_yaml(str(slot.get('name') or 'SLOT'))}")
            if slot.get("file"):
                lines.append(f"    file: {quote_yaml(placeholderize_value(str(slot['file']), root, apfsim_dir))}")
            if slot.get("has_address", True):
                lines.append(f"    address: 0x{int(slot['address']):08X}")
            if slot.get("setup_only"):
                lines.append("    setup_only: true")
            if slot.get("required") is not None:
                lines.append(f"    required: {str(bool(slot['required'])).lower()}")
            if slot.get("nonvolatile"):
                lines.append("    nonvolatile: true")
            if slot.get("deferload"):
                lines.append("    deferload: true")
            if slot.get("expected_checksum"):
                lines.append(f"    expected_checksum: 0x{int(slot['expected_checksum']):016X}")
    lines.extend([
        "run:",
        "  until_frames: 12",
        "  timeout_cycles: 50000000",
        "expect:",
        "  status: running",
        "  video:",
        f"    active_width: {width or 0}",
        f"    active_height: {height or 0}",
        "    min_frames: 1",
        "    max_errors: 0",
        "    require_rgb_zero_when_de_low: true",
        "    require_single_cycle_sync: true",
        "    require_skip_only_during_de: true",
        "  audio:",
        "    min_samples: 1",
        "  data:",
        "    require_required_slots: true",
        "    require_all_file_slots_loaded: true",
    ])
    if total_loaded:
        lines.append(f"    expected_total_loaded_bytes: {total_loaded}")
    lines.extend([
        "  reset:",
        "    require_reset_enter: true",
        "    require_reset_exit: true",
        "    require_ready_to_run: true",
    ])
    if any(slot.get("nonvolatile") for slot in slots):
        lines.extend([
            "  save:",
            "    require_nonvolatile_unload: true",
        ])
    return "\n".join(lines) + "\n", warnings


def scenario_slot(root: Path, slot: dict[str, Any], apfsim_dir: Path) -> dict[str, Any] | None:
    slot_id = int_value(slot.get("id", slot.get("slot")))
    address = int_value(slot.get("address", slot.get("loadaddress", slot.get("load_address"))))
    if slot_id is None:
        return None
    setup_only = False
    if address is None:
        if not is_setup_only_slot(slot):
            return None
        address = 0
        setup_only = True
    nonvolatile = bool(slot.get("nonvolatile") or slot.get("save") or slot.get("savefile"))
    deferload = setup_only or bool(slot.get("deferload") or slot.get("deferred") or slot.get("defer"))
    file_path = None
    if nonvolatile:
        candidate = apfsim_dir / "examples/assets/mock.hi"
        if candidate.exists():
            file_path = str(candidate)
    else:
        file_path = match_asset(root, slot)
    out = {
        "id": slot_id,
        "name": slot.get("name") or f"SLOT{slot_id}",
        "address": address,
        "has_address": not setup_only,
        "setup_only": setup_only,
        "required": bool(slot.get("required", True)),
        "nonvolatile": nonvolatile,
        "deferload": deferload,
    }
    if file_path:
        out["file"] = file_path
        if not nonvolatile and not deferload:
            checksum = fnv1a64(Path(file_path).read_bytes())
            out["expected_checksum"] = checksum
    return out


def is_setup_only_slot(slot: dict[str, Any]) -> bool:
    parameters = int_value(slot.get("parameters"))
    extensions = [str(ext).lower().lstrip(".") for ext in slot.get("extensions", []) if str(ext)]
    filename = str(slot.get("filename") or slot.get("file") or "").lower()
    name = str(slot.get("name") or "").lower()
    instance_json = bool(parameters is not None and (parameters & (1 << 4)))
    json_named = "json" in extensions or filename.endswith(".json") or "json" in name or "setup" in name
    return instance_json or json_named


def match_asset(root: Path, slot: dict[str, Any]) -> str | None:
    asset_roots = [path for path in [root / "dist/Assets", root / "Assets", root / "release/pocket/Assets"] if path.exists()]
    if not asset_roots:
        return None
    filename = str(slot.get("filename") or "")
    if filename:
        for base in asset_roots:
            for path in base.rglob("*"):
                if path.is_file() and path.name.lower() == filename.lower():
                    return str(path)
    extensions = [str(ext).lower().lstrip(".") for ext in slot.get("extensions", []) if str(ext)]
    candidates: list[Path] = []
    for base in asset_roots:
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if extensions and path.suffix.lower().lstrip(".") not in extensions:
                continue
            candidates.append(path)
    if len(candidates) == 1:
        return str(candidates[0])
    if candidates:
        return str(sorted(candidates, key=lambda p: (len(p.name), p.name.lower()))[0])
    return None


def first_video_mode(video_json: Path | None) -> tuple[int, int]:
    if not video_json:
        return 0, 0
    data = read_json(video_json)
    modes = find_video_modes(data)
    return modes[0] if modes else (0, 0)


def profile_risks(inv: Any, selected_shims: list[str], qsf_project: QsfProject | None = None) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    qsf_vhdl_count = len(qsf_project.vhdl_files) if qsf_project else 0
    if inv.vhdl_files or qsf_vhdl_count:
        risks.append({
            "code": "VHDL_ENTITY_STUBBED",
            "severity": "warning",
            "kind": "mixed_hdl",
            "message": "VHDL sources were detected but generated Verilator profiles do not compile VHDL directly.",
            "evidence": {
                "discovered_vhdl_files": inv.vhdl_files,
                "qsf_vhdl_files": qsf_vhdl_count,
            },
            "recommended_action": "Provide translated RTL, a faithful SystemVerilog shim, or an explicit mixed-language strategy before treating gameplay behavior as verified.",
        })
    if not selected_shims and (inv.uses_pll or inv.uses_altsyncram or inv.uses_dcfifo or inv.qip_files):
        risks.append({
            "code": "SHIM_REQUIRED",
            "severity": "warning",
            "kind": "vendor_ip",
            "message": "Vendor/IP usage was detected without a selected shim catalog entry.",
            "recommended_action": "Add a deterministic simulation shim or catalog entry for each non-Verilator-friendly primitive.",
        })
    return risks


def generation_warnings(
    inv: Any,
    selected_shims: list[str],
    filelist_lines: list[str],
    qsf_project: QsfProject | None = None,
    excluded_sources: set[Path] | None = None,
    memory: dict[str, Any] | None = None,
    expected_top: str | None = None,
) -> list[str]:
    warnings: list[str] = []
    if inv.status not in {"candidate", "needs-ip-shims", "profiled"}:
        warnings.append(f"discovery status is {inv.status}: {inv.action}")
    if qsf_project and qsf_project.path:
        _, skipped = filter_hdl_paths(qsf_project.sources, excluded_sources)
        if skipped:
            warnings.append(f"QSF source filtering skipped or replaced {len(skipped)} entries; review candidate.json for details")
        if qsf_project.missing_sources:
            warnings.append(f"QSF references {len(qsf_project.missing_sources)} missing RTL source(s)")
        if qsf_project.qip_files:
            warnings.append("QSF references QIP/IP files; verify corresponding Verilator shims or public implementations")
    if inv.vhdl_files or (qsf_project and qsf_project.vhdl_files):
        warnings.append("VHDL files were detected; generated Verilog profile may need public stubs or mixed-language strategy")
    memory_doc = memory if isinstance(memory, dict) else inv.memory
    for risk in memory_doc.get("risks", []):
        if isinstance(risk, dict) and risk.get("code"):
            warnings.append(f"{risk['code']}: {risk.get('message', 'memory model risk')}")
    if not selected_shims and (inv.uses_pll or inv.uses_altsyncram or inv.uses_dcfifo or inv.qip_files):
        warnings.append("vendor/IP usage detected; filelist includes generic shims but may need catalog entries")
    expected_top = expected_top or (qsf_project.top_level_entity if qsf_project and qsf_project.top_level_entity else "core_top")
    if not any(line.endswith(f"{expected_top}.sv") or line.endswith(f"{expected_top}.v") for line in filelist_lines):
        warnings.append(f"{expected_top} was not found in generated filelist")
    return warnings


def qsf_report(qsf_project: QsfProject | None, excluded_sources: set[Path] | None = None) -> dict[str, Any] | None:
    if not qsf_project or not qsf_project.path:
        return None
    source_paths, skipped = filter_hdl_paths(qsf_project.sources, excluded_sources)
    return {
        "path": str(qsf_project.path),
        "top_level_entity": qsf_project.top_level_entity,
        "source_count": len(qsf_project.sources),
        "verilator_source_count": len(source_paths),
        "include_dirs": [str(path) for path in qsf_project.include_dirs],
        "defines": qsf_project.defines,
        "skipped_sources": skipped,
        "missing_sources": [str(path) for path in qsf_project.missing_sources],
        "vhdl_files": [str(path) for path in qsf_project.vhdl_files],
        "qip_files": [str(path) for path in qsf_project.qip_files],
    }


def render_notes(
    inv: Any,
    profile: dict[str, Any],
    selected_shim_details: list[dict[str, Any]],
    warnings: list[str],
    profile_path: Path,
    filelist_path: Path,
    scenario_path: Path,
    qsf_project: QsfProject | None = None,
    excluded_sources: set[Path] | None = None,
) -> str:
    lines = [
        f"# Generated apfsim Profile: {profile['name']}",
        "",
        "This is a generated candidate. Review it before committing or running it as a production gate.",
        "",
        "## Outputs",
        "",
        f"- Profile: `{profile_path}`",
        f"- Filelist: `{filelist_path}`",
        f"- Scenario: `{scenario_path}`",
        "",
        "## Discovery",
        "",
        f"- Root: `{inv.root}`",
        f"- Status: `{inv.status}`",
        f"- Action: {inv.action}",
        f"- Core IDs: {', '.join(inv.core_ids) or '-'}",
        f"- Video modes: {', '.join(inv.video_modes) or '-'}",
        f"- HDL: sv={inv.sv_files} v={inv.v_files} vhdl={inv.vhdl_files}",
        "",
        "## Quartus Project",
        "",
    ]
    if qsf_project and qsf_project.path:
        source_paths, skipped = filter_hdl_paths(qsf_project.sources, excluded_sources)
        lines.extend([
            f"- QSF: `{qsf_project.path}`",
            f"- Top-level entity: `{qsf_project.top_level_entity or 'not specified'}`",
            f"- Verilator RTL sources from QSF: {len(source_paths)} / {len(qsf_project.sources)}",
            f"- Defines: {', '.join(qsf_project.defines) or '-'}",
            f"- Include/search paths: {len(qsf_project.include_dirs)}",
            f"- VHDL files: {len(qsf_project.vhdl_files)}",
            f"- QIP files: {len(qsf_project.qip_files)}",
            f"- Filtered/replaced sources: {len(skipped)}",
            "",
        ])
    else:
        lines.extend([
            "- No QSF detected; filelist source order was generated from filesystem heuristics.",
            "",
        ])
    lines.extend([
        "## Shim Catalog Entries",
        "",
    ])
    if selected_shim_details:
        for shim in selected_shim_details:
            modules = ", ".join(str(item) for item in shim.get("modules", [])) or "-"
            label = f"{shim.get('kind') or 'shim'}/{shim.get('confidence') or 'unknown'}"
            lines.append(f"- `{shim['name']}` ({label}): {modules}")
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Suggested Review Commands",
        "",
        "```sh",
        f"bin/apfsim build --profile {profile_path} --preflight-only",
        f"bin/apfsim build --profile {profile_path}",
        f"bin/apfsim run --profile {profile_path} --artifacts output/{profile['name']}-generated",
        "```",
        "",
    ])
    return "\n".join(lines)


def sample_source_text(root: Path) -> str:
    chunks: list[str] = []
    for path in hdl_paths(root)[:200]:
        try:
            chunks.append(path.read_text(errors="ignore")[:100000])
        except OSError:
            pass
    return "\n".join(chunks)


def read_json(path: Path | None) -> Any:
    if not path:
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return None
    return None


def quote_yaml(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def fnv1a64(data: bytes) -> int:
    value = 0xCBF29CE484222325
    for byte in data:
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return value


def dedupe(values: list[Any]) -> list[Any]:
    out: list[Any] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out
