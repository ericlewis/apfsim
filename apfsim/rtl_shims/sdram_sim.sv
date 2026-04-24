// Behavioral four-port SDRAM replacement for Verilator profiles.
//
// This matches the Sorgelig/Genesis-style `sdram` module interface used by
// several arcade ports: each port submits a request by toggling reqN, and the
// memory completes by copying reqN to ackN with doutN valid.
module sdram (
    inout      [15:0] SDRAM_DQ,
    output reg [12:0] SDRAM_A,
    output            SDRAM_DQML,
    output            SDRAM_DQMH,
    output reg  [1:0] SDRAM_BA,
    output            SDRAM_nCS,
    output reg        SDRAM_nWE,
    output reg        SDRAM_nRAS,
    output reg        SDRAM_nCAS,
    output            SDRAM_CLK,
    output            SDRAM_CKE,
    output            ready,

    input             init,
    input             clk,
    input       [1:0] prio_mode,

    input      [24:1] addr0,
    input             wrl0,
    input             wrh0,
    input      [15:0] din0,
    output reg [15:0] dout0,
    input             req0,
    output reg        ack0,

    input      [24:1] addr1,
    input             wrl1,
    input             wrh1,
    input      [15:0] din1,
    output reg [15:0] dout1,
    input             req1,
    output reg        ack1,

    input      [24:1] addr2,
    input             wrl2,
    input             wrh2,
    input      [15:0] din2,
    output reg [15:0] dout2,
    input             req2,
    output reg        ack2,

    input      [24:1] addr3,
    input             wrl3,
    input             wrh3,
    input      [15:0] din3,
    output reg [15:0] dout3,
    input             req3,
    output reg        ack3
);
    localparam integer ADDR_BITS = 24;
    localparam integer MEM_WORDS = 1 << ADDR_BITS;
    localparam integer INIT_CYCLES = 64;

    reg [15:0] mem [0:MEM_WORDS-1];
    reg [15:0] init_count;
    reg        ready_r;

    assign SDRAM_DQ = 16'hZZZZ;
    assign SDRAM_DQML = 1'b0;
    assign SDRAM_DQMH = 1'b0;
    assign SDRAM_nCS = 1'b0;
    assign SDRAM_CKE = 1'b1;
    assign SDRAM_CLK = clk;
    assign ready = ready_r;

    initial begin
        SDRAM_A = 13'd0;
        SDRAM_BA = 2'd0;
        SDRAM_nWE = 1'b1;
        SDRAM_nRAS = 1'b1;
        SDRAM_nCAS = 1'b1;
        dout0 = 16'd0;
        dout1 = 16'd0;
        dout2 = 16'd0;
        dout3 = 16'd0;
        ack0 = 1'b0;
        ack1 = 1'b0;
        ack2 = 1'b0;
        ack3 = 1'b0;
        init_count = 16'd0;
        ready_r = 1'b0;
    end

    always @(posedge clk) begin
        reg [15:0] next0;
        reg [15:0] next1;
        reg [15:0] next2;
        reg [15:0] next3;

        SDRAM_A <= 13'd0;
        SDRAM_BA <= 2'd0;
        SDRAM_nWE <= 1'b1;
        SDRAM_nRAS <= 1'b1;
        SDRAM_nCAS <= 1'b1;

        if (init) begin
            ready_r <= 1'b0;
            init_count <= 16'd0;
        end else if (!ready_r) begin
            init_count <= init_count + 16'd1;
            if (init_count >= INIT_CYCLES[15:0]) ready_r <= 1'b1;
        end else begin
            if (req0 != ack0) begin
                next0 = mem[addr0];
                if (wrl0) next0[7:0] = din0[7:0];
                if (wrh0) next0[15:8] = din0[15:8];
                if (wrl0 || wrh0) mem[addr0] <= next0;
                dout0 <= next0;
                ack0 <= req0;
            end

            if (req1 != ack1) begin
                next1 = mem[addr1];
                if (wrl1) next1[7:0] = din1[7:0];
                if (wrh1) next1[15:8] = din1[15:8];
                if (wrl1 || wrh1) mem[addr1] <= next1;
                dout1 <= next1;
                ack1 <= req1;
            end

            if (req2 != ack2) begin
                next2 = mem[addr2];
                if (wrl2) next2[7:0] = din2[7:0];
                if (wrh2) next2[15:8] = din2[15:8];
                if (wrl2 || wrh2) mem[addr2] <= next2;
                dout2 <= next2;
                ack2 <= req2;
            end

            if (req3 != ack3) begin
                next3 = mem[addr3];
                if (wrl3) next3[7:0] = din3[7:0];
                if (wrh3) next3[15:8] = din3[15:8];
                if (wrl3 || wrh3) mem[addr3] <= next3;
                dout3 <= next3;
                ack3 <= req3;
            end
        end
    end

    wire unused_prio = |prio_mode;
endmodule
