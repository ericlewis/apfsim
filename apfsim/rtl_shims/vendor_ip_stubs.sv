`timescale 1ns/1ps
// Minimal behavioral vendor-IP replacements. Extend this file only when a core needs a
// specific primitive; do not silently stub stateful devices that affect gameplay.
module lpm_mult #(
    parameter integer lpm_widtha = 8,
    parameter integer lpm_widthb = 8,
    parameter integer lpm_widthp = lpm_widtha + lpm_widthb,
    parameter integer lpm_pipeline = 0
) (
    input  wire [lpm_widtha-1:0] dataa,
    input  wire [lpm_widthb-1:0] datab,
    input  wire clock,
    output reg  [lpm_widthp-1:0] result
);
    always @(*) result = dataa * datab;
endmodule

module lpm_add_sub #(
    parameter integer lpm_width = 8,
    parameter string lpm_direction = "ADD"
) (
    input  wire [lpm_width-1:0] dataa,
    input  wire [lpm_width-1:0] datab,
    input  wire add_sub,
    output wire [lpm_width-1:0] result,
    output wire cout
);
    wire do_sub = (lpm_direction == "SUB") ? 1'b1 : ((lpm_direction == "ADD") ? 1'b0 : add_sub);
    wire [lpm_width:0] tmp = do_sub ? ({1'b0, dataa} - {1'b0, datab}) : ({1'b0, dataa} + {1'b0, datab});
    assign result = tmp[lpm_width-1:0];
    assign cout = tmp[lpm_width];
endmodule

module altddio_out #(
    parameter integer width = 1,
    parameter power_up_high = "OFF",
    parameter oe_reg = "UNUSED",
    parameter extend_oe_disable = "UNUSED",
    parameter intended_device_family = "Cyclone V",
    parameter invert_output = "OFF",
    parameter lpm_type = "altddio_out",
    parameter lpm_hint = "UNUSED"
) (
    input  wire [width-1:0] datain_h,
    input  wire [width-1:0] datain_l,
    input  wire             outclock,
    input  wire             outclocken,
    input  wire             aset,
    input  wire             aclr,
    input  wire             sset,
    input  wire             sclr,
    input  wire             oe,
    output wire [width-1:0] dataout,
    output wire [width-1:0] oe_out
);
    assign oe_out = {width{oe}};
    assign dataout = aclr ? {width{1'b0}} :
                     (aset ? {width{1'b1}} :
                     ((sclr || !outclocken) ? {width{1'b0}} :
                     (sset ? {width{1'b1}} : (outclock ? datain_h : datain_l))));
endmodule

module altddio_bidir #(
    parameter integer width = 1,
    parameter power_up_high = "OFF",
    parameter oe_reg = "UNUSED",
    parameter extend_oe_disable = "UNUSED",
    parameter implement_input_in_lcell = "UNUSED",
    parameter invert_output = "OFF",
    parameter intended_device_family = "Cyclone V",
    parameter lpm_type = "altddio_bidir",
    parameter lpm_hint = "UNUSED"
) (
    input  wire [width-1:0] datain_h,
    input  wire [width-1:0] datain_l,
    input  wire             inclock,
    input  wire             inclocken,
    input  wire             outclock,
    input  wire             outclocken,
    input  wire             aset,
    input  wire             aclr,
    input  wire             sset,
    input  wire             sclr,
    input  wire             oe,
    output reg  [width-1:0] dataout_h,
    output reg  [width-1:0] dataout_l,
    output wire [width-1:0] combout,
    output wire [width-1:0] oe_out,
    output wire [width-1:0] dqsundelayedout,
    inout  wire [width-1:0] padio
);
    wire [width-1:0] drive_value;

    assign padio = oe ? drive_value : {width{1'bz}};
    assign combout = padio;
    assign oe_out = {width{oe}};
    assign dqsundelayedout = padio;

    assign drive_value = aclr ? {width{1'b0}} :
                         (aset ? {width{1'b1}} :
                         ((sclr || !outclocken) ? {width{1'b0}} :
                         (sset ? {width{1'b1}} : (outclock ? datain_h : datain_l))));

    initial begin
        dataout_h = {width{1'b0}};
        dataout_l = {width{1'b0}};
    end

    always @(posedge inclock) begin
        if (inclocken) dataout_h <= padio;
    end

    always @(negedge inclock) begin
        if (inclocken) dataout_l <= padio;
    end
endmodule
