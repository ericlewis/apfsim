module io_sdram #(
    parameter ADDR_BITS = 23,
    parameter INIT_DELAY = 32
) (
    input  wire            controller_clk,
    input  wire            chip_clk,
    input  wire            clk_90,
    input  wire            reset_n,

    output reg             phy_cke,
    output wire            phy_clk,
    output wire            phy_cas,
    output wire            phy_ras,
    output wire            phy_we,
    output reg     [1:0]   phy_ba,
    output reg     [12:0]  phy_a,
    inout  wire    [15:0]  phy_dq,
    output reg     [1:0]   phy_dqm,

    input  wire            burst_rd,
    input  wire    [24:0]  burst_addr,
    input  wire    [10:0]  burst_len,
    input  wire            burst_32bit,
    output reg     [31:0]  burst_data,
    output reg             burst_data_valid,
    output reg             burst_data_done,

    input  wire            burstwr,
    input  wire    [24:0]  burstwr_addr,
    output reg             burstwr_ready,
    input  wire            burstwr_strobe,
    input  wire    [15:0]  burstwr_data,
    input  wire            burstwr_done,

    input  wire            word_rd,
    input  wire            word_wr,
    input  wire    [23:0]  word_addr,
    input  wire    [31:0]  word_data,
    output reg     [31:0]  word_q,
    output reg             word_q_valid,
    output wire            word_busy,
    output wire            init_done
);
    localparam DEPTH = (1 << ADDR_BITS);

    reg [15:0] mem [0:DEPTH-1];
    reg [7:0] init_count;
    reg initialized;

    reg burst_active;
    reg [24:0] burst_ptr;
    reg [10:0] burst_remaining;
    reg burst_mode_32;

    reg burstwr_active;
    reg [24:0] burstwr_ptr;

    assign phy_clk = chip_clk;
    assign phy_cas = 1'b1;
    assign phy_ras = 1'b1;
    assign phy_we = 1'b1;
    assign phy_dq = 16'hzzzz;
    assign word_busy = 1'b0;
    assign init_done = initialized;

    wire [ADDR_BITS-1:0] word_half_addr = {word_addr[ADDR_BITS-2:0], 1'b0};
    wire [ADDR_BITS-1:0] burst_index = burst_ptr[ADDR_BITS-1:0];
    wire [24:0] burst_ptr_plus1 = burst_ptr + 25'd1;
    wire [ADDR_BITS-1:0] burst_next_index = burst_ptr_plus1[ADDR_BITS-1:0];
    wire [ADDR_BITS-1:0] burstwr_index = burstwr_ptr[ADDR_BITS-1:0];

    always @(posedge controller_clk or negedge reset_n) begin
        if (!reset_n) begin
            phy_cke <= 1'b0;
            phy_ba <= 2'b00;
            phy_a <= 13'h0000;
            phy_dqm <= 2'b00;
            burst_data <= 32'h00000000;
            burst_data_valid <= 1'b0;
            burst_data_done <= 1'b0;
            burstwr_ready <= 1'b0;
            word_q <= 32'h00000000;
            word_q_valid <= 1'b0;
            init_count <= 8'h00;
            initialized <= 1'b0;
            burst_active <= 1'b0;
            burst_ptr <= 25'h0000000;
            burst_remaining <= 11'h000;
            burst_mode_32 <= 1'b0;
            burstwr_active <= 1'b0;
            burstwr_ptr <= 25'h0000000;
        end else begin
            phy_cke <= 1'b1;
            burst_data_valid <= 1'b0;
            burst_data_done <= 1'b0;
            burstwr_ready <= 1'b0;
            word_q_valid <= 1'b0;

            if (!initialized) begin
                init_count <= init_count + 8'd1;
                if (init_count == (INIT_DELAY - 1)) initialized <= 1'b1;
            end

            if (word_wr) begin
                mem[word_half_addr] <= word_data[31:16];
                mem[word_half_addr + {{(ADDR_BITS-1){1'b0}}, 1'b1}] <= word_data[15:0];
            end

            if (word_rd) begin
                word_q <= {
                    mem[word_half_addr],
                    mem[word_half_addr + {{(ADDR_BITS-1){1'b0}}, 1'b1}]
                };
                word_q_valid <= 1'b1;
            end

            if (burst_rd && !burst_active) begin
                burst_active <= 1'b1;
                burst_ptr <= burst_addr;
                burst_remaining <= burst_len;
                burst_mode_32 <= burst_32bit;
            end

            if (burst_active) begin
                if (burst_mode_32) begin
                    burst_data <= {mem[burst_index], mem[burst_next_index]};
                    burst_ptr <= burst_ptr + 25'd2;
                    burst_remaining <= (burst_remaining > 11'd1) ? (burst_remaining - 11'd2) : 11'd0;
                    burst_data_valid <= 1'b1;
                    if (burst_remaining <= 11'd2) begin
                        burst_active <= 1'b0;
                        burst_data_done <= 1'b1;
                    end
                end else begin
                    burst_data <= {16'h0000, mem[burst_index]};
                    burst_ptr <= burst_ptr + 25'd1;
                    burst_remaining <= burst_remaining - 11'd1;
                    burst_data_valid <= 1'b1;
                    if (burst_remaining <= 11'd1) begin
                        burst_active <= 1'b0;
                        burst_data_done <= 1'b1;
                    end
                end
            end

            if (burstwr && !burstwr_active) begin
                burstwr_active <= 1'b1;
                burstwr_ptr <= burstwr_addr;
            end

            if (burstwr_active) begin
                burstwr_ready <= 1'b1;
                if (burstwr_strobe) begin
                    mem[burstwr_index] <= burstwr_data;
                    burstwr_ptr <= burstwr_ptr + 25'd1;
                end
                if (burstwr_done) burstwr_active <= 1'b0;
            end
        end
    end
endmodule
