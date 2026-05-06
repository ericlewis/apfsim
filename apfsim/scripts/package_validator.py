#!/usr/bin/env python3
"""APF package/metadata validator for hardware-queue decisions."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SCHEMA = "apfsim.package_check.v1"
REQUIRED_CORE_FILES = ("core.json", "audio.json", "data.json", "input.json", "interact.json", "variants.json", "video.json")


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"missing {path.name}"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "top-level JSON value must be an object"
    return data, None


def _section(data: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    value = data.get(key)
    return value if isinstance(value, dict) else data


def _array(section: dict[str, Any], key: str) -> list[Any]:
    value = section.get(key)
    return value if isinstance(value, list) else []


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip(), 0)
        except ValueError:
            return default
    return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _clean_rel(value: str) -> str:
    return value.replace("\\", "/").lstrip("/")


def _add(items: list[dict[str, Any]], code: str, message: str, *, path: str = "", severity: str = "error") -> None:
    items.append({"code": code, "severity": severity, "path": path, "message": message})


def find_core_dir(root: Path) -> Path | None:
    root = root.resolve()
    if (root / "core.json").exists():
        return root
    cores_dir = root / "Cores"
    if cores_dir.is_dir():
        candidates = sorted(path.parent for path in cores_dir.glob("*/core.json"))
        if candidates:
            return candidates[0]
    candidates = sorted(
        (path.parent for path in root.glob("**/core.json") if "/build/" not in path.as_posix()),
        key=lambda p: (len(p.relative_to(root).parts), str(p)),
    )
    return candidates[0] if candidates else None


def validate_package(root: Path, *, expected_platform_id: str | None = None) -> dict[str, Any]:
    root = Path(os.path.expanduser(os.path.expandvars(str(root)))).resolve()
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    core_dir = find_core_dir(root)
    if core_dir is None:
        _add(errors, "CORE_JSON_MISSING", "No core.json found under root.", path=str(root))
        return _doc(root, None, {}, {}, {}, errors, warnings, {}, [], [], [])

    files: dict[str, dict[str, Any] | None] = {}
    for name in REQUIRED_CORE_FILES:
        path = core_dir / name
        data, issue = _load_json(path)
        files[name] = data
        if issue:
            _add(errors, "REQUIRED_JSON_MISSING" if "missing" in issue else "JSON_INVALID", issue, path=str(path))

    core_json = _section(files.get("core.json"), "core")
    metadata = core_json.get("metadata") if isinstance(core_json.get("metadata"), dict) else {}
    author = str(metadata.get("author") or "").strip()
    shortname = str(metadata.get("shortname") or metadata.get("/") or "").strip()
    platform_ids = [str(item) for item in metadata.get("platform_ids", [])] if isinstance(metadata.get("platform_ids"), list) else []
    expected_core_name = f"{author}.{shortname}" if author and shortname else ""

    if not author:
        _add(errors, "CORE_AUTHOR_MISSING", "core.metadata.author is required.", path=str(core_dir / "core.json"))
    if not shortname:
        _add(errors, "CORE_SHORTNAME_MISSING", "core.metadata.shortname is required.", path=str(core_dir / "core.json"))
    if expected_core_name:
        if core_dir.parent.name == "Cores" and core_dir.name != expected_core_name:
            _add(errors, "CORE_FOLDER_NAME_MISMATCH", f"Core folder is {core_dir.name}, expected {expected_core_name}.", path=str(core_dir))
        elif core_dir.name != expected_core_name:
            _add(warnings, "CHECKOUT_NOT_SD_CORE_FOLDER", f"Checkout folder is {core_dir.name}; SD core folder should be {expected_core_name}.", path=str(core_dir), severity="warning")

    if expected_platform_id and expected_platform_id not in platform_ids:
        _add(errors, "PLATFORM_ID_MISMATCH", f"Expected platform id {expected_platform_id} is not declared.", path=str(core_dir / "core.json"))

    sd_core_dir = f"/Cores/{expected_core_name or core_dir.name}"
    sd_paths = {
        "core_dir": sd_core_dir,
        "core_files": {name: f"{sd_core_dir}/{name}" for name in REQUIRED_CORE_FILES},
        "bitstreams": [],
        "assets": [],
        "saves": [],
        "platforms": [],
    }

    _validate_bitstreams(core_dir, core_json, sd_paths, errors, warnings)
    platform_paths = _validate_platforms(root, core_dir, platform_ids, expected_core_name, sd_paths, errors, warnings)
    assets, saves = _validate_data_slots(root, core_dir, files.get("data.json"), platform_ids, expected_core_name, sd_paths, errors, warnings)
    _validate_video(files.get("video.json"), errors, warnings, core_dir / "video.json")
    _validate_interact(files.get("interact.json"), errors, warnings, core_dir / "interact.json")
    _validate_input(files.get("input.json"), errors, warnings, core_dir / "input.json")
    _validate_variants(files.get("variants.json"), errors, warnings, core_dir / "variants.json")

    metadata_out = {
        "author": author,
        "shortname": shortname,
        "core_folder": core_dir.name,
        "expected_core_folder": expected_core_name,
        "platform_ids": platform_ids,
    }
    return _doc(root, core_dir, metadata_out, core_json, sd_paths, errors, warnings, platform_paths, assets, saves, files)


def _validate_bitstreams(core_dir: Path, core_json: dict[str, Any], sd_paths: dict[str, Any], errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    cores = _array(core_json, "cores")
    if not cores:
        _add(errors, "BITSTREAM_LIST_MISSING", "core.cores must contain at least one bitstream entry.", path=str(core_dir / "core.json"))
        return
    seen_ids: set[int] = set()
    for idx, item in enumerate(cores):
        if not isinstance(item, dict):
            _add(errors, "BITSTREAM_ENTRY_INVALID", f"core.cores[{idx}] must be an object.", path=str(core_dir / "core.json"))
            continue
        core_id = _as_int(item.get("id"), -1)
        if core_id in seen_ids:
            _add(errors, "BITSTREAM_ID_DUPLICATE", f"Duplicate bitstream id {core_id}.", path=str(core_dir / "core.json"))
        seen_ids.add(core_id)
        filename = str(item.get("filename") or "").strip()
        if not filename:
            _add(errors, "BITSTREAM_FILENAME_MISSING", f"core.cores[{idx}].filename is required.", path=str(core_dir / "core.json"))
            continue
        sd_paths["bitstreams"].append(f"{sd_paths['core_dir']}/{filename}")
        if not (core_dir / filename).exists():
            _add(errors, "BITSTREAM_FILE_MISSING", f"Bitstream file {filename} is not present beside core.json.", path=str(core_dir / filename))
        if not filename.endswith(".rbf_r"):
            _add(warnings, "BITSTREAM_NOT_RBF_R", f"Bitstream filename {filename} does not end with .rbf_r.", path=str(core_dir / filename), severity="warning")


def _validate_platforms(
    root: Path,
    core_dir: Path,
    platform_ids: list[str],
    core_name: str,
    sd_paths: dict[str, Any],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> list[str]:
    found: list[str] = []
    for platform_id in platform_ids:
        rel = f"/Platforms/{platform_id}.json"
        sd_paths["platforms"].append(rel)
        candidates = [root / "Platforms" / f"{platform_id}.json", core_dir.parent.parent / "Platforms" / f"{platform_id}.json"]
        if any(path.exists() for path in candidates):
            found.append(rel)
        else:
            _add(errors, "PLATFORM_JSON_MISSING", f"Platform metadata {rel} is missing.", path=rel)
    if not platform_ids:
        _add(warnings, "PLATFORM_STANDALONE", f"{core_name or core_dir.name} declares no platform_ids; treating as standalone.", path=str(core_dir / "core.json"), severity="warning")
    return found


def _slot_asset_base(platform_ids: list[str], core_name: str, parameters: int) -> str:
    core_specific = bool(parameters & (1 << 1))
    platform_index = (parameters >> 24) & 0x3
    platform = platform_ids[platform_index] if platform_ids and platform_index < len(platform_ids) else "_none"
    owner = core_name if core_specific or platform == "_none" else "common"
    return f"/Assets/{platform}/{owner}"


def _slot_save_base(platform_ids: list[str], core_name: str, parameters: int) -> str:
    core_specific = bool(parameters & (1 << 1))
    platform_index = (parameters >> 24) & 0x3
    platform = platform_ids[platform_index] if platform_ids and platform_index < len(platform_ids) else "_none"
    owner = core_name if core_specific or platform == "_none" else "common"
    return f"/Saves/{platform}/{owner}"


def _validate_data_slots(
    root: Path,
    core_dir: Path,
    data_json: dict[str, Any] | None,
    platform_ids: list[str],
    core_name: str,
    sd_paths: dict[str, Any],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    data = _section(data_json, "data")
    slots = _array(data, "data_slots")
    assets: list[str] = []
    saves: list[str] = []
    if len(slots) > 32:
        _add(errors, "DATA_SLOT_COUNT_EXCEEDED", f"data.json defines {len(slots)} slots; APF supports at most 32.", path=str(core_dir / "data.json"))
    seen_ids: set[int] = set()
    for idx, slot in enumerate(slots):
        if not isinstance(slot, dict):
            _add(errors, "DATA_SLOT_INVALID", f"data_slots[{idx}] must be an object.", path=str(core_dir / "data.json"))
            continue
        slot_id = _as_int(slot.get("id"), -1)
        if not 0 <= slot_id <= 0xFFFF:
            _add(errors, "DATA_SLOT_ID_INVALID", f"data_slots[{idx}].id must be 0..65535.", path=str(core_dir / "data.json"))
        if slot_id in seen_ids:
            _add(errors, "DATA_SLOT_ID_DUPLICATE", f"Duplicate data slot id {slot_id}.", path=str(core_dir / "data.json"))
        seen_ids.add(slot_id)
        if "address" in slot and slot.get("address") not in (None, ""):
            address = _as_int(slot.get("address"), -1)
        else:
            address = 0
        if not 0 <= address <= 0xFFFFFFFF:
            _add(errors, "DATA_SLOT_ADDRESS_INVALID", f"data slot {slot_id} has invalid 32-bit address.", path=str(core_dir / "data.json"))
        size_exact = _as_int(slot.get("size_exact"), 0)
        size_maximum = _as_int(slot.get("size_maximum"), 0)
        if size_exact and size_maximum and size_exact > size_maximum:
            _add(errors, "DATA_SLOT_SIZE_INVALID", f"slot {slot_id} size_exact exceeds size_maximum.", path=str(core_dir / "data.json"))
        extensions = slot.get("extensions", [])
        if extensions and (not isinstance(extensions, list) or len(extensions) > 4):
            _add(errors, "DATA_SLOT_EXTENSIONS_INVALID", f"slot {slot_id} extensions must contain at most 4 items.", path=str(core_dir / "data.json"))
        parameters = _as_int(slot.get("parameters"), 0)
        filename = str(slot.get("filename") or slot.get("file") or "").strip()
        if filename:
            asset = f"{_slot_asset_base(platform_ids, core_name, parameters)}/{_clean_rel(filename)}"
            assets.append(asset)
            sd_paths["assets"].append(asset)
            host_asset = root / asset.lstrip("/")
            if not host_asset.exists() and (root / "Assets").exists():
                _add(errors, "ASSET_FILE_MISSING", f"Required asset path does not exist: {asset}", path=str(host_asset))
            elif not host_asset.exists():
                _add(warnings, "ASSET_FILE_NOT_IN_CHECKOUT", f"Asset path expected on SD: {asset}", path=asset, severity="warning")
        if _as_bool(slot.get("nonvolatile"), False):
            ext = "sav"
            if isinstance(extensions, list) and extensions:
                ext = str(extensions[0]).lstrip(".") or ext
            stem = Path(filename).stem if filename else f"slot_{slot_id}"
            save = f"{_slot_save_base(platform_ids, core_name, parameters)}/{stem}.{ext}"
            saves.append(save)
            sd_paths["saves"].append(save)
    return assets, saves


def _validate_video(video_json: dict[str, Any] | None, errors: list[dict[str, Any]], warnings: list[dict[str, Any]], path: Path) -> None:
    video = _section(video_json, "video")
    modes = _array(video, "scaler_modes")
    if not modes:
        _add(errors, "VIDEO_SCALER_MODES_MISSING", "video.scaler_modes must contain at least one mode.", path=str(path))
        return
    if len(modes) > 8:
        _add(errors, "VIDEO_SCALER_MODE_COUNT_EXCEEDED", f"video.json defines {len(modes)} scaler modes; APF supports at most 8.", path=str(path))
    for idx, mode in enumerate(modes):
        if not isinstance(mode, dict):
            _add(errors, "VIDEO_SCALER_MODE_INVALID", f"scaler_modes[{idx}] must be an object.", path=str(path))
            continue
        width = _as_int(mode.get("width"), 0)
        height = _as_int(mode.get("height"), 0)
        if not 16 <= width <= 800 or not 16 <= height <= 720:
            _add(errors, "VIDEO_DIMENSIONS_INVALID", f"scaler mode {idx} has invalid APF dimensions {width}x{height}.", path=str(path))
        rotation = _as_int(mode.get("rotation"), 0)
        if rotation not in {0, 90, 180, 270}:
            _add(errors, "VIDEO_ROTATION_INVALID", f"scaler mode {idx} rotation must be 0, 90, 180, or 270.", path=str(path))
        if _as_int(mode.get("aspect_w"), 1) <= 0 or _as_int(mode.get("aspect_h"), 1) <= 0:
            _add(errors, "VIDEO_ASPECT_INVALID", f"scaler mode {idx} aspect ratio must be positive.", path=str(path))


def _validate_interact(interact_json: dict[str, Any] | None, errors: list[dict[str, Any]], warnings: list[dict[str, Any]], path: Path) -> None:
    interact = _section(interact_json, "interact")
    variables = _array(interact, "variables")
    if len(variables) > 16:
        _add(warnings, "INTERACT_VARIABLE_COUNT_EXCEEDED", f"interact.json defines {len(variables)} variables; Pocket displays at most 16 plus reload actions.", path=str(path), severity="warning")
    seen_ids: set[int] = set()
    persistent_ids: set[int] = set()
    for idx, variable in enumerate(variables):
        if not isinstance(variable, dict):
            _add(errors, "INTERACT_VARIABLE_INVALID", f"variables[{idx}] must be an object.", path=str(path))
            continue
        var_id = _as_int(variable.get("id"), -1)
        if not 0 <= var_id <= 0xFFFF:
            _add(errors, "INTERACT_ID_INVALID", f"variables[{idx}].id must be 0..65535.", path=str(path))
        if var_id in seen_ids:
            _add(errors, "INTERACT_ID_DUPLICATE", f"Duplicate interact id {var_id}.", path=str(path))
        seen_ids.add(var_id)
        address = _as_int(variable.get("address"), -1)
        if not 0 <= address <= 0xFFFFFFFF:
            _add(errors, "INTERACT_ADDRESS_INVALID", f"interact id {var_id} has invalid 32-bit bridge address.", path=str(path))
        if _as_bool(variable.get("persist"), False):
            if var_id in persistent_ids:
                _add(errors, "INTERACT_PERSIST_ID_DUPLICATE", f"Duplicate persistent interact id {var_id}.", path=str(path))
            persistent_ids.add(var_id)


def _validate_input(input_json: dict[str, Any] | None, errors: list[dict[str, Any]], warnings: list[dict[str, Any]], path: Path) -> None:
    input_section = _section(input_json, "input")
    controllers = _array(input_section, "controllers")
    if len(controllers) > 4:
        _add(errors, "INPUT_CONTROLLER_COUNT_EXCEEDED", f"input.json defines {len(controllers)} controllers; APF supports at most 4.", path=str(path))
    for idx, controller in enumerate(controllers):
        if not isinstance(controller, dict):
            _add(errors, "INPUT_CONTROLLER_INVALID", f"controllers[{idx}] must be an object.", path=str(path))
            continue
        mappings = controller.get("mappings", [])
        if isinstance(mappings, list) and len(mappings) > 8:
            _add(warnings, "INPUT_MAPPING_COUNT_EXCEEDED", f"controller {idx} defines {len(mappings)} mappings; Controls menu supports up to 8.", path=str(path), severity="warning")


def _validate_variants(variants_json: dict[str, Any] | None, errors: list[dict[str, Any]], warnings: list[dict[str, Any]], path: Path) -> None:
    variants = _section(variants_json, "variants")
    variant_list = _array(variants, "variant_list")
    if len(variant_list) > 8:
        _add(errors, "VARIANT_COUNT_EXCEEDED", f"variants.json defines {len(variant_list)} variants; APF supports at most 8.", path=str(path))


def _doc(
    root: Path,
    core_dir: Path | None,
    metadata: dict[str, Any],
    core_json: dict[str, Any],
    sd_paths: dict[str, Any],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    platform_paths: Any,
    assets: Any,
    saves: Any,
    files: Any,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "root": str(root),
        "core_dir": str(core_dir) if core_dir else "",
        "ok": not errors,
        "metadata": metadata,
        "package_errors": errors,
        "package_warnings": warnings,
        "sd_paths": sd_paths or {"core_dir": "", "core_files": {}, "bitstreams": [], "assets": [], "saves": [], "platforms": []},
        "counts": {
            "errors": len(errors),
            "warnings": len(warnings),
            "assets": len(assets) if isinstance(assets, list) else 0,
            "saves": len(saves) if isinstance(saves, list) else 0,
            "platforms": len(platform_paths) if isinstance(platform_paths, list) else 0,
        },
    }


def write_package_check(root: Path, output: Path, *, expected_platform_id: str | None = None) -> dict[str, Any]:
    doc = validate_package(root, expected_platform_id=expected_platform_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc
