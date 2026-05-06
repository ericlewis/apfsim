import json
import shutil
import subprocess
from pathlib import Path

import pytest


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


def test_generate_profile_reports_memory_dependencies(tmp_path):
    core = tmp_path / "openFPGA-MemoryCore"
    write_fake_core(core, name="MemoryCore")
    rtl_dir = core / "src" / "fpga" / "core"
    (rtl_dir / "memory_glue.sv").write_text(
        "module memory_glue;"
        " sdram sdram_inst();"
        " psram psram_inst();"
        " wire [15:0] SRAM_DQ;"
        " wire [15:0] PSRAM_DQ;"
        " wire CRAM_WAIT;"
        " altsyncram bram_inst();"
        " dcfifo fifo_inst();"
        "endmodule\n"
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
    profile = json.loads(Path(report["paths"]["profile"]).read_text())
    filelist = Path(report["paths"]["filelist"]).read_text()
    assert candidate["memory"]["schema"] == "apfsim.memory_dependencies.v1"
    assert set(candidate["memory"]["classes"]) >= {"sdram", "sram", "psram", "cram", "bram", "fifo"}
    assert set(candidate["memory"]["external_classes"]) >= {"sdram", "sram", "psram", "cram"}
    assert "CRAM_MODEL_REQUIRED" not in {risk["code"] for risk in candidate["memory"]["risks"]}
    assert set(candidate["memory"]["selected_model_classes"]) >= {"sdram", "sram", "psram", "cram"}
    assert "external_sram_pin_model" in candidate["selected_shims"]
    assert "psram_cram_transactional_models" in candidate["selected_shims"]
    assert "sdram_ideal_transactional" in candidate["selected_shims"]
    assert "sdram_ideal_transactional" in {item["name"] for item in report["selected_shim_details"]}
    details = {item["name"]: item for item in candidate["selected_shim_details"]}
    assert details["sdram_ideal_transactional"]["confidence"] == "bringup_only"
    assert "rtl_shims/sdram_sim.sv" in details["sdram_ideal_transactional"]["filelist_entries"]
    assert "apfsim_async_sram_16_model" in details["external_sram_pin_model"]["modules"]
    assert "sram" in candidate["memory"]["available_models"]
    assert "rtl_shims/external_memory_models.sv" in filelist
    assert "{profile_dir}/apfsim_memory_models.sv" in filelist
    assert (Path(report["paths"]["profile"]).parent / "apfsim_memory_models.sv").exists()
    assert profile["memory"]["models"]["sdram"]["selected"] == "ideal_transactional"
    assert "external_sram_pin_model" in profile["shim_catalog"]
    assert profile["wrapper_generation"]["memory_models"]["generated"] is True
    assert set(profile["wrapper_generation"]["memory_models"]["classes"]) == {"sram", "psram", "cram"}
    assert profile["wrapper_generation"]["memory_models"]["model_defaults"]["sram"]["addr_width"] == 17
    wrapper_text = (Path(report["paths"]["profile"]).parent / "apfsim_memory_models.sv").read_text()
    assert "input  wire [16:0] sram_addr" in wrapper_text
    assert ".ADDR_WIDTH(17)" in wrapper_text
    assert ".BYTE_ENABLE_WIDTH(2)" in wrapper_text
    assert ".LATENCY_CYCLES(6)" in wrapper_text
    assert ".LATENCY_CYCLES(4)" in wrapper_text
    assert not any("CRAM_MODEL_REQUIRED" in warning for warning in candidate["warnings"])


def test_generated_external_memory_scaffold_lints_when_verilator_available(tmp_path):
    if shutil.which("verilator") is None:
        pytest.skip("verilator is not installed")
    core = tmp_path / "openFPGA-MemoryCore"
    write_fake_core(core, name="MemoryCore")
    rtl_dir = core / "src" / "fpga" / "core"
    (rtl_dir / "memory_glue.sv").write_text(
        "module memory_glue;"
        " psram psram_inst();"
        " wire [15:0] SRAM_DQ;"
        " wire [15:0] PSRAM_DQ;"
        " wire CRAM_WAIT;"
        "endmodule\n"
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
    wrapper = Path(report["paths"]["profile"]).parent / "apfsim_memory_models.sv"
    top_module = next(
        line.split()[1]
        for line in wrapper.read_text().splitlines()
        if line.startswith("module ")
    )
    r = subprocess.run([
        "verilator",
        "--lint-only",
        "-Wno-fatal",
        "-Wno-DECLFILENAME",
        "-Wno-UNUSEDSIGNAL",
        "--top-module", top_module,
        str(ROOT / "rtl_shims" / "external_memory_models.sv"),
        str(wrapper),
    ], cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_generate_profile_uses_qsf_source_order_defines_and_filters(tmp_path):
    core = tmp_path / "openFPGA-QsfCore"
    write_fake_core(core, name="QsfCore")
    fpga_dir = core / "src" / "fpga"
    include_dir = fpga_dir / "core" / "includes"
    lib_dir = fpga_dir / "core" / "lib"
    include_dir.mkdir(parents=True)
    lib_dir.mkdir(parents=True)
    (lib_dir / "first.v").write_text("module first; endmodule\n")
    (fpga_dir / "core" / "pocket_top.sv").write_text("module pocket_top; endmodule\n")
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
            "set_global_assignment -name TOP_LEVEL_ENTITY pocket_top",
            'set_global_assignment -name VERILOG_MACRO "SIM_HEADER=1"',
            "set_global_assignment -name SEARCH_PATH core/includes",
            "set_global_assignment -name VERILOG_FILE core/lib/first.v",
            "set_global_assignment -name SYSTEMVERILOG_FILE core/core_top.sv",
            "set_global_assignment -name SYSTEMVERILOG_FILE core/pocket_top.sv",
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
    profile = json.loads(Path(report["paths"]["profile"]).read_text())
    filelist = Path(report["paths"]["filelist"]).read_text()
    first_path = "{root}/src/fpga/core/lib/first.v"
    core_top_path = "{root}/src/fpga/core/core_top.sv"
    pocket_top_path = "{root}/src/fpga/core/pocket_top.sv"
    assert "+define+SIM_HEADER=1" in filelist
    assert "+incdir+{root}/src/fpga/core/includes" in filelist
    assert filelist.index(first_path) < filelist.index(core_top_path)
    assert pocket_top_path in filelist
    assert profile["top"] == "pocket_top"
    assert candidate["qsf"]["top_level_entity"] == "pocket_top"
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
    assert any(risk["code"] == "VHDL_ENTITY_STUBBED" for risk in candidate["risks"])
    assert any(risk["code"] == "VHDL_ENTITY_STUBBED" for risk in report["risks"])
    assert any(risk["code"] == "VHDL_ENTITY_STUBBED" for risk in profile["risks"])
    assert any("VHDL files were detected" in warning for warning in candidate["warnings"])


def test_generate_profile_accepts_setup_only_json_slot_without_address(tmp_path):
    core = tmp_path / "openFPGA-SetupSlot"
    write_fake_core(core, name="SetupSlot")
    core_dir = core / "dist" / "Cores" / "example.SetupSlot"
    data_path = core_dir / "data.json"
    data = json.loads(data_path.read_text())
    data["data"]["data_slots"].insert(0, {
        "id": 0,
        "name": "Game JSON Setup",
        "required": True,
        "parameters": "0x113",
        "filename": "fake_setup.json",
        "extensions": ["json"],
        "size_maximum": 4096,
    })
    data_path.write_text(json.dumps(data) + "\n")
    (core / "dist" / "Assets" / "fake_setup.json").write_text("{}\n")
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
    scenario = Path(report["paths"]["scenario"]).read_text()
    assert "could not translate data slot" not in "\n".join(candidate["warnings"])
    assert "setup_only: true" in scenario
    assert "deferload: true" in scenario
    assert "expected_total_loaded_bytes: 32" in scenario


def test_generate_profile_selects_public_jtframe_t80_and_ddio_shims(tmp_path):
    core = tmp_path / "openFPGA-JTFrame"
    write_fake_core(core, name="JTFrame")
    fpga_dir = core / "src" / "fpga"
    jt_t80 = core / "modules" / "jtframe" / "hdl" / "cpu" / "t80" / "T80s.v"
    jt_t80.parent.mkdir(parents=True)
    jt_t80.write_text(
        "module T80s(input RESET_n, input CLK, input CEN, input WAIT_n, input INT_n, input NMI_n,"
        " input BUSRQ_n, input OUT0, input [7:0] DI, output M1_n, output MREQ_n, output IORQ_n,"
        " output RD_n, output WR_n, output RFSH_n, output HALT_n, output BUSAK_n,"
        " output [15:0] A, output [7:0] DOUT); endmodule\n"
    )
    jt_t48 = core / "modules" / "jtframe" / "hdl" / "cpu" / "t48" / "t48_core.v"
    jt_t48.parent.mkdir(parents=True)
    jt_t48.write_text("module t48_core(input reset_i, input clk_i); endmodule\n")
    jt_t8243 = core / "modules" / "jtframe" / "hdl" / "cpu" / "t8243" / "t8243_sync_notri.v"
    jt_t8243.parent.mkdir(parents=True)
    jt_t8243.write_text("module t8243_sync_notri(input clk_i); endmodule\n")
    (fpga_dir / "core" / "pocket_top.sv").write_text(
        "module pocket_top(input refclk);"
        " wire [1:0] clocks; wire locked; wire [0:0] ddio_out;"
        " altera_pll #(.number_of_clocks(2)) pll(.refclk(refclk), .rst(1'b0), .outclk(clocks), .locked(locked), .fboutclk(), .fbclk(1'b0));"
        " altddio_out #(.width(1)) ddio(.datain_h(1'b1), .datain_l(1'b0), .outclock(refclk), .outclocken(1'b1), .aset(1'b0), .aclr(1'b0), .sset(1'b0), .sclr(1'b0), .oe(1'b1), .dataout(ddio_out), .oe_out());"
        " T80s cpu(.RESET_n(1'b1), .CLK(refclk), .CEN(1'b1), .WAIT_n(1'b1), .INT_n(1'b1), .NMI_n(1'b1), .BUSRQ_n(1'b1), .OUT0(1'b0), .DI(8'h00));"
        " t48_core mcu(.reset_i(1'b1), .clk_i(refclk));"
        " t8243_sync_notri expander(.clk_i(refclk));"
        " endmodule\n"
    )
    (fpga_dir / "ap_core.qsf").write_text(
        "\n".join([
            "set_global_assignment -name TOP_LEVEL_ENTITY pocket_top",
            "set_global_assignment -name SYSTEMVERILOG_FILE core/pocket_top.sv",
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
    details = {item["name"]: item for item in candidate["selected_shim_details"]}
    filelist = Path(report["paths"]["filelist"]).read_text()
    assert "intel_pllbase_sim" in candidate["selected_shims"]
    assert "intel_ddio_shims" in candidate["selected_shims"]
    assert "jtframe_t80s_public_translation" in candidate["selected_shims"]
    assert "jtframe_t48_public_translation" in candidate["selected_shims"]
    assert "jtframe_t8243_public_translation" in candidate["selected_shims"]
    assert details["jtframe_t80s_public_translation"]["fallback_used"] is False
    assert details["jtframe_t80s_public_translation"]["catalog_source"] == "{root}/modules/jtframe/hdl/cpu/t80/T80s.v"
    assert details["jtframe_t48_public_translation"]["catalog_source"] == "{root}/modules/jtframe/hdl/cpu/t48/t48_core.v"
    assert details["jtframe_t8243_public_translation"]["catalog_source"] == "{root}/modules/jtframe/hdl/cpu/t8243/t8243_sync_notri.v"
    assert "{root}/modules/jtframe/hdl/cpu/t80/T80s.v" in filelist
    assert "{root}/modules/jtframe/hdl/cpu/t48/t48_core.v" in filelist
    assert "{root}/modules/jtframe/hdl/cpu/t8243/t8243_sync_notri.v" in filelist
    assert "rtl_shims/jtframe_t80s_stub.sv" not in filelist


def test_generate_profile_wraps_jtframe_pocket_logical_top(tmp_path):
    core = tmp_path / "openFPGA-JTLogical"
    write_fake_core(core, name="JTLogical")
    fpga_dir = core / "src" / "fpga"
    (fpga_dir / "core" / "pocket_top.sv").write_text(
        "module pocket_top(input clk_74a, input clk_74b); jtframe_pocket u_core(); endmodule\n"
    )
    (fpga_dir / "core" / "jtframe_pocket.sv").write_text(
        "module jtframe_pocket(input clk_74a, input clk_74b, inout [15:0] SDRAM_DQ, output [12:0] SDRAM_A,"
        " output [1:0] SDRAM_BA, output SDRAM_DQML, output SDRAM_DQMH, output SDRAM_nWE,"
        " output SDRAM_nCAS, output SDRAM_nRAS, output SDRAM_nCS, output SDRAM_CLK, output SDRAM_CKE); endmodule\n"
    )
    (fpga_dir / "ap_core.qsf").write_text(
        "\n".join([
            "set_global_assignment -name TOP_LEVEL_ENTITY pocket_top",
            "set_global_assignment -name SYSTEMVERILOG_FILE core/jtframe_pocket.sv",
            "set_global_assignment -name SYSTEMVERILOG_FILE core/pocket_top.sv",
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
    profile = json.loads(Path(report["paths"]["profile"]).read_text())
    filelist = Path(report["paths"]["filelist"]).read_text()
    wrapper = Path(report["paths"]["profile"]).parent / "apfsim_jtframe_pocket_wrapper.sv"
    wrapper_text = wrapper.read_text()
    assert profile["top"] == "core_top"
    assert profile["memory_activity"]["top_port_classes"] == ["sdram"]
    assert wrapper.exists()
    assert "video_rgb_clock <= core_pxl_cen" in wrapper_text
    assert "VIDEO_WIDTH = `JTFRAME_WIDTH" in wrapper_text
    assert "core_de_cropped" in wrapper_text
    assert "apfsim_sdram_pin_model" in wrapper_text
    assert "apfsim_sdram_read_count" in wrapper_text
    assert "apfsim_sdram_rom_preload_count" in wrapper_text
    assert "apfsim_sdram_first_rom_mismatch_expected" in wrapper_text
    assert "u_core.u_board.u_sdram.din" in wrapper_text
    assert "apfsim_sdram_write_drive" in wrapper_text
    assert "u_core.prog_we" in wrapper_text
    assert "u_core.prog_we && u_core.prog_ack" in wrapper_text
    assert "{profile_dir}/apfsim_jtframe_pocket_wrapper.sv" in filelist
    assert "rtl_shims/external_memory_models.sv" in filelist
    assert "{root}/src/fpga/core/pocket_top.sv" not in filelist
    assert "{root}/src/fpga/core/jtframe_pocket.sv" in filelist
    assert "sdram_pin_model" in candidate["selected_shims"]
    assert profile["memory"]["models"]["sdram"]["selected"] == "sdram_pin_level"
    assert candidate["wrapper_generation"]["jtframe_pocket_logical_wrapper"]["top"] == "core_top"
    assert candidate["wrapper_generation"]["jtframe_pocket_logical_wrapper"]["memory_model"]["class"] == "sdram"
    assert "apfsim_sdram_rom_mismatch_count" in candidate["wrapper_generation"]["jtframe_pocket_logical_wrapper"]["memory_model"]["counter_ports"]
    assert "apfsim_sdram_first_rom_mismatch_actual" in candidate["wrapper_generation"]["jtframe_pocket_logical_wrapper"]["memory_model"]["counter_ports"]
