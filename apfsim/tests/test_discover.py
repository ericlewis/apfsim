import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "apfsim"


def test_discover_inventories_fake_core(tmp_path):
    core = tmp_path / "openFPGA-Fake"
    core_dir = core / "dist" / "Cores" / "example.Fake"
    rtl_dir = core / "src" / "fpga" / "core"
    core_dir.mkdir(parents=True)
    rtl_dir.mkdir(parents=True)
    (core_dir / "core.json").write_text('{"core": {"metadata": {"name": "Fake"}}}\n')
    (core_dir / "video.json").write_text('{"video": {"width": 256, "height": 224}}\n')
    (core_dir / "data.json").write_text('{"data": {"data_slots": [{"id": 1, "name": "ROM", "address": "0x10000000"}]}}\n')
    (rtl_dir / "core_top.sv").write_text(
        "module core_top(input clk_74a, input clk_74b, input [31:0] bridge_addr,"
        " input bridge_rd, input bridge_wr, input [31:0] bridge_wr_data,"
        " output [31:0] bridge_rd_data, output bridge_endian_little,"
        " output video_rgb_clock, output [23:0] video_rgb, output video_de,"
        " output video_hs, output video_vs, output audio_mclk, output audio_lrck,"
        " output audio_dac, input [15:0] cont1_key); endmodule\n"
    )

    out = tmp_path / "inventory"
    r = subprocess.run([
        str(CLI),
        "discover",
        "--root", str(tmp_path),
        "--output", str(out),
    ], cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr

    report = json.loads((out / "cores.json").read_text())
    assert report["core_count"] == 1
    discovered = report["cores"][0]
    assert discovered["name"] == "openFPGA-Fake"
    assert discovered["core_ids"] == ["example.Fake"]
    assert discovered["data_slot_count"] == 1
    assert discovered["video_modes"] == ["256x224"]
    assert discovered["git_state"] == "no-git"
    assert discovered["git_dirty_count"] == 0
    assert discovered["status"] in {"candidate", "needs-ip-shims"}
    assert (out / "cores.md").exists()


def write_fake_core(root: Path, *, name: str = "Fake", width: int = 256, height: int = 224):
    core_dir = root / "dist" / "Cores" / f"example.{name}"
    asset_dir = root / "dist" / "Assets"
    rtl_dir = root / "src" / "fpga" / "core"
    core_dir.mkdir(parents=True)
    asset_dir.mkdir(parents=True)
    rtl_dir.mkdir(parents=True)
    (core_dir / "core.json").write_text('{"core": {"metadata": {"name": "Fake"}}}\n')
    (core_dir / "video.json").write_text(json.dumps({"video": {"scaler_modes": [{"width": width, "height": height}]}}) + "\n")
    (core_dir / "data.json").write_text(json.dumps({
        "data": {
            "data_slots": [
                {"id": 1, "name": "ROM", "address": "0x10000000", "required": True, "extensions": ["rom"], "filename": "fake.rom"}
            ]
        }
    }) + "\n")
    (asset_dir / "fake.rom").write_bytes(bytes(range(32)))
    (rtl_dir / "core_top.sv").write_text(
        "module core_top(input clk_74a, input clk_74b, input [31:0] bridge_addr,"
        " input bridge_rd, input bridge_wr, input [31:0] bridge_wr_data,"
        " output [31:0] bridge_rd_data, output bridge_endian_little,"
        " output video_rgb_clock, output [23:0] video_rgb, output video_de,"
        " output video_hs, output video_vs, output audio_mclk, output audio_lrck,"
        " output audio_dac, input [15:0] cont1_key); endmodule\n"
    )


def test_generate_profile_writes_reviewable_candidate(tmp_path):
    core = tmp_path / "openFPGA-Fake"
    write_fake_core(core)
    out = tmp_path / "generated"

    r = subprocess.run([
        str(CLI),
        "generate-profile",
        "--root", str(core),
        "--output", str(out),
        "--json",
    ], cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr

    report = json.loads(r.stdout)
    profile_path = Path(report["paths"]["profile"])
    filelist_path = Path(report["paths"]["filelist"])
    scenario_path = Path(report["paths"]["scenario"])
    assert profile_path.exists()
    assert filelist_path.exists()
    assert scenario_path.exists()
    profile = json.loads(profile_path.read_text())
    assert profile["name"] == "fake"
    assert profile["metadata_jsons"]["video"].endswith("video.json")
    assert profile["metadata_jsons"]["video"].startswith("{root}/")
    assert "root_default" not in profile
    assert profile["filelist"] == "{profile_dir}/filelist.f"
    assert profile["scenario"] == "{profile_dir}/scenario.yml"
    assert "video_shape.json" in profile["expected_artifacts"]
    filelist = filelist_path.read_text()
    assert "rtl_shims/mf_pllbase_sim.sv" in filelist
    assert "{root}/src/fpga/core/core_top.sv" in filelist
    assert str(core) not in filelist
    scenario = scenario_path.read_text()
    assert "active_width: 256" in scenario
    assert "expected_checksum:" in scenario
    assert str(core) not in scenario


def test_generate_profile_uses_qsf_source_order_defines_and_filters(tmp_path):
    core = tmp_path / "openFPGA-QsfCore"
    write_fake_core(core, name="QsfCore")
    fpga_dir = core / "src" / "fpga"
    include_dir = fpga_dir / "core" / "includes"
    lib_dir = fpga_dir / "core" / "lib"
    include_dir.mkdir(parents=True)
    lib_dir.mkdir(parents=True)
    (lib_dir / "first.v").write_text("module first; endmodule\n")
    (fpga_dir / "core" / "mf_pllbase.v").write_text("module mf_pllbase; endmodule\n")
    (fpga_dir / "core" / "extra.v").write_text("module extra; endmodule\n")
    (fpga_dir / "core" / "cpu.vhd").write_text("entity cpu is end cpu;\n")
    (fpga_dir / "core" / "ip.qip").write_text("")
    (fpga_dir / "core" / "qip_child.v").write_text("module qip_child; endmodule\n")
    (fpga_dir / "core" / "source_bundle.qip").write_text(
        'set_global_assignment -name VERILOG_FILE [file join $::quartus(qip_path) "qip_child.v"]\n'
    )
    (fpga_dir / "ap_core.qsf").write_text(
        "\n".join([
            'set_global_assignment -name VERILOG_MACRO "SIM_HEADER=1"',
            "set_global_assignment -name SEARCH_PATH core/includes",
            "set_global_assignment -name VERILOG_FILE core/lib/first.v",
            "set_global_assignment -name SYSTEMVERILOG_FILE core/core_top.sv",
            "set_global_assignment -name VERILOG_FILE core/mf_pllbase.v",
            "set_global_assignment -name VHDL_FILE core/cpu.vhd",
            "set_global_assignment -name QIP_FILE core/ip.qip",
            "set_global_assignment -name QIP_FILE core/source_bundle.qip",
            "",
        ])
    )
    out = tmp_path / "generated"

    r = subprocess.run([
        str(CLI),
        "generate-profile",
        "--root", str(core),
        "--output", str(out),
        "--json",
    ], cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr

    report = json.loads(r.stdout)
    candidate = json.loads(Path(report["paths"]["report"]).read_text())
    filelist = Path(report["paths"]["filelist"]).read_text()
    first_path = "{root}/src/fpga/core/lib/first.v"
    core_top_path = "{root}/src/fpga/core/core_top.sv"
    assert "+define+SIM_HEADER=1" in filelist
    assert "+incdir+{root}/src/fpga/core/includes" in filelist
    assert filelist.index(first_path) < filelist.index(core_top_path)
    assert "{root}/src/fpga/core/qip_child.v" in filelist
    assert str(fpga_dir / "core" / "mf_pllbase.v") not in filelist
    assert str(fpga_dir / "core" / "extra.v") not in filelist
    assert candidate["qsf"]["path"].endswith("ap_core.qsf")
    assert candidate["qsf"]["defines"] == ["SIM_HEADER=1"]
    assert candidate["qsf"]["qip_files"] == [
        str(fpga_dir / "core" / "ip.qip"),
        str(fpga_dir / "core" / "source_bundle.qip"),
    ]
    assert any("mf_pllbase.v" in item for item in candidate["qsf"]["skipped_sources"])
