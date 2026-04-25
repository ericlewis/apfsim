#!/usr/bin/env python3
"""Profile-driven APF Verilator regression gate."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from artifact_validator import ArtifactValidationError, annotate_result_phases, validate_artifacts
from corpus_runner import run_corpus_manifest
from core_discovery import DEFAULT_DISCOVERY_ROOTS, discover_cores, write_discovery_report
from diagnostics import write_diagnostics
from log_analyzer import analyze_logs, write_json_report
from memory_attribution import build_rom_validation
from package_validator import write_package_check
from profile_generator import generate_profile_candidate
from run_summary import write_summary
from source_intake import build_source_contract, write_source_contract
from wrapper_synthesizer import synthesize_wrapper_profile

APFSIM_DIR = Path(__file__).resolve().parents[1]
PROFILES_DIR = APFSIM_DIR / "profiles"
CATALOGS_DIR = APFSIM_DIR / "catalogs"
DEFAULT_SHIM_CATALOG = CATALOGS_DIR / "shims.json"
SKIP_EXIT = 77


class ApfSimError(RuntimeError):
    def __init__(self, message: str, phase: str = "preflight"):
        super().__init__(message)
        self.phase = phase


class ProfileSkipped(RuntimeError):
    pass


@dataclass
class Profile:
    name: str
    path: Path
    raw: dict[str, Any]
    root: Path | None

    @property
    def kind(self) -> str:
        return str(self.raw.get("kind", "verilator"))

    @property
    def top(self) -> str:
        return str(self.raw["top"])

    @property
    def build_dir(self) -> Path:
        return resolve_path(self.raw.get("build_dir", f"build/profiles/{self.name}/obj"), self)

    @property
    def artifact_root(self) -> Path:
        return resolve_path(self.raw.get("artifact_root", f"build/profiles/{self.name}/run"), self)

    @property
    def filelist(self) -> Path:
        return resolve_path(self.raw["filelist"], self)

    @property
    def scenario(self) -> Path:
        return resolve_path(self.raw["scenario"], self)

    @property
    def core_id(self) -> str:
        if self.raw.get("core_id"):
            return str(self.raw["core_id"])
        env_name = self.raw.get("core_id_env")
        if env_name and os.environ.get(str(env_name)):
            return os.environ[str(env_name)]
        return ""


def eprint(*args: object, **kwargs: Any) -> None:
    print(*args, file=sys.stderr, **kwargs)


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open() as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise ApfSimError(f"profile not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ApfSimError(f"invalid JSON profile {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ApfSimError(f"profile must be a JSON object: {path}")
    return data


def profile_path(name_or_path: str) -> Path:
    path = Path(name_or_path)
    if path.exists() or path.suffix == ".json" or "/" in name_or_path:
        return path if path.is_absolute() else (Path.cwd() / path).resolve()
    return PROFILES_DIR / f"{name_or_path}.json"


def profile_root(raw: dict[str, Any]) -> Path | None:
    if "root" in raw:
        return Path(os.path.expanduser(os.path.expandvars(str(raw["root"]))))
    env_name = raw.get("root_env")
    if env_name and os.environ.get(str(env_name)):
        return Path(os.path.expanduser(os.path.expandvars(os.environ[str(env_name)])))
    for alt_env in raw.get("root_env_alternates", []):
        if alt_env and os.environ.get(str(alt_env)):
            return Path(os.path.expanduser(os.path.expandvars(os.environ[str(alt_env)])))
    if "root_default" in raw:
        return Path(os.path.expanduser(os.path.expandvars(str(raw["root_default"]))))
    return None


def load_profile(name_or_path: str) -> Profile:
    path = profile_path(name_or_path)
    raw = load_json(path)
    name = str(raw.get("name") or path.stem)
    raw = expand_profile_shim_catalog(raw, name)
    return Profile(name=name, path=path, raw=raw, root=profile_root(raw))


def load_profile_with_root(name_or_path: str, root: Path) -> Profile:
    path = profile_path(name_or_path)
    raw = load_json(path)
    raw["root"] = str(root)
    name = str(raw.get("name") or path.stem)
    raw = expand_profile_shim_catalog(raw, name)
    return Profile(name=name, path=path, raw=raw, root=root)


def resolve_path(value: str | os.PathLike[str], profile: Profile | None = None) -> Path:
    text = str(value)
    root = profile.root if profile and profile.root else APFSIM_DIR
    profile_name = profile.name if profile else ""
    core_id = profile.core_id if profile else ""
    profile_dir = profile.path.parent if profile else APFSIM_DIR
    text = (
        text.replace("{apfsim}", str(APFSIM_DIR))
        .replace("{root}", str(root))
        .replace("{profile}", profile_name)
        .replace("{profile_dir}", str(profile_dir))
        .replace("{core_id}", core_id)
    )
    text = os.path.expanduser(os.path.expandvars(text))
    path = Path(text)
    if path.is_absolute():
        return path
    return (APFSIM_DIR / path).resolve()


def expand_profile_text(text: str, profile: Profile) -> str:
    root = profile.root if profile.root else APFSIM_DIR
    return os.path.expanduser(
        os.path.expandvars(
            text.replace("{apfsim}", str(APFSIM_DIR))
            .replace("{root}", str(root))
            .replace("{profile}", profile.name)
            .replace("{profile_dir}", str(profile.path.parent))
            .replace("{core_id}", profile.core_id)
        )
    )


def materialize_profile_text_file(profile: Profile, source: Path, kind: str) -> Path:
    text = source.read_text()
    expanded = expand_profile_text(text, profile)
    if expanded == text:
        return source
    dest = profile.build_dir / f"{kind}.resolved{source.suffix or '.txt'}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(expanded)
    return dest


def build_filelist_path(profile: Profile) -> Path:
    return materialize_profile_text_file(profile, profile.filelist, "filelist")


def runtime_scenario_path(profile: Profile, scenario: Path) -> Path:
    return materialize_profile_text_file(profile, scenario, "scenario")


def load_shim_catalog(path: Path = DEFAULT_SHIM_CATALOG) -> dict[str, dict[str, Any]]:
    data = load_json(path)
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ApfSimError(f"shim catalog must contain an entries list: {path}", phase="preflight")
    out: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("name"):
            raise ApfSimError(f"shim catalog entry missing name: {path}", phase="preflight")
        out[str(entry["name"])] = entry
    return out


def expand_profile_shim_catalog(raw: dict[str, Any], profile_name: str) -> dict[str, Any]:
    specs = raw.get("shim_catalog", [])
    if not specs:
        return raw
    if not isinstance(specs, list):
        raise ApfSimError("profile shim_catalog must be a list", phase="preflight")
    catalog_path = resolve_catalog_path(raw.get("shim_catalog_file", str(DEFAULT_SHIM_CATALOG)), raw, profile_name)
    catalog = load_shim_catalog(catalog_path)
    expanded = dict(raw)
    generated_files = list(expanded.get("generated_files", []))
    required_paths = list(expanded.get("required_paths", []))
    verilator_flags = list(expanded.get("verilator_flags", []))
    expected_artifacts = list(expanded.get("expected_artifacts", []))
    runtime_cwd = expanded.get("runtime_cwd")
    catalog_expanded: list[dict[str, Any]] = []

    for spec in specs:
        if isinstance(spec, str):
            name = spec
            variables: dict[str, Any] = {}
        elif isinstance(spec, dict):
            name = str(spec.get("name", ""))
            variables = dict(spec.get("vars", {}))
        else:
            raise ApfSimError("shim_catalog entries must be names or objects", phase="preflight")
        if not name or name not in catalog:
            raise ApfSimError(f"unknown shim catalog entry: {name}", phase="preflight")
        entry = catalog[name]
        catalog_source = select_catalog_source(entry, expanded, profile_name, variables)
        context = {"catalog_source": catalog_source, **{str(k): str(v) for k, v in variables.items()}}

        for item in entry.get("generated_files", []):
            if not isinstance(item, dict):
                continue
            generated = expand_catalog_value(item, expanded, profile_name, context)
            if isinstance(generated, dict):
                generated["catalog_entry"] = name
                generated_files.append(generated)
        for value in entry.get("required_paths", []):
            required_paths.append(str(expand_catalog_value(value, expanded, profile_name, context)))
        for value in entry.get("verilator_flags", []):
            verilator_flags.append(str(expand_catalog_value(value, expanded, profile_name, context)))
        for value in entry.get("expected_artifacts", []):
            expected_artifacts.append(str(expand_catalog_value(value, expanded, profile_name, context)))
        if not runtime_cwd and entry.get("runtime_cwd"):
            runtime_cwd = str(expand_catalog_value(entry["runtime_cwd"], expanded, profile_name, context))
        catalog_expanded.append({
            "name": name,
            "description": entry.get("description", ""),
            "kind": entry.get("kind", ""),
            "confidence": entry.get("confidence", ""),
            "modules": entry.get("modules", []),
            "memory_classes": entry.get("memory_classes", []),
            "diagnostic_codes": entry.get("diagnostic_codes", []),
            "catalog_source": catalog_source,
            "generated_files": len(entry.get("generated_files", [])),
        })

    expanded["generated_files"] = dedupe_generated_files(generated_files)
    expanded["required_paths"] = dedupe_strings(required_paths)
    expanded["verilator_flags"] = dedupe_strings(verilator_flags)
    expanded["expected_artifacts"] = dedupe_strings(expected_artifacts)
    if runtime_cwd:
        expanded["runtime_cwd"] = str(runtime_cwd)
    expanded["shim_catalog_expanded"] = catalog_expanded
    return expanded


def resolve_catalog_path(value: str, raw: dict[str, Any], profile_name: str) -> Path:
    text = expand_catalog_string(str(value), raw, profile_name, {})
    path = Path(os.path.expanduser(os.path.expandvars(text)))
    if path.is_absolute():
        return path
    return (APFSIM_DIR / path).resolve()


def select_catalog_source(entry: dict[str, Any], raw: dict[str, Any], profile_name: str, variables: dict[str, Any]) -> str:
    candidates = entry.get("source_candidates", [])
    if not isinstance(candidates, list) or not candidates:
        return ""
    first = ""
    context = {str(k): str(v) for k, v in variables.items()}
    for candidate in candidates:
        expanded = expand_catalog_string(str(candidate), raw, profile_name, context)
        path = Path(os.path.expanduser(os.path.expandvars(expanded)))
        if not path.is_absolute():
            path = APFSIM_DIR / path
        if not first:
            first = str(path)
        if path.exists():
            return str(path)
    return first


def expand_catalog_value(value: Any, raw: dict[str, Any], profile_name: str, context: dict[str, str]) -> Any:
    if isinstance(value, str):
        return expand_catalog_string(value, raw, profile_name, context)
    if isinstance(value, list):
        return [expand_catalog_value(item, raw, profile_name, context) for item in value]
    if isinstance(value, dict):
        return {key: expand_catalog_value(item, raw, profile_name, context) for key, item in value.items()}
    return value


def expand_catalog_string(value: str, raw: dict[str, Any], profile_name: str, context: dict[str, str]) -> str:
    root = profile_root(raw) or APFSIM_DIR
    text = value.replace("{apfsim}", str(APFSIM_DIR)).replace("{root}", str(root)).replace("{profile}", profile_name)
    for key, item in context.items():
        text = text.replace("{" + key + "}", item)
    return os.path.expanduser(os.path.expandvars(text))


def dedupe_strings(values: list[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        text = str(value)
        if text not in out:
            out.append(text)
    return out


def dedupe_generated_files(values: list[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[tuple[str, str, str]] = set()
    for value in values:
        if isinstance(value, dict):
            key = (str(value.get("type", "")), str(value.get("source", "")), str(value.get("dest", "")))
            if key in seen:
                continue
            seen.add(key)
        out.append(value)
    return out


def memory_activity_top_port_classes(profile: Profile) -> list[str]:
    cfg = profile.raw.get("memory_activity") if isinstance(profile.raw.get("memory_activity"), dict) else {}
    values = cfg.get("top_port_classes", profile.raw.get("memory_activity_top_port_classes", []))
    if isinstance(values, str):
        values = [values]
    allowed = {"sram", "psram", "cram", "sdram"}
    return [cls for cls in dedupe_strings(list(values) if isinstance(values, list) else []) if cls in allowed]


def require_keys(profile: Profile, keys: list[str]) -> None:
    missing = [key for key in keys if key not in profile.raw]
    if missing:
        raise ApfSimError(f"profile {profile.name} missing required key(s): {', '.join(missing)}")


def parse_scenario_files(path: Path, profile: Profile | None = None) -> list[Path]:
    files: list[Path] = []
    if not path.exists():
        return files
    section = ""
    in_slot = False
    for raw in path.read_text().splitlines():
        stripped = raw.split("#", 1)[0].strip()
        if not stripped:
            continue
        if not raw.startswith(" ") and stripped.endswith(":"):
            section = stripped[:-1]
            in_slot = False
            continue
        if section == "data_slots":
            if stripped.startswith("-"):
                in_slot = True
                stripped = stripped[1:].strip()
            if in_slot and stripped.startswith("file:"):
                value = stripped.split(":", 1)[1].strip().strip("'\"")
                if value:
                    if profile is not None:
                        value = expand_profile_text(value, profile)
                    candidate = Path(os.path.expanduser(os.path.expandvars(value)))
                    files.append(candidate if candidate.is_absolute() else (APFSIM_DIR / candidate).resolve())
    return files


def preflight(profile: Profile, check_assets: bool = True) -> None:
    if profile.kind != "verilator":
        raise ApfSimError(f"profile {profile.name} has unsupported kind: {profile.kind}")
    require_keys(profile, ["top", "filelist", "scenario"])
    if profile.raw.get("external") and (profile.root is None or not profile.root.exists()):
        root_text = str(profile.root) if profile.root else "<unset>"
        raise ProfileSkipped(f"profile {profile.name} skipped: external root missing: {root_text}")
    if profile.raw.get("external") and profile.raw.get("core_id_env") and not profile.core_id:
        raise ProfileSkipped(f"profile {profile.name} skipped: core id env missing: {profile.raw['core_id_env']}")

    paths: list[tuple[str, Path]] = [
        ("filelist", profile.filelist),
        ("scenario", profile.scenario),
    ]
    for key, value in dict(profile.raw.get("metadata_jsons", {})).items():
        if value:
            paths.append((f"metadata_jsons.{key}", resolve_path(value, profile)))
    for i, value in enumerate(profile.raw.get("required_paths", [])):
        paths.append((f"required_paths[{i}]", resolve_path(value, profile)))
    for i, item in enumerate(profile.raw.get("generated_files", [])):
        if item.get("source"):
            paths.append((f"generated_files[{i}].source", resolve_path(item["source"], profile)))

    missing = [f"{label}: {path}" for label, path in paths if not path.exists()]
    if check_assets:
        for asset in parse_scenario_files(profile.scenario, profile):
            if not asset.exists():
                missing.append(f"scenario data slot file: {asset}")
    if missing:
        raise ApfSimError("preflight failed; missing path(s):\n" + "\n".join(f"  - {m}" for m in missing))

def generate_files(profile: Profile) -> None:
    for item in profile.raw.get("generated_files", []):
        kind = item.get("type")
        source = resolve_path(item["source"], profile)
        dest = resolve_path(item["dest"], profile)
        original = source.read_text()
        if kind == "rename_module":
            needle = str(item.get("from", "module core_top"))
            replacement = str(item.get("to", "module core_top_impl"))
            replacements = [(needle, replacement)]
        elif kind in {"text_replace", "copy_replace"}:
            replacements = [(str(rep["from"]), str(rep["to"])) for rep in item.get("replacements", [])]
            if not replacements:
                raise ApfSimError(f"cannot generate {dest}: no replacements configured")
        else:
            raise ApfSimError(f"unsupported generated_files type for {profile.name}: {kind}")
        generated = original
        for needle, replacement in replacements:
            if needle not in generated:
                raise ApfSimError(f"cannot generate {dest}: source does not contain {needle!r}")
            generated = generated.replace(needle, replacement, 1)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(generated)


def sdl2_flags() -> tuple[str, str]:
    sdl2_config = shutil.which("sdl2-config")
    if not sdl2_config:
        raise ApfSimError("SDL2 is required for apfsim play; install sdl2 so sdl2-config is on PATH", phase="preflight")
    cflags = subprocess.check_output([sdl2_config, "--cflags"], text=True).strip()
    libs = subprocess.check_output([sdl2_config, "--libs"], text=True).strip()
    return cflags, libs


def verilator_base_args(profile: Profile, waves: bool = False, sdl: bool = False) -> list[str]:
    cflags = "-std=c++20 -O2 -Icpp"
    for cls in memory_activity_top_port_classes(profile):
        cflags = f"{cflags} -DAPFSIM_MEMORY_COUNTER_{cls.upper()}=1"
    ldflags: str | None = None
    if sdl:
        sdl_cflags, sdl_libs = sdl2_flags()
        cflags = f"{cflags} -DAPFSIM_ENABLE_SDL=1 {sdl_cflags}"
        ldflags = sdl_libs
    args = [
        os.environ.get("VERILATOR", "verilator"),
        "--cc",
        "--exe",
        "cpp/main.cpp",
        "--top-module",
        profile.top,
        "--Mdir",
        str(profile.build_dir),
        "-f",
        str(build_filelist_path(profile)),
        "-Irtl_shims",
        "-Wno-fatal",
        "--assert",
        "-CFLAGS",
        cflags,
    ]
    if ldflags:
        args.extend(["-LDFLAGS", ldflags])
    args.extend(str(flag) for flag in profile.raw.get("verilator_flags", []))
    if waves:
        args.extend(["--trace", "--trace-fst", "--trace-structs"])
    args.append("--build")
    return args


def run_command(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd or APFSIM_DIR, env=env, text=True, capture_output=True, timeout=timeout)


def print_completed(proc: subprocess.CompletedProcess[str]) -> None:
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        eprint(proc.stderr, end="")


def build_profile(profile: Profile, waves: bool = False, sdl: bool = False) -> int:
    preflight(profile)
    generate_files(profile)
    profile.build_dir.mkdir(parents=True, exist_ok=True)
    proc = run_command(verilator_base_args(profile, waves=waves, sdl=sdl), timeout=600)
    print_completed(proc)
    return proc.returncode


def run_profile(args: argparse.Namespace, profile: Profile) -> int:
    preflight(profile)
    if not args.no_build:
        rc = build_profile(profile, waves=args.waves)
        if rc != 0:
            return rc
    artifact_root = resolve_path(args.artifacts, profile) if args.artifacts else profile.artifact_root
    if args.clean_artifacts and artifact_root.exists():
        shutil.rmtree(artifact_root)
    (artifact_root / "video").mkdir(parents=True, exist_ok=True)
    (artifact_root / "audio").mkdir(parents=True, exist_ok=True)
    (artifact_root / "saves").mkdir(parents=True, exist_ok=True)
    (artifact_root / "savestates").mkdir(parents=True, exist_ok=True)

    binary = profile.build_dir / f"V{profile.top}"
    if not binary.exists():
        raise ApfSimError(f"built simulator not found: {binary}", phase="build")

    scenario = resolve_path(args.scenario, profile) if args.scenario else profile.scenario
    scenario = runtime_scenario_path(profile, scenario)
    frames = args.frames if args.frames is not None else int(profile.raw.get("frames", 0) or 0)
    timeout_cycles = args.timeout_cycles if args.timeout_cycles is not None else int(profile.raw.get("timeout_cycles", 0) or 0)
    cmd = [
        str(binary),
        "--scenario", str(scenario),
        "--dump-frames", str(artifact_root / "video"),
        "--dump-audio", str(artifact_root / "audio" / "out.wav"),
        "--audio-stats", str(artifact_root / "audio" / "stats.json"),
        "--dump-saves", str(artifact_root / "saves"),
        "--dump-savestates", str(artifact_root / "savestates"),
        "--result-json", str(artifact_root / "result.json"),
        "--bridge-log", str(artifact_root / "bridge.log"),
        "--bridge-summary", str(artifact_root / "bridge_summary.json"),
        "--video-shape-json", str(artifact_root / "video_shape.json"),
    ]
    for key, value in dict(profile.raw.get("metadata_jsons", {})).items():
        if value:
            cmd.extend([f"--{key}", str(resolve_path(value, profile))])
    if frames:
        cmd.extend(["--frames", str(frames)])
    if timeout_cycles:
        cmd.extend(["--timeout-cycles", str(timeout_cycles)])
    write_idle = args.write_idle_cycles if args.write_idle_cycles is not None else profile.raw.get("write_idle_cycles")
    if write_idle is not None:
        cmd.extend(["--write-idle-cycles", str(write_idle)])
    read_latency = args.bridge_read_latency_cycles if args.bridge_read_latency_cycles is not None else profile.raw.get("bridge_read_latency_cycles")
    if read_latency is not None:
        cmd.extend(["--bridge-read-latency-cycles", str(read_latency)])
    write_strobe = args.bridge_write_strobe_cycles if args.bridge_write_strobe_cycles is not None else profile.raw.get("bridge_write_strobe_cycles")
    if write_strobe is not None:
        cmd.extend(["--bridge-write-strobe-cycles", str(write_strobe)])
    bridge_endian = args.bridge_endian or profile.raw.get("bridge_endian")
    if bridge_endian:
        cmd.extend(["--bridge-endian", str(bridge_endian)])
    target_service_interval = args.target_service_interval_cycles
    if target_service_interval is None:
        target_service_interval = profile.raw.get("target_service_interval_cycles")
    if target_service_interval is not None:
        cmd.extend(["--target-service-interval-cycles", str(target_service_interval)])
    if args.interact_no_verify or profile.raw.get("interact_verify_readback") is False:
        cmd.append("--interact-no-verify")
    if args.bridge_trace or profile.raw.get("bridge_trace"):
        cmd.extend(["--bridge-trace", str(artifact_root / "bridge_transactions.jsonl")])
    for slot in args.slot or []:
        cmd.extend(["--slot", slot])
    if args.verbose_bridge:
        cmd.append("--verbose-bridge")

    env = os.environ.copy()
    if args.waves:
        env["APFSIM_WAVES"] = "1"
        env.setdefault("APFSIM_WAVE_PATH", str(artifact_root / "dump.fst"))
    runtime_cwd = resolve_path(profile.raw["runtime_cwd"], profile) if profile.raw.get("runtime_cwd") else APFSIM_DIR
    proc = run_command(cmd, env=env, timeout=args.timeout, cwd=runtime_cwd)
    print_completed(proc)
    if proc.returncode != 0:
        annotate_result_phases(artifact_root)
        write_profile_diagnostics(profile, artifact_root)
        print_failure_hint(artifact_root)
    else:
        try:
            validate_runtime_artifacts(profile, artifact_root)
            validate_expected_artifacts(profile, artifact_root)
        finally:
            write_profile_diagnostics(profile, artifact_root)
    return proc.returncode

def cmd_play(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    preflight(profile)
    if profile.kind != "verilator":
        raise ApfSimError(f"play requires a verilator profile, got {profile.kind}")
    if not args.no_build:
        rc = build_profile(profile, waves=args.waves, sdl=True)
        if rc != 0:
            return rc

    artifact_root = resolve_path(args.artifacts, profile) if args.artifacts else APFSIM_DIR / "output" / f"{profile.name}-play"
    if args.clean_artifacts and artifact_root.exists():
        shutil.rmtree(artifact_root)
    (artifact_root / "audio").mkdir(parents=True, exist_ok=True)
    (artifact_root / "saves").mkdir(parents=True, exist_ok=True)
    (artifact_root / "savestates").mkdir(parents=True, exist_ok=True)

    binary = profile.build_dir / f"V{profile.top}"
    if not binary.exists():
        raise ApfSimError(f"built simulator not found: {binary}", phase="build")

    scenario = resolve_path(args.scenario, profile) if args.scenario else profile.scenario
    scenario = runtime_scenario_path(profile, scenario)
    timeout_cycles = args.timeout_cycles if args.timeout_cycles is not None else int(profile.raw.get("timeout_cycles", 0) or 0)
    cmd = [
        str(binary),
        "--interactive",
        "--scenario", str(scenario),
        "--dump-audio", str(artifact_root / "audio" / "out.wav"),
        "--audio-stats", str(artifact_root / "audio" / "stats.json"),
        "--dump-saves", str(artifact_root / "saves"),
        "--dump-savestates", str(artifact_root / "savestates"),
        "--result-json", str(artifact_root / "result.json"),
        "--bridge-log", str(artifact_root / "bridge.log"),
        "--bridge-summary", str(artifact_root / "bridge_summary.json"),
        "--video-shape-json", str(artifact_root / "video_shape.json"),
        "--play-scale", str(args.scale),
        "--play-speed-percent", str(args.speed_percent),
    ]
    for key, value in dict(profile.raw.get("metadata_jsons", {})).items():
        if value:
            cmd.extend([f"--{key}", str(resolve_path(value, profile))])
    if timeout_cycles:
        cmd.extend(["--timeout-cycles", str(timeout_cycles)])
    write_idle = args.write_idle_cycles if args.write_idle_cycles is not None else profile.raw.get("write_idle_cycles")
    if write_idle is not None:
        cmd.extend(["--write-idle-cycles", str(write_idle)])
    read_latency = args.bridge_read_latency_cycles if args.bridge_read_latency_cycles is not None else profile.raw.get("bridge_read_latency_cycles")
    if read_latency is not None:
        cmd.extend(["--bridge-read-latency-cycles", str(read_latency)])
    write_strobe = args.bridge_write_strobe_cycles if args.bridge_write_strobe_cycles is not None else profile.raw.get("bridge_write_strobe_cycles")
    if write_strobe is not None:
        cmd.extend(["--bridge-write-strobe-cycles", str(write_strobe)])
    bridge_endian = args.bridge_endian or profile.raw.get("bridge_endian")
    if bridge_endian:
        cmd.extend(["--bridge-endian", str(bridge_endian)])
    target_service_interval = args.target_service_interval_cycles
    if target_service_interval is None:
        target_service_interval = profile.raw.get("target_service_interval_cycles")
    if target_service_interval is not None:
        cmd.extend(["--target-service-interval-cycles", str(target_service_interval)])
    if args.interact_no_verify or profile.raw.get("interact_verify_readback") is False:
        cmd.append("--interact-no-verify")
    if args.bridge_trace or profile.raw.get("bridge_trace"):
        cmd.extend(["--bridge-trace", str(artifact_root / "bridge_transactions.jsonl")])
    for slot in args.slot or []:
        cmd.extend(["--slot", slot])
    if args.verbose_bridge:
        cmd.append("--verbose-bridge")

    env = os.environ.copy()
    if args.waves:
        env["APFSIM_WAVES"] = "1"
        env.setdefault("APFSIM_WAVE_PATH", str(artifact_root / "dump.fst"))
    runtime_cwd = resolve_path(profile.raw["runtime_cwd"], profile) if profile.raw.get("runtime_cwd") else APFSIM_DIR
    timeout = args.timeout if args.timeout and args.timeout > 0 else None
    try:
        proc = subprocess.run(cmd, cwd=runtime_cwd, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        print_failure_hint(artifact_root)
        eprint(f"apfsim play timed out after {timeout}s")
        return 124
    if proc.returncode != 0:
        annotate_result_phases(artifact_root)
        write_profile_diagnostics(profile, artifact_root)
        print_failure_hint(artifact_root)
    else:
        try:
            validate_runtime_artifacts(profile, artifact_root)
        finally:
            write_profile_diagnostics(profile, artifact_root)
        print(f"apfsim play artifacts: {artifact_root}")
    return proc.returncode


def diagnostic_profile_raw(profile: Profile) -> dict[str, Any]:
    raw = dict(profile.raw)
    if profile.root:
        raw.setdefault("root", str(profile.root))
    return raw


def profile_video_metadata_path(profile: Profile) -> Path | None:
    video_metadata = dict(profile.raw.get("metadata_jsons", {})).get("video")
    return resolve_path(video_metadata, profile) if video_metadata else None


def write_profile_diagnostics(profile: Profile, artifact_root: Path) -> dict[str, Any] | None:
    try:
        write_source_provenance(profile, artifact_root)
        return write_diagnostics(
            artifact_root,
            profile=diagnostic_profile_raw(profile),
            video_metadata_path=profile_video_metadata_path(profile),
        )
    except Exception as exc:
        eprint(f"apfsim diagnostics warning: {exc}")
        return None


def write_source_provenance(profile: Profile, artifact_root: Path) -> dict[str, Any]:
    shimmed_modules: list[dict[str, Any]] = []
    for entry in profile.raw.get("shim_catalog_expanded", []):
        if not isinstance(entry, dict):
            continue
        shimmed_modules.append({
            "name": entry.get("name", ""),
            "description": entry.get("description", ""),
            "kind": entry.get("kind", ""),
            "confidence": entry.get("confidence", ""),
            "modules": entry.get("modules", []),
            "memory_classes": entry.get("memory_classes", []),
            "diagnostic_codes": entry.get("diagnostic_codes", []),
            "catalog_source": entry.get("catalog_source", ""),
            "generated_files": entry.get("generated_files", 0),
        })
    generated_files = []
    for item in profile.raw.get("generated_files", []):
        if not isinstance(item, dict):
            continue
        generated_files.append({
            "type": item.get("type", ""),
            "source": str(resolve_path(item["source"], profile)) if item.get("source") else "",
            "dest": str(resolve_path(item["dest"], profile)) if item.get("dest") else "",
            "catalog_entry": item.get("catalog_entry", ""),
        })
    generated_file_provenance = []
    for item in profile.raw.get("generated_file_provenance", []):
        if not isinstance(item, dict):
            continue
        record = dict(item)
        for key in ("path", "source", "dest"):
            if record.get(key):
                record[key] = expand_profile_text(str(record[key]), profile)
        generated_file_provenance.append(record)
    memory_dependencies = profile.raw.get("memory") if isinstance(profile.raw.get("memory"), dict) else {}
    memory_models = []
    for cls, model in dict(memory_dependencies.get("models", {})).items():
        if not isinstance(model, dict):
            continue
        memory_models.append({
            "class": str(cls),
            "model": str(model.get("selected", "")),
            "confidence": str(model.get("confidence", "")),
            "source": str(model.get("source", "")),
            "notes": str(model.get("notes", "")),
        })
    explicit_sim_only_paths = [
        expand_profile_text(str(path), profile)
        for path in profile.raw.get("sim_only_paths", [])
        if isinstance(path, str) and path
    ]
    heuristic_sim_only_paths = [
        expand_profile_text(path, profile)
        for path in profile.raw.get("required_paths", [])
        if isinstance(path, str) and ("rtl_shims" in path or "generated" in path)
    ]
    doc = {
        "schema": "apfsim.source_provenance.v1",
        "profile": profile.name,
        "profile_path": str(profile.path),
        "root": str(profile.root) if profile.root else "",
        "top": profile.top,
        "filelist": str(profile.filelist),
        "shimmed_modules": shimmed_modules,
        "generated_files": generated_files,
        "generated_file_provenance": generated_file_provenance,
        "memory_dependencies": memory_dependencies,
        "memory_models": memory_models,
        "memory_activity": profile.raw.get("memory_activity", {}),
        "wrapper_generation": profile.raw.get("wrapper_generation", {}),
        "sim_only_paths": dedupe_strings(explicit_sim_only_paths + heuristic_sim_only_paths),
    }
    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "source_provenance.json").write_text(json.dumps(doc, indent=2) + "\n")
    write_memory_activity(profile, artifact_root, doc)
    return doc


def write_memory_activity(profile: Profile, artifact_root: Path, provenance: dict[str, Any]) -> dict[str, Any]:
    memory_dependencies = provenance.get("memory_dependencies") if isinstance(provenance.get("memory_dependencies"), dict) else {}
    wrapper_generation = provenance.get("wrapper_generation") if isinstance(provenance.get("wrapper_generation"), dict) else {}
    memory_wrapper = wrapper_generation.get("memory_models") if isinstance(wrapper_generation.get("memory_models"), dict) else {}
    result_memory: dict[str, Any] = {}
    result: dict[str, Any] = {}
    result_path = artifact_root / "result.json"
    if result_path.exists():
        try:
            result = load_json(result_path)
            if isinstance(result.get("memory_activity"), dict):
                result_memory = result["memory_activity"]
        except Exception:
            result = {}
            result_memory = {}
    shimmed = [item for item in provenance.get("shimmed_modules", []) if isinstance(item, dict)]
    memory_shims = [
        {
            "name": item.get("name", ""),
            "kind": item.get("kind", ""),
            "confidence": item.get("confidence", ""),
            "memory_classes": item.get("memory_classes", []),
        }
        for item in shimmed
        if item.get("memory_classes")
    ]
    errors = []
    for risk in memory_dependencies.get("risks", []):
        if not isinstance(risk, dict):
            continue
        if str(risk.get("severity", "warning")) != "error":
            continue
        errors.append({
            "code": str(risk.get("code") or "MEMORY_MODEL_REQUIRED"),
            "severity": "error",
            "message": str(risk.get("message") or ""),
            "observed": False,
        })
    runtime_errors = [
        item for item in result_memory.get("errors", [])
        if isinstance(item, dict) and str(item.get("code", ""))
    ]
    classes = [str(item) for item in memory_dependencies.get("classes", [])]
    declared_counters = [str(item) for item in memory_wrapper.get("activity_counters", [])]
    for item in wrapper_generation.values():
        if not isinstance(item, dict):
            continue
        model = item.get("memory_model")
        if not isinstance(model, dict):
            continue
        declared_counters.extend(str(counter) for counter in model.get("counter_ports", []))
    declared_counters = dedupe_strings(declared_counters)
    observed = bool(result_memory.get("observed"))
    runtime_counters = [
        item for item in result_memory.get("counters", [])
        if isinstance(item, dict) and str(item.get("name", ""))
    ]
    rom_regions = [
        item for item in memory_dependencies.get("rom_regions", [])
        if isinstance(item, dict)
    ]
    rom_validation = build_rom_validation({"counters": runtime_counters, "rom_regions": rom_regions}, result)
    enriched_runtime_errors = []
    for error in runtime_errors:
        enriched = dict(error)
        for event in rom_validation["events"]:
            if event.get("code") == enriched.get("code") and (
                not enriched.get("counter") or event.get("counter") == enriched.get("counter")
            ):
                enriched["first_event"] = event
                enriched["source"] = event.get("source", {})
                break
        enriched_runtime_errors.append(enriched)
    doc = {
        "schema": "apfsim.memory_activity.v1",
        "profile": profile.name,
        "observed": observed,
        "classes": classes,
        "external_classes": [str(item) for item in memory_dependencies.get("external_classes", [])],
        "models": provenance.get("memory_models", []),
        "selected_shims": memory_shims,
        "wrapper_generation": memory_wrapper,
        "declared_counters": declared_counters,
        "counter_status": "observed" if observed else ("declared_not_observed" if declared_counters else "none"),
        "counters": runtime_counters if observed else [],
        "rom_regions": rom_regions,
        "rom_validation": rom_validation,
        "errors": errors + enriched_runtime_errors,
        "notes": [
            "Memory activity was observed through standard apfsim top-level counter ports." if observed else
            "Memory activity is a provenance artifact unless the generated wrapper wires public counter probes.",
            "Use data-slot readback and bridge traces to catch ROM corruption until live memory counters are connected.",
        ] if classes else ["No memory dependencies were discovered for this profile."],
    }
    (artifact_root / "memory_activity.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def validate_runtime_artifacts(profile: Profile, artifact_root: Path) -> None:
    video_metadata = dict(profile.raw.get("metadata_jsons", {})).get("video")
    video_metadata_path = resolve_path(video_metadata, profile) if video_metadata else None
    try:
        validate_artifacts(artifact_root, video_metadata_path=video_metadata_path, update_result=True)
    except ArtifactValidationError as exc:
        raise ApfSimError(str(exc), phase="artifact") from exc


def validate_expected_artifacts(profile: Profile, artifact_root: Path) -> None:
    missing = []
    for rel in profile.raw.get("expected_artifacts", []):
        path = artifact_root / str(rel)
        if not path.exists():
            missing.append(str(path))
    if missing:
        raise ApfSimError("expected artifact(s) missing:\n" + "\n".join(f"  - {p}" for p in missing), phase="artifact")


def cmd_validate_artifacts(args: argparse.Namespace) -> int:
    artifact_root = resolve_user_path(args.artifact_dir)
    video_metadata_path = resolve_user_path(args.video_json) if args.video_json else None
    try:
        result = validate_artifacts(artifact_root, video_metadata_path=video_metadata_path, update_result=not args.no_update)
    except ArtifactValidationError as exc:
        raise ApfSimError(str(exc), phase="artifact") from exc
    print(
        "PASS artifacts: "
        f"ok={bool(result.get('ok'))} "
        f"video={result.get('video', {}).get('active_width', '?')}x{result.get('video', {}).get('active_height', '?')} "
        f"frames={result.get('video', {}).get('frames_completed', '?')} "
        f"audio_samples={result.get('audio', {}).get('samples', '?')}"
    )
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    artifact_root = resolve_user_path(args.artifact_dir)
    profile_raw: dict[str, Any] | None = None
    video_metadata_path = resolve_user_path(args.video_json) if args.video_json else None
    if args.profile:
        profile = load_profile(args.profile)
        profile_raw = diagnostic_profile_raw(profile)
        if video_metadata_path is None:
            video_metadata_path = profile_video_metadata_path(profile)
    doc = write_diagnostics(artifact_root, profile=profile_raw, video_metadata_path=video_metadata_path)
    if args.json:
        print(json.dumps(doc, indent=2 if args.pretty else None, sort_keys=True))
    else:
        summary = doc["summary"]
        print(
            "diagnostics: "
            f"status={doc['status']} "
            f"errors={summary['errors']} "
            f"warnings={summary['warnings']} "
            f"infos={summary['infos']}"
        )
        for item in doc["diagnostics"]:
            print(f"{item['severity'].upper()} {item['code']}: {item['summary']}")
        print(f"artifacts: {artifact_root}")
    return 1 if args.strict and doc["summary"]["errors"] else 0


def cmd_bringup(args: argparse.Namespace) -> int:
    if not args.profile and not (args.root and (args.auto_profile or args.synth_wrapper)):
        raise ApfSimError("bringup requires --profile or --root with --auto-profile/--synth-wrapper", phase="bringup")

    out = resolve_user_path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    profile: Profile
    generated_payload: dict[str, Any] | None = None
    if args.root and args.synth_wrapper:
        root = resolve_user_path(args.root)
        generated_dir = out / "synth-wrapper"
        try:
            synthesis = synthesize_wrapper_profile(
                root,
                generated_dir,
                apfsim_dir=APFSIM_DIR,
                profile_name=args.name,
                source_top=args.source_top,
                force=True,
            )
        except FileExistsError as exc:
            raise ApfSimError(str(exc), phase="synth-wrapper") from exc
        attach_source_contract(synthesis, root, name=args.name, source_top=args.source_top)
        profile_path = Path(synthesis["paths"]["profile"])
        raw = load_json(profile_path)
        raw["root"] = str(root)
        name = str(raw.get("name") or profile_path.stem)
        raw = expand_profile_shim_catalog(raw, name)
        profile = Profile(name=name, path=profile_path, raw=raw, root=root)
        generated_payload = {
            "schema": "apfsim.bringup_profile.v1",
            "profile": name,
            "root": str(root),
            "kind": "synth-wrapper",
            "paths": synthesis["paths"],
            "warnings": synthesis.get("warnings", []),
            "blockers": synthesis.get("blockers", []),
            "confidence": synthesis.get("confidence", 0),
        }
        (out / "profile.generated.json").write_text(json.dumps(generated_payload, indent=2) + "\n")
    elif args.root and args.auto_profile:
        root = resolve_user_path(args.root)
        generated_dir = out / "generated-profile"
        generated = generate_profile_candidate(
            root,
            generated_dir,
            apfsim_dir=APFSIM_DIR,
            profile_name=args.name,
            catalog_path=resolve_user_path(args.catalog) if args.catalog else DEFAULT_SHIM_CATALOG,
            force=True,
        )
        raw = load_json(generated.profile_path)
        raw["root"] = str(root)
        name = str(raw.get("name") or generated.profile_path.stem)
        raw = expand_profile_shim_catalog(raw, name)
        profile = Profile(name=name, path=generated.profile_path, raw=raw, root=root)
        generated_payload = {
            "schema": "apfsim.bringup_profile.v1",
            "profile": name,
            "root": str(root),
            "paths": {
                "profile": str(generated.profile_path),
                "filelist": str(generated.filelist_path),
                "scenario": str(generated.scenario_path),
                "notes": str(generated.notes_path),
                "report": str(generated.report_path),
            },
            "selected_shims": generated.selected_shims,
            "warnings": generated.warnings,
        }
        (out / "profile.generated.json").write_text(json.dumps(generated_payload, indent=2) + "\n")
    else:
        profile = load_profile_with_root(args.profile, resolve_user_path(args.root)) if args.root else load_profile(args.profile)

    slots = list(args.slot or [])
    if args.rom:
        slots.append(f"{args.rom_slot_id}={resolve_user_path(args.rom)}")
    run_args = argparse.Namespace(**vars(args))
    run_args.profile = profile.name
    run_args.slot = slots
    run_args.artifacts = str(args.artifacts or (out / "run"))
    run_args.clean_artifacts = args.clean_artifacts
    artifact_root = resolve_path(run_args.artifacts, profile)
    package_path = artifact_root / "package_check.json"
    package_root = resolve_user_path(args.root) if args.root else profile.root
    rc = run_profile(run_args, profile)
    if package_root:
        try:
            write_package_check(package_root, package_path, expected_platform_id=args.expected_platform_id)
        except Exception as exc:
            eprint(f"apfsim package-check warning: {exc}")

    diagnostics_path = artifact_root / "diagnostics.json"
    diagnostics_doc = load_json(diagnostics_path) if diagnostics_path.exists() else {}
    if args.repair or args.emit_patches:
        write_repair_plan(artifact_root, diagnostics_doc, emit_patches=args.emit_patches)
    summary_doc = write_summary(
        artifact_root,
        package_check_path=package_path if package_path.exists() else None,
    )

    first_error = first_diagnostic_code(diagnostics_doc, severity="error")
    if rc != 0 or first_error:
        print(f"FAIL {first_error or 'BRINGUP_FAILED'}")
    else:
        print("PASS bringup")
    print(f"artifacts: {artifact_root}")
    print(f"summary: {artifact_root / 'summary.json'}")
    if generated_payload:
        print(f"generated profile: {generated_payload['paths']['profile']}")
    return rc if rc != 0 else (1 if first_error or summary_doc.get("ok") is False else 0)


def cmd_package_check(args: argparse.Namespace) -> int:
    root = resolve_user_path(args.root)
    output = resolve_user_path(args.json_out) if args.json_out else APFSIM_DIR / "output" / "package-check" / root.name / "package_check.json"
    doc = write_package_check(root, output, expected_platform_id=args.expected_platform_id)
    if args.json:
        print(json.dumps(doc, indent=2 if args.pretty else None, sort_keys=True))
    else:
        print(
            "package-check: "
            f"ok={bool(doc.get('ok'))} "
            f"errors={len(doc.get('package_errors', []))} "
            f"warnings={len(doc.get('package_warnings', []))}"
        )
        print(f"json: {output}")
        for item in doc.get("package_errors", []):
            print(f"ERROR {item.get('code')}: {item.get('message')}")
        for item in doc.get("package_warnings", []):
            print(f"WARN {item.get('code')}: {item.get('message')}")
    return 1 if args.strict and not doc.get("ok") else 0


def cmd_summarize_run(args: argparse.Namespace) -> int:
    artifact_dir = resolve_user_path(args.artifact_dir)
    package_check_path = resolve_user_path(args.package_check) if args.package_check else None
    json_out = resolve_user_path(args.json_out) if args.json_out else None
    tsv_out = resolve_user_path(args.tsv_out) if args.tsv_out else None
    doc = write_summary(artifact_dir, json_out=json_out, tsv_out=tsv_out, package_check_path=package_check_path)
    if args.json:
        print(json.dumps(doc, indent=2 if args.pretty else None, sort_keys=True))
    else:
        row = doc["row"]
        print(
            "summary: "
            f"ok={row['ok']} "
            f"first_error={row['first_error_code'] or 'none'} "
            f"video={row['active_width']}x{row['active_height']} "
            f"audio={row['audio_activity']} "
            f"loaded_bytes={row['loaded_bytes_total']}"
        )
    return 1 if args.strict and not doc.get("ok") else 0


def cmd_corpus_run(args: argparse.Namespace) -> int:
    manifest = resolve_user_path(args.manifest)
    out = resolve_user_path(args.out)
    apfsim_cmd = args.apfsim_cmd or str(APFSIM_DIR / "bin" / "apfsim")
    try:
        doc = run_corpus_manifest(
            manifest,
            out,
            apfsim_cmd=apfsim_cmd,
            strict=args.strict,
            fail_fast=args.fail_fast,
        )
    except (OSError, ValueError) as exc:
        raise ApfSimError(str(exc), phase="corpus") from exc
    totals = doc["totals"]
    print(
        "corpus: "
        f"total={totals['total']} "
        f"passed={totals['passed']} "
        f"failed={totals['failed']} "
        f"skipped={totals['skipped']}"
    )
    if doc.get("top_blockers"):
        blockers = ", ".join(f"{item['code']}={item['count']}" for item in doc["top_blockers"][:8])
        print(f"top blockers: {blockers}")
    print(f"json: {out / 'corpus_summary.json'}")
    print(f"tsv: {out / 'corpus_summary.tsv'}")
    if args.json:
        print(json.dumps(doc, indent=2 if args.pretty else None, sort_keys=True))
    return 1 if args.strict and totals["failed"] else 0


def first_diagnostic_code(doc: dict[str, Any], *, severity: str) -> str:
    for item in doc.get("diagnostics", []):
        if isinstance(item, dict) and item.get("severity") == severity:
            return str(item.get("code") or "")
    return ""


def write_repair_plan(artifact_root: Path, diagnostics_doc: dict[str, Any], *, emit_patches: bool = False) -> None:
    repairs: list[dict[str, Any]] = []
    memory_hints: list[dict[str, Any]] = []
    for diagnostic in diagnostics_doc.get("diagnostics", []):
        if not isinstance(diagnostic, dict):
            continue
        code = str(diagnostic.get("code") or "")
        for repair in diagnostic.get("repairs", []):
            if not isinstance(repair, dict):
                continue
            item = dict(repair)
            item["diagnostic_code"] = code
            item["phase"] = diagnostic.get("phase")
            item["severity"] = diagnostic.get("severity")
            repairs.append(item)
        for hint in memory_repair_hints(code):
            item = {
                **hint,
                "diagnostic_code": code,
                "phase": diagnostic.get("phase"),
                "severity": diagnostic.get("severity"),
            }
            repairs.append(item)
            memory_hints.append(item)
    plan = {
        "schema": "apfsim.repair_plan.v1",
        "artifact_dir": str(artifact_root),
        "automatic_apply": False,
        "patches_emitted": False,
        "repairs": repairs,
    }
    if emit_patches:
        patches_dir = artifact_root / "patches"
        patches_dir.mkdir(parents=True, exist_ok=True)
        readme = patches_dir / "README.md"
        readme.write_text(
            "# apfsim patches\n\n"
            "This bring-up run produced repair suggestions, but this slice only emits a reviewable repair plan. "
            "Source patches are intentionally not synthesized until the matching repair rule is implemented.\n",
            encoding="utf-8",
        )
        if memory_hints:
            write_memory_repair_hints(patches_dir, memory_hints)
        plan["patches_dir"] = str(patches_dir)
    (artifact_root / "repair-plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")


def memory_repair_hints(code: str) -> list[dict[str, Any]]:
    table: dict[str, list[dict[str, Any]]] = {
        "DATA_SLOT_READBACK_MISMATCH": [
            {
                "kind": "memory_corruption_probe",
                "confidence": 0.80,
                "description": "Enable ROM/data-slot readback and inspect address lane, byte lane, endian, and write-strobe timing around the failing slot.",
                "actions": [
                    "Run the scenario with verify_readback enabled on the affected slot.",
                    "Inspect bridge.log for observed_first_write_address/observed_last_write_address and short writes.",
                    "If the slot maps to external RAM, wire the generated memory model counters and rerun.",
                ],
            }
        ],
        "SRAM_MODEL_REQUIRED": [
            {
                "kind": "profile_patch_hint",
                "confidence": 0.72,
                "description": "Select the public async SRAM pin model and generate a wrapper that connects SRAM pins to apfsim_async_sram_16_model.",
                "profile_fields": {"shim_catalog": ["external_sram_pin_model"]},
            }
        ],
        "PSRAM_MODEL_REQUIRED": [
            {
                "kind": "profile_patch_hint",
                "confidence": 0.68,
                "description": "Select the PSRAM transactional model and wire the generated wrapper to the core's PSRAM request/ack interface.",
                "profile_fields": {"shim_catalog": ["psram_cram_transactional_models"]},
            }
        ],
        "CRAM_MODEL_REQUIRED": [
            {
                "kind": "profile_patch_hint",
                "confidence": 0.68,
                "description": "Select the CRAM transactional model and wire the generated wrapper to the core's CRAM/cart-RAM interface.",
                "profile_fields": {"shim_catalog": ["psram_cram_transactional_models"]},
            }
        ],
        "MEMORY_BYTE_ENABLE_MISMATCH": [
            {
                "kind": "wrapper_patch_hint",
                "confidence": 0.70,
                "description": "Audit byte-enable polarity and lane ordering; Pocket cores often corrupt ROMs when low/high byte strobes are swapped or active-low lanes are treated as active-high.",
            }
        ],
        "MEMORY_WIDTH_MISMATCH": [
            {
                "kind": "wrapper_patch_hint",
                "confidence": 0.66,
                "description": "Insert an explicit width adapter between bridge-loaded 32-bit words and the external RAM data bus.",
            }
        ],
        "MEMORY_UNINITIALIZED_READ": [
            {
                "kind": "scenario_patch_hint",
                "confidence": 0.62,
                "description": "Add a ROM-load stress scenario and hold reset until required data-slot writes complete.",
            }
        ],
        "MEMORY_STALL_TIMEOUT": [
            {
                "kind": "memory_model_hint",
                "confidence": 0.62,
                "description": "Use a latency-configurable memory profile and check that the core handles ack/busy stalls instead of assuming zero-latency RAM.",
            }
        ],
    }
    return [dict(item) for item in table.get(code, [])]


def write_memory_repair_hints(patches_dir: Path, hints: list[dict[str, Any]]) -> None:
    lines = [
        "# Memory Repair Hints",
        "",
        "These are reviewable hints, not source mutations. Apply the relevant profile/wrapper changes manually or through a generator rule.",
        "",
    ]
    for idx, hint in enumerate(hints, start=1):
        lines.extend([
            f"## {idx}. {hint.get('diagnostic_code', 'UNKNOWN')}",
            "",
            f"- kind: `{hint.get('kind', '')}`",
            f"- confidence: `{hint.get('confidence', '')}`",
            f"- description: {hint.get('description', '')}",
            "",
        ])
        actions = hint.get("actions")
        if isinstance(actions, list) and actions:
            lines.append("Actions:")
            for action in actions:
                lines.append(f"- {action}")
            lines.append("")
        profile_fields = hint.get("profile_fields")
        if isinstance(profile_fields, dict) and profile_fields:
            lines.append("Profile fields:")
            lines.append("```json")
            lines.append(json.dumps(profile_fields, indent=2))
            lines.append("```")
            lines.append("")
    (patches_dir / "memory_model_hints.md").write_text("\n".join(lines), encoding="utf-8")


def print_failure_hint(artifact_root: Path) -> None:
    result = artifact_root / "result.json"
    if result.exists():
        try:
            data = json.loads(result.read_text())
            eprint(f"apfsim failure phase={data.get('failed_phase', '')} message={data.get('message', '')}")
        except json.JSONDecodeError:
            pass
    diagnostics = artifact_root / "diagnostics.json"
    if diagnostics.exists():
        try:
            data = json.loads(diagnostics.read_text())
            code = first_diagnostic_code(data, severity="error")
            if code:
                eprint(f"apfsim diagnostic={code}")
        except json.JSONDecodeError:
            pass
    eprint(f"apfsim artifacts: {artifact_root}")


def available_profiles() -> list[str]:
    return sorted(path.stem for path in PROFILES_DIR.glob("*.json") if not path.name.startswith("invalid_"))


def cmd_doctor(args: argparse.Namespace) -> int:
    print(f"apfsim_dir={APFSIM_DIR}")
    print(f"verilator={shutil.which(os.environ.get('VERILATOR', 'verilator')) or 'missing'}")
    rc = 0
    names = [args.profile] if args.profile else available_profiles()
    for name in names:
        try:
            profile = load_profile(name)
            preflight(profile, check_assets=not args.no_assets)
            status = "ok"
        except ProfileSkipped as exc:
            status = f"skip ({exc})"
        except Exception as exc:
            status = f"fail ({exc})"
            rc = 1
        print(f"profile {name}: {status}")
    return rc


def cmd_build(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    if args.preflight_only:
        preflight(profile)
        print(f"PASS preflight: {profile.name}")
        return 0
    return build_profile(profile, waves=args.waves, sdl=args.sdl)


def matrix_profiles(name: str) -> list[str]:
    if name == "ci":
        return ["mock_port_gate", "mock_target_commands", "mock_lifecycle", "mock_external_sram"]
    if name == "local-fast":
        return ["mock_port_gate", "mock_target_commands", "mock_lifecycle", "mock_external_sram", "core_template"]
    if name == "local-real":
        return ["mock_port_gate", "mock_target_commands", "mock_lifecycle", "mock_external_sram", "core_template", "interact", "kbmouse_targetdata", "basicassets", "basicchip32"]
    if name == "official-examples":
        return ["core_template", "interact", "kbmouse_targetdata", "basicassets", "basicchip32"]
    raise ApfSimError(f"unknown matrix: {name}")


def cmd_test(args: argparse.Namespace) -> int:
    failures = 0
    skipped = 0
    passed = 0
    for name in matrix_profiles(args.matrix):
        print(f"== apfsim profile {name} ==")
        try:
            profile = load_profile(name)
            preflight(profile)
            run_args = argparse.Namespace(**vars(args))
            run_args.profile = name
            run_args.scenario = None
            run_args.artifacts = str(APFSIM_DIR / "build" / "matrix" / args.matrix / name)
            run_args.clean_artifacts = True
            rc = run_profile(run_args, profile)
            if rc == 0:
                passed += 1
            else:
                failures += 1
        except ProfileSkipped as exc:
            skipped += 1
            print(str(exc))
        except Exception as exc:
            failures += 1
            eprint(f"profile {name} failed: {exc}")
    print(f"matrix {args.matrix}: passed={passed} skipped={skipped} failed={failures}")
    return 1 if failures else 0


def resolve_user_path(value: str) -> Path:
    path = Path(os.path.expanduser(os.path.expandvars(value)))
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


VIDEO_SHAPE_FIELDS = [
    "active_width",
    "active_height",
    "active_width_min",
    "active_width_max",
    "active_height_min",
    "active_height_max",
    "total_width_min",
    "total_width_max",
    "pixels_per_line_min",
    "pixels_per_line_max",
    "hs_after_vs_gap_min",
    "hs_to_de_gap_min",
    "de_to_hs_gap_min",
    "vs_to_first_de_lines",
    "vs_to_first_de_lines_min",
    "vs_to_first_de_lines_max",
    "hs_pulses_min",
    "hs_pulses_max",
    "de_errors",
    "rgb_when_de_low_errors",
    "pulse_width_errors",
    "skip_errors",
    "errors",
    "stable_dimensions",
    "protocol_valid",
    "frames_measured",
    "frames_considered",
    "frames_completed",
    "ignored_startup_frames",
    "startup_frames_ignored",
    "first_error_cycle",
    "first_error_frame",
    "first_error_pixel",
    "first_error_code",
    "trace_window",
    "source_signals",
]


def result_json_path(path: Path) -> Path:
    if path.is_dir():
        return path / "result.json"
    return path


def video_shape_json_path(path: Path) -> Path:
    if path.is_dir() and (path / "video_shape.json").exists():
        return path / "video_shape.json"
    return path


def _coerce_video_shape_from_legacy_video(video: dict[str, Any]) -> dict[str, Any]:
    width_min = video.get("active_width_frame_min", video.get("active_width"))
    width_max = video.get("active_width_frame_max", video.get("active_width"))
    height_min = video.get("active_height_frame_min", video.get("active_height"))
    height_max = video.get("active_height_frame_max", video.get("active_height"))
    errors = int(video.get("errors") or 0)
    return {
        "active_width": video.get("active_width"),
        "active_height": video.get("active_height"),
        "active_width_min": width_min,
        "active_width_max": width_max,
        "active_height_min": height_min,
        "active_height_max": height_max,
        "total_width_min": video.get("total_width_min", video.get("pixels_per_line_min")),
        "total_width_max": video.get("total_width_max", video.get("pixels_per_line_max")),
        "pixels_per_line_min": video.get("pixels_per_line_min"),
        "pixels_per_line_max": video.get("pixels_per_line_max"),
        "hs_after_vs_gap_min": video.get("hs_after_vs_gap_min"),
        "hs_to_de_gap_min": video.get("hs_to_de_gap_min"),
        "de_to_hs_gap_min": video.get("de_to_hs_gap_min"),
        "vs_to_first_de_lines": video.get("vs_to_first_de_lines", 0),
        "de_errors": video.get("de_errors", 0),
        "rgb_when_de_low_errors": video.get("rgb_when_de_low_errors", 0),
        "pulse_width_errors": video.get("pulse_width_errors", 0),
        "skip_errors": video.get("skip_errors", 0),
        "errors": errors,
        "stable_dimensions": width_min == width_max and height_min == height_max and int(video.get("unstable_dimension_frames") or 0) == 0,
        "protocol_valid": errors == 0,
        "frames_measured": video.get("validated_frames", video.get("frames_completed")),
        "frames_completed": video.get("frames_completed"),
        "ignored_startup_frames": video.get("ignored_startup_frames", 0),
        "source_signals": ["video_rgb", "video_de", "video_hs", "video_vs", "video_skip"],
    }


def extract_video_shape(result: dict[str, Any], source: Path) -> dict[str, Any]:
    if isinstance(result.get("video_shape"), dict):
        shape = {field: result["video_shape"].get(field) for field in VIDEO_SHAPE_FIELDS if field in result["video_shape"]}
    else:
        video = result.get("video")
        if not isinstance(video, dict):
            raise ApfSimError(f"result has no video object: {source}", phase="video-shape")
        missing = [field for field in ("active_width", "active_height") if field not in video]
        if missing:
            raise ApfSimError(f"result video object missing required field(s): {', '.join(missing)}", phase="video-shape")
        shape = _coerce_video_shape_from_legacy_video(video)

    phases = result.get("phases") if isinstance(result.get("phases"), dict) else {}
    video_phase = phases.get("video") if isinstance(phases.get("video"), dict) else {}
    return {
        "schema": str(result.get("schema") or "apfsim.video_shape.v1"),
        "source_result": str(result.get("source_result") or source),
        "result_ok": bool(result.get("result_ok", result.get("ok", False))),
        "status": result.get("status", ""),
        "video_phase_status": video_phase.get("status", ""),
        "video_shape": shape,
    }


def extract_video_shape_from_path(path: Path) -> dict[str, Any]:
    source = video_shape_json_path(path)
    if source.is_dir() or source.name != "video_shape.json":
        source = result_json_path(path)
    try:
        result = load_json(source)
    except ApfSimError as exc:
        raise ApfSimError(str(exc), phase="video-shape") from exc
    return extract_video_shape(result, source)


def write_shape_output(shape: dict[str, Any], json_out: str | None, pretty: bool) -> None:
    text = json.dumps(shape, indent=2 if pretty else None, sort_keys=True) + "\n"
    if json_out:
        path = resolve_user_path(json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    else:
        print(text, end="")


def cmd_video_shape(args: argparse.Namespace) -> int:
    rc = 0
    if args.profile:
        profile = load_profile(args.profile)
        if args.artifacts is None:
            args.artifacts = str(APFSIM_DIR / "output" / "video-shape" / profile.name)
        rc = run_profile(args, profile)
        artifact_root = resolve_path(args.artifacts, profile)
        shape = extract_video_shape_from_path(artifact_root)
        write_shape_output(shape, args.json_out, args.pretty)
        return rc

    if not args.result:
        raise ApfSimError("video-shape requires either a result/artifact path or --profile", phase="video-shape")
    shape = extract_video_shape_from_path(resolve_user_path(args.result))
    write_shape_output(shape, args.json_out, args.pretty)
    return 0


def extract_video_modes(data: Any) -> list[dict[str, Any]]:
    modes: list[dict[str, Any]] = []
    if isinstance(data, dict):
        if isinstance(data.get("scaler_modes"), list):
            for idx, mode in enumerate(data["scaler_modes"]):
                if not isinstance(mode, dict):
                    continue
                width = parse_optional_int(mode.get("width", mode.get("expected_width")))
                height = parse_optional_int(mode.get("height", mode.get("expected_height")))
                if width and height:
                    modes.append({
                        "index": idx,
                        "width": width,
                        "height": height,
                        "rotation": parse_optional_int(mode.get("rotation")),
                        "aspect_w": parse_optional_int(mode.get("aspect_w")),
                        "aspect_h": parse_optional_int(mode.get("aspect_h")),
                    })
        width = parse_optional_int(data.get("expected_width", data.get("width")))
        height = parse_optional_int(data.get("expected_height", data.get("height")))
        if width and height:
            candidate = {"index": len(modes), "width": width, "height": height}
            if not any(mode.get("width") == width and mode.get("height") == height for mode in modes):
                modes.append(candidate)
        for value in data.values():
            modes.extend(extract_video_modes(value))
    elif isinstance(data, list):
        for value in data:
            modes.extend(extract_video_modes(value))
    return dedupe_modes(modes)


def dedupe_modes(modes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, int, Any]] = set()
    for mode in modes:
        key = (int(mode["width"]), int(mode["height"]), mode.get("rotation"))
        if key in seen:
            continue
        seen.add(key)
        mode = dict(mode)
        mode["index"] = len(out)
        out.append(mode)
    return out


def parse_optional_int(value: Any) -> int | None:
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


def compare_video_shape_to_json(shape_doc: dict[str, Any], video_json_path: Path, *, allow_swapped: bool = False) -> dict[str, Any]:
    video_json = load_json(video_json_path)
    modes = extract_video_modes(video_json)
    shape = shape_doc.get("video_shape") if isinstance(shape_doc.get("video_shape"), dict) else {}
    width = parse_optional_int(shape.get("active_width"))
    height = parse_optional_int(shape.get("active_height"))
    failures: list[str] = []
    warnings: list[str] = []
    if width is None or height is None:
        failures.append("video_shape missing active_width/active_height")
    if not modes:
        failures.append(f"no video dimensions found in {video_json_path}")

    exact_matches = []
    swapped_matches = []
    if width is not None and height is not None:
        exact_matches = [mode for mode in modes if mode.get("width") == width and mode.get("height") == height]
        swapped_matches = [mode for mode in modes if mode.get("width") == height and mode.get("height") == width]
        if not exact_matches:
            if allow_swapped and swapped_matches:
                warnings.append(f"video_json only matches when dimensions are swapped: simulated {width}x{height}")
            else:
                expected = ", ".join(f"{mode['width']}x{mode['height']}" for mode in modes)
                failures.append(f"video_json dimensions [{expected}] do not include simulated shape {width}x{height}")

    if shape.get("stable_dimensions") is not True:
        failures.append("video_shape.stable_dimensions is not true")
    for key in ("de_errors", "pulse_width_errors", "skip_errors"):
        value = parse_optional_int(shape.get(key))
        if value is None:
            failures.append(f"video_shape missing {key}")
        elif value != 0:
            failures.append(f"video_shape.{key} is {value}")
    if parse_optional_int(shape.get("errors")) not in (None, 0):
        failures.append(f"video_shape.errors is {shape.get('errors')}")
    if shape.get("protocol_valid") is False:
        failures.append("video_shape.protocol_valid is false")

    return {
        "schema": "apfsim.video_compare.v1",
        "ok": not failures,
        "shape_source": shape_doc.get("source_result", ""),
        "video_json": str(video_json_path),
        "simulated": {
            "active_width": width,
            "active_height": height,
            "stable_dimensions": shape.get("stable_dimensions"),
            "protocol_valid": shape.get("protocol_valid"),
            "de_errors": shape.get("de_errors"),
            "pulse_width_errors": shape.get("pulse_width_errors"),
            "skip_errors": shape.get("skip_errors"),
        },
        "modes": modes,
        "matched_modes": exact_matches or (swapped_matches if allow_swapped else []),
        "allow_swapped": allow_swapped,
        "failures": failures,
        "warnings": warnings,
    }


def cmd_compare_video_json(args: argparse.Namespace) -> int:
    shape_doc = extract_video_shape_from_path(resolve_user_path(args.shape))
    report = compare_video_shape_to_json(shape_doc, resolve_user_path(args.video_json), allow_swapped=args.allow_swapped)
    text = json.dumps(report, indent=2 if args.pretty else None, sort_keys=True) + "\n"
    if args.json_out:
        path = resolve_user_path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    else:
        print(text, end="")
    if report["ok"]:
        if args.json_out:
            print("PASS video-json: simulated shape matches metadata")
        return 0
    for failure in report["failures"]:
        eprint(f"FAIL video-json: {failure}")
    return 1


def apply_video_shape_to_json(
    video_json: dict[str, Any],
    shape_doc: dict[str, Any],
    *,
    mode_index: int | None = None,
    timing_hints: bool = False,
    force: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    shape = shape_doc.get("video_shape") if isinstance(shape_doc.get("video_shape"), dict) else {}
    width = parse_optional_int(shape.get("active_width"))
    height = parse_optional_int(shape.get("active_height"))
    failures: list[str] = []
    warnings: list[str] = []
    patches: list[dict[str, Any]] = []

    if width is None or height is None or width <= 0 or height <= 0:
        failures.append("video_shape missing positive active_width/active_height")
    if not force:
        if shape.get("stable_dimensions") is not True:
            failures.append("video_shape.stable_dimensions is not true")
        for key in ("de_errors", "pulse_width_errors", "skip_errors"):
            value = parse_optional_int(shape.get(key))
            if value not in (0, None):
                failures.append(f"video_shape.{key} is {value}")
        if shape.get("protocol_valid") is False:
            failures.append("video_shape.protocol_valid is false")
    if failures and not force:
        return video_json, make_video_apply_report(False, False, patches, failures, warnings, shape_doc, "")

    patched = json.loads(json.dumps(video_json))
    if width is not None and height is not None:
        patch_scaler_modes(patched, width, height, mode_index, patches)
        if not patches:
            patch_top_level_dimensions(patched, width, height, patches)
    if timing_hints:
        add_video_timing_hints(patched, shape, patches)
    changed = bool(patches)
    return patched, make_video_apply_report(True, changed, patches, failures, warnings, shape_doc, "")


def patch_scaler_modes(data: Any, width: int, height: int, mode_index: int | None, patches: list[dict[str, Any]], path: str = "") -> None:
    if isinstance(data, dict):
        modes = data.get("scaler_modes")
        if isinstance(modes, list):
            for idx, mode in enumerate(modes):
                if mode_index is not None and idx != mode_index:
                    continue
                if not isinstance(mode, dict):
                    continue
                old_width = parse_optional_int(mode.get("width"))
                old_height = parse_optional_int(mode.get("height"))
                if old_width == width and old_height == height:
                    continue
                mode["width"] = width
                mode["height"] = height
                patches.append({
                    "path": f"{path}/scaler_modes/{idx}",
                    "old_width": old_width,
                    "old_height": old_height,
                    "new_width": width,
                    "new_height": height,
                })
        for key, value in data.items():
            if key == "scaler_modes":
                continue
            patch_scaler_modes(value, width, height, mode_index, patches, f"{path}/{key}")
    elif isinstance(data, list):
        for idx, value in enumerate(data):
            patch_scaler_modes(value, width, height, mode_index, patches, f"{path}/{idx}")


def patch_top_level_dimensions(data: dict[str, Any], width: int, height: int, patches: list[dict[str, Any]]) -> None:
    target = data.get("video") if isinstance(data.get("video"), dict) else data
    if not isinstance(target, dict):
        return
    old_width = parse_optional_int(target.get("width", target.get("expected_width")))
    old_height = parse_optional_int(target.get("height", target.get("expected_height")))
    width_key = "width" if "width" in target else "expected_width"
    height_key = "height" if "height" in target else "expected_height"
    if old_width == width and old_height == height:
        return
    target[width_key] = width
    target[height_key] = height
    patches.append({
        "path": "/video" if target is not data else "",
        "old_width": old_width,
        "old_height": old_height,
        "new_width": width,
        "new_height": height,
    })


def add_video_timing_hints(data: dict[str, Any], shape: dict[str, Any], patches: list[dict[str, Any]]) -> None:
    target = data.get("video") if isinstance(data.get("video"), dict) else data
    if not isinstance(target, dict):
        return
    hint = {
        "schema": "apfsim.video_shape_hint.v1",
        "active_width": shape.get("active_width"),
        "active_height": shape.get("active_height"),
        "total_width_min": shape.get("total_width_min"),
        "total_width_max": shape.get("total_width_max"),
        "hs_to_de_gap_min": shape.get("hs_to_de_gap_min"),
        "de_to_hs_gap_min": shape.get("de_to_hs_gap_min"),
        "vs_to_first_de_lines": shape.get("vs_to_first_de_lines"),
        "stable_dimensions": shape.get("stable_dimensions"),
        "protocol_valid": shape.get("protocol_valid"),
    }
    if target.get("_apfsim_video_shape") == hint:
        return
    target["_apfsim_video_shape"] = hint
    patches.append({"path": "/video/_apfsim_video_shape" if target is not data else "/_apfsim_video_shape", "timing_hints": True})


def make_video_apply_report(
    ok: bool,
    changed: bool,
    patches: list[dict[str, Any]],
    failures: list[str],
    warnings: list[str],
    shape_doc: dict[str, Any],
    output: str,
) -> dict[str, Any]:
    shape = shape_doc.get("video_shape") if isinstance(shape_doc.get("video_shape"), dict) else {}
    return {
        "schema": "apfsim.video_apply.v1",
        "ok": ok,
        "changed": changed,
        "output": output,
        "shape_source": shape_doc.get("source_result", ""),
        "simulated": {
            "active_width": shape.get("active_width"),
            "active_height": shape.get("active_height"),
            "stable_dimensions": shape.get("stable_dimensions"),
            "protocol_valid": shape.get("protocol_valid"),
        },
        "patches": patches,
        "failures": failures,
        "warnings": warnings,
    }


def cmd_apply_video_shape(args: argparse.Namespace) -> int:
    if args.in_place and args.out:
        raise ApfSimError("apply-video-shape accepts either --out or --in-place, not both", phase="video-shape")
    shape_doc = extract_video_shape_from_path(resolve_user_path(args.shape))
    video_json_path = resolve_user_path(args.video_json)
    video_json = load_json(video_json_path)
    patched, report = apply_video_shape_to_json(
        video_json,
        shape_doc,
        mode_index=args.mode_index,
        timing_hints=args.timing_hints,
        force=args.force,
    )
    output_path: Path | None = None
    if report["ok"] and (args.out or args.in_place):
        output_path = video_json_path if args.in_place else resolve_user_path(args.out)
        if args.backup and output_path == video_json_path:
            backup = video_json_path.with_suffix(video_json_path.suffix + ".bak")
            backup.write_text(video_json_path.read_text())
            report["backup"] = str(backup)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(patched, indent=2) + "\n")
        report["output"] = str(output_path)
    text = json.dumps(report, indent=2 if args.pretty else None, sort_keys=True) + "\n"
    if args.json_out:
        path = resolve_user_path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    else:
        print(text, end="")
    if not report["ok"]:
        for failure in report["failures"]:
            eprint(f"FAIL apply-video-shape: {failure}")
        return 2
    return 0


def cmd_analyze_log(args: argparse.Namespace) -> int:
    paths = [resolve_user_path(value) for value in args.log]
    missing = [path for path in paths if not path.exists()]
    if missing:
        raise ApfSimError("missing log file(s):\n" + "\n".join(f"  - {path}" for path in missing), phase="preflight")

    report = analyze_logs(paths)
    if args.json:
        write_json_report(report, resolve_user_path(args.json))

    for item in report["files"]:
        print(f"== {item['path']} ==")
        print(f"lines={item['line_count']} events={item['event_count']} lifecycle={'ok' if item['sequence_ok'] else 'incomplete'}")
        if item["statuses"]:
            status_text = ", ".join(f"{s['status']}@{s['line']}" for s in item["statuses"])
            print(f"statuses: {status_text}")
        if item["data_slots"]:
            for slot in item["data_slots"]:
                slot_id = "?" if slot["id"] is None else str(slot["id"])
                size = "?" if slot["bytes"] is None else str(slot["bytes"])
                address = "?" if slot["address"] is None else f"0x{slot['address']:08X}"
                print(f"data slot {slot_id}: bytes={size} address={address} writes32={slot['writes32']}")
        if item["missing_phases"]:
            print("missing: " + ", ".join(item["missing_phases"]))
        if item["order_errors"]:
            for error in item["order_errors"]:
                print(f"order error: {error}")
        if args.verbose:
            commands = [f"{cmd['command']}@{cmd['line']}" for cmd in item["host_commands"]]
            targets = [f"{cmd['command']}@{cmd['line']}" for cmd in item["target_commands"]]
            if commands:
                print("host commands: " + " -> ".join(commands))
            if targets:
                print("target commands: " + " -> ".join(targets))

    return 1 if args.strict_lifecycle and not report["ok"] else 0


def cmd_discover(args: argparse.Namespace) -> int:
    roots = [resolve_user_path(value) for value in (args.root or [str(root) for root in DEFAULT_DISCOVERY_ROOTS])]
    report = discover_cores(roots, profiles_dir=PROFILES_DIR)
    json_path, md_path = write_discovery_report(report, resolve_user_path(args.output))
    print(f"discovered cores={report['core_count']} profiled={report['profiled_count']}")
    for status, count in sorted(report["status_counts"].items()):
        print(f"{status}: {count}")
    for state, count in sorted(report.get("git_state_counts", {}).items()):
        print(f"git-{state}: {count}")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")
    return 0


def cmd_generate_profile(args: argparse.Namespace) -> int:
    root = resolve_user_path(args.root)
    output = resolve_user_path(args.output)
    catalog = resolve_user_path(args.catalog) if args.catalog else DEFAULT_SHIM_CATALOG
    try:
        generated = generate_profile_candidate(
            root,
            output,
            apfsim_dir=APFSIM_DIR,
            profile_name=args.name,
            catalog_path=catalog,
            force=args.force,
        )
    except FileExistsError as exc:
        raise ApfSimError(str(exc), phase="generate-profile") from exc
    payload = {
        "schema": "apfsim.generated_profile.v1",
        "profile": generated.profile_name,
        "root": str(generated.root),
        "output_dir": str(generated.output_dir),
        "paths": {
            "profile": str(generated.profile_path),
            "filelist": str(generated.filelist_path),
            "scenario": str(generated.scenario_path),
            "notes": str(generated.notes_path),
            "report": str(generated.report_path),
        },
        "selected_shims": generated.selected_shims,
        "selected_shim_details": generated.selected_shim_details,
        "risks": generated.risks,
        "warnings": generated.warnings,
    }
    if generated.qsf:
        payload["qsf"] = generated.qsf
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"generated profile candidate: {generated.profile_name}")
        print(f"profile: {generated.profile_path}")
        print(f"filelist: {generated.filelist_path}")
        print(f"scenario: {generated.scenario_path}")
        print(f"notes: {generated.notes_path}")
        if generated.selected_shims:
            print("shim_catalog: " + ", ".join(generated.selected_shims))
        if generated.warnings:
            print("warnings:")
            for warning in generated.warnings:
                print(f"  - {warning}")
    return 0


def cmd_synth_wrapper(args: argparse.Namespace) -> int:
    root = resolve_user_path(args.root)
    output = resolve_user_path(args.output)
    try:
        synthesis = synthesize_wrapper_profile(
            root,
            output,
            apfsim_dir=APFSIM_DIR,
            profile_name=args.name,
            source_top=args.top,
            force=args.force,
        )
    except FileExistsError as exc:
        raise ApfSimError(str(exc), phase="synth-wrapper") from exc
    attach_source_contract(synthesis, root, name=args.name, source_top=args.top)
    if args.json:
        print(json.dumps(synthesis, indent=2, sort_keys=True))
    else:
        print(f"wrapper synthesis: {synthesis['status']} confidence={synthesis['confidence']}")
        print(f"profile: {synthesis['paths']['profile']}")
        print(f"wrapper: {synthesis['paths']['wrapper']}")
        if synthesis.get("blockers"):
            print("blockers:")
            for item in synthesis["blockers"]:
                print(f"  - {item['code']}: {item['message']}")
    return 0


def attach_source_contract(synthesis: dict[str, Any], root: Path, *, name: str | None, source_top: str | None) -> None:
    profile_path = Path(str(synthesis["paths"]["profile"]))
    output_dir = profile_path.parent
    contract = build_source_contract(root, output_dir=output_dir, profile_name=name, source_top=source_top)
    json_path, md_path = write_source_contract(contract, output_dir)
    synthesis["paths"]["source_contract"] = str(json_path)
    synthesis["paths"]["source_contract_markdown"] = str(md_path)
    report_path = output_dir / "wrapper_synthesis.json"
    if report_path.exists():
        report = load_json(report_path)
        report.setdefault("paths", {}).update({
            "source_contract": str(json_path),
            "source_contract_markdown": str(md_path),
        })
        report_path.write_text(json.dumps(report, indent=2) + "\n")


def cmd_intake(args: argparse.Namespace) -> int:
    root = resolve_user_path(args.root)
    output = resolve_user_path(args.output)
    contract = build_source_contract(root, output_dir=output, profile_name=args.name, source_top=args.top)
    json_path, md_path = write_source_contract(contract, output)
    contract["paths"] = {
        "contract": str(json_path),
        "markdown": str(md_path),
    }
    if args.json:
        print(json.dumps(contract, indent=2, sort_keys=True))
    else:
        classification = contract["classification"]
        print(f"intake: {classification['mode']} status={classification['status']} confidence={classification['confidence']}")
        print(f"top: {contract['top']['selected'] or '-'}")
        print(f"contract: {json_path}")
        print(f"markdown: {md_path}")
        if contract.get("blockers"):
            print("blockers:")
            for item in contract["blockers"]:
                print(f"  - {item['severity']} {item['code']}: {item['message']}")
    return 0


def cmd_shim_catalog(args: argparse.Namespace) -> int:
    catalog_path = resolve_user_path(args.catalog) if args.catalog else DEFAULT_SHIM_CATALOG
    if args.profile:
        if args.catalog:
            path = profile_path(args.profile)
            raw = load_json(path)
            raw["shim_catalog_file"] = str(catalog_path)
            name = str(raw.get("name") or path.stem)
            profile = Profile(name=name, path=path, raw=expand_profile_shim_catalog(raw, name), root=profile_root(raw))
        else:
            profile = load_profile(args.profile)
        payload = {
            "schema": "apfsim.shim_catalog_expanded.v1",
            "profile": profile.name,
            "catalog": str(catalog_path),
            "entries": profile.raw.get("shim_catalog_expanded", []),
            "generated_files": [
                item for item in profile.raw.get("generated_files", [])
                if isinstance(item, dict) and item.get("catalog_entry")
            ],
            "required_paths": profile.raw.get("required_paths", []),
            "runtime_cwd": profile.raw.get("runtime_cwd", ""),
            "verilator_flags": profile.raw.get("verilator_flags", []),
        }
    else:
        catalog = load_shim_catalog(catalog_path)
        payload = {
            "schema": "apfsim.shim_catalog.v1",
            "catalog": str(catalog_path),
            "entries": [
                {
                    "name": name,
                    "description": entry.get("description", ""),
                    "kind": entry.get("kind", ""),
                    "confidence": entry.get("confidence", ""),
                    "modules": entry.get("modules", []),
                    "memory_classes": entry.get("memory_classes", []),
                    "diagnostic_codes": entry.get("diagnostic_codes", []),
                    "generated_files": len(entry.get("generated_files", [])),
                    "required_paths": len(entry.get("required_paths", [])),
                }
                for name, entry in sorted(catalog.items())
            ],
        }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for entry in payload["entries"]:
            print(f"{entry['name']}: {entry.get('description', '')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apfsim")
    sub = parser.add_subparsers(dest="cmd", required=True)

    doctor = sub.add_parser("doctor", help="check tools, profiles, metadata, and local assets")
    doctor.add_argument("--profile")
    doctor.add_argument("--no-assets", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    build = sub.add_parser("build", help="build a Verilated simulator for a profile")
    build.add_argument("--profile", required=True)
    build.add_argument("--waves", action="store_true")
    build.add_argument("--sdl", action="store_true", help="link the simulator with SDL2 for interactive play")
    build.add_argument("--preflight-only", action="store_true")
    build.set_defaults(func=cmd_build)

    run = sub.add_parser("run", help="build and run a profile scenario")
    add_run_args(run)
    run.set_defaults(func=lambda ns: run_profile(ns, load_profile(ns.profile)))

    bringup = sub.add_parser("bringup", help="discover/profile/run/diagnose one APF core bring-up")
    bringup.add_argument("--profile", help="existing apfsim profile name or path")
    bringup.add_argument("--root", help="Pocket core checkout/package root; binds {root} for --profile or generates a profile with --auto-profile")
    bringup.add_argument("--auto-profile", action="store_true", help="generate a reviewable profile candidate before running")
    bringup.add_argument("--synth-wrapper", action="store_true", help="synthesize a reviewable APF wrapper/profile before running")
    bringup.add_argument("--source-top", help="source module to instantiate when using --synth-wrapper")
    bringup.add_argument("--name", help="generated profile name when using --auto-profile")
    bringup.add_argument("--catalog", help="shim catalog JSON path; defaults to catalogs/shims.json")
    bringup.add_argument("--rom", help="ROM/asset file to bind to --rom-slot-id")
    bringup.add_argument("--rom-slot-id", type=int, default=1, help="data slot id used for --rom; default 1")
    bringup.add_argument("--expected-platform-id", help="fail package-check if core.json does not declare this platform id")
    bringup.add_argument("--out", required=True, help="bring-up artifact directory")
    bringup.add_argument("--repair", action="store_true", help="emit repair-plan.json from diagnostics")
    bringup.add_argument("--explain", action="store_true", help="reserved for verbose diagnostic explanations")
    bringup.add_argument("--emit-patches", action="store_true", help="create patches/ when repair rules can emit reviewable patches")
    add_run_args(bringup, include_profile=False)
    bringup.set_defaults(func=cmd_bringup)

    play = sub.add_parser("play", help="boot a profile and play it in an SDL2 window")
    add_run_args(play)
    play.add_argument("--scale", type=int, default=3, help="integer window scale for active video")
    play.add_argument("--speed-percent", type=int, default=100, help="presentation throttle; 0 means unthrottled")
    play.set_defaults(func=cmd_play, timeout=0)

    test = sub.add_parser("test", help="run a profile matrix")
    test.add_argument("--matrix", choices=["ci", "local-fast", "local-real", "official-examples"], default="local-fast")
    add_run_args(test, include_profile=False)
    test.set_defaults(func=cmd_test)

    discover = sub.add_parser("discover", help="inventory local Pocket/APF core checkouts and classify sim-readiness")
    discover.add_argument("--root", action="append", help="root to scan; repeatable. If omitted, APFSIM_DISCOVERY_ROOTS is split on the OS path separator")
    discover.add_argument("--output", default="output/core-inventory", help="directory for cores.json and cores.md")
    discover.set_defaults(func=cmd_discover)

    intake = sub.add_parser("intake", help="build a source contract for one core checkout before profile/wrapper generation")
    intake.add_argument("--root", required=True, help="Pocket/core checkout root")
    intake.add_argument("--top", help="source module to classify; defaults to QSF top or best-scored module")
    intake.add_argument("--name", help="contract/profile name; defaults to normalized checkout name")
    intake.add_argument("--output", "--out", default="output/intake", help="directory for source_contract.json and source_contract.md")
    intake.add_argument("--json", action="store_true", help="emit machine-readable source contract")
    intake.set_defaults(func=cmd_intake)

    gen_profile = sub.add_parser("generate-profile", help="generate a reviewable profile/filelist/scenario candidate for a core checkout")
    gen_profile.add_argument("--root", required=True, help="Pocket core checkout root")
    gen_profile.add_argument("--name", help="profile name; defaults to normalized checkout name")
    gen_profile.add_argument("--output", default="output/generated-profiles", help="directory for generated profile bundles")
    gen_profile.add_argument("--catalog", help="shim catalog JSON path; defaults to catalogs/shims.json")
    gen_profile.add_argument("--force", action="store_true", help="overwrite an existing generated bundle")
    gen_profile.add_argument("--json", action="store_true", help="emit machine-readable generation report")
    gen_profile.set_defaults(func=cmd_generate_profile)

    synth = sub.add_parser("synth-wrapper", help="synthesize a reviewable APF core_top wrapper/profile for a source top")
    synth.add_argument("--root", required=True, help="Pocket/core checkout root")
    synth.add_argument("--top", help="source module to instantiate; defaults to QSF top or best-scored module")
    synth.add_argument("--name", help="profile name; defaults to normalized checkout name")
    synth.add_argument("--output", default="output/synth-wrapper", help="directory for synthesized wrapper/profile bundles")
    synth.add_argument("--force", action="store_true", help="overwrite an existing synthesized bundle")
    synth.add_argument("--json", action="store_true", help="emit machine-readable wrapper synthesis report")
    synth.set_defaults(func=cmd_synth_wrapper)

    shim_catalog = sub.add_parser("shim-catalog", help="list shim/substitution catalog entries or show profile expansion")
    shim_catalog.add_argument("--catalog", help="catalog JSON path; defaults to catalogs/shims.json")
    shim_catalog.add_argument("--profile", help="profile to expand through the catalog")
    shim_catalog.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    shim_catalog.set_defaults(func=cmd_shim_catalog)

    validate = sub.add_parser("validate-artifacts", help="validate a run artifact directory and update derived contract files")
    validate.add_argument("artifact_dir", help="directory containing result.json and run artifacts")
    validate.add_argument("--video-json", help="optional APF video.json to compare frame dimensions against")
    validate.add_argument("--no-update", action="store_true", help="do not add derived phases/lifecycle to result.json or lifecycle.json")
    validate.set_defaults(func=cmd_validate_artifacts)

    package = sub.add_parser("package-check", help="validate APF package metadata and SD-card path expectations")
    package.add_argument("--root", required=True, help="core checkout or package root")
    package.add_argument("--expected-platform-id", help="expected platform id that must be declared by core.json")
    package.add_argument("--json-out", help="write package_check.json here; defaults to apfsim/output/package-check/<root>/package_check.json")
    package.add_argument("--json", action="store_true", help="print package_check JSON")
    package.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    package.add_argument("--strict", action="store_true", help="return nonzero when package errors are present")
    package.set_defaults(func=cmd_package_check)

    summarize = sub.add_parser("summarize-run", help="flatten run artifacts into summary.json and summary.tsv")
    summarize.add_argument("artifact_dir", help="run artifact directory")
    summarize.add_argument("--package-check", help="optional package_check.json path; defaults to artifact_dir/package_check.json")
    summarize.add_argument("--json-out", help="write summary JSON here; defaults to artifact_dir/summary.json")
    summarize.add_argument("--tsv-out", help="write one-row TSV here; defaults to artifact_dir/summary.tsv")
    summarize.add_argument("--json", action="store_true", help="print summary JSON")
    summarize.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    summarize.add_argument("--strict", action="store_true", help="return nonzero when summary ok=false")
    summarize.set_defaults(func=cmd_summarize_run)

    corpus = sub.add_parser("corpus", help="run manifest-driven bring-up corpora and aggregate rows")
    corpus_sub = corpus.add_subparsers(dest="corpus_cmd", required=True)
    corpus_run = corpus_sub.add_parser("run", help="run a corpus manifest through bringup/package stages")
    corpus_run.add_argument("--manifest", required=True, help="corpus manifest JSON or simple YAML")
    corpus_run.add_argument("--out", required=True, help="corpus artifact directory")
    corpus_run.add_argument("--strict", action="store_true", help="return nonzero if any core fails")
    corpus_run.add_argument("--fail-fast", action="store_true", help="stop after the first failed core")
    corpus_run.add_argument("--apfsim-cmd", help=argparse.SUPPRESS)
    corpus_run.add_argument("--json", action="store_true", help="print corpus_summary JSON after the concise summary")
    corpus_run.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    corpus_run.set_defaults(func=cmd_corpus_run)

    diagnose = sub.add_parser("diagnose", help="classify run artifacts into stable APF contract diagnostics")
    diagnose.add_argument("artifact_dir", help="directory containing result.json and run artifacts")
    diagnose.add_argument("--profile", help="optional profile for expected metadata and profile risk context")
    diagnose.add_argument("--video-json", help="optional APF video.json to compare against")
    diagnose.add_argument("--json", action="store_true", help="print diagnostics JSON")
    diagnose.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    diagnose.add_argument("--strict", action="store_true", help="return nonzero when error diagnostics are present")
    diagnose.set_defaults(func=cmd_diagnose)

    video_shape = sub.add_parser("video-shape", help="extract or run stable APF-facing video timing/shape discovery")
    video_shape.add_argument("result", nargs="?", help="path to result.json, video_shape.json, or an artifact directory")
    video_shape.add_argument("--profile", help="run a profile first, then emit the discovered video shape")
    add_run_args(video_shape, include_profile=False)
    video_shape.add_argument("--json-out", help="write the video shape document to this path instead of stdout")
    video_shape.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    video_shape.set_defaults(func=cmd_video_shape)

    compare_video = sub.add_parser("compare-video-json", help="compare discovered video_shape against APF video.json scaler dimensions")
    compare_video.add_argument("--shape", required=True, help="path to result.json, video_shape.json, or an artifact directory")
    compare_video.add_argument("--video-json", required=True, help="path to APF video.json")
    compare_video.add_argument("--json-out", help="write comparison report JSON to this path")
    compare_video.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    compare_video.add_argument("--allow-swapped", action="store_true", help="allow width/height swapped matches as warnings instead of hard failures")
    compare_video.set_defaults(func=cmd_compare_video_json)

    apply_video = sub.add_parser("apply-video-shape", help="patch APF video.json scaler dimensions from a discovered video_shape")
    apply_video.add_argument("--shape", required=True, help="path to result.json, video_shape.json, or an artifact directory")
    apply_video.add_argument("--video-json", required=True, help="path to APF video.json to patch")
    apply_video.add_argument("--out", help="write patched video.json here")
    apply_video.add_argument("--in-place", action="store_true", help="overwrite --video-json")
    apply_video.add_argument("--backup", action="store_true", help="write <video.json>.bak before --in-place overwrite")
    apply_video.add_argument("--mode-index", type=int, help="patch only one scaler_modes index; default patches all scaler modes")
    apply_video.add_argument("--timing-hints", action="store_true", help="add _apfsim_video_shape timing hints from the discovered shape")
    apply_video.add_argument("--force", action="store_true", help="patch even if video_shape is unstable or has protocol errors")
    apply_video.add_argument("--json-out", help="write apply report JSON to this path")
    apply_video.add_argument("--pretty", action="store_true", help="pretty-print report JSON")
    apply_video.set_defaults(func=cmd_apply_video_shape)

    analyze = sub.add_parser("analyze-log", help="extract APF lifecycle events from Pocket or apfsim logs")
    analyze.add_argument("log", nargs="+")
    analyze.add_argument("--json", help="write structured lifecycle report")
    analyze.add_argument("--strict-lifecycle", action="store_true", help="return nonzero if a full boot lifecycle is missing or out of order")
    analyze.add_argument("--verbose", action="store_true", help="print host and target command sequence")
    analyze.set_defaults(func=cmd_analyze_log)
    return parser


def add_run_args(parser: argparse.ArgumentParser, include_profile: bool = True) -> None:
    if include_profile:
        parser.add_argument("--profile", required=True)
    parser.add_argument("--scenario")
    parser.add_argument("--frames", type=int)
    parser.add_argument("--timeout-cycles", type=int)
    parser.add_argument("--write-idle-cycles", type=int)
    parser.add_argument("--slot", action="append")
    parser.add_argument("--artifacts")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--no-clean-artifacts", dest="clean_artifacts", action="store_false")
    parser.add_argument("--waves", action="store_true")
    parser.add_argument("--verbose-bridge", action="store_true")
    parser.add_argument("--bridge-read-latency-cycles", type=int)
    parser.add_argument("--bridge-write-strobe-cycles", type=int)
    parser.add_argument("--bridge-endian", choices=["little", "big"])
    parser.add_argument("--target-service-interval-cycles", type=int, help="poll target-to-host commands during runtime every N clk_74a cycles; 0 disables runtime polling")
    parser.add_argument("--interact-no-verify", action="store_true", help="apply persistent interact writes without immediate readback verification")
    parser.add_argument("--bridge-trace", action="store_true", help="write bridge_transactions.jsonl with every bridge read/write")
    parser.set_defaults(clean_artifacts=True)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ProfileSkipped as exc:
        print(str(exc))
        return SKIP_EXIT
    except ApfSimError as exc:
        eprint(f"apfsim {exc.phase} error: {exc}")
        return 2
    except subprocess.TimeoutExpired as exc:
        eprint(f"apfsim timeout: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
