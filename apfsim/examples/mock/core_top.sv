module core_top (
    input  wire        clk_74a,
    input  wire        clk_74b,

    input  wire        bridge_wr,
    input  wire        bridge_rd,
    input  wire [31:0] bridge_addr,
    input  wire [31:0] bridge_wr_data,
    output reg  [31:0] bridge_rd_data,
    input  wire        bridge_endian_little,

    input  wire [31:0] cont1_key,
    input  wire [31:0] cont2_key,
    input  wire [31:0] cont3_key,
    input  wire [31:0] cont4_key,
    input  wire [31:0] cont1_joy,
    input  wire [31:0] cont2_joy,
    input  wire [31:0] cont3_joy,
    input  wire [31:0] cont4_joy,
    input  wire [31:0] cont1_trig,
    input  wire [31:0] cont2_trig,
    input  wire [31:0] cont3_trig,
    input  wire [31:0] cont4_trig,

    output wire        video_rgb_clock,
    output wire        video_rgb_clock_90,
    output reg         video_de,
    output reg         video_skip,
    output reg         video_vs,
    output reg         video_hs,
    output reg  [23:0] video_rgb,

    output reg         audio_mclk,
    output reg         audio_lrck,
    output reg         audio_dac
);
    localparam [31:0] APF_BASE   = 32'hF8000000;
    localparam [31:0] TGT_BASE   = 32'hF8001000;
    localparam [31:0] SLOT_TABLE = 32'hF8002000;

    localparam [15:0] CMD_STATUS = 16'h0000;
    localparam [15:0] CMD_RESET_ENTER = 16'h0010;
    localparam [15:0] CMD_RESET_EXIT  = 16'h0011;
    localparam [15:0] CMD_SLOT_WRITE  = 16'h0082;
    localparam [15:0] CMD_ALL_DONE    = 16'h008F;
    localparam [15:0] CMD_RTC         = 16'h0090;

    localparam [15:0] ST_BOOTING = 16'h0001;
    localparam [15:0] ST_SETUP   = 16'h0002;
    localparam [15:0] ST_RUNNING = 16'h0004;

    assign video_rgb_clock = clk_74a;
    assign video_rgb_clock_90 = ~clk_74a;

    reg [15:0] status;
    reg [31:0] host_param0;
    reg [31:0] host_param1;
    reg [31:0] host_param2;
    reg [31:0] host_param3;
    reg [31:0] host_status_word;
    reg [31:0] read_pipe;
    reg [15:0] boot_count;
    reg data_complete;
    reg rtc_seen;
    reg ready_ack;
    reg [31:0] setting0;
    reg [31:0] rom_write_count;
    reg [31:0] input_sample_count;

    reg [31:0] save_mem [0:16383];
    integer i;

    function automatic [31:0] ok_word(input [15:0] result);
        ok_word = 32'h4F4B0000 | {16'h0000, result};
    endfunction

    function automatic [31:0] cmd_word(input [15:0] command);
        cmd_word = 32'h636D0000 | {16'h0000, command};
    endfunction

    function automatic [31:0] decode_read(input [31:0] addr);
        begin
            if (addr == APF_BASE) begin
                decode_read = host_status_word;
            end else if (addr == TGT_BASE) begin
                decode_read = (data_complete && rtc_seen && !ready_ack) ? cmd_word(16'h0140) : 32'h00000000;
            end else if (addr == 32'h50000010) begin
                decode_read = setting0;
            end else if (addr == 32'h50000020) begin
                decode_read = rom_write_count;
            end else if (addr == 32'h50000024) begin
                decode_read = input_sample_count;
            end else if (addr[31:16] == 16'h2000) begin
                decode_read = save_mem[addr[15:2]];
            end else begin
                decode_read = 32'h00000000;
            end
        end
    endfunction

    initial begin
        bridge_rd_data = 32'h00000000;
        read_pipe = 32'h00000000;
        status = ST_BOOTING;
        host_param0 = 32'h0;
        host_param1 = 32'h0;
        host_param2 = 32'h0;
        host_param3 = 32'h0;
        host_status_word = ok_word(ST_BOOTING);
        boot_count = 16'h0;
        data_complete = 1'b0;
        rtc_seen = 1'b0;
        ready_ack = 1'b0;
        setting0 = 32'h0;
        rom_write_count = 32'h0;
        input_sample_count = 32'h0;
        video_de = 1'b0;
        video_skip = 1'b0;
        video_vs = 1'b0;
        video_hs = 1'b0;
        video_rgb = 24'h000000;
        audio_mclk = 1'b0;
        audio_lrck = 1'b0;
        audio_dac = 1'b0;
        for (i = 0; i < 16384; i = i + 1) save_mem[i] = 32'h00000000;
    end

    wire [15:0] host_cmd = bridge_wr_data[15:0];

    always @(posedge clk_74a) begin
        if (boot_count < 16'd64) begin
            boot_count <= boot_count + 1'b1;
        end else if (status == ST_BOOTING) begin
            status <= ST_SETUP;
            host_status_word <= ok_word(ST_SETUP);
        end

        if (cont1_key[13:0] != 14'h0000) input_sample_count <= input_sample_count + 1'b1;

        if (bridge_wr) begin
            if (bridge_addr == APF_BASE + 32'h0020) host_param0 <= bridge_wr_data;
            else if (bridge_addr == APF_BASE + 32'h0024) host_param1 <= bridge_wr_data;
            else if (bridge_addr == APF_BASE + 32'h0028) host_param2 <= bridge_wr_data;
            else if (bridge_addr == APF_BASE + 32'h002C) host_param3 <= bridge_wr_data;
            else if (bridge_addr == APF_BASE) begin
                if (bridge_wr_data[31:16] == 16'h434D) begin
                    case (host_cmd)
                        CMD_STATUS: host_status_word <= ok_word(status);
                        CMD_RESET_ENTER: begin
                            status <= ST_SETUP;
                            host_status_word <= ok_word(16'h0000);
                        end
                        CMD_RESET_EXIT: begin
                            status <= ST_RUNNING;
                            host_status_word <= ok_word(16'h0000);
                        end
                        CMD_SLOT_WRITE: host_status_word <= ok_word(16'h0000);
                        CMD_ALL_DONE: begin
                            data_complete <= 1'b1;
                            host_status_word <= ok_word(16'h0000);
                        end
                        CMD_RTC: begin
                            rtc_seen <= 1'b1;
                            host_status_word <= ok_word(16'h0000);
                        end
                        default: host_status_word <= ok_word(16'h0000);
                    endcase
                end
            end else if (bridge_addr == TGT_BASE) begin
                if (bridge_wr_data[31:16] == 16'h6F6B || bridge_wr_data[31:16] == 16'h4F4B) ready_ack <= 1'b1;
            end else if (bridge_addr[31:24] == 8'h10) begin
                rom_write_count <= rom_write_count + 32'd4;
            end else if (bridge_addr[31:16] == 16'h2000) begin
                save_mem[bridge_addr[15:2]] <= bridge_wr_data;
            end else if (bridge_addr == 32'h50000010) begin
                setting0 <= bridge_wr_data;
            end else if (bridge_addr >= SLOT_TABLE && bridge_addr < SLOT_TABLE + 32'd256) begin
                // Slot table writes are accepted but do not affect this mock core.
            end
        end

        if (bridge_rd) read_pipe <= decode_read(bridge_addr);
        bridge_rd_data <= read_pipe;
    end

    localparam [9:0] ACTIVE_W = 10'd256;
    localparam [9:0] ACTIVE_H = 10'd224;
    localparam [9:0] TOTAL_W = 10'd320;
    localparam [9:0] TOTAL_H = 10'd240;
    reg [9:0] px;
    reg [9:0] py;
    wire active_next = (px >= 10'd6) && (px < (10'd6 + ACTIVE_W)) && (py < ACTIVE_H);

    initial begin
        px = 10'd0;
        py = 10'd0;
    end

    always @(posedge clk_74a) begin
        video_vs <= (px == 10'd0 && py == 10'd0);
        video_hs <= (px == 10'd4);
        video_de <= active_next;
        video_skip <= 1'b0;
        if (active_next) begin
            video_rgb <= {px[7:0], py[7:0], (px[7:0] ^ py[7:0])};
        end else begin
            video_rgb <= 24'h000000;
        end

        if (px == (TOTAL_W - 10'd1)) begin
            px <= 10'd0;
            if (py == (TOTAL_H - 10'd1)) py <= 10'd0;
            else py <= py + 1'b1;
        end else begin
            px <= px + 1'b1;
        end
    end

    reg [5:0] aud_bit;
    reg [15:0] aud_sample_l;
    reg [15:0] aud_sample_r;
    reg [15:0] aud_shift;
    initial begin
        aud_bit = 6'd0;
        aud_sample_l = 16'sd1024;
        aud_sample_r = -16'sd1024;
        aud_shift = 16'd0;
    end

    always @(posedge clk_74b) begin
        audio_mclk <= ~audio_mclk;
        if (!audio_mclk) begin
            if (aud_bit == 6'd0) begin
                aud_shift <= audio_lrck ? aud_sample_r : aud_sample_l;
                aud_sample_l <= aud_sample_l + 16'sd17;
                aud_sample_r <= aud_sample_r - 16'sd13;
            end else begin
                aud_shift <= {aud_shift[14:0], 1'b0};
            end
            audio_dac <= aud_shift[15];
            aud_bit <= aud_bit + 1'b1;
            if (aud_bit == 6'd31) begin
                aud_bit <= 6'd0;
                audio_lrck <= ~audio_lrck;
            end
        end
    end
endmodule
