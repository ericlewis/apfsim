// Small behavioral dual-port RAM used by MiSTer-style arcade cores.
module dpram #(
    parameter integer addr_width = 10,
    parameter integer data_width = 8
) (
    input  wire                    clock_a,
    input  wire [addr_width-1:0]   address_a,
    input  wire [data_width-1:0]   data_a,
    input  wire                    wren_a,
    input  wire                    enable_a,
    output reg  [data_width-1:0]   q_a,

    input  wire                    clock_b,
    input  wire [addr_width-1:0]   address_b,
    input  wire [data_width-1:0]   data_b,
    input  wire                    wren_b,
    input  wire                    enable_b,
    output reg  [data_width-1:0]   q_b
);
    localparam integer DEPTH = 1 << addr_width;
    reg [data_width-1:0] mem [0:DEPTH-1];

    integer i;
    initial begin
        q_a = '0;
        q_b = '0;
        for (i = 0; i < DEPTH; i = i + 1) mem[i] = '0;
    end

    function automatic bit known_addr(input [addr_width-1:0] addr);
        known_addr = (^addr !== 1'bx);
    endfunction

    always @(posedge clock_a) begin
        if (enable_a !== 1'b0 && known_addr(address_a)) begin
            if (wren_a === 1'b1) mem[address_a] <= data_a;
            q_a <= (wren_a === 1'b1) ? data_a : mem[address_a];
        end
    end

    always @(posedge clock_b) begin
        if (enable_b !== 1'b0 && known_addr(address_b)) begin
            if (wren_b === 1'b1) mem[address_b] <= data_b;
            q_b <= (wren_b === 1'b1) ? data_b : mem[address_b];
        end
    end
endmodule
