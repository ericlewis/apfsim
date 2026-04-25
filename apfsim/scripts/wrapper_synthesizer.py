#!/usr/bin/env python3
"""Synthesize a reviewable APF-facing wrapper for arbitrary Verilog tops."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core_discovery import inspect_core
from profile_generator import (
    COMMON_SHIMS,
    build_scenario,
    env_prefix,
    filter_hdl_paths,
    first_existing,
    hdl_paths,
    normalize_profile_name,
    parse_qsf_project,
    placeholderize_path,
    qsf_report,
    select_qsf,
)

RTL_EXTS = {".v", ".sv"}

APF_PORTS = [
    ("input", "", "clk_74a"),
    ("input", "", "clk_74b"),
    ("input", "[31:0]", "bridge_addr"),
    ("input", "", "bridge_rd"),
    ("output", "[31:0]", "bridge_rd_data"),
    ("input", "", "bridge_wr"),
    ("input", "[31:0]", "bridge_wr_data"),
    ("output", "", "bridge_endian_little"),
    ("input", "[31:0]", "cont1_key"),
    ("input", "[31:0]", "cont2_key"),
    ("input", "[31:0]", "cont3_key"),
    ("input", "[31:0]", "cont4_key"),
    ("input", "[31:0]", "cont1_joy"),
    ("input", "[31:0]", "cont2_joy"),
    ("input", "[31:0]", "cont3_joy"),
    ("input", "[31:0]", "cont4_joy"),
    ("input", "[15:0]", "cont1_trig"),
    ("input", "[15:0]", "cont2_trig"),
    ("input", "[15:0]", "cont3_trig"),
    ("input", "[15:0]", "cont4_trig"),
    ("output", "", "video_rgb_clock"),
    ("output", "", "video_rgb_clock_90"),
    ("output", "[23:0]", "video_rgb"),
    ("output", "", "video_de"),
    ("output", "", "video_hs"),
    ("output", "", "video_vs"),
    ("output", "", "video_skip"),
    ("output", "", "audio_mclk"),
    ("output", "", "audio_lrck"),
    ("output", "", "audio_dac"),
]


@dataclass
class Port:
    name: str
    direction: str = ""
    width: str = ""

    @property
    def wire_decl(self) -> str:
        width = f" {self.width}" if self.width else ""
        return f"wire{width} src_{self.name};"


@dataclass
class ModuleInfo:
    name: str
    path: Path
    ports: dict[str, Port] = field(default_factory=dict)


def synthesize_wrapper_profile(
    root: Path,
    output_dir: Path,
    *,
    apfsim_dir: Path,
    profile_name: str | None = None,
    source_top: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    root = root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    name = profile_name or normalize_profile_name(root.name)
    profile_dir = output_dir / name
    if profile_dir.exists() and any(profile_dir.iterdir()) and not force:
        raise FileExistsError(f"output directory already exists: {profile_dir}")
    profile_dir.mkdir(parents=True, exist_ok=True)

    inv = inspect_core(root, source_root=str(root.parent), profile_by_root={})
    qsf_project = parse_qsf_project(select_qsf(root, inv))
    sources = qsf_project.sources if qsf_project.sources else hdl_paths(root)
    sources, skipped = filter_hdl_paths(sources)
    modules = parse_modules(sources)
    chosen = choose_top(modules, explicit=source_top, qsf_top=qsf_project.top_level_entity)

    data_json = first_existing(root, inv.data_jsons)
    video_json = first_existing(root, inv.video_jsons)
    scenario_text, scenario_warnings = build_scenario(root, data_json, video_json, apfsim_dir, name)
    scenario_path = profile_dir / "scenario.yml"
    scenario_path.write_text(scenario_text)

    wrapper_path = profile_dir / "apfsim_core_top.sv"
    synthesis = build_synthesis_report(chosen, modules)
    if chosen:
        wrapper_path.write_text(render_wrapper(chosen, synthesis))
    else:
        wrapper_path.write_text(render_empty_wrapper("no source top could be selected"))
        synthesis["status"] = "blocked"
        synthesis["blockers"].append({
            "code": "PORT_MISSING",
            "message": "No Verilog/SystemVerilog source module could be selected for wrapper synthesis.",
        })

    filelist_path = profile_dir / "filelist.f"
    filelist_lines = build_synth_filelist(root, apfsim_dir, sources, wrapper_path)
    filelist_path.write_text("\n".join(filelist_lines) + "\n")

    profile = {
        "name": name,
        "description": f"Synthesized APF wrapper profile for {root.name}; review wrapper_synthesis.json before trusting failures.",
        "external": True,
        "root_env": f"{env_prefix(name)}_ROOT",
        "top": "core_top",
        "filelist": "{profile_dir}/filelist.f",
        "scenario": "{profile_dir}/scenario.yml",
        "frames": 12,
        "timeout_cycles": 50000000,
        "write_idle_cycles": 64,
        "build_dir": f"build/synth-wrapper/{name}/obj",
        "artifact_root": f"output/synth-wrapper/{name}/run",
        "verilator_flags": ["--sv"],
        "wrapper_synthesis": {
            "report": "{profile_dir}/wrapper_synthesis.json",
            "wrapper": "{profile_dir}/apfsim_core_top.sv",
        },
        "required_paths": [
            "{profile_dir}/apfsim_core_top.sv",
            "{profile_dir}/filelist.f",
            "{profile_dir}/scenario.yml",
        ],
        "expected_artifacts": [
            "result.json",
            "video_shape.json",
            "bridge.log",
            "video/frame_000001.json",
            "audio/out.wav",
            "audio/stats.json",
        ],
    }
    metadata_jsons: dict[str, str] = {}
    if data_json:
        metadata_jsons["data"] = placeholderize_path(data_json, root, apfsim_dir)
        profile["required_paths"].append(metadata_jsons["data"])
    if video_json:
        metadata_jsons["video"] = placeholderize_path(video_json, root, apfsim_dir)
        profile["required_paths"].append(metadata_jsons["video"])
    if metadata_jsons:
        profile["metadata_jsons"] = metadata_jsons

    profile_path = profile_dir / f"{name}.json"
    profile_path.write_text(json.dumps(profile, indent=2) + "\n")

    synthesis.update({
        "schema": "apfsim.wrapper_synthesis.v1",
        "profile": name,
        "root": str(root),
        "source_top": chosen.name if chosen else "",
        "source_file": str(chosen.path) if chosen else "",
        "paths": {
            "profile": str(profile_path),
            "filelist": str(filelist_path),
            "scenario": str(scenario_path),
            "wrapper": str(wrapper_path),
        },
        "qsf": qsf_report(qsf_project),
        "warnings": scenario_warnings + [f"skipped source: {item}" for item in skipped],
    })
    report_path = profile_dir / "wrapper_synthesis.json"
    report_path.write_text(json.dumps(synthesis, indent=2) + "\n")
    notes_path = profile_dir / "NOTES.md"
    notes_path.write_text(render_notes(synthesis, profile_path, wrapper_path, filelist_path))
    synthesis["paths"]["notes"] = str(notes_path)
    report_path.write_text(json.dumps(synthesis, indent=2) + "\n")
    return synthesis


def strip_comments(text: str) -> str:
    text = re.sub(r"//.*", "", text)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def parse_modules(paths: list[Path]) -> dict[str, ModuleInfo]:
    modules: dict[str, ModuleInfo] = {}
    for path in paths:
        try:
            text = strip_comments(path.read_text(errors="ignore"))
        except OSError:
            continue
        for match in re.finditer(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)\b", text):
            name = match.group(1)
            header = module_header_after(text, match.end())
            if header is None:
                continue
            body_start = text.find(";", match.end())
            body_end = text.find("endmodule", body_start)
            body = text[body_start:body_end] if body_start >= 0 and body_end >= 0 else ""
            modules[name] = ModuleInfo(name=name, path=path, ports=parse_ports(header, body))
    return modules


def module_header_after(text: str, start: int) -> str | None:
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    if index < len(text) and text[index] == "#":
        paren = text.find("(", index)
        if paren < 0:
            return None
        end = find_matching_paren(text, paren)
        if end < 0:
            return None
        index = end + 1
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text) or text[index] != "(":
        return None
    end = find_matching_paren(text, index)
    if end < 0:
        return None
    return text[index + 1:end]


def find_matching_paren(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def split_commas(text: str) -> list[str]:
    items: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            items.append(text[start:index])
            start = index + 1
    items.append(text[start:])
    return items


def parse_ports(header: str, body: str) -> dict[str, Port]:
    ports: dict[str, Port] = {}
    current_direction = ""
    current_width = ""
    for raw_item in split_commas(header):
        item = " ".join(raw_item.strip().split())
        if not item:
            continue
        direction_match = re.match(r"\b(input|output|inout)\b\s*(.*)$", item)
        if direction_match:
            current_direction = direction_match.group(1)
            item = direction_match.group(2).strip()
        item = re.sub(r"\b(wire|reg|logic|signed|unsigned)\b", " ", item)
        width_match = re.search(r"(\[[^\]]+\])", item)
        if width_match:
            current_width = width_match.group(1)
            item = item.replace(current_width, " ")
        name_match = re.search(r"([A-Za-z_][A-Za-z0-9_$]*)\s*(?:=.*)?$", item.strip())
        if name_match:
            name = name_match.group(1)
            ports[name] = Port(name=name, direction=current_direction, width=current_width)
    apply_body_port_declarations(ports, body)
    return ports


def apply_body_port_declarations(ports: dict[str, Port], body: str) -> None:
    decl_re = re.compile(r"\b(input|output|inout)\b\s+(?:wire|reg|logic)?\s*(signed|unsigned)?\s*(\[[^\]]+\])?\s*([^;]+);")
    for match in decl_re.finditer(body):
        direction = match.group(1)
        width = (match.group(3) or "").strip()
        for name in re.findall(r"\b([A-Za-z_][A-Za-z0-9_$]*)\b", match.group(4)):
            if name in {"wire", "reg", "logic", "signed", "unsigned"}:
                continue
            port = ports.get(name, Port(name=name))
            port.direction = direction
            if width:
                port.width = width
            ports[name] = port


def choose_top(modules: dict[str, ModuleInfo], *, explicit: str | None, qsf_top: str | None) -> ModuleInfo | None:
    for name in [explicit, qsf_top, "pocket_top", "emu", "mist_top", "main"]:
        if name and name in modules:
            return modules[name]
    if not modules:
        return None
    return max(modules.values(), key=module_score)


def module_score(module: ModuleInfo) -> int:
    names = {norm(name) for name in module.ports}
    score = 0
    for group in [
        ("clk74a", "clk74", "clk", "clock", "refclk"),
        ("bridgerd", "bridgewr", "bridgeaddr", "ioctldownload", "ioctlwr"),
        ("videorgb", "vidrgb", "vgar", "videor", "hblank", "vblank", "videode"),
        ("audiomclk", "audiolrck", "audiodac", "audiol", "audior"),
    ]:
        if any(item in names for item in group):
            score += 10
    return score + len(module.ports)


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def build_synthesis_report(module: ModuleInfo | None, modules: dict[str, ModuleInfo]) -> dict[str, Any]:
    mappings: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    if module is None:
        return {
            "status": "blocked",
            "confidence": 0.0,
            "mappings": mappings,
            "blockers": blockers,
            "modules": sorted(modules),
        }
    video = infer_video(module.ports)
    bridge = infer_bridge(module.ports)
    audio = infer_audio(module.ports)
    mappings.extend(video["mappings"])
    mappings.extend(bridge["mappings"])
    mappings.extend(audio["mappings"])
    blockers.extend(video["blockers"])
    blockers.extend(bridge["blockers"])
    blockers.extend(audio["blockers"])
    confidences = [float(item.get("confidence", 0.0)) for item in mappings]
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    if blockers:
        confidence = min(confidence, 0.69)
    return {
        "status": "partial" if blockers else "ready",
        "confidence": round(confidence, 3),
        "mappings": mappings,
        "blockers": blockers,
        "modules": sorted(modules),
        "port_count": len(module.ports),
        "source_ports": [
            {"name": port.name, "direction": port.direction, "width": port.width}
            for port in module.ports.values()
        ],
    }


def mapping(apf_signal: str, source: str, confidence: float, *, expression: str = "", risk: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {
        "apf_signal": apf_signal,
        "source": source,
        "confidence": confidence,
    }
    if expression:
        out["expression"] = expression
    if risk:
        out["risk"] = risk
    return out


def blocker(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def find_port(ports: dict[str, Port], candidates: list[str], direction: str | None = None) -> Port | None:
    by_norm = {norm(name): port for name, port in ports.items()}
    for candidate in candidates:
        port = by_norm.get(norm(candidate))
        if port and (direction is None or not port.direction or port.direction == direction):
            return port
    return None


def infer_bridge(ports: dict[str, Port]) -> dict[str, Any]:
    mappings: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for apf in ["bridge_addr", "bridge_rd", "bridge_wr", "bridge_wr_data", "bridge_rd_data"]:
        port = find_port(ports, [apf])
        if port:
            mappings.append(mapping(apf, port.name, 0.98))
    if not any(item["apf_signal"] == "bridge_rd_data" for item in mappings):
        blockers.append(blocker("BRIDGE_MAPPING_MISSING", "No APF bridge read-data output was inferred. Boot may not work without a real bridge adapter."))
    return {"mappings": mappings, "blockers": blockers}


def infer_video(ports: dict[str, Port]) -> dict[str, Any]:
    mappings: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    rgb = find_port(ports, ["video_rgb", "vid_rgb", "rgb", "VGA_RGB"], "output")
    r = find_port(ports, ["video_r", "vid_r", "vga_r", "VGA_R", "R"], "output")
    g = find_port(ports, ["video_g", "vid_g", "vga_g", "VGA_G", "G"], "output")
    b = find_port(ports, ["video_b", "vid_b", "vga_b", "VGA_B", "B"], "output")
    if rgb:
        mappings.append(mapping("video_rgb", rgb.name, 0.95))
    elif r and g and b:
        mappings.append(mapping("video_rgb", ",".join([r.name, g.name, b.name]), 0.82, expression="{expand8(r), expand8(g), expand8(b)}", risk="RGB channel width inferred"))
    else:
        blockers.append(blocker("VIDEO_RGB_MAPPING_MISSING", "No RGB output was inferred."))

    de = find_port(ports, ["video_de", "vid_de", "de", "data_enable"], "output")
    lhbl = find_port(ports, ["lhbl", "video_lhbl", "hblank_n", "hbl_n"], "output")
    lvbl = find_port(ports, ["lvbl", "video_lvbl", "vblank_n", "vbl_n"], "output")
    hblank = find_port(ports, ["hblank", "hblk", "HBLANK", "VGA_BLANK_N"], "output")
    vblank = find_port(ports, ["vblank", "vblk", "VBLANK"], "output")
    if de:
        mappings.append(mapping("video_de", de.name, 0.96))
    elif lhbl and lvbl:
        mappings.append(mapping("video_de", f"{lhbl.name},{lvbl.name}", 0.78, expression=f"{lhbl.name} & {lvbl.name}", risk="active-high blanking polarity inferred"))
    elif hblank and vblank:
        mappings.append(mapping("video_de", f"{hblank.name},{vblank.name}", 0.72, expression=f"~{hblank.name} & ~{vblank.name}", risk="active-low DE inferred from blanking outputs"))
    else:
        blockers.append(blocker("VIDEO_DE_MAPPING_MISSING", "No DE or blanking pair was inferred."))

    for apf, candidates in {
        "video_hs": ["video_hs", "vid_hs", "hs", "hsync", "vga_hs", "HSync"],
        "video_vs": ["video_vs", "vid_vs", "vs", "vsync", "vga_vs", "VSync"],
    }.items():
        port = find_port(ports, candidates, "output")
        if port:
            mappings.append(mapping(apf, port.name, 0.86))
        else:
            blockers.append(blocker(f"{apf.upper()}_MAPPING_MISSING", f"No {apf} output was inferred."))

    clk = find_port(ports, ["video_rgb_clock", "vid_rgb_clock", "video_clk", "clk_video", "pclk", "PCLK"], "output")
    if clk:
        mappings.append(mapping("video_rgb_clock", clk.name, 0.86))
    else:
        mappings.append(mapping("video_rgb_clock", "clk_74a", 0.35, expression="clk_74a", risk="pixel clock not found; using APF clock"))
    return {"mappings": mappings, "blockers": blockers}


def infer_audio(ports: dict[str, Port]) -> dict[str, Any]:
    mappings: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    found = False
    for apf, candidates in {
        "audio_mclk": ["audio_mclk", "aud_mclk", "mclk"],
        "audio_lrck": ["audio_lrck", "aud_lrck", "lrck"],
        "audio_dac": ["audio_dac", "aud_dac", "dac"],
    }.items():
        port = find_port(ports, candidates, "output")
        if port:
            found = True
            mappings.append(mapping(apf, port.name, 0.9))
    if not found:
        blockers.append(blocker("AUDIO_MAPPING_MISSING", "No I2S-style APF audio pins were inferred; wrapper drives silence."))
    return {"mappings": mappings, "blockers": blockers}


def render_wrapper(module: ModuleInfo, synthesis: dict[str, Any]) -> str:
    ports = module.ports
    conns = []
    for port in ports.values():
        expr = instance_connection(port)
        conns.append(f"        .{port.name}({expr})")
    conn_text = ",\n".join(conns)
    declarations = "\n".join(
        f"    {port.wire_decl}"
        for port in ports.values()
        if port.direction in {"output", "inout"}
    )
    rgb_expr = video_rgb_expression(ports)
    de_expr = video_de_expression(ports)
    hs_expr = output_expr(ports, ["video_hs", "vid_hs", "hs", "hsync", "vga_hs", "HSync"], "1'b0")
    vs_expr = output_expr(ports, ["video_vs", "vid_vs", "vs", "vsync", "vga_vs", "VSync"], "1'b0")
    pixclk_expr = output_expr(ports, ["video_rgb_clock", "vid_rgb_clock", "video_clk", "clk_video", "pclk", "PCLK"], "clk_74a")
    bridge_rd_data_expr = output_expr(ports, ["bridge_rd_data"], "32'h00000000")
    endian_expr = output_expr(ports, ["bridge_endian_little"], "1'b1")
    audio_mclk_expr = output_expr(ports, ["audio_mclk", "aud_mclk", "mclk"], "1'b0")
    audio_lrck_expr = output_expr(ports, ["audio_lrck", "aud_lrck", "lrck"], "1'b0")
    audio_dac_expr = output_expr(ports, ["audio_dac", "aud_dac", "dac"], "1'b0")
    return f"""// Generated by apfsim synth-wrapper.
// Review wrapper_synthesis.json before treating this as a trusted APF integration.
`timescale 1ns/1ps

module core_top (
{render_apf_ports()}
);
{declarations}

    function automatic [7:0] apfsim_expand8(input [31:0] value);
        begin
            apfsim_expand8 = value[7:0];
        end
    endfunction

    {module.name} u_source (
{conn_text}
    );

    assign bridge_rd_data = {bridge_rd_data_expr};
    assign bridge_endian_little = {endian_expr};
    assign video_rgb_clock = {pixclk_expr};
    assign video_rgb_clock_90 = {pixclk_expr};
    assign video_rgb = {de_expr} ? {rgb_expr} : 24'h000000;
    assign video_de = {de_expr};
    assign video_hs = {hs_expr};
    assign video_vs = {vs_expr};
    assign video_skip = 1'b0;
    assign audio_mclk = {audio_mclk_expr};
    assign audio_lrck = {audio_lrck_expr};
    assign audio_dac = {audio_dac_expr};
endmodule
"""


def render_empty_wrapper(reason: str) -> str:
    return f"""// Generated by apfsim synth-wrapper.
// Blocked: {reason}
`timescale 1ns/1ps

module core_top (
{render_apf_ports()}
);
    assign bridge_rd_data = 32'h00000000;
    assign bridge_endian_little = 1'b1;
    assign video_rgb_clock = clk_74a;
    assign video_rgb_clock_90 = clk_74a;
    assign video_rgb = 24'h000000;
    assign video_de = 1'b0;
    assign video_hs = 1'b0;
    assign video_vs = 1'b0;
    assign video_skip = 1'b0;
    assign audio_mclk = 1'b0;
    assign audio_lrck = 1'b0;
    assign audio_dac = 1'b0;
endmodule
"""


def render_apf_ports() -> str:
    lines = []
    for index, (direction, width, name) in enumerate(APF_PORTS):
        comma = "," if index + 1 < len(APF_PORTS) else ""
        width_text = f" {width}" if width else ""
        lines.append(f"    {direction} wire{width_text} {name}{comma}")
    return "\n".join(lines)


def instance_connection(port: Port) -> str:
    name = port.name
    if port.direction == "output" or port.direction == "inout":
        return f"src_{name}"
    exact = {
        "clk_74a": "clk_74a",
        "clk_74b": "clk_74b",
        "bridge_addr": "bridge_addr",
        "bridge_rd": "bridge_rd",
        "bridge_wr": "bridge_wr",
        "bridge_wr_data": "bridge_wr_data",
        "cont1_key": "cont1_key",
        "cont2_key": "cont2_key",
        "cont3_key": "cont3_key",
        "cont4_key": "cont4_key",
        "cont1_joy": "cont1_joy",
        "cont2_joy": "cont2_joy",
        "cont3_joy": "cont3_joy",
        "cont4_joy": "cont4_joy",
        "cont1_trig": "cont1_trig",
        "cont2_trig": "cont2_trig",
        "cont3_trig": "cont3_trig",
        "cont4_trig": "cont4_trig",
    }
    normalized = norm(name)
    for key, expr in exact.items():
        if normalized == norm(key):
            return expr
    if normalized in {"clk", "clock", "refclk", "clk74", "clk74a"}:
        return "clk_74a"
    if normalized in {"clk74b"}:
        return "clk_74b"
    if "resetn" in normalized or normalized in {"rstn", "resetl", "rstl"}:
        return "1'b1"
    if "reset" in normalized or normalized == "rst":
        return "1'b0"
    width = port.width or ""
    return zero_for_width(width)


def zero_for_width(width: str) -> str:
    if not width:
        return "1'b0"
    return "'0"


def src(name: str) -> str:
    return f"src_{name}"


def output_expr(ports: dict[str, Port], candidates: list[str], fallback: str) -> str:
    port = find_port(ports, candidates, "output")
    return src(port.name) if port else fallback


def video_rgb_expression(ports: dict[str, Port]) -> str:
    rgb = find_port(ports, ["video_rgb", "vid_rgb", "rgb", "VGA_RGB"], "output")
    if rgb:
        return src(rgb.name)
    r = find_port(ports, ["video_r", "vid_r", "vga_r", "VGA_R", "R"], "output")
    g = find_port(ports, ["video_g", "vid_g", "vga_g", "VGA_G", "G"], "output")
    b = find_port(ports, ["video_b", "vid_b", "vga_b", "VGA_B", "B"], "output")
    if r and g and b:
        return f"{{apfsim_expand8(32'({src(r.name)})), apfsim_expand8(32'({src(g.name)})), apfsim_expand8(32'({src(b.name)}))}}"
    return "24'h000000"


def video_de_expression(ports: dict[str, Port]) -> str:
    de = find_port(ports, ["video_de", "vid_de", "de", "data_enable"], "output")
    if de:
        return src(de.name)
    lhbl = find_port(ports, ["lhbl", "video_lhbl", "hblank_n", "hbl_n"], "output")
    lvbl = find_port(ports, ["lvbl", "video_lvbl", "vblank_n", "vbl_n"], "output")
    if lhbl and lvbl:
        return f"({src(lhbl.name)} & {src(lvbl.name)})"
    hblank = find_port(ports, ["hblank", "hblk", "HBLANK"], "output")
    vblank = find_port(ports, ["vblank", "vblk", "VBLANK"], "output")
    if hblank and vblank:
        return f"(~{src(hblank.name)} & ~{src(vblank.name)})"
    return "1'b0"


def build_synth_filelist(root: Path, apfsim_dir: Path, sources: list[Path], wrapper_path: Path) -> list[str]:
    lines = ["+incdir+rtl_shims"]
    lines.extend(COMMON_SHIMS)
    for source in sources:
        if source.suffix.lower() in RTL_EXTS:
            lines.append(placeholderize_path(source, root, apfsim_dir))
    lines.append("{profile_dir}/apfsim_core_top.sv")
    return dedupe(lines)


def dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def render_notes(synthesis: dict[str, Any], profile_path: Path, wrapper_path: Path, filelist_path: Path) -> str:
    lines = [
        "# APF Wrapper Synthesis",
        "",
        f"Status: `{synthesis.get('status')}`",
        f"Confidence: `{synthesis.get('confidence')}`",
        "",
        "Review this before running hardware or treating simulator failures as core failures.",
        "",
        f"- Profile: `{profile_path}`",
        f"- Wrapper: `{wrapper_path}`",
        f"- Filelist: `{filelist_path}`",
        "",
        "## Blockers",
    ]
    blockers = synthesis.get("blockers", [])
    if blockers:
        lines.extend(f"- `{item.get('code')}`: {item.get('message')}" for item in blockers if isinstance(item, dict))
    else:
        lines.append("- None")
    lines.extend(["", "## Mappings"])
    for item in synthesis.get("mappings", []):
        if not isinstance(item, dict):
            continue
        suffix = f" risk={item['risk']}" if item.get("risk") else ""
        lines.append(f"- `{item.get('apf_signal')}` <= `{item.get('source')}` confidence={item.get('confidence')}{suffix}")
    lines.append("")
    return "\n".join(lines)
