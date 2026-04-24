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
    input  wire                  reset,
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
        if (reset) begin
            read_count <= 32'd0;
            write_count <= 32'd0;
            bus_contention_error <= 1'b0;
            byte_enable_error <= 1'b0;
        end else if (!ce_n) begin
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
    parameter integer DATA_WIDTH = 16,
    parameter integer BYTE_ENABLE_WIDTH = DATA_WIDTH / 8,
    parameter integer LATENCY_CYCLES = 6
) (
    input  wire                         clk,
    input  wire                         reset,
    input  wire                         req,
    input  wire                         we,
    input  wire [ADDR_WIDTH-1:0]        addr,
    input  wire [DATA_WIDTH-1:0]        din,
    input  wire [BYTE_ENABLE_WIDTH-1:0] byteena,
    output wire [DATA_WIDTH-1:0]        dout,
    output wire                         ack,
    output wire                         busy,
    output wire [31:0]                  read_count,
    output wire [31:0]                  write_count,
    output wire                         overrun_error,
    output wire                         byte_enable_error
);
    apfsim_transactional_ram_model #(
        .ADDR_WIDTH(ADDR_WIDTH),
        .DATA_WIDTH(DATA_WIDTH),
        .BYTE_ENABLE_WIDTH(BYTE_ENABLE_WIDTH),
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
    parameter integer DATA_WIDTH = 16,
    parameter integer BYTE_ENABLE_WIDTH = DATA_WIDTH / 8,
    parameter integer LATENCY_CYCLES = 4
) (
    input  wire                         clk,
    input  wire                         reset,
    input  wire                         req,
    input  wire                         we,
    input  wire [ADDR_WIDTH-1:0]        addr,
    input  wire [DATA_WIDTH-1:0]        din,
    input  wire [BYTE_ENABLE_WIDTH-1:0] byteena,
    output wire [DATA_WIDTH-1:0]        dout,
    output wire                         ack,
    output wire                         busy,
    output wire [31:0]                  read_count,
    output wire [31:0]                  write_count,
    output wire                         overrun_error,
    output wire                         byte_enable_error
);
    apfsim_transactional_ram_model #(
        .ADDR_WIDTH(ADDR_WIDTH),
        .DATA_WIDTH(DATA_WIDTH),
        .BYTE_ENABLE_WIDTH(BYTE_ENABLE_WIDTH),
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

module apfsim_sdram_pin_model #(
    parameter integer ADDR_WIDTH = 24,
    parameter integer COL_WIDTH = 9,
    parameter integer CAS_LATENCY = 2,
    parameter integer DEFAULT_BURST_LENGTH = 8
) (
    input  wire        Clk,
    input  wire        Cke,
    inout  wire [15:0] Dq,
    input  wire [12:0] Addr,
    input  wire [1:0]  Ba,
    input  wire        Cs_n,
    input  wire        Ras_n,
    input  wire        Cas_n,
    input  wire        We_n,
    input  wire [1:0]  Dqm,
    input  wire        preload_clk,
    input  wire        preload_we,
    input  wire [ADDR_WIDTH-1:0] preload_addr,
    input  wire [15:0] preload_data,
    input  wire [1:0]  preload_dqm,

    output reg  [31:0] read_count,
    output reg  [31:0] write_count,
    output reg  [31:0] activate_count,
    output reg  [31:0] refresh_count,
    output reg  [31:0] preload_count,
    output reg  [31:0] coverage_gap_count,
    output reg  [31:0] rom_mismatch_count,
    output reg  [31:0] rom_unwritten_read_count,
    output reg  [ADDR_WIDTH-1:0] first_coverage_gap_addr,
    output reg  [ADDR_WIDTH-1:0] first_rom_mismatch_addr,
    output reg  [ADDR_WIDTH-1:0] first_rom_unwritten_read_addr,
    output reg  [15:0] first_rom_mismatch_expected,
    output reg  [15:0] first_rom_mismatch_actual,
    output reg  [1:0]  first_rom_mismatch_dqm,
    output reg  [15:0] first_rom_unwritten_expected,
    output reg  [1:0]  first_rom_unwritten_dqm,
    output reg          command_error,
    output reg          bus_contention_error,
    output reg          byte_enable_error,
    output reg          rom_mismatch_error,
    output reg          uninitialized_read_error
);
    localparam integer DEPTH = 1 << ADDR_WIDTH;
    localparam integer ROW_WIDTH = ADDR_WIDTH - COL_WIDTH - 2;
    localparam integer MAX_LATENCY = CAS_LATENCY < 1 ? 1 : CAS_LATENCY;

    reg [15:0] mem [0:DEPTH-1];
    reg        mem_valid [0:DEPTH-1];
    reg [15:0] expected_mem [0:DEPTH-1];
    reg        expected_valid [0:DEPTH-1];
    reg [ROW_WIDTH-1:0] active_row [0:3];
    reg [3:0] bank_active;
    reg [2:0] burst_length;

    reg [MAX_LATENCY-1:0] read_valid_pipe;
    reg [ADDR_WIDTH-1:0] read_addr_pipe [0:MAX_LATENCY-1];
    reg [1:0] read_dqm_pipe [0:MAX_LATENCY-1];
    reg drive_enable;
    reg [15:0] drive_data;
    reg [1:0] drive_dqm;

    reg [ADDR_WIDTH-1:0] read_burst_addr;
    reg [3:0] read_burst_remaining;
    reg [1:0] read_burst_dqm;
    reg [ADDR_WIDTH-1:0] write_burst_addr;
    reg [3:0] write_burst_remaining;

    wire [15:0] drive_masked = {
        drive_dqm[1] ? 8'hZZ : drive_data[15:8],
        drive_dqm[0] ? 8'hZZ : drive_data[7:0]
    };
    assign Dq = drive_enable ? drive_masked : 16'hZZZZ;

    wire command_cycle = Cke && !Cs_n;
    wire cmd_active = command_cycle && !Ras_n &&  Cas_n &&  We_n;
    wire cmd_read =   command_cycle &&  Ras_n && !Cas_n &&  We_n;
    wire cmd_write =  command_cycle &&  Ras_n && !Cas_n && !We_n;
    wire cmd_pre =    command_cycle && !Ras_n &&  Cas_n && !We_n;
    wire cmd_refresh = command_cycle && !Ras_n && !Cas_n &&  We_n;
    wire cmd_mode =   command_cycle && !Ras_n && !Cas_n && !We_n;
    wire cmd_bterm =  command_cycle &&  Ras_n &&  Cas_n && !We_n;

    function automatic [2:0] decode_burst_length(input [2:0] mode_bits);
        begin
            case (mode_bits)
                3'b000: decode_burst_length = 3'd1;
                3'b001: decode_burst_length = 3'd2;
                3'b010: decode_burst_length = 3'd4;
                3'b011: decode_burst_length = 3'd7; // encode eight beats as 7 plus first beat
                default: decode_burst_length = DEFAULT_BURST_LENGTH[2:0] == 3'd0 ? 3'd7 : DEFAULT_BURST_LENGTH[2:0];
            endcase
        end
    endfunction

    function automatic [ADDR_WIDTH-1:0] linear_addr(input [1:0] bank, input [ROW_WIDTH-1:0] row, input [COL_WIDTH-1:0] col);
        begin
            linear_addr = {bank, row, col};
        end
    endfunction

    function automatic [COL_WIDTH-1:0] command_col(input [12:0] addr);
        begin
            command_col = addr[COL_WIDTH-1:0];
        end
    endfunction

    function automatic bit word_mismatch(input [15:0] actual, input [15:0] expected, input [1:0] dqm);
        begin
            word_mismatch = (!dqm[0] && actual[7:0] != expected[7:0]) ||
                            (!dqm[1] && actual[15:8] != expected[15:8]);
        end
    endfunction

    task automatic note_rom_mismatch(input [ADDR_WIDTH-1:0] addr, input [15:0] actual, input [15:0] expected, input [1:0] dqm);
        begin
            rom_mismatch_error <= 1'b1;
            if (rom_mismatch_count == 32'd0) begin
                first_rom_mismatch_addr <= addr;
                first_rom_mismatch_expected <= expected;
                first_rom_mismatch_actual <= actual;
                first_rom_mismatch_dqm <= dqm;
            end
            rom_mismatch_count <= rom_mismatch_count + 32'd1;
        end
    endtask

    task automatic write_word(input [ADDR_WIDTH-1:0] addr, input [15:0] data, input [1:0] dqm);
        reg [15:0] word;
        begin
            if (^dqm === 1'bx) byte_enable_error <= 1'b1;
            word = mem_valid[addr] === 1'b1 ? mem[addr] : 16'h0000;
            if (!dqm[0]) word[7:0] = data[7:0];
            if (!dqm[1]) word[15:8] = data[15:8];
            if (dqm != 2'b11) begin
                mem[addr] <= word;
                mem_valid[addr] <= 1'b1;
                write_count <= write_count + 32'd1;
            end
        end
    endtask

    task automatic schedule_read(input [ADDR_WIDTH-1:0] addr, input [1:0] dqm);
        begin
            read_addr_pipe[0] <= addr;
            read_dqm_pipe[0] <= dqm;
            read_valid_pipe[0] <= 1'b1;
            read_count <= read_count + 32'd1;
        end
    endtask

    always @(posedge preload_clk) begin
        reg [15:0] expected_word;

        if (preload_we && preload_dqm != 2'b11) begin
            expected_word = expected_valid[preload_addr] === 1'b1 ? expected_mem[preload_addr] : 16'h0000;
            if (!preload_dqm[0]) expected_word[7:0] = preload_data[7:0];
            if (!preload_dqm[1]) expected_word[15:8] = preload_data[15:8];
            expected_mem[preload_addr] <= expected_word;
            expected_valid[preload_addr] <= 1'b1;
            preload_count <= preload_count + 32'd1;
        end
    end

    integer i;
    initial begin
        read_count = 32'd0;
        write_count = 32'd0;
        activate_count = 32'd0;
        refresh_count = 32'd0;
        preload_count = 32'd0;
        coverage_gap_count = 32'd0;
        rom_mismatch_count = 32'd0;
        rom_unwritten_read_count = 32'd0;
        first_coverage_gap_addr = {ADDR_WIDTH{1'b0}};
        first_rom_mismatch_addr = {ADDR_WIDTH{1'b0}};
        first_rom_unwritten_read_addr = {ADDR_WIDTH{1'b0}};
        first_rom_mismatch_expected = 16'h0000;
        first_rom_mismatch_actual = 16'h0000;
        first_rom_mismatch_dqm = 2'b11;
        first_rom_unwritten_expected = 16'h0000;
        first_rom_unwritten_dqm = 2'b11;
        command_error = 1'b0;
        bus_contention_error = 1'b0;
        byte_enable_error = 1'b0;
        rom_mismatch_error = 1'b0;
        uninitialized_read_error = 1'b0;
        bank_active = 4'd0;
        burst_length = decode_burst_length(DEFAULT_BURST_LENGTH[2:0]);
        read_valid_pipe = {MAX_LATENCY{1'b0}};
        drive_enable = 1'b0;
        drive_data = 16'h0000;
        drive_dqm = 2'b11;
        read_burst_addr = {ADDR_WIDTH{1'b0}};
        read_burst_remaining = 4'd0;
        read_burst_dqm = 2'b11;
        write_burst_addr = {ADDR_WIDTH{1'b0}};
        write_burst_remaining = 4'd0;
        for (i = 0; i < 4; i = i + 1) active_row[i] = {ROW_WIDTH{1'b0}};
    end

    always @(posedge Clk) begin
        reg [ADDR_WIDTH-1:0] access_addr;
        reg [COL_WIDTH-1:0] col;
        reg [ADDR_WIDTH-1:0] read_addr;

        if (drive_enable && !drive_dqm[0] && (^Dq[7:0] === 1'bx)) bus_contention_error <= 1'b1;
        if (drive_enable && !drive_dqm[1] && (^Dq[15:8] === 1'bx)) bus_contention_error <= 1'b1;

        drive_enable <= read_valid_pipe[MAX_LATENCY-1];
        drive_dqm <= read_dqm_pipe[MAX_LATENCY-1];
        if (read_valid_pipe[MAX_LATENCY-1]) begin
            read_addr = read_addr_pipe[MAX_LATENCY-1];
            if (mem_valid[read_addr] === 1'b1) begin
                drive_data <= mem[read_addr];
                if (expected_valid[read_addr] === 1'b1 &&
                    word_mismatch(mem[read_addr], expected_mem[read_addr], read_dqm_pipe[MAX_LATENCY-1])) begin
                    note_rom_mismatch(read_addr, mem[read_addr], expected_mem[read_addr], read_dqm_pipe[MAX_LATENCY-1]);
                end
            end else if (expected_valid[read_addr] === 1'b1) begin
                drive_data <= expected_mem[read_addr];
                uninitialized_read_error <= 1'b1;
                if (rom_unwritten_read_count == 32'd0) begin
                    first_rom_unwritten_read_addr <= read_addr;
                    first_rom_unwritten_expected <= expected_mem[read_addr];
                    first_rom_unwritten_dqm <= read_dqm_pipe[MAX_LATENCY-1];
                end
                rom_unwritten_read_count <= rom_unwritten_read_count + 32'd1;
            end else begin
                drive_data <= 16'h0000;
                if (preload_count == 32'd0) begin
                    uninitialized_read_error <= 1'b1;
                    if (rom_unwritten_read_count == 32'd0) begin
                        first_rom_unwritten_read_addr <= read_addr;
                        first_rom_unwritten_expected <= 16'h0000;
                        first_rom_unwritten_dqm <= read_dqm_pipe[MAX_LATENCY-1];
                    end
                    rom_unwritten_read_count <= rom_unwritten_read_count + 32'd1;
                end else begin
                    if (coverage_gap_count == 32'd0) first_coverage_gap_addr <= read_addr;
                    coverage_gap_count <= coverage_gap_count + 32'd1;
                end
            end
        end

        for (i = MAX_LATENCY - 1; i > 0; i = i - 1) begin
            read_valid_pipe[i] <= read_valid_pipe[i - 1];
            read_addr_pipe[i] <= read_addr_pipe[i - 1];
            read_dqm_pipe[i] <= read_dqm_pipe[i - 1];
        end
        read_valid_pipe[0] <= 1'b0;
        read_dqm_pipe[0] <= 2'b11;

        if (cmd_mode) begin
            burst_length <= decode_burst_length(Addr[2:0]);
        end

        if (cmd_refresh) refresh_count <= refresh_count + 32'd1;

        if (cmd_active) begin
            active_row[Ba] <= Addr[ROW_WIDTH-1:0];
            bank_active[Ba] <= 1'b1;
            activate_count <= activate_count + 32'd1;
        end

        if (cmd_pre) begin
            if (Addr[10]) bank_active <= 4'd0;
            else bank_active[Ba] <= 1'b0;
            read_burst_remaining <= 4'd0;
            write_burst_remaining <= 4'd0;
        end

        if (cmd_bterm) begin
            read_burst_remaining <= 4'd0;
            write_burst_remaining <= 4'd0;
        end

        if (cmd_read) begin
            if (!bank_active[Ba]) begin
                command_error <= 1'b1;
            end else begin
                col = command_col(Addr);
                access_addr = linear_addr(Ba, active_row[Ba], col);
                schedule_read(access_addr, Dqm);
                if (burst_length > 3'd1) begin
                    read_burst_addr <= access_addr + {{(ADDR_WIDTH-1){1'b0}}, 1'b1};
                    read_burst_remaining <= {1'b0, burst_length} - 4'd1;
                    read_burst_dqm <= Dqm;
                end
            end
        end else if (read_burst_remaining != 4'd0) begin
            schedule_read(read_burst_addr, read_burst_dqm);
            read_burst_addr <= read_burst_addr + {{(ADDR_WIDTH-1){1'b0}}, 1'b1};
            read_burst_remaining <= read_burst_remaining - 4'd1;
        end

        if (cmd_write) begin
            if (!bank_active[Ba]) begin
                command_error <= 1'b1;
            end else begin
                col = command_col(Addr);
                access_addr = linear_addr(Ba, active_row[Ba], col);
                write_word(access_addr, Dq, Dqm);
                if (burst_length > 3'd1) begin
                    write_burst_addr <= access_addr + {{(ADDR_WIDTH-1){1'b0}}, 1'b1};
                    write_burst_remaining <= {1'b0, burst_length} - 4'd1;
                end
            end
        end else if (write_burst_remaining != 4'd0) begin
            write_word(write_burst_addr, Dq, Dqm);
            write_burst_addr <= write_burst_addr + {{(ADDR_WIDTH-1){1'b0}}, 1'b1};
            write_burst_remaining <= write_burst_remaining - 4'd1;
        end
    end
endmodule
