import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from apfsim_cli import write_repair_plan


def test_repair_plan_adds_memory_specific_hints_and_patch_notes(tmp_path):
    artifacts = tmp_path / "run"
    artifacts.mkdir()
    diagnostics = {
        "schema": "apfsim.diagnostics.v1",
        "diagnostics": [
            {
                "code": "DATA_SLOT_READBACK_MISMATCH",
                "phase": "data",
                "severity": "error",
                "repairs": [],
            },
            {
                "code": "SRAM_MODEL_REQUIRED",
                "phase": "source",
                "severity": "error",
                "repairs": [],
            },
        ],
    }

    write_repair_plan(artifacts, diagnostics, emit_patches=True)

    plan = json.loads((artifacts / "repair-plan.json").read_text())
    assert plan["schema"] == "apfsim.repair_plan.v1"
    kinds = {item["kind"] for item in plan["repairs"]}
    assert "memory_corruption_probe" in kinds
    assert "profile_patch_hint" in kinds
    assert (artifacts / "patches" / "memory_model_hints.md").exists()
    hints = (artifacts / "patches" / "memory_model_hints.md").read_text()
    assert "DATA_SLOT_READBACK_MISMATCH" in hints
    assert "external_sram_pin_model" in hints
