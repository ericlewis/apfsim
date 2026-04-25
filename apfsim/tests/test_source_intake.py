import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "apfsim"


def make_shell_core(root: Path) -> Path:
    core_dir = root / "dist" / "Cores" / "example.Shell"
    rtl_dir = root / "src" / "fpga" / "core"
    asset_dir = root / "dist" / "Assets"
    core_dir.mkdir(parents=True)
    rtl_dir.mkdir(parents=True)
    asset_dir.mkdir(parents=True)
    (asset_dir / "shell.rom").write_bytes(bytes(range(32)))
    (core_dir / "core.json").write_text('{"core":{"metadata":{"shortname":"Shell","platform_ids":["shell"]}}}\n')
    (core_dir / "video.json").write_text('{"video":{"scaler_modes":[{"width":320,"height":240}]}}\n')
    (core_dir / "interact.json").write_text('{"interact":{"variables":[]}}\n')
    (core_dir / "data.json").write_text(json.dumps({
        "data": {
            "data_slots": [
                {
                    "id": 1,
                    "name": "ROM",
                    "address": "0x10000000",
                    "required": True,
                    "filename": "shell.rom",
                    "extensions": ["rom"],
                }
            ]
        }
    }) + "\n")
    (rtl_dir / "game_top.sv").write_text(
        """
module game_top(
    input  wire       refclk,
    input  wire       reset_n,
    input  wire [31:0] joystick_0,
    output wire [3:0] VGA_R,
    output wire [3:0] VGA_G,
    output wire [3:0] VGA_B,
    output wire       HSync,
    output wire       VSync,
    output wire       HBLANK,
    output wire       VBLANK,
    output wire [15:0] audio_l
);
    assign VGA_R = joystick_0[3:0];
    assign VGA_G = 4'h0;
    assign VGA_B = 4'h0;
    assign HSync = 1'b0;
    assign VSync = 1'b0;
    assign HBLANK = 1'b0;
    assign VBLANK = 1'b0;
    assign audio_l = 16'h0;
endmodule
"""
    )
    (root / "src" / "fpga" / "ap_core.qsf").write_text(
        "\n".join([
            "set_global_assignment -name TOP_LEVEL_ENTITY game_top",
            "set_global_assignment -name SYSTEMVERILOG_FILE core/game_top.sv",
            "",
        ])
    )
    return root


def test_intake_emits_source_contract_for_shell_core(tmp_path):
    core = make_shell_core(tmp_path / "openFPGA-Shell")
    out = tmp_path / "intake"
    r = subprocess.run([
        str(CLI),
        "intake",
        "--root", str(core),
        "--output", str(out),
        "--json",
    ], cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr

    contract = json.loads(r.stdout)
    assert contract["schema"] == "apfsim.source_contract.v1"
    assert contract["classification"]["mode"] == "shell-mode"
    assert contract["classification"]["status"] == "blocked"
    assert contract["top"]["selected"] == "game_top"
    assert contract["top"]["qsf_top"] == "game_top"
    assert "video" in contract["top"]["candidates"][0]["signals"]
    assert contract["metadata"]["video_modes"] == ["320x240"]
    assert contract["metadata"]["data_slots"][0]["address"] == "0x10000000"
    assert any(item["code"] == "BRIDGE_MAPPING_MISSING" for item in contract["blockers"])
    assert (out / "source_contract.json").exists()
    assert (out / "source_contract.md").exists()


def test_synth_wrapper_attaches_source_contract(tmp_path):
    core = make_shell_core(tmp_path / "openFPGA-Shell")
    out = tmp_path / "synth"
    r = subprocess.run([
        str(CLI),
        "synth-wrapper",
        "--root", str(core),
        "--output", str(out),
        "--json",
    ], cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr

    report = json.loads(r.stdout)
    contract_path = Path(report["paths"]["source_contract"])
    assert contract_path.exists()
    contract = json.loads(contract_path.read_text())
    assert contract["schema"] == "apfsim.source_contract.v1"
    assert contract["top"]["selected"] == "game_top"
    persisted = json.loads((contract_path.parent / "wrapper_synthesis.json").read_text())
    assert persisted["paths"]["source_contract"] == str(contract_path)
