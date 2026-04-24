import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "apfsim"
sys.path.insert(0, str(ROOT / "scripts"))

from apfsim_cli import Profile, write_source_provenance


def test_source_provenance_keeps_generated_sim_only_and_memory_counter_declarations(tmp_path):
    root = tmp_path / "core"
    root.mkdir()
    profile_path = tmp_path / "profiles" / "fake.json"
    profile_path.parent.mkdir()
    raw = {
        "name": "fake",
        "top": "core_top",
        "filelist": "{profile_dir}/filelist.f",
        "scenario": "{profile_dir}/scenario.yml",
        "root": str(root),
        "required_paths": ["{apfsim}/rtl_shims/external_memory_models.sv"],
        "sim_only_paths": ["{root}/generated/apfsim/coreir_apfsim_compat.sv"],
        "generated_file_provenance": [
            {
                "path": "{root}/generated/apfsim/coreir_apfsim_compat.sv",
                "kind": "compat_wrapper",
                "sim_only": True,
            }
        ],
        "memory": {
            "classes": ["sram"],
            "external_classes": ["sram"],
            "models": {
                "sram": {
                    "selected": "async_sram_16_pin",
                    "confidence": "scaffold_only",
                    "source": "rtl_shims/external_memory_models.sv",
                }
            },
            "risks": [
                {
                    "code": "SRAM_MODEL_REQUIRED",
                    "severity": "error",
                    "message": "SRAM wrapper wiring is required.",
                }
            ],
        },
        "wrapper_generation": {
            "memory_models": {
                "generated": True,
                "activity_counters": ["sram_read_count", "sram_write_count"],
            }
        },
    }
    profile = Profile(name="fake", path=profile_path, raw=raw, root=root)

    doc = write_source_provenance(profile, tmp_path / "run")

    compat_path = str(root / "generated" / "apfsim" / "coreir_apfsim_compat.sv")
    assert compat_path in doc["sim_only_paths"]
    assert doc["generated_file_provenance"][0]["path"] == compat_path
    memory = json.loads((tmp_path / "run" / "memory_activity.json").read_text())
    assert memory["declared_counters"] == ["sram_read_count", "sram_write_count"]
    assert memory["counter_status"] == "declared_not_observed"
    assert memory["errors"][0]["code"] == "SRAM_MODEL_REQUIRED"


def test_memory_activity_merges_runtime_counters_from_result_json(tmp_path):
    root = tmp_path / "core"
    root.mkdir()
    profile_path = tmp_path / "profiles" / "fake.json"
    profile_path.parent.mkdir()
    raw = {
        "name": "fake",
        "top": "core_top",
        "filelist": "{profile_dir}/filelist.f",
        "scenario": "{profile_dir}/scenario.yml",
        "root": str(root),
        "memory": {
            "classes": ["sram"],
            "external_classes": ["sram"],
            "models": {
                "sram": {
                    "selected": "standard_top_counter_ports",
                    "confidence": "observed",
                    "source": "generated/apfsim/wrapper.sv",
                }
            },
            "risks": [],
        },
        "wrapper_generation": {
            "memory_models": {
                "generated": False,
                "activity_counters": ["sram_read_count", "sram_write_count"],
            }
        },
    }
    artifacts = tmp_path / "run"
    artifacts.mkdir()
    (artifacts / "result.json").write_text(json.dumps({
        "ok": True,
        "memory_activity": {
            "schema": "apfsim.memory_activity.runtime.v1",
            "observed": True,
            "counter_status": "observed",
            "counters": [
                {"name": "sram_read_count", "class": "sram", "value": 12, "error": False},
                {"name": "sram_byte_enable_error", "class": "sram", "value": 1, "error": True, "error_code": "MEMORY_BYTE_ENABLE_MISMATCH"},
            ],
            "errors": [
                {"code": "MEMORY_BYTE_ENABLE_MISMATCH", "severity": "error", "counter": "sram_byte_enable_error", "observed": True},
            ],
        },
    }))
    profile = Profile(name="fake", path=profile_path, raw=raw, root=root)

    write_source_provenance(profile, artifacts)

    memory = json.loads((artifacts / "memory_activity.json").read_text())
    assert memory["observed"] is True
    assert memory["counter_status"] == "observed"
    assert memory["counters"][0]["name"] == "sram_read_count"
    assert memory["counters"][0]["value"] == 12
    assert memory["errors"][0]["code"] == "MEMORY_BYTE_ENABLE_MISMATCH"


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_mock_memory_activity_profile_observes_standard_counter_ports(tmp_path):
    artifacts = tmp_path / "mock-memory"
    r = subprocess.run([
        str(CLI),
        "run",
        "--profile", "mock_memory_activity",
        "--frames", "2",
        "--artifacts", str(artifacts),
    ], cwd=ROOT, text=True, capture_output=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr

    result = json.loads((artifacts / "result.json").read_text())
    runtime = result["memory_activity"]
    assert runtime["observed"] is True
    counters = {item["name"]: item["value"] for item in runtime["counters"]}
    assert counters["sram_write_count"] > 0
    assert "sram_read_count" in counters

    memory = json.loads((artifacts / "memory_activity.json").read_text())
    assert memory["observed"] is True
    assert memory["counter_status"] == "observed"
    assert {item["name"] for item in memory["counters"]} >= {"sram_read_count", "sram_write_count"}
