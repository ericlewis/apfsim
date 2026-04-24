#!/usr/bin/env python3
"""Manifest-driven corpus runner for APF bring-up batches."""
from __future__ import annotations

import csv
import json
import os
import re
import shlex
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA = "apfsim.corpus_summary.v1"
TSV_COLUMNS = [
    "name",
    "status",
    "ok",
    "returncode",
    "stage",
    "stop_stage",
    "family",
    "profile",
    "root",
    "rom",
    "expected_platform_id",
    "first_error_code",
    "blocking_codes",
    "warning_codes",
    "package_ok",
    "active_width",
    "active_height",
    "frames_considered",
    "video_protocol_valid",
    "audio_activity",
    "audio_nonzero_samples",
    "loaded_bytes_total",
    "data_crc_list",
    "shimmed_modules",
    "shim_kinds",
    "shim_confidences",
    "memory_classes",
    "memory_models",
    "memory_risks",
    "memory_activity_observed",
    "memory_error_codes",
    "artifact_dir",
    "run_dir",
    "skip_reason",
]


def load_manifest(path: Path) -> dict[str, Any]:
    path = path.resolve()
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        stripped = text.lstrip()
        if stripped.startswith("{"):
            data = json.loads(text)
        else:
            data = parse_simple_yaml(text)
    if not isinstance(data, dict):
        raise ValueError(f"corpus manifest must be an object: {path}")
    cores = data.get("cores")
    if not isinstance(cores, list):
        raise ValueError(f"corpus manifest must contain a cores list: {path}")
    for idx, item in enumerate(cores):
        if not isinstance(item, dict):
            raise ValueError(f"corpus manifest cores[{idx}] must be an object")
    data["manifest_path"] = str(path)
    return data


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse the small YAML subset used by corpus manifests.

    This intentionally avoids a runtime PyYAML dependency. Supported shapes are
    top-level scalars, a top-level defaults map, and a top-level cores list of
    scalar maps.
    """
    doc: dict[str, Any] = {}
    section = ""
    current: dict[str, Any] | None = None
    cores: list[dict[str, Any]] = []

    for raw in text.splitlines():
        line = strip_yaml_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0 and stripped.endswith(":"):
            if section == "cores" and current is not None:
                cores.append(current)
                current = None
            section = stripped[:-1]
            doc[section] = [] if section == "cores" else {}
            continue

        if section == "cores" and indent >= 2:
            if stripped.startswith("- "):
                if current is not None:
                    cores.append(current)
                current = {}
                rest = stripped[2:].strip()
                if rest:
                    key, value = split_yaml_key_value(rest)
                    current[key] = parse_scalar(value)
                continue
            if current is None:
                raise ValueError("corpus manifest core entry field found before '-' item")
            key, value = split_yaml_key_value(stripped)
            current[key] = parse_scalar(value)
            continue

        if section and isinstance(doc.get(section), dict) and indent >= 2:
            key, value = split_yaml_key_value(stripped)
            doc[section][key] = parse_scalar(value)
            continue

        if indent == 0:
            if section == "cores" and current is not None:
                cores.append(current)
                current = None
            section = ""
            key, value = split_yaml_key_value(stripped)
            doc[key] = parse_scalar(value)
            continue

        raise ValueError(f"unsupported corpus manifest YAML line: {raw}")

    if section == "cores" and current is not None:
        cores.append(current)
    if cores:
        doc["cores"] = cores
    return doc


def strip_yaml_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    out: list[str] = []
    for ch in line:
        if ch == "\\" and in_double and not escaped:
            escaped = True
            out.append(ch)
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single and not escaped:
            in_double = not in_double
        if ch == "#" and not in_single and not in_double:
            break
        out.append(ch)
        escaped = False
    return "".join(out)


def split_yaml_key_value(text: str) -> tuple[str, str]:
    if ":" not in text:
        raise ValueError(f"expected key: value in corpus manifest line: {text}")
    key, value = text.split(":", 1)
    key = key.strip()
    if not key:
        raise ValueError(f"empty key in corpus manifest line: {text}")
    return key, value.strip()


def parse_scalar(value: str) -> Any:
    if value == "":
        return ""
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    lower = value.lower()
    if lower in {"true", "yes", "on"}:
        return True
    if lower in {"false", "no", "off"}:
        return False
    if lower in {"null", "none", "~"}:
        return None
    try:
        return int(value, 0)
    except ValueError:
        return value


def run_corpus_manifest(
    manifest_path: Path,
    out_dir: Path,
    *,
    apfsim_cmd: str | Path | list[str],
    strict: bool = False,
    fail_fast: bool = False,
) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    out_dir = out_dir.resolve()
    manifest = load_manifest(manifest_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    defaults = manifest.get("defaults") if isinstance(manifest.get("defaults"), dict) else {}
    rows: list[dict[str, Any]] = []
    safe_counts: Counter[str] = Counter()
    for idx, raw_core in enumerate(manifest["cores"]):
        core = merge_defaults(defaults, raw_core)
        base_safe = safe_name(str(core.get("name") or core.get("profile") or core.get("root") or f"core_{idx:03d}"))
        safe_counts[base_safe] += 1
        if safe_counts[base_safe] > 1:
            core["_apfsim_safe_name"] = f"{base_safe}-{safe_counts[base_safe]:02d}"
        else:
            core["_apfsim_safe_name"] = base_safe
        row = run_corpus_core(
            core,
            idx=idx,
            manifest_dir=manifest_path.parent,
            out_dir=out_dir,
            apfsim_cmd=apfsim_cmd,
        )
        rows.append(row)
        if fail_fast and row.get("status") == "failed":
            break

    doc = build_corpus_summary(manifest, rows, out_dir)
    if strict and doc["totals"]["failed"]:
        doc["exit_code"] = 1
    else:
        doc["exit_code"] = 0
    write_corpus_outputs(doc, out_dir)
    return doc


def merge_defaults(defaults: dict[str, Any], core: dict[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    merged.update(core)
    return merged


def run_corpus_core(
    core: dict[str, Any],
    *,
    idx: int,
    manifest_dir: Path,
    out_dir: Path,
    apfsim_cmd: str | Path | list[str],
) -> dict[str, Any]:
    name = str(core.get("name") or core.get("profile") or core.get("root") or f"core_{idx:03d}")
    safe = str(core.get("_apfsim_safe_name") or safe_name(name))
    core_out = out_dir / "cores" / safe
    core_out.mkdir(parents=True, exist_ok=True)

    row = base_row(core, idx, name, core_out, manifest_dir)
    stop_stage = row["stop_stage"]

    root_path = optional_path(core.get("root"), manifest_dir)
    rom_path = optional_path(core.get("rom"), manifest_dir)
    if root_path is not None:
        row["root"] = str(root_path)
        if not root_path.exists():
            return finish_skipped(row, "root_missing", f"root does not exist: {root_path}")
    if rom_path is not None:
        row["rom"] = str(rom_path)
        if not rom_path.exists():
            return finish_preflight_failure(row, "ROM_MISSING", f"ROM/asset does not exist: {rom_path}")

    if stop_stage in {"package", "package-check", "package_check"}:
        if root_path is None:
            return finish_preflight_failure(row, "ROOT_REQUIRED", "package stop stage requires root")
        cmd = command_prefix(apfsim_cmd) + [
            "package-check",
            "--root", str(root_path),
            "--json-out", str(core_out / "package_check.json"),
        ]
        if core.get("expected_platform_id"):
            cmd.extend(["--expected-platform-id", str(core["expected_platform_id"])])
        if truthy(core.get("strict_package")):
            cmd.append("--strict")
        return run_and_collect(row, cmd, core_out, stop_stage="package", summary_kind="package")

    cmd = command_prefix(apfsim_cmd) + ["bringup", "--out", str(core_out)]
    profile = core.get("profile")
    if profile:
        cmd.extend(["--profile", str(profile)])
        if root_path is not None:
            cmd.extend(["--root", str(root_path)])
    elif root_path is not None:
        cmd.extend(["--root", str(root_path)])
        if truthy(core.get("auto_profile", True)):
            cmd.append("--auto-profile")
    else:
        return finish_preflight_failure(row, "PROFILE_OR_ROOT_REQUIRED", "bringup requires profile or root")

    if core.get("generated_profile_name") or core.get("name"):
        if not profile and root_path is not None:
            cmd.extend(["--name", str(core.get("generated_profile_name") or safe)])
    if core.get("catalog"):
        cmd.extend(["--catalog", str(resolve_value_path(core["catalog"], manifest_dir))])
    if rom_path is not None:
        cmd.extend(["--rom", str(rom_path)])
    if core.get("rom_slot_id") is not None:
        cmd.extend(["--rom-slot-id", str(core["rom_slot_id"])])
    if core.get("expected_platform_id"):
        cmd.extend(["--expected-platform-id", str(core["expected_platform_id"])])
    if core.get("scenario"):
        cmd.extend(["--scenario", str(resolve_value_path(core["scenario"], manifest_dir))])
    for key, flag in [
        ("frames", "--frames"),
        ("timeout_cycles", "--timeout-cycles"),
        ("timeout", "--timeout"),
        ("write_idle_cycles", "--write-idle-cycles"),
        ("bridge_read_latency_cycles", "--bridge-read-latency-cycles"),
        ("bridge_write_strobe_cycles", "--bridge-write-strobe-cycles"),
        ("target_service_interval_cycles", "--target-service-interval-cycles"),
    ]:
        if core.get(key) is not None:
            cmd.extend([flag, str(core[key])])
    if core.get("bridge_endian"):
        cmd.extend(["--bridge-endian", str(core["bridge_endian"])])
    for slot in list_value(core.get("slots")) + list_value(core.get("slot")):
        cmd.extend(["--slot", str(slot)])
    if truthy(core.get("no_build")):
        cmd.append("--no-build")
    if truthy(core.get("repair")):
        cmd.append("--repair")
    if truthy(core.get("emit_patches")):
        cmd.append("--emit-patches")
    if truthy(core.get("explain")):
        cmd.append("--explain")
    if truthy(core.get("waves")):
        cmd.append("--waves")
    if truthy(core.get("bridge_trace")):
        cmd.append("--bridge-trace")
    if truthy(core.get("interact_no_verify")):
        cmd.append("--interact-no-verify")

    return run_and_collect(row, cmd, core_out, stop_stage="bringup", summary_kind="run")


def base_row(core: dict[str, Any], idx: int, name: str, core_out: Path, manifest_dir: Path) -> dict[str, Any]:
    family = str(core.get("family") or core.get("family_hint") or "unknown")
    return {
        "index": idx,
        "name": name,
        "status": "pending",
        "ok": False,
        "returncode": None,
        "stage": "preflight",
        "stop_stage": str(core.get("stop_stage") or "bringup"),
        "family": family,
        "profile": str(core.get("profile") or ""),
        "root": str(optional_path(core.get("root"), manifest_dir) or ""),
        "rom": str(optional_path(core.get("rom"), manifest_dir) or ""),
        "url": str(core.get("url") or ""),
        "top_file": str(core.get("top_file") or ""),
        "expected_platform_id": str(core.get("expected_platform_id") or ""),
        "first_error_code": "",
        "blocking_codes": [],
        "warning_codes": [],
        "package_ok": None,
        "shim_kinds": [],
        "shim_confidences": [],
        "memory_classes": [],
        "memory_models": [],
        "memory_risks": [],
        "memory_activity_observed": False,
        "memory_error_codes": [],
        "artifact_dir": str(core_out),
        "run_dir": str(core_out / "run"),
        "summary_path": "",
        "package_check_path": "",
        "stdout_log": str(core_out / "bringup.stdout.log"),
        "stderr_log": str(core_out / "bringup.stderr.log"),
        "skip_reason": "",
        "message": "",
    }


def run_and_collect(row: dict[str, Any], cmd: list[str], core_out: Path, *, stop_stage: str, summary_kind: str) -> dict[str, Any]:
    stdout_log = Path(row["stdout_log"])
    stderr_log = Path(row["stderr_log"])
    command_log = core_out / "command.json"
    command_log.write_text(json.dumps({"argv": cmd}, indent=2) + "\n", encoding="utf-8")
    timeout = command_timeout_from_cmd(cmd)
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        stdout_log.write_text(proc.stdout, encoding="utf-8")
        stderr_log.write_text(proc.stderr, encoding="utf-8")
        row["returncode"] = proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout_log.write_text(exc.stdout or "", encoding="utf-8")
        stderr_log.write_text((exc.stderr or "") + f"\ncorpus command timed out after {timeout}s\n", encoding="utf-8")
        row["returncode"] = 124
        return finish_failure(row, "CORPUS_COMMAND_TIMEOUT", f"command timed out after {timeout}s")

    if row.get("returncode") == 77:
        message = (proc.stdout or proc.stderr or "profile skipped").strip().splitlines()
        return finish_skipped(row, "profile_skipped", message[-1] if message else "profile skipped")

    if summary_kind == "package":
        package_path = core_out / "package_check.json"
        row["package_check_path"] = str(package_path)
        package = optional_json(package_path)
        package_ok = bool(package.get("ok")) if package else False
        row["package_ok"] = package_ok
        errors = [item for item in package.get("package_errors", []) if isinstance(item, dict)] if package else []
        warnings = [item for item in package.get("package_warnings", []) if isinstance(item, dict)] if package else []
        row["blocking_codes"] = [str(item.get("code") or "PACKAGE_ERROR") for item in errors]
        row["warning_codes"] = [str(item.get("code") or "PACKAGE_WARNING") for item in warnings]
        row["first_error_code"] = row["blocking_codes"][0] if row["blocking_codes"] else ("PACKAGE_CHECK_FAILED" if proc_failed(row) else "")
        row["stage"] = "package"
        if package_ok and not proc_failed(row):
            return finish_passed(row)
        return finish_failed_existing(row, row["first_error_code"] or "PACKAGE_CHECK_FAILED")

    run_dir = core_out / "run"
    row["run_dir"] = str(run_dir)
    summary_path = run_dir / "summary.json"
    row["summary_path"] = str(summary_path)
    package_path = run_dir / "package_check.json"
    if package_path.exists():
        row["package_check_path"] = str(package_path)
    summary = optional_json(summary_path)
    if summary:
        apply_run_summary(row, summary)
    elif proc_failed(row):
        diagnostics = optional_json(run_dir / "diagnostics.json")
        code = first_diagnostic_code(diagnostics) or "BRINGUP_FAILED"
        return finish_failure(row, code, "bringup failed before summary.json was written")
    else:
        return finish_failure(row, "SUMMARY_MISSING", "bringup did not write summary.json")

    row["stage"] = stop_stage
    if not proc_failed(row) and row.get("ok") is True:
        return finish_passed(row)
    return finish_failed_existing(row, row.get("first_error_code") or "BRINGUP_FAILED")


def apply_run_summary(row: dict[str, Any], summary: dict[str, Any]) -> None:
    summary_row = summary.get("row") if isinstance(summary.get("row"), dict) else {}
    for key in [
        "ok",
        "first_error_code",
        "blocking_codes",
        "warning_codes",
        "package_ok",
        "active_width",
        "active_height",
        "frames_considered",
        "video_protocol_valid",
        "audio_activity",
        "audio_nonzero_samples",
        "loaded_bytes_total",
        "data_crc_list",
        "shimmed_modules",
        "shim_kinds",
        "shim_confidences",
        "memory_classes",
        "memory_models",
        "memory_risks",
        "memory_activity_observed",
        "memory_error_codes",
    ]:
        if key in summary_row:
            row[key] = summary_row[key]
    diagnostics = summary.get("diagnostics") if isinstance(summary.get("diagnostics"), dict) else {}
    if not row.get("first_error_code"):
        row["first_error_code"] = str(diagnostics.get("first_error_code") or "")
    if not row.get("blocking_codes"):
        row["blocking_codes"] = list_value(diagnostics.get("blocking_codes"))
    if not row.get("warning_codes"):
        row["warning_codes"] = list_value(diagnostics.get("warning_codes"))


def finish_skipped(row: dict[str, Any], reason: str, message: str) -> dict[str, Any]:
    row.update({"status": "skipped", "ok": False, "stage": "preflight", "skip_reason": reason, "message": message, "returncode": 77})
    return row


def finish_preflight_failure(row: dict[str, Any], code: str, message: str) -> dict[str, Any]:
    row.update({"status": "failed", "ok": False, "stage": "preflight", "first_error_code": code, "blocking_codes": [code], "message": message, "returncode": 2})
    return row


def finish_failure(row: dict[str, Any], code: str, message: str) -> dict[str, Any]:
    if not row.get("blocking_codes"):
        row["blocking_codes"] = [code]
    row.update({"status": "failed", "ok": False, "first_error_code": code, "message": message})
    return row


def finish_failed_existing(row: dict[str, Any], code: str) -> dict[str, Any]:
    if code and not row.get("first_error_code"):
        row["first_error_code"] = code
    if code and not row.get("blocking_codes"):
        row["blocking_codes"] = [code]
    row["status"] = "failed"
    row["ok"] = False
    return row


def finish_passed(row: dict[str, Any]) -> dict[str, Any]:
    row["status"] = "passed"
    row["ok"] = True
    if row.get("returncode") is None:
        row["returncode"] = 0
    return row


def build_corpus_summary(manifest: dict[str, Any], rows: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    status_counts = Counter(str(row.get("status") or "unknown") for row in rows)
    blocker_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    for row in rows:
        family_counts[str(row.get("family") or "unknown")] += 1
        if row.get("status") == "failed":
            code = str(row.get("first_error_code") or "UNKNOWN_FAILURE")
            blocker_counts[code] += 1
    totals = {
        "total": len(rows),
        "passed": status_counts.get("passed", 0),
        "failed": status_counts.get("failed", 0),
        "skipped": status_counts.get("skipped", 0),
    }
    return {
        "schema": SCHEMA,
        "manifest": manifest.get("manifest_path", ""),
        "out_dir": str(out_dir),
        "ok": totals["failed"] == 0,
        "totals": totals,
        "status_counts": dict(sorted(status_counts.items())),
        "family_counts": dict(sorted(family_counts.items())),
        "top_blockers": [{"code": code, "count": count} for code, count in blocker_counts.most_common()],
        "cores": rows,
    }


def write_corpus_outputs(doc: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "corpus_summary.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    with (out_dir / "corpus_summary.tsv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TSV_COLUMNS, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in doc.get("cores", []):
            writer.writerow({key: tsv_value(row.get(key)) for key in TSV_COLUMNS})


def command_prefix(cmd: str | Path | list[str]) -> list[str]:
    if isinstance(cmd, list):
        return [str(item) for item in cmd]
    text = str(cmd)
    parts = shlex.split(text)
    return parts if parts else [text]


def command_timeout_from_cmd(cmd: list[str]) -> int | None:
    if "--timeout" in cmd:
        try:
            idx = cmd.index("--timeout")
            runtime_timeout = int(cmd[idx + 1])
            return runtime_timeout + 120
        except (ValueError, IndexError):
            return None
    return None


def optional_path(value: Any, base: Path) -> Path | None:
    if value in (None, ""):
        return None
    return resolve_value_path(value, base)


def resolve_value_path(value: Any, base: Path) -> Path:
    text = os.path.expanduser(os.path.expandvars(str(value)))
    path = Path(text)
    return path if path.is_absolute() else (base / path).resolve()


def proc_failed(row: dict[str, Any]) -> bool:
    rc = row.get("returncode")
    return isinstance(rc, int) and rc not in (0,)


def first_diagnostic_code(doc: dict[str, Any]) -> str:
    for item in doc.get("diagnostics", []):
        if isinstance(item, dict) and item.get("severity") == "error":
            return str(item.get("code") or "")
    return ""


def optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    return value or "core"


def tsv_value(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
