`timescale 1ns/1ps
// Public compile-only fallback for JTFRAME's T80s CPU entity.
//
// The shim catalog prefers the public translated RTL at
// modules/jtframe/hdl/cpu/t80/T80s.v when it is available. This file exists so
// generated profiles can still elaborate far enough to report that a real CPU
// translation is missing. Do not treat gameplay, ROM fetch, or video behavior
// as verified when this fallback appears in source_provenance.json.
module T80s (
    input  wire        RESET_n,
    input  wire        CLK,
    input  wire        CEN,
    input  wire        WAIT_n,
    input  wire        INT_n,
    input  wire        NMI_n,
    input  wire        BUSRQ_n,
    input  wire        OUT0,
    input  wire [7:0]  DI,
    output wire        M1_n,
    output wire        MREQ_n,
    output wire        IORQ_n,
    output wire        RD_n,
    output wire        WR_n,
    output wire        RFSH_n,
    output wire        HALT_n,
    output wire        BUSAK_n,
    output wire [15:0] A,
    output wire [7:0]  DOUT
);
    assign M1_n = 1'b1;
    assign MREQ_n = 1'b1;
    assign IORQ_n = 1'b1;
    assign RD_n = 1'b1;
    assign WR_n = 1'b1;
    assign RFSH_n = 1'b1;
    assign HALT_n = 1'b0;
    assign BUSAK_n = BUSRQ_n;
    assign A = 16'h0000;
    assign DOUT = 8'h00;

    wire _unused = &{RESET_n, CLK, CEN, WAIT_n, INT_n, NMI_n, OUT0, DI};
endmodule
