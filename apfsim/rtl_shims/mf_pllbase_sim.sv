`timescale 1ns/1ps
// Simulation-friendly replacement for common Quartus mf_pllbase-generated PLL wrappers.
// It intentionally models observable behavior only: deterministic derived clocks and lock.
`ifndef APFSIM_MF_PLLBASE_DIVIDE_0
`define APFSIM_MF_PLLBASE_DIVIDE_0 1
`endif
`ifndef APFSIM_MF_PLLBASE_DIVIDE_1
`define APFSIM_MF_PLLBASE_DIVIDE_1 1
`endif
`ifndef APFSIM_MF_PLLBASE_DIVIDE_2
`define APFSIM_MF_PLLBASE_DIVIDE_2 8
`endif
`ifndef APFSIM_MF_PLLBASE_DIVIDE_3
`define APFSIM_MF_PLLBASE_DIVIDE_3 8
`endif
`ifndef APFSIM_MF_PLLBASE_DIVIDE_4
`define APFSIM_MF_PLLBASE_DIVIDE_4 8
`endif
`ifndef APFSIM_MF_PLLBASE_DIVIDE_5
`define APFSIM_MF_PLLBASE_DIVIDE_5 8
`endif
`ifndef APFSIM_MF_PLLBASE_LOCK_AFTER_CYCLES
`define APFSIM_MF_PLLBASE_LOCK_AFTER_CYCLES 1024
`endif

module mf_pllbase #(
    parameter integer DIVIDE_0 = `APFSIM_MF_PLLBASE_DIVIDE_0,
    parameter integer DIVIDE_1 = `APFSIM_MF_PLLBASE_DIVIDE_1,
    parameter integer DIVIDE_2 = `APFSIM_MF_PLLBASE_DIVIDE_2,
    parameter integer DIVIDE_3 = `APFSIM_MF_PLLBASE_DIVIDE_3,
    parameter integer DIVIDE_4 = `APFSIM_MF_PLLBASE_DIVIDE_4,
    parameter integer DIVIDE_5 = `APFSIM_MF_PLLBASE_DIVIDE_5,
    parameter integer LOCK_AFTER_CYCLES = `APFSIM_MF_PLLBASE_LOCK_AFTER_CYCLES
) (
    input  wire refclk,
    input  wire rst,
    output reg  outclk_0,
    output reg  outclk_1,
    output reg  outclk_2,
    output reg  outclk_3,
    output reg  outclk_4,
    output reg  outclk_5,
    output reg  locked
);
    integer lock_count;
    integer cnt0;
    integer cnt1;
    integer cnt2;
    integer cnt3;
    integer cnt4;
    integer cnt5;

    initial begin
        outclk_0 = 1'b0;
        outclk_1 = 1'b0;
        outclk_2 = 1'b0;
        outclk_3 = 1'b0;
        outclk_4 = 1'b0;
        outclk_5 = 1'b0;
        locked = 1'b0;
        lock_count = 0;
        cnt0 = 0;
        cnt1 = 0;
        cnt2 = 0;
        cnt3 = 0;
        cnt4 = 0;
        cnt5 = 0;
    end

    always @(posedge refclk or posedge rst) begin
        if (rst) begin
            outclk_0 <= 1'b0;
            outclk_1 <= 1'b0;
            outclk_2 <= 1'b0;
            outclk_3 <= 1'b0;
            outclk_4 <= 1'b0;
            outclk_5 <= 1'b0;
            locked <= 1'b0;
            lock_count <= 0;
            cnt0 <= 0;
            cnt1 <= 0;
            cnt2 <= 0;
            cnt3 <= 0;
            cnt4 <= 0;
            cnt5 <= 0;
        end else begin
            if (lock_count >= LOCK_AFTER_CYCLES) locked <= 1'b1;
            else lock_count <= lock_count + 1;

            cnt0 <= (cnt0 + 1) % (DIVIDE_0 < 1 ? 1 : DIVIDE_0);
            cnt1 <= (cnt1 + 1) % (DIVIDE_1 < 1 ? 1 : DIVIDE_1);
            cnt2 <= (cnt2 + 1) % (DIVIDE_2 < 1 ? 1 : DIVIDE_2);
            cnt3 <= (cnt3 + 1) % (DIVIDE_3 < 1 ? 1 : DIVIDE_3);
            cnt4 <= (cnt4 + 1) % (DIVIDE_4 < 1 ? 1 : DIVIDE_4);
            cnt5 <= (cnt5 + 1) % (DIVIDE_5 < 1 ? 1 : DIVIDE_5);
            if (cnt0 == 0) outclk_0 <= ~outclk_0;
            if (cnt1 == 0) outclk_1 <= ~outclk_1;
            if (cnt2 == 0) outclk_2 <= ~outclk_2;
            if (cnt3 == 0) outclk_3 <= ~outclk_3;
            if (cnt4 == 0) outclk_4 <= ~outclk_4;
            if (cnt5 == 0) outclk_5 <= ~outclk_5;
        end
    end
endmodule


// Minimal public altera_pll model for Quartus-generated wrappers.
// It preserves the observable APF bring-up contract: output clocks toggle and
// locked asserts deterministically after reset. It is not a timing-accurate PLL.
module altera_pll #(
    parameter c_cnt_bypass_en0 = 0,
    parameter c_cnt_bypass_en1 = 0,
    parameter c_cnt_bypass_en10 = 0,
    parameter c_cnt_bypass_en11 = 0,
    parameter c_cnt_bypass_en12 = 0,
    parameter c_cnt_bypass_en13 = 0,
    parameter c_cnt_bypass_en14 = 0,
    parameter c_cnt_bypass_en15 = 0,
    parameter c_cnt_bypass_en16 = 0,
    parameter c_cnt_bypass_en17 = 0,
    parameter c_cnt_bypass_en2 = 0,
    parameter c_cnt_bypass_en3 = 0,
    parameter c_cnt_bypass_en4 = 0,
    parameter c_cnt_bypass_en5 = 0,
    parameter c_cnt_bypass_en6 = 0,
    parameter c_cnt_bypass_en7 = 0,
    parameter c_cnt_bypass_en8 = 0,
    parameter c_cnt_bypass_en9 = 0,
    parameter c_cnt_hi_div0 = 0,
    parameter c_cnt_hi_div1 = 0,
    parameter c_cnt_hi_div10 = 0,
    parameter c_cnt_hi_div11 = 0,
    parameter c_cnt_hi_div12 = 0,
    parameter c_cnt_hi_div13 = 0,
    parameter c_cnt_hi_div14 = 0,
    parameter c_cnt_hi_div15 = 0,
    parameter c_cnt_hi_div16 = 0,
    parameter c_cnt_hi_div17 = 0,
    parameter c_cnt_hi_div2 = 0,
    parameter c_cnt_hi_div3 = 0,
    parameter c_cnt_hi_div4 = 0,
    parameter c_cnt_hi_div5 = 0,
    parameter c_cnt_hi_div6 = 0,
    parameter c_cnt_hi_div7 = 0,
    parameter c_cnt_hi_div8 = 0,
    parameter c_cnt_hi_div9 = 0,
    parameter c_cnt_in_src0 = "",
    parameter c_cnt_in_src1 = "",
    parameter c_cnt_in_src10 = "",
    parameter c_cnt_in_src11 = "",
    parameter c_cnt_in_src12 = "",
    parameter c_cnt_in_src13 = "",
    parameter c_cnt_in_src14 = "",
    parameter c_cnt_in_src15 = "",
    parameter c_cnt_in_src16 = "",
    parameter c_cnt_in_src17 = "",
    parameter c_cnt_in_src2 = "",
    parameter c_cnt_in_src3 = "",
    parameter c_cnt_in_src4 = "",
    parameter c_cnt_in_src5 = "",
    parameter c_cnt_in_src6 = "",
    parameter c_cnt_in_src7 = "",
    parameter c_cnt_in_src8 = "",
    parameter c_cnt_in_src9 = "",
    parameter c_cnt_lo_div0 = 0,
    parameter c_cnt_lo_div1 = 0,
    parameter c_cnt_lo_div10 = 0,
    parameter c_cnt_lo_div11 = 0,
    parameter c_cnt_lo_div12 = 0,
    parameter c_cnt_lo_div13 = 0,
    parameter c_cnt_lo_div14 = 0,
    parameter c_cnt_lo_div15 = 0,
    parameter c_cnt_lo_div16 = 0,
    parameter c_cnt_lo_div17 = 0,
    parameter c_cnt_lo_div2 = 0,
    parameter c_cnt_lo_div3 = 0,
    parameter c_cnt_lo_div4 = 0,
    parameter c_cnt_lo_div5 = 0,
    parameter c_cnt_lo_div6 = 0,
    parameter c_cnt_lo_div7 = 0,
    parameter c_cnt_lo_div8 = 0,
    parameter c_cnt_lo_div9 = 0,
    parameter c_cnt_odd_div_duty_en0 = 0,
    parameter c_cnt_odd_div_duty_en1 = 0,
    parameter c_cnt_odd_div_duty_en10 = 0,
    parameter c_cnt_odd_div_duty_en11 = 0,
    parameter c_cnt_odd_div_duty_en12 = 0,
    parameter c_cnt_odd_div_duty_en13 = 0,
    parameter c_cnt_odd_div_duty_en14 = 0,
    parameter c_cnt_odd_div_duty_en15 = 0,
    parameter c_cnt_odd_div_duty_en16 = 0,
    parameter c_cnt_odd_div_duty_en17 = 0,
    parameter c_cnt_odd_div_duty_en2 = 0,
    parameter c_cnt_odd_div_duty_en3 = 0,
    parameter c_cnt_odd_div_duty_en4 = 0,
    parameter c_cnt_odd_div_duty_en5 = 0,
    parameter c_cnt_odd_div_duty_en6 = 0,
    parameter c_cnt_odd_div_duty_en7 = 0,
    parameter c_cnt_odd_div_duty_en8 = 0,
    parameter c_cnt_odd_div_duty_en9 = 0,
    parameter c_cnt_ph_mux_prst0 = "",
    parameter c_cnt_ph_mux_prst1 = "",
    parameter c_cnt_ph_mux_prst10 = "",
    parameter c_cnt_ph_mux_prst11 = "",
    parameter c_cnt_ph_mux_prst12 = "",
    parameter c_cnt_ph_mux_prst13 = "",
    parameter c_cnt_ph_mux_prst14 = "",
    parameter c_cnt_ph_mux_prst15 = "",
    parameter c_cnt_ph_mux_prst16 = "",
    parameter c_cnt_ph_mux_prst17 = "",
    parameter c_cnt_ph_mux_prst2 = "",
    parameter c_cnt_ph_mux_prst3 = "",
    parameter c_cnt_ph_mux_prst4 = "",
    parameter c_cnt_ph_mux_prst5 = "",
    parameter c_cnt_ph_mux_prst6 = "",
    parameter c_cnt_ph_mux_prst7 = "",
    parameter c_cnt_ph_mux_prst8 = "",
    parameter c_cnt_ph_mux_prst9 = "",
    parameter c_cnt_prst0 = "",
    parameter c_cnt_prst1 = "",
    parameter c_cnt_prst10 = "",
    parameter c_cnt_prst11 = "",
    parameter c_cnt_prst12 = "",
    parameter c_cnt_prst13 = "",
    parameter c_cnt_prst14 = "",
    parameter c_cnt_prst15 = "",
    parameter c_cnt_prst16 = "",
    parameter c_cnt_prst17 = "",
    parameter c_cnt_prst2 = "",
    parameter c_cnt_prst3 = "",
    parameter c_cnt_prst4 = "",
    parameter c_cnt_prst5 = "",
    parameter c_cnt_prst6 = "",
    parameter c_cnt_prst7 = "",
    parameter c_cnt_prst8 = "",
    parameter c_cnt_prst9 = "",
    parameter duty_cycle0 = 0,
    parameter duty_cycle1 = 0,
    parameter duty_cycle10 = 0,
    parameter duty_cycle11 = 0,
    parameter duty_cycle12 = 0,
    parameter duty_cycle13 = 0,
    parameter duty_cycle14 = 0,
    parameter duty_cycle15 = 0,
    parameter duty_cycle16 = 0,
    parameter duty_cycle17 = 0,
    parameter duty_cycle2 = 0,
    parameter duty_cycle3 = 0,
    parameter duty_cycle4 = 0,
    parameter duty_cycle5 = 0,
    parameter duty_cycle6 = 0,
    parameter duty_cycle7 = 0,
    parameter duty_cycle8 = 0,
    parameter duty_cycle9 = 0,
    parameter fractional_vco_multiplier = "",
    parameter m_cnt_bypass_en = 0,
    parameter m_cnt_hi_div = 0,
    parameter m_cnt_lo_div = 0,
    parameter m_cnt_odd_div_duty_en = 0,
    parameter mimic_fbclk_type = "",
    parameter n_cnt_bypass_en = 0,
    parameter n_cnt_hi_div = 0,
    parameter n_cnt_lo_div = 0,
    parameter n_cnt_odd_div_duty_en = 0,
    parameter number_of_clocks = 1,
    parameter operation_mode = "",
    parameter output_clock_frequency0 = "",
    parameter output_clock_frequency1 = "",
    parameter output_clock_frequency10 = "",
    parameter output_clock_frequency11 = "",
    parameter output_clock_frequency12 = "",
    parameter output_clock_frequency13 = "",
    parameter output_clock_frequency14 = "",
    parameter output_clock_frequency15 = "",
    parameter output_clock_frequency16 = "",
    parameter output_clock_frequency17 = "",
    parameter output_clock_frequency2 = "",
    parameter output_clock_frequency3 = "",
    parameter output_clock_frequency4 = "",
    parameter output_clock_frequency5 = "",
    parameter output_clock_frequency6 = "",
    parameter output_clock_frequency7 = "",
    parameter output_clock_frequency8 = "",
    parameter output_clock_frequency9 = "",
    parameter phase_shift0 = 0,
    parameter phase_shift1 = 0,
    parameter phase_shift10 = 0,
    parameter phase_shift11 = 0,
    parameter phase_shift12 = 0,
    parameter phase_shift13 = 0,
    parameter phase_shift14 = 0,
    parameter phase_shift15 = 0,
    parameter phase_shift16 = 0,
    parameter phase_shift17 = 0,
    parameter phase_shift2 = 0,
    parameter phase_shift3 = 0,
    parameter phase_shift4 = 0,
    parameter phase_shift5 = 0,
    parameter phase_shift6 = 0,
    parameter phase_shift7 = 0,
    parameter phase_shift8 = 0,
    parameter phase_shift9 = 0,
    parameter pll_bwctrl = 0,
    parameter pll_cp_current = 0,
    parameter pll_dsm_out_sel = 0,
    parameter pll_fbclk_mux_1 = "",
    parameter pll_fbclk_mux_2 = "",
    parameter pll_fractional_cout = "",
    parameter pll_fractional_division = "",
    parameter pll_m_cnt_in_src = "",
    parameter pll_output_clk_frequency = "",
    parameter pll_slf_rst = "",
    parameter pll_subtype = "",
    parameter pll_type = "",
    parameter pll_vco_div = 0,
    parameter reference_clock_frequency = ""
) (
    input  wire refclk,
    input  wire rst,
    input  wire fbclk,
    input  wire [63:0] reconfig_to_pll,
    output wire [number_of_clocks-1:0] outclk,
    output wire fboutclk,
    output reg  locked,
    output wire [63:0] reconfig_from_pll
);
    reg [15:0] lock_count;

    assign outclk = {number_of_clocks{refclk}};
    assign fboutclk = refclk;
    assign reconfig_from_pll = 64'd0;

    initial begin
        lock_count = 16'd0;
        locked = 1'b0;
    end

    always @(posedge refclk or posedge rst) begin
        if (rst) begin
            lock_count <= 16'd0;
            locked <= 1'b0;
        end else if (!locked) begin
            lock_count <= lock_count + 16'd1;
            if (lock_count >= 16'd32) locked <= 1'b1;
        end
    end
endmodule
