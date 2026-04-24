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
