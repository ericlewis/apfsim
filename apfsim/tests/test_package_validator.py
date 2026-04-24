import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "apfsim"
sys.path.insert(0, str(ROOT / "scripts"))


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def make_package(root: Path, *, folder="Dev.Good", bitstream=True):
    core_dir = root / "Cores" / folder
    core_dir.mkdir(parents=True)
    write_json(core_dir / "core.json", {
        "core": {
            "magic": "APF_VER_1",
            "metadata": {
                "platform_ids": ["arcade_good"],
                "shortname": "Good",
                "author": "Dev",
                "description": "Good core",
                "url": "https://example.invalid",
                "version": "1.0.0",
                "date_release": "2026-04-24",
            },
            "framework": {"target_product": "Analogue Pocket", "version_required": "1.1"},
            "cores": [{"id": 0, "filename": "bitstream.rbf_r"}],
        }
    })
    if bitstream:
        (core_dir / "bitstream.rbf_r").write_bytes(b"rbf")
    write_json(core_dir / "audio.json", {"audio": {"magic": "APF_VER_1"}})
    write_json(core_dir / "data.json", {
        "data": {
            "magic": "APF_VER_1",
            "data_slots": [
                {"id": 1, "name": "ROM", "required": True, "parameters": 0, "filename": "game.rom", "extensions": ["rom"], "size_maximum": 1024, "address": "0x10000000"},
                {"id": 4, "name": "SAVE", "nonvolatile": True, "parameters": 0, "extensions": ["sav"], "size_maximum": 64, "address": "0x20000000"},
            ],
        }
    })
    write_json(core_dir / "input.json", {"input": {"controllers": [{"type": "default", "mappings": [{"id": 0, "name": "A", "key": "pad_btn_a"}]}]}})
    write_json(core_dir / "interact.json", {"interact": {"variables": [{"id": 1, "name": "Dip", "type": "check", "address": "0x50000010", "persist": True}]}})
    write_json(core_dir / "variants.json", {"variants": {"magic": "APF_VER_1", "variant_list": []}})
    write_json(core_dir / "video.json", {"video": {"magic": "APF_VER_1", "scaler_modes": [{"width": 256, "height": 224, "aspect_w": 4, "aspect_h": 3, "rotation": 0, "mirror": 0}]}})
    write_json(root / "Platforms" / "arcade_good.json", {"platform": {"category": "Arcade", "name": "Good", "manufacturer": "Dev", "year": 1980}})
    (root / "Assets" / "arcade_good" / "common").mkdir(parents=True)
    (root / "Assets" / "arcade_good" / "common" / "game.rom").write_bytes(b"rom")
    return core_dir


def test_package_validator_accepts_valid_sd_package(tmp_path):
    from package_validator import validate_package

    make_package(tmp_path)
    doc = validate_package(tmp_path, expected_platform_id="arcade_good")

    assert doc["schema"] == "apfsim.package_check.v1"
    assert doc["ok"] is True
    assert doc["package_errors"] == []
    assert doc["sd_paths"]["core_dir"] == "/Cores/Dev.Good"
    assert "/Assets/arcade_good/common/game.rom" in doc["sd_paths"]["assets"]
    assert doc["sd_paths"]["saves"] == ["/Saves/arcade_good/common/slot_4.sav"]


def test_package_validator_reports_folder_and_bitstream_errors(tmp_path):
    from package_validator import validate_package

    make_package(tmp_path, folder="Wrong.Name", bitstream=False)
    doc = validate_package(tmp_path, expected_platform_id="other")
    codes = {item["code"] for item in doc["package_errors"]}

    assert doc["ok"] is False
    assert "CORE_FOLDER_NAME_MISMATCH" in codes
    assert "BITSTREAM_FILE_MISSING" in codes
    assert "PLATFORM_ID_MISMATCH" in codes


def test_package_check_cli_writes_json_out(tmp_path):
    make_package(tmp_path)
    out = tmp_path / "package_check.json"
    r = subprocess.run(
        [str(CLI), "package-check", "--root", str(tmp_path), "--expected-platform-id", "arcade_good", "--json-out", str(out), "--strict"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(out.read_text())
    assert doc["ok"] is True
    assert "package-check: ok=True" in r.stdout
