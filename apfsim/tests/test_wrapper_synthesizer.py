import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "apfsim"


def make_wrappable_core(root: Path) -> Path:
    core_dir = root / "dist" / "Cores" / "example.Wrap"
    rtl_dir = root / "src" / "fpga" / "core"
    asset_dir = root / "dist" / "Assets"
    core_dir.mkdir(parents=True)
    rtl_dir.mkdir(parents=True)
    asset_dir.mkdir(parents=True)
    (asset_dir / "wrap.rom").write_bytes(bytes(range(16)))
    (core_dir / "core.json").write_text('{"core":{"metadata":{"shortname":"Wrap","platform_ids":["wrap"]}}}\n')
    (core_dir / "video.json").write_text('{"video":{"scaler_modes":[{"width":256,"height":224}]}}\n')
    (core_dir / "interact.json").write_text('{"interact":{"variables":[]}}\n')
    (core_dir / "data.json").write_text(json.dumps({
        "data": {
            "data_slots": [
                {
                    "id": 1,
                    "name": "ROM",
                    "address": "0x10000000",
                    "required": True,
                    "extensions": ["rom"],
                    "filename": "wrap.rom",
                }
            ]
        }
    }) + "\n")
    (rtl_dir / "game_top.sv").write_text(
        """
module game_top(
    input  wire       refclk,
    input  wire       reset_n,
    input  wire [31:0] cont1_key,
    output wire [3:0] VGA_R,
    output wire [3:0] VGA_G,
    output wire [3:0] VGA_B,
    output wire       HSync,
    output wire       VSync,
    output wire       HBLANK,
    output wire       VBLANK,
    output wire [15:0] audio_l
);
    assign VGA_R = cont1_key[3:0];
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


def test_synth_wrapper_emits_reviewable_profile_and_contract(tmp_path):
    core = make_wrappable_core(tmp_path / "openFPGA-Wrap")
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
    profile = json.loads(Path(report["paths"]["profile"]).read_text())
    wrapper = Path(report["paths"]["wrapper"]).read_text()
    filelist = Path(report["paths"]["filelist"]).read_text()

    assert report["schema"] == "apfsim.wrapper_synthesis.v1"
    assert report["source_top"] == "game_top"
    assert report["status"] == "partial"
    assert any(item["code"] == "BRIDGE_MAPPING_MISSING" for item in report["blockers"])
    assert any(item["apf_signal"] == "video_de" and "HBLANK" in item["source"] for item in report["mappings"])
    assert profile["top"] == "core_top"
    assert profile["wrapper_synthesis"]["wrapper"] == "{profile_dir}/apfsim_core_top.sv"
    assert "{profile_dir}/apfsim_core_top.sv" in filelist
    assert "{root}/src/fpga/core/game_top.sv" in filelist
    assert ".refclk(clk_74a)" in wrapper
    assert ".reset_n(1'b1)" in wrapper
    assert "assign video_de = (~src_HBLANK & ~src_VBLANK)" in wrapper
    assert "assign video_rgb =" in wrapper
    assert (Path(report["paths"]["notes"])).exists()


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator is not installed")
def test_synth_wrapper_lints_for_simple_top(tmp_path):
    core = make_wrappable_core(tmp_path / "openFPGA-Wrap")
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

    r = subprocess.run([
        "verilator",
        "--lint-only",
        "--sv",
        "-Wno-fatal",
        "-Wno-DECLFILENAME",
        "-Wno-UNUSEDSIGNAL",
        "--top-module", "core_top",
        str(core / "src" / "fpga" / "core" / "game_top.sv"),
        report["paths"]["wrapper"],
    ], cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
