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

APFSIM_DIR = Path(__file__).resolve().parents[1]
PROFILES_DIR = APFSIM_DIR / "profiles"
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
    if "root_default" in raw:
        return Path(os.path.expanduser(os.path.expandvars(str(raw["root_default"]))))
    return None


def load_profile(name_or_path: str) -> Profile:
    path = profile_path(name_or_path)
    raw = load_json(path)
    name = str(raw.get("name") or path.stem)
    return Profile(name=name, path=path, raw=raw, root=profile_root(raw))


def resolve_path(value: str | os.PathLike[str], profile: Profile | None = None) -> Path:
    text = str(value)
    root = profile.root if profile and profile.root else APFSIM_DIR
    text = text.replace("{apfsim}", str(APFSIM_DIR)).replace("{root}", str(root))
    text = os.path.expanduser(os.path.expandvars(text))
    path = Path(text)
    if path.is_absolute():
        return path
    return (APFSIM_DIR / path).resolve()


def require_keys(profile: Profile, keys: list[str]) -> None:
    missing = [key for key in keys if key not in profile.raw]
    if missing:
        raise ApfSimError(f"profile {profile.name} missing required key(s): {', '.join(missing)}")


def parse_scenario_files(path: Path) -> list[Path]:
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
                    candidate = Path(os.path.expanduser(os.path.expandvars(value)))
                    files.append(candidate if candidate.is_absolute() else (APFSIM_DIR / candidate).resolve())
    return files


def preflight(profile: Profile, check_assets: bool = True) -> None:
    require_keys(profile, ["top", "filelist", "scenario"])
    if profile.raw.get("external") and (profile.root is None or not profile.root.exists()):
        root_text = str(profile.root) if profile.root else "<unset>"
        raise ProfileSkipped(f"profile {profile.name} skipped: external root missing: {root_text}")

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
        for asset in parse_scenario_files(profile.scenario):
            if not asset.exists():
                missing.append(f"scenario data slot file: {asset}")
    if missing:
        raise ApfSimError("preflight failed; missing path(s):\n" + "\n".join(f"  - {m}" for m in missing))


def generate_files(profile: Profile) -> None:
    for item in profile.raw.get("generated_files", []):
        kind = item.get("type")
        if kind != "rename_module":
            raise ApfSimError(f"unsupported generated_files type for {profile.name}: {kind}")
        source = resolve_path(item["source"], profile)
        dest = resolve_path(item["dest"], profile)
        original = source.read_text()
        needle = str(item.get("from", "module core_top"))
        replacement = str(item.get("to", "module core_top_impl"))
        if needle not in original:
            raise ApfSimError(f"cannot generate {dest}: source does not contain {needle!r}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(original.replace(needle, replacement, 1))


def verilator_base_args(profile: Profile, waves: bool = False) -> list[str]:
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
        str(profile.filelist),
        "-Irtl_shims",
        "-Wno-fatal",
        "--assert",
        "-CFLAGS",
        "-std=c++20 -O2 -Icpp",
    ]
    args.extend(str(flag) for flag in profile.raw.get("verilator_flags", []))
    if waves:
        args.extend(["--trace", "--trace-fst", "--trace-structs"])
    args.append("--build")
    return args


def run_command(args: list[str], *, env: dict[str, str] | None = None, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=APFSIM_DIR, env=env, text=True, capture_output=True, timeout=timeout)


def print_completed(proc: subprocess.CompletedProcess[str]) -> None:
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        eprint(proc.stderr, end="")


def build_profile(profile: Profile, waves: bool = False) -> int:
    preflight(profile)
    generate_files(profile)
    profile.build_dir.mkdir(parents=True, exist_ok=True)
    proc = run_command(verilator_base_args(profile, waves=waves), timeout=600)
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

    binary = profile.build_dir / f"V{profile.top}"
    if not binary.exists():
        raise ApfSimError(f"built simulator not found: {binary}", phase="build")

    scenario = resolve_path(args.scenario, profile) if args.scenario else profile.scenario
    frames = args.frames if args.frames is not None else int(profile.raw.get("frames", 0) or 0)
    timeout_cycles = args.timeout_cycles if args.timeout_cycles is not None else int(profile.raw.get("timeout_cycles", 0) or 0)
    cmd = [
        str(binary),
        "--scenario", str(scenario),
        "--dump-frames", str(artifact_root / "video"),
        "--dump-audio", str(artifact_root / "audio" / "out.wav"),
        "--audio-stats", str(artifact_root / "audio" / "stats.json"),
        "--dump-saves", str(artifact_root / "saves"),
        "--result-json", str(artifact_root / "result.json"),
        "--bridge-log", str(artifact_root / "bridge.log"),
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
    for slot in args.slot or []:
        cmd.extend(["--slot", slot])
    if args.verbose_bridge:
        cmd.append("--verbose-bridge")

    env = os.environ.copy()
    if args.waves:
        env["APFSIM_WAVES"] = "1"
        env.setdefault("APFSIM_WAVE_PATH", str(artifact_root / "dump.fst"))
    proc = run_command(cmd, env=env, timeout=args.timeout)
    print_completed(proc)
    if proc.returncode != 0:
        print_failure_hint(artifact_root)
    else:
        validate_expected_artifacts(profile, artifact_root)
    return proc.returncode


def validate_expected_artifacts(profile: Profile, artifact_root: Path) -> None:
    missing = []
    for rel in profile.raw.get("expected_artifacts", []):
        path = artifact_root / str(rel)
        if not path.exists():
            missing.append(str(path))
    if missing:
        raise ApfSimError("expected artifact(s) missing:\n" + "\n".join(f"  - {p}" for p in missing), phase="artifact")


def print_failure_hint(artifact_root: Path) -> None:
    result = artifact_root / "result.json"
    if result.exists():
        try:
            data = json.loads(result.read_text())
            eprint(f"apfsim failure phase={data.get('failed_phase', '')} message={data.get('message', '')}")
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
    return build_profile(profile, waves=args.waves)


def matrix_profiles(name: str) -> list[str]:
    if name == "ci":
        return ["mock_port_gate"]
    if name == "local-fast":
        return ["mock_port_gate", "core_template"]
    if name == "local-real":
        return ["mock_port_gate", "core_template", "basicassets", "pacman"]
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
    build.add_argument("--preflight-only", action="store_true")
    build.set_defaults(func=cmd_build)

    run = sub.add_parser("run", help="build and run a profile scenario")
    add_run_args(run)
    run.set_defaults(func=lambda ns: run_profile(ns, load_profile(ns.profile)))

    test = sub.add_parser("test", help="run a profile matrix")
    test.add_argument("--matrix", choices=["ci", "local-fast", "local-real"], default="local-fast")
    add_run_args(test, include_profile=False)
    test.set_defaults(func=cmd_test)
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
