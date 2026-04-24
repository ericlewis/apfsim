import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "apfsim"
sys.path.insert(0, str(ROOT / "scripts"))

from run_summary import summarize_run, write_summary


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def make_artifacts(root: Path):
    write_json(root / "result.json", {
        "ok": True,
        "video_shape": {
            "active_width": 256,
            "active_height": 224,
            "frames_considered": 3,
            "startup_frames_ignored": 1,
            "protocol_valid": True,
        },
        "video_protocol": {"valid": True, "first_error_cycle": 0},
        "audio": {"activity": "active", "samples": 100, "nonzero_samples": 99, "peak": 1234},
        "data_load": {
            "total_loaded_bytes": 1024,
            "slots": [{"id": 1, "loaded_bytes": 1024, "crc": "0x12345678"}],
        },
        "input": {"input_effect_seen": True},
        "input_effect_seen": True,
        "interact_readback": {"verified": True},
        "reset_action_seen": True,
    })
    write_json(root / "diagnostics.json", {
        "schema": "apfsim.diagnostics.v1",
        "status": "pass",
        "summary": {"errors": 0, "warnings": 1, "infos": 0},
        "diagnostics": [{"code": "VIDEO_STATIC_FRAME", "severity": "warning"}],
    })
    write_json(root / "package_check.json", {
        "schema": "apfsim.package_check.v1",
        "ok": True,
        "package_errors": [],
        "package_warnings": [],
    })
    write_json(root / "source_provenance.json", {
        "schema": "apfsim.source_provenance.v1",
        "shimmed_modules": [{
            "name": "intel_bram_shims",
            "kind": "behavioral_model",
            "confidence": "sim_only",
            "modules": ["altsyncram"],
        }],
        "memory_dependencies": {
            "schema": "apfsim.memory_dependencies.v1",
            "required": True,
            "classes": ["sdram", "bram"],
            "external_classes": ["sdram"],
            "models": {
                "sdram": {"selected": "ideal_transactional", "confidence": "bringup_only", "source": "rtl_shims/sdram_sim.sv"}
            },
            "risks": [{"code": "SDRAM_TIMING_NOT_POCKET_LIKE", "severity": "warning"}],
        },
        "memory_models": [
            {"class": "sdram", "model": "ideal_transactional", "confidence": "bringup_only", "source": "rtl_shims/sdram_sim.sv"}
        ],
    })
    write_json(root / "memory_activity.json", {
        "schema": "apfsim.memory_activity.v1",
        "profile": "fake",
        "observed": False,
        "classes": ["sdram", "bram"],
        "external_classes": ["sdram"],
        "models": [],
        "counters": [],
        "errors": [{"code": "SDRAM_INIT_TIMEOUT", "severity": "error", "observed": False}],
    })


def test_summarize_run_flattens_artifacts(tmp_path):
    artifacts = tmp_path / "run"
    make_artifacts(artifacts)

    doc = summarize_run(artifacts)

    assert doc["schema"] == "apfsim.run_summary.v1"
    assert doc["ok"] is True
    row = doc["row"]
    assert row["active_width"] == 256
    assert row["active_height"] == 224
    assert row["frames_considered"] == 3
    assert row["audio_activity"] == "active"
    assert row["data_crc_list"] == ["0x12345678"]
    assert row["shimmed_modules"] == ["intel_bram_shims"]
    assert row["shim_kinds"] == ["intel_bram_shims:behavioral_model"]
    assert row["shim_confidences"] == ["intel_bram_shims:sim_only"]
    assert row["memory_classes"] == ["sdram", "bram"]
    assert row["memory_models"] == ["sdram:ideal_transactional"]
    assert row["memory_risks"] == ["SDRAM_TIMING_NOT_POCKET_LIKE"]
    assert row["memory_activity_observed"] is False
    assert row["memory_error_codes"] == ["SDRAM_INIT_TIMEOUT"]
    assert doc["source_provenance"]["shim_details"][0]["modules"] == ["altsyncram"]
    assert doc["source_provenance"]["memory_activity"]["schema"] == "apfsim.memory_activity.v1"


def test_write_summary_emits_json_and_tsv(tmp_path):
    artifacts = tmp_path / "run"
    make_artifacts(artifacts)

    doc = write_summary(artifacts)

    assert doc["ok"] is True
    assert (artifacts / "summary.json").exists()
    tsv = (artifacts / "summary.tsv").read_text()
    assert "first_error_code" in tsv.splitlines()[0]
    assert "0x12345678" in tsv


def test_summarize_run_cli(tmp_path):
    artifacts = tmp_path / "run"
    make_artifacts(artifacts)
    out = tmp_path / "summary.json"
    tsv = tmp_path / "summary.tsv"

    r = subprocess.run(
        [str(CLI), "summarize-run", str(artifacts), "--json-out", str(out), "--tsv-out", str(tsv), "--strict"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert r.returncode == 0, r.stdout + r.stderr
    assert out.exists()
    assert tsv.exists()
    assert "summary: ok=True" in r.stdout
