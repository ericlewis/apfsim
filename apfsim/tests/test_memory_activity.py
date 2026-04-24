import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
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
