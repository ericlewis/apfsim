// Small behavioral subset of Intel/Altera altsyncram for RTL simulation.
module altsyncram #(
    parameter integer width_a = 8,
    parameter integer widthad_a = 10,
    parameter integer numwords_a = (1 << widthad_a),
    parameter integer width_b = width_a,
    parameter integer widthad_b = widthad_a,
    parameter integer numwords_b = (1 << widthad_b),
    parameter integer width_byteena_a = 1,
    parameter integer width_byteena_b = 1,
    parameter string address_aclr_b = "NONE",
    parameter string address_reg_b = "CLOCK1",
    parameter string clock_enable_input_a = "BYPASS",
    parameter string clock_enable_input_b = "BYPASS",
    parameter string clock_enable_output_a = "BYPASS",
    parameter string clock_enable_output_b = "BYPASS",
    parameter string indata_reg_b = "CLOCK1",
    parameter string init_file = "",
    parameter string intended_device_family = "Cyclone V",
    parameter string lpm_type = "altsyncram",
    parameter string operation_mode = "BIDIR_DUAL_PORT",
    parameter string outdata_aclr_a = "NONE",
    parameter string outdata_aclr_b = "NONE",
    parameter string outdata_reg_a = "CLOCK0",
    parameter string outdata_reg_b = "CLOCK1",
    parameter string power_up_uninitialized = "FALSE",
    parameter string read_during_write_mode_mixed_ports = "DONT_CARE",
    parameter string read_during_write_mode_port_a = "NEW_DATA_NO_NBE_READ",
    parameter string read_during_write_mode_port_b = "NEW_DATA_NO_NBE_READ",
    parameter string wrcontrol_wraddress_reg_b = "CLOCK1"
) (
    input  wire clock0,
    input  wire clock1,
    input  wire aclr0,
    input  wire aclr1,
    input  wire [widthad_a-1:0] address_a,
    input  wire [widthad_b-1:0] address_b,
    input  wire addressstall_a,
    input  wire addressstall_b,
    input  wire [width_a-1:0] data_a,
    input  wire [width_b-1:0] data_b,
    input  wire wren_a,
    input  wire wren_b,
    input  wire rden_a,
    input  wire rden_b,
    input  wire [width_byteena_a-1:0] byteena_a,
    input  wire [width_byteena_b-1:0] byteena_b,
    input  wire clocken0,
    input  wire clocken1,
    input  wire clocken2,
    input  wire clocken3,
    output reg  [width_a-1:0] q_a,
    output reg  [width_b-1:0] q_b,
    output wire [2:0] eccstatus
);
    localparam integer DEPTH = (numwords_a > numwords_b) ? numwords_a : numwords_b;
    localparam integer WIDTH = (width_a > width_b) ? width_a : width_b;
    reg [WIDTH-1:0] mem [0:DEPTH-1];
    assign eccstatus = 3'b000;

    integer i;
    initial begin
        q_a = '0;
        q_b = '0;
        for (i = 0; i < DEPTH; i = i + 1) mem[i] = '0;
    end

    task automatic write_a(input [widthad_a-1:0] addr, input [width_a-1:0] data, input [width_byteena_a-1:0] be);
        integer b;
        begin
            if (width_byteena_a <= 1) begin
                mem[addr][width_a-1:0] <= data;
            end else begin
                for (b = 0; b < width_byteena_a; b = b + 1) begin
                    if (be[b]) mem[addr][(b * (width_a / width_byteena_a)) +: (width_a / width_byteena_a)] <= data[(b * (width_a / width_byteena_a)) +: (width_a / width_byteena_a)];
                end
            end
        end
    endtask

    task automatic write_b(input [widthad_b-1:0] addr, input [width_b-1:0] data, input [width_byteena_b-1:0] be);
        integer b;
        begin
            if (width_byteena_b <= 1) begin
                mem[addr][width_b-1:0] <= data;
            end else begin
                for (b = 0; b < width_byteena_b; b = b + 1) begin
                    if (be[b]) mem[addr][(b * (width_b / width_byteena_b)) +: (width_b / width_byteena_b)] <= data[(b * (width_b / width_byteena_b)) +: (width_b / width_byteena_b)];
                end
            end
        end
    endtask

    always @(posedge clock0) begin
        if (clocken0 !== 1'b0) begin
            if (wren_a) write_a(address_a, data_a, byteena_a);
            if (rden_a !== 1'b0) q_a <= mem[address_a][width_a-1:0];
        end
    end

    generate
        if (address_reg_b == "CLOCK0" || indata_reg_b == "CLOCK0" || outdata_reg_b == "CLOCK0" || wrcontrol_wraddress_reg_b == "CLOCK0") begin : port_b_clock0
            always @(posedge clock0) begin
                if (clocken0 !== 1'b0) begin
                    if (wren_b) write_b(address_b, data_b, byteena_b);
                    if (rden_b !== 1'b0) q_b <= mem[address_b][width_b-1:0];
                end
            end
        end else begin : port_b_clock1
            always @(posedge clock1) begin
                if (clocken1 !== 1'b0) begin
                    if (wren_b) write_b(address_b, data_b, byteena_b);
                    if (rden_b !== 1'b0) q_b <= mem[address_b][width_b-1:0];
                end
            end
        end
    endgenerate
endmodule
