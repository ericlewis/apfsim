from __future__ import annotations

import json
import os
import subprocess
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_DISCOVERY_ROOTS = [
    Path(item)
    for item in os.environ.get("APFSIM_DISCOVERY_ROOTS", "").split(os.pathsep)
    if item
]


@dataclass
class CoreInventory:
    name: str
    root: str
    source_root: str
    git_root: str = ""
    git_state: str = "unknown"
    git_dirty_count: int = 0
    git_dirty_paths: list[str] = field(default_factory=list)
    core_ids: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)
    status: str = "unknown"
    action: str = ""
    top_files: list[str] = field(default_factory=list)
    qsf_files: list[str] = field(default_factory=list)
    core_jsons: list[str] = field(default_factory=list)
    data_jsons: list[str] = field(default_factory=list)
    input_jsons: list[str] = field(default_factory=list)
    interact_jsons: list[str] = field(default_factory=list)
    video_jsons: list[str] = field(default_factory=list)
    asset_dirs: list[str] = field(default_factory=list)
    asset_file_count: int = 0
    data_slot_count: int = 0
    nonvolatile_slot_count: int = 0
    deferred_slot_count: int = 0
    required_slot_count: int = 0
    video_modes: list[str] = field(default_factory=list)
    sv_files: int = 0
    v_files: int = 0
    vhdl_files: int = 0
    qip_files: int = 0
    uses_pll: bool = False
    uses_altsyncram: bool = False
    uses_dcfifo: bool = False
    uses_sdram: bool = False
    uses_ddr: bool = False
    apf_ports: list[str] = field(default_factory=list)
    missing_apf_ports: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def discover_cores(roots: list[Path], profiles_dir: Path | None = None) -> dict[str, Any]:
    resolved_roots = [root.expanduser().resolve() for root in roots]
    profile_by_root = load_profiles_by_root(profiles_dir) if profiles_dir else {}
    candidate_roots = find_candidate_roots(resolved_roots)

    cores = []
    for root in sorted(candidate_roots):
        source_root = matching_source_root(root, resolved_roots)
        inv = inspect_core(root, source_root=source_root, profile_by_root=profile_by_root)
        cores.append(inv)

    by_status = Counter(core.status for core in cores)
    by_git_state = Counter(core.git_state for core in cores)
    by_source = Counter(core.source_root for core in cores)
    profiled = sum(1 for core in cores if core.profiles)
    report = {
        "roots": [str(root) for root in resolved_roots],
        "core_count": len(cores),
        "profiled_count": profiled,
        "status_counts": dict(sorted(by_status.items())),
        "git_state_counts": dict(sorted(by_git_state.items())),
        "source_counts": dict(sorted(by_source.items())),
        "cores": [asdict(core) for core in cores],
    }
    return report


def write_discovery_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "cores.json"
    md_path = output_dir / "cores.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    md_path.write_text(render_markdown(report))
    return json_path, md_path


def load_profiles_by_root(profiles_dir: Path | None) -> dict[str, list[str]]:
    if not profiles_dir or not profiles_dir.exists():
        return {}
    out: dict[str, list[str]] = defaultdict(list)
    for path in sorted(profiles_dir.glob("*.json")):
        if path.name.startswith("invalid_"):
            continue
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        root_text = raw.get("root_default") or raw.get("root")
        if not root_text:
            continue
        root = Path(os.path.expanduser(os.path.expandvars(str(root_text)))).resolve()
        out[str(root)].append(str(raw.get("name") or path.stem))
    return dict(out)


def find_candidate_roots(roots: list[Path]) -> set[Path]:
    candidates: set[Path] = set()
    marker_names = {"core.json", "core_top.sv", "core_top.v", "ap_core.qsf"}
    skip_dirs = {".git", ".claude", "node_modules", "__pycache__", "build", "obj_dir", "output", ".venv"}

    for root in roots:
        if not root.exists():
            continue
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            current_path = Path(current)
            for filename in files:
                if filename not in marker_names:
                    continue
                path = current_path / filename
                candidate = root_from_marker(path)
                if candidate is not None:
                    candidates.add(candidate.resolve())
    return candidates


def root_from_marker(path: Path) -> Path | None:
    parts = path.parts
    for i, part in enumerate(parts):
        if part == "dist" and i + 2 < len(parts) and parts[i + 1] == "Cores":
            return Path(*parts[:i])
        if part == "pkg" and "Cores" in parts[i + 1:]:
            return Path(*parts[:i])
        if part == "src" and i + 2 < len(parts) and parts[i + 1] in {"fpga", "core"}:
            return Path(*parts[:i])
    if path.name == "ap_core.qsf":
        for i, part in enumerate(parts):
            if part == "src":
                return Path(*parts[:i])
    return None


def matching_source_root(root: Path, source_roots: list[Path]) -> str:
    best = ""
    for source in source_roots:
        try:
            root.relative_to(source)
        except ValueError:
            continue
        if len(str(source)) > len(best):
            best = str(source)
    return best or str(root.anchor)


def inspect_core(root: Path, source_root: str, profile_by_root: dict[str, list[str]]) -> CoreInventory:
    inv = CoreInventory(name=root.name, root=str(root), source_root=source_root)
    inv.profiles = sorted(profile_by_root.get(str(root.resolve()), []))

    inspect_git_state(root, inv)
    inv.top_files = rels(root, list(root.glob("src/fpga/core/core_top.sv")) + list(root.glob("src/fpga/core/core_top.v")) + list(root.glob("src/core/core_top.sv")) + list(root.glob("src/core/core_top.v")))
    inv.qsf_files = rels(root, list(root.glob("src/ap_core.qsf")) + list(root.glob("src/fpga/ap_core.qsf")) + list(root.glob("*.qsf")))
    core_dirs = find_core_dirs(root)
    inv.core_jsons = rels(root, [core_dir / "core.json" for core_dir in core_dirs if (core_dir / "core.json").exists()])
    inv.data_jsons = rels(root, [core_dir / "data.json" for core_dir in core_dirs if (core_dir / "data.json").exists()])
    inv.input_jsons = rels(root, [core_dir / "input.json" for core_dir in core_dirs if (core_dir / "input.json").exists()])
    inv.interact_jsons = rels(root, [core_dir / "interact.json" for core_dir in core_dirs if (core_dir / "interact.json").exists()])
    inv.video_jsons = rels(root, [core_dir / "video.json" for core_dir in core_dirs if (core_dir / "video.json").exists()])
    inv.core_ids = sorted({core_dir.name for core_dir in core_dirs})

    asset_dirs = [root / "dist" / "Assets", root / "Assets", root / "release" / "pocket" / "Assets"]
    existing_asset_dirs = [path for path in asset_dirs if path.exists()]
    inv.asset_dirs = rels(root, existing_asset_dirs)
    inv.asset_file_count = sum(1 for directory in existing_asset_dirs for item in directory.rglob("*") if item.is_file())

    inspect_metadata(root, inv)
    inspect_sources(root, inv)
    classify(inv)
    return inv


def inspect_git_state(root: Path, inv: CoreInventory) -> None:
    rev = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if rev.returncode != 0:
        inv.git_state = "no-git"
        return

    inv.git_root = rev.stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        text=True,
        capture_output=True,
    )
    if status.returncode != 0:
        inv.git_state = "unknown"
        return

    lines = [line for line in status.stdout.splitlines() if line.strip()]
    inv.git_dirty_count = len(lines)
    inv.git_dirty_paths = lines[:20]
    inv.git_state = "dirty" if lines else "clean"


def find_core_dirs(root: Path) -> list[Path]:
    core_dirs: set[Path] = set()
    for base in [root / "dist" / "Cores"]:
        if base.exists():
            core_dirs.update(path for path in base.iterdir() if path.is_dir())
    pkg = root / "pkg"
    if pkg.exists():
        for path in pkg.rglob("Cores"):
            if path.is_dir():
                core_dirs.update(child for child in path.iterdir() if child.is_dir())
    return sorted(core_dirs)


def inspect_metadata(root: Path, inv: CoreInventory) -> None:
    for rel in inv.data_jsons:
        data = read_json(root / rel)
        slots = list(find_slot_objects(data))
        inv.data_slot_count += len(slots)
        for slot in slots:
            if bool(slot.get("nonvolatile") or slot.get("save") or slot.get("savefile")):
                inv.nonvolatile_slot_count += 1
            if bool(slot.get("deferload") or slot.get("deferred") or slot.get("defer")):
                inv.deferred_slot_count += 1
            if slot.get("required", True):
                inv.required_slot_count += 1

    for rel in inv.video_jsons:
        data = read_json(root / rel)
        for width, height in find_video_modes(data):
            mode = f"{width}x{height}"
            if mode not in inv.video_modes:
                inv.video_modes.append(mode)


def inspect_sources(root: Path, inv: CoreInventory) -> None:
    source_roots = [path for path in [root / "src" / "fpga", root / "src" / "core", root / "target" / "pocket"] if path.exists()]
    text_samples: list[str] = []
    for source_root in source_roots:
        for path in source_root.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix == ".sv":
                inv.sv_files += 1
            elif suffix == ".v":
                inv.v_files += 1
            elif suffix in {".vhd", ".vhdl"}:
                inv.vhdl_files += 1
            elif suffix == ".qip":
                inv.qip_files += 1
            if suffix in {".sv", ".v", ".vh", ".svh"} and len(text_samples) < 200:
                try:
                    text_samples.append(path.read_text(errors="ignore")[:200000])
                except OSError:
                    pass
    text = "\n".join(text_samples)
    lower_text = text.lower()
    inv.uses_pll = "mf_pllbase" in text or "altpll" in text or "pll" in lower_text
    inv.uses_altsyncram = "altsyncram" in text
    inv.uses_dcfifo = "dcfifo" in text
    inv.uses_sdram = "sdram" in lower_text
    inv.uses_ddr = any(token in lower_text for token in ["ddr_", " ddr", "\nddr", "ddram", "lpddr"])

    top_text = ""
    for rel in inv.top_files[:2]:
        try:
            top_text += (root / rel).read_text(errors="ignore") + "\n"
        except OSError:
            pass
    required = [
        "clk_74a", "clk_74b", "bridge_addr", "bridge_rd", "bridge_wr",
        "bridge_wr_data", "bridge_rd_data", "bridge_endian_little",
        "video_rgb_clock", "video_rgb", "video_de", "video_hs", "video_vs",
        "audio_mclk", "audio_lrck", "audio_dac", "cont1_key",
    ]
    inv.apf_ports = [port for port in required if port in top_text]
    inv.missing_apf_ports = [port for port in required if port not in top_text]


def classify(inv: CoreInventory) -> None:
    if inv.profiles:
        inv.status = "profiled"
        inv.action = "run existing apfsim profile"
    elif not inv.top_files:
        inv.status = "package-only" if inv.core_jsons else "no-core-top"
        inv.action = "locate generated Pocket RTL/source top before Verilator profile"
    elif len(inv.missing_apf_ports) > 4:
        inv.status = "needs-apf-shell-review"
        inv.action = "inspect top-level APF shell/port naming before profile generation"
    elif inv.vhdl_files:
        inv.status = "needs-vhdl-shims"
        inv.action = "add Verilog sim stubs or generated wrappers for VHDL-only blocks"
    elif inv.uses_sdram or inv.uses_ddr:
        inv.status = "needs-memory-model"
        inv.action = "add transactional SDRAM/DDR model before expecting gameplay frames"
    elif inv.uses_pll or inv.uses_altsyncram or inv.uses_dcfifo or inv.qip_files:
        inv.status = "needs-ip-shims"
        inv.action = "verify existing RTL shims cover vendor IP, then generate filelist/profile"
    else:
        inv.status = "candidate"
        inv.action = "generate filelist/profile and run lint/build"

    if not inv.core_jsons:
        inv.notes.append("missing core.json metadata")
    if not inv.video_jsons:
        inv.notes.append("missing video.json metadata")
    if inv.data_slot_count and inv.asset_file_count == 0:
        inv.notes.append("data slots declared but no local dist/Assets files found")
    if inv.nonvolatile_slot_count:
        inv.notes.append(f"{inv.nonvolatile_slot_count} nonvolatile slot(s)")


def rels(root: Path, paths: list[Path]) -> list[str]:
    out = []
    for path in paths:
        try:
            out.append(str(path.resolve().relative_to(root.resolve())))
        except ValueError:
            out.append(str(path))
    return sorted(dict.fromkeys(out))


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def find_slot_objects(data: Any) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    if isinstance(data, dict):
        if ("id" in data or "slot" in data) and ("address" in data or "loadaddress" in data or "filename" in data or "name" in data):
            slots.append(data)
        for key, value in data.items():
            if key.lower() in {"data", "slots", "data_slots", "dataslots"} or isinstance(value, (dict, list)):
                slots.extend(find_slot_objects(value))
    elif isinstance(data, list):
        for item in data:
            slots.extend(find_slot_objects(item))
    return slots


def find_video_modes(data: Any) -> list[tuple[int, int]]:
    modes: list[tuple[int, int]] = []
    if isinstance(data, dict):
        width = int_value(data.get("width") or data.get("active_width") or data.get("expected_width"))
        height = int_value(data.get("height") or data.get("active_height") or data.get("expected_height"))
        if width and height:
            modes.append((width, height))
        for value in data.values():
            if isinstance(value, (dict, list)):
                modes.extend(find_video_modes(value))
    elif isinstance(data, list):
        for item in data:
            modes.extend(find_video_modes(item))
    return list(dict.fromkeys(modes))


def int_value(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return 0
    return 0


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# APFSIM Core Inventory",
        "",
        f"Core roots scanned: {len(report['roots'])}",
        f"Core candidates found: {report['core_count']}",
        f"Already profiled: {report['profiled_count']}",
        "",
        "## Roots",
        "",
    ]
    for root in report["roots"]:
        lines.append(f"- `{root}`")
    lines.extend(["", "## Status Counts", ""])
    for status, count in sorted(report["status_counts"].items()):
        lines.append(f"- `{status}`: {count}")
    lines.extend(["", "## Git State Counts", ""])
    for state, count in sorted(report.get("git_state_counts", {}).items()):
        lines.append(f"- `{state}`: {count}")

    lines.extend(["", "## Next Profile Candidates", ""])
    candidates = [core for core in report["cores"] if core["status"] in {"candidate", "needs-ip-shims", "needs-memory-model", "needs-vhdl-shims"}]
    priority = {"candidate": 0, "needs-ip-shims": 1, "needs-vhdl-shims": 2, "needs-memory-model": 3}
    for core in sorted(candidates, key=lambda item: (priority.get(item["status"], 9), item["name"]))[:30]:
        ids = ", ".join(core["core_ids"]) or "-"
        video = ", ".join(core["video_modes"]) or "-"
        lines.append(f"- `{core['name']}` ({core['status']}, git={core.get('git_state', 'unknown')}): ids={ids}; video={video}; action={core['action']}")

    lines.extend([
        "",
        "## All Cores",
        "",
        "| Core | IDs | Profiles | Status | Git | Video | Data Slots | HDL | Action |",
        "| --- | --- | --- | --- | --- | --- | ---: | --- | --- |",
    ])
    for core in sorted(report["cores"], key=lambda item: (item["source_root"], item["name"])):
        ids = "<br>".join(core["core_ids"]) or "-"
        profiles = ", ".join(core["profiles"]) or "-"
        video = ", ".join(core["video_modes"]) or "-"
        git = core.get("git_state", "unknown")
        dirty_count = int(core.get("git_dirty_count") or 0)
        if dirty_count:
            git = f"{git} ({dirty_count})"
        hdl = f"sv={core['sv_files']} v={core['v_files']} vhdl={core['vhdl_files']}"
        action = core["action"].replace("|", "/")
        root_link = core["root"]
        lines.append(
            f"| `{core['name']}`<br>`{root_link}` | {ids} | {profiles} | `{core['status']}` | `{git}` | {video} | "
            f"{core['data_slot_count']} | {hdl} | {action} |"
        )
    lines.append("")
    return "\n".join(lines)
