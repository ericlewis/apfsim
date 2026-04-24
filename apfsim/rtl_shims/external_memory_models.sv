// Generic external RAM models for APF contract bring-up.
//
// These models are intentionally public, deterministic, and conservative.
// They are not timing-accurate Pocket memory devices. Use them to make wrapper
// mappings, byte lanes, request/ack flows, and ROM readback diagnosable.

module apfsim_async_sram_16_model #(
    parameter integer ADDR_WIDTH = 20,
    parameter [15:0] INIT_VALUE = 16'h0000
) (
    input  wire                  clk,
    input  wire                  ce_n,
    input  wire                  oe_n,
    input  wire                  we_n,
    input  wire                  lb_n,
    input  wire                  ub_n,
    input  wire [ADDR_WIDTH-1:0] addr,
    inout  wire [15:0]           dq,

    output reg  [31:0]           read_count,
    output reg  [31:0]           write_count,
    output reg                   bus_contention_error,
    output reg                   byte_enable_error
);
    localparam integer DEPTH = 1 << ADDR_WIDTH;

    reg [15:0] mem [0:DEPTH-1];
    reg [15:0] drive_data;

    assign dq = (!ce_n && !oe_n && we_n) ? drive_data : 16'hZZZZ;

    integer i;
    initial begin
        drive_data = INIT_VALUE;
        read_count = 32'd0;
        write_count = 32'd0;
        bus_contention_error = 1'b0;
        byte_enable_error = 1'b0;
        for (i = 0; i < DEPTH; i = i + 1) mem[i] = INIT_VALUE;
    end

    always @* begin
        drive_data = mem[addr];
    end

    always @(posedge clk) begin
        if (!ce_n) begin
            if (!oe_n && !we_n) bus_contention_error <= 1'b1;
            if (!we_n) begin
                if (lb_n && ub_n) byte_enable_error <= 1'b1;
                if (!lb_n) mem[addr][7:0] <= dq[7:0];
                if (!ub_n) mem[addr][15:8] <= dq[15:8];
                write_count <= write_count + 32'd1;
            end else if (!oe_n) begin
                read_count <= read_count + 32'd1;
            end
        end
    end
endmodule

module apfsim_transactional_ram_model #(
    parameter integer ADDR_WIDTH = 24,
    parameter integer DATA_WIDTH = 16,
    parameter integer BYTE_ENABLE_WIDTH = DATA_WIDTH / 8,
    parameter integer LATENCY_CYCLES = 2
) (
    input  wire                         clk,
    input  wire                         reset,
    input  wire                         req,
    input  wire                         we,
    input  wire [ADDR_WIDTH-1:0]        addr,
    input  wire [DATA_WIDTH-1:0]        din,
    input  wire [BYTE_ENABLE_WIDTH-1:0] byteena,
    output reg  [DATA_WIDTH-1:0]        dout,
    output reg                          ack,
    output reg                          busy,

    output reg  [31:0]                  read_count,
    output reg  [31:0]                  write_count,
    output reg                          overrun_error,
    output reg                          byte_enable_error
);
    localparam integer DEPTH = 1 << ADDR_WIDTH;
    localparam integer COUNT_WIDTH = LATENCY_CYCLES < 2 ? 2 : $clog2(LATENCY_CYCLES + 1);

    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];
    reg [ADDR_WIDTH-1:0] pending_addr;
    reg [DATA_WIDTH-1:0] pending_din;
    reg [BYTE_ENABLE_WIDTH-1:0] pending_byteena;
    reg pending_we;
    reg [COUNT_WIDTH-1:0] latency_count;

    integer i;
    integer b;
    initial begin
        dout = '0;
        ack = 1'b0;
        busy = 1'b0;
        read_count = 32'd0;
        write_count = 32'd0;
        overrun_error = 1'b0;
        byte_enable_error = 1'b0;
        pending_addr = '0;
        pending_din = '0;
        pending_byteena = '0;
        pending_we = 1'b0;
        latency_count = '0;
        for (i = 0; i < DEPTH; i = i + 1) mem[i] = '0;
    end

    task automatic complete_pending;
        reg [DATA_WIDTH-1:0] word;
        begin
            word = mem[pending_addr];
            if (pending_we) begin
                if (pending_byteena == '0) byte_enable_error <= 1'b1;
                for (b = 0; b < BYTE_ENABLE_WIDTH; b = b + 1) begin
                    if (pending_byteena[b]) begin
                        word[(b * 8) +: 8] = pending_din[(b * 8) +: 8];
                    end
                end
                mem[pending_addr] <= word;
                write_count <= write_count + 32'd1;
            end else begin
                read_count <= read_count + 32'd1;
            end
            dout <= word;
            ack <= 1'b1;
            busy <= 1'b0;
        end
    endtask

    always @(posedge clk) begin
        if (reset) begin
            ack <= 1'b0;
            busy <= 1'b0;
            latency_count <= '0;
        end else begin
            ack <= 1'b0;
            if (req && busy) begin
                overrun_error <= 1'b1;
            end
            if (req && !busy) begin
                pending_addr <= addr;
                pending_din <= din;
                pending_byteena <= byteena;
                pending_we <= we;
                busy <= 1'b1;
                latency_count <= COUNT_WIDTH'(LATENCY_CYCLES);
            end else if (busy) begin
                if (latency_count == 0) begin
                    complete_pending();
                end else begin
                    latency_count <= latency_count - 1'b1;
                end
            end
        end
    end
endmodule

module apfsim_psram_like_model #(
    parameter integer ADDR_WIDTH = 24,
    parameter integer LATENCY_CYCLES = 6
) (
    input  wire                  clk,
    input  wire                  reset,
    input  wire                  req,
    input  wire                  we,
    input  wire [ADDR_WIDTH-1:0] addr,
    input  wire [15:0]           din,
    input  wire [1:0]            byteena,
    output wire [15:0]           dout,
    output wire                  ack,
    output wire                  busy,
    output wire [31:0]           read_count,
    output wire [31:0]           write_count,
    output wire                  overrun_error,
    output wire                  byte_enable_error
);
    apfsim_transactional_ram_model #(
        .ADDR_WIDTH(ADDR_WIDTH),
        .DATA_WIDTH(16),
        .BYTE_ENABLE_WIDTH(2),
        .LATENCY_CYCLES(LATENCY_CYCLES)
    ) ram (
        .clk(clk),
        .reset(reset),
        .req(req),
        .we(we),
        .addr(addr),
        .din(din),
        .byteena(byteena),
        .dout(dout),
        .ack(ack),
        .busy(busy),
        .read_count(read_count),
        .write_count(write_count),
        .overrun_error(overrun_error),
        .byte_enable_error(byte_enable_error)
    );
endmodule

module apfsim_cram_like_model #(
    parameter integer ADDR_WIDTH = 21,
    parameter integer LATENCY_CYCLES = 4
) (
    input  wire                  clk,
    input  wire                  reset,
    input  wire                  req,
    input  wire                  we,
    input  wire [ADDR_WIDTH-1:0] addr,
    input  wire [15:0]           din,
    input  wire [1:0]            byteena,
    output wire [15:0]           dout,
    output wire                  ack,
    output wire                  busy,
    output wire [31:0]           read_count,
    output wire [31:0]           write_count,
    output wire                  overrun_error,
    output wire                  byte_enable_error
);
    apfsim_transactional_ram_model #(
        .ADDR_WIDTH(ADDR_WIDTH),
        .DATA_WIDTH(16),
        .BYTE_ENABLE_WIDTH(2),
        .LATENCY_CYCLES(LATENCY_CYCLES)
    ) ram (
        .clk(clk),
        .reset(reset),
        .req(req),
        .we(we),
        .addr(addr),
        .din(din),
        .byteena(byteena),
        .dout(dout),
        .ack(ack),
        .busy(busy),
        .read_count(read_count),
        .write_count(write_count),
        .overrun_error(overrun_error),
        .byte_enable_error(byte_enable_error)
    );
endmodule
