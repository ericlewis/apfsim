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
`ifdef APFSIM_MEMORY_COUNTER_TEST
    ,
    output wire [31:0] apfsim_sram_read_count,
    output wire [31:0] apfsim_sram_write_count,
    output wire        apfsim_sram_bus_contention_error,
    output wire        apfsim_sram_byte_enable_error
`endif
);
    localparam [31:0] APF_BASE   = 32'hF8000000;
    localparam [31:0] TGT_BASE   = 32'hF8001000;
    localparam [31:0] SLOT_TABLE = 32'hF8002000;

    localparam [15:0] CMD_STATUS = 16'h0000;
    localparam [15:0] CMD_RESET_ENTER = 16'h0010;
    localparam [15:0] CMD_RESET_EXIT  = 16'h0011;
    localparam [15:0] CMD_SLOT_WRITE  = 16'h0082;
    localparam [15:0] CMD_SLOT_UPDATE = 16'h008A;
    localparam [15:0] CMD_ALL_DONE    = 16'h008F;
    localparam [15:0] CMD_RTC         = 16'h0090;
    localparam [15:0] CMD_SSTATE      = 16'h00A0;
    localparam [15:0] CMD_MENU_STATE  = 16'h00B0;
    localparam [15:0] CMD_CART_ADAPT  = 16'h00B1;
    localparam [15:0] CMD_DOCK_STATE  = 16'h00B2;
    localparam [15:0] CMD_DISPLAY     = 16'h00B8;

`ifdef APFSIM_TARGET_COMMAND_SMOKE
    localparam [15:0] TCMD_READY      = 16'h0140;
    localparam [15:0] TCMD_DEBUG      = 16'h0152;
    localparam [15:0] TCMD_READ       = 16'h0180;
    localparam [15:0] TCMD_READ48     = 16'h0181;
    localparam [15:0] TCMD_WRITE      = 16'h0184;
    localparam [15:0] TCMD_WRITE48    = 16'h0185;
    localparam [15:0] TCMD_FLUSH      = 16'h0188;
    localparam [15:0] TCMD_FILENAME   = 16'h0190;
    localparam [15:0] TCMD_OPEN_FILE  = 16'h0192;
`endif

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
    reg [31:0] host_response0;
    reg [31:0] host_response1;
    reg [31:0] host_response2;
    reg [31:0] menu_state_last;
    reg [31:0] cart_notify_last;
    reg [31:0] docked_state_last;
    reg [31:0] display_mode_last;
    reg [31:0] data_update_count;
    reg [31:0] data_update_slot;
    reg [31:0] data_update_size;
    reg [31:0] savestate_query_count;
    reg [31:0] savestate_start_count;
    reg [3:0]  savestate_busy_count;
    reg        gameplay_latched;

`ifdef APFSIM_TARGET_COMMAND_SMOKE
    reg [3:0]  target_state;
    reg [7:0]  target_wait;
    reg [31:0] target_read_payload_count;
    reg [31:0] target_read_word0;
    reg [31:0] target_filename_write_count;
`endif

    reg [31:0] rom_mem [0:511];
    reg [31:0] save_mem [0:16383];
    integer i;

`ifdef APFSIM_EXTERNAL_SRAM_MODEL
    wire rom_bridge_region = bridge_addr[31:24] == 8'h10;
    wire [16:0] sram_addr = bridge_addr[18:2];
    wire [15:0] sram_lo_dq;
    wire [15:0] sram_hi_dq;
    wire [31:0] sram_read_word = {sram_hi_dq, sram_lo_dq};
    wire [15:0] sram_lo_write_data;
    wire [15:0] sram_hi_write_data;
    wire [31:0] sram_lo_read_count;
    wire [31:0] sram_lo_write_count;
    wire        sram_lo_bus_contention_error;
    wire        sram_lo_byte_enable_error;
    wire [31:0] sram_hi_read_count;
    wire [31:0] sram_hi_write_count;
    wire        sram_hi_bus_contention_error;
    wire        sram_hi_byte_enable_error;

`ifdef APFSIM_EXTERNAL_SRAM_CORRUPT_BYTE_LANE
    assign sram_lo_write_data = {bridge_wr_data[7:0], bridge_wr_data[15:8]};
`else
    assign sram_lo_write_data = bridge_wr_data[15:0];
`endif
    assign sram_hi_write_data = bridge_wr_data[31:16];
    assign sram_lo_dq = (bridge_wr && rom_bridge_region) ? sram_lo_write_data : 16'hZZZZ;
    assign sram_hi_dq = (bridge_wr && rom_bridge_region) ? sram_hi_write_data : 16'hZZZZ;

    apfsim_async_sram_16_model #(
        .ADDR_WIDTH(17)
    ) rom_sram_lo (
        .clk(clk_74a),
        .reset(1'b0),
        .ce_n(!rom_bridge_region),
        .oe_n(!(bridge_rd && rom_bridge_region)),
        .we_n(!(bridge_wr && rom_bridge_region)),
        .lb_n(1'b0),
        .ub_n(1'b0),
        .addr(sram_addr),
        .dq(sram_lo_dq),
        .read_count(sram_lo_read_count),
        .write_count(sram_lo_write_count),
        .bus_contention_error(sram_lo_bus_contention_error),
        .byte_enable_error(sram_lo_byte_enable_error)
    );

    apfsim_async_sram_16_model #(
        .ADDR_WIDTH(17)
    ) rom_sram_hi (
        .clk(clk_74a),
        .reset(1'b0),
        .ce_n(!rom_bridge_region),
        .oe_n(!(bridge_rd && rom_bridge_region)),
        .we_n(!(bridge_wr && rom_bridge_region)),
        .lb_n(1'b0),
        .ub_n(1'b0),
        .addr(sram_addr),
        .dq(sram_hi_dq),
        .read_count(sram_hi_read_count),
        .write_count(sram_hi_write_count),
        .bus_contention_error(sram_hi_bus_contention_error),
        .byte_enable_error(sram_hi_byte_enable_error)
    );
`endif

`ifdef APFSIM_MEMORY_COUNTER_TEST
`ifdef APFSIM_EXTERNAL_SRAM_MODEL
    assign apfsim_sram_read_count = sram_lo_read_count + sram_hi_read_count;
    assign apfsim_sram_write_count = sram_lo_write_count + sram_hi_write_count;
    assign apfsim_sram_bus_contention_error = sram_lo_bus_contention_error | sram_hi_bus_contention_error;
    assign apfsim_sram_byte_enable_error = sram_lo_byte_enable_error | sram_hi_byte_enable_error;
`else
    assign apfsim_sram_read_count = input_sample_count;
    assign apfsim_sram_write_count = rom_write_count;
    assign apfsim_sram_bus_contention_error = 1'b0;
    assign apfsim_sram_byte_enable_error = 1'b0;
`endif
`endif

    function automatic [31:0] ok_word(input [15:0] result);
        ok_word = 32'h4F4B0000 | {16'h0000, result};
    endfunction

    function automatic [31:0] cmd_word(input [15:0] command);
        cmd_word = 32'h636D0000 | {16'h0000, command};
    endfunction

`ifdef APFSIM_TARGET_COMMAND_SMOKE
    function automatic [31:0] target_status_word;
        begin
            case (target_state)
                4'd0: target_status_word = (data_complete && rtc_seen && !ready_ack) ? cmd_word(TCMD_READY) : 32'h00000000;
                4'd1: target_status_word = cmd_word(TCMD_READ);
                4'd2: target_status_word = cmd_word(TCMD_WRITE);
                4'd3: target_status_word = cmd_word(TCMD_FLUSH);
                4'd4: target_status_word = cmd_word(TCMD_FILENAME);
                4'd5: target_status_word = cmd_word(TCMD_DEBUG);
                4'd6: target_status_word = cmd_word(TCMD_READ48);
                4'd7: target_status_word = cmd_word(TCMD_WRITE48);
                4'd8: target_status_word = cmd_word(TCMD_OPEN_FILE);
                default: target_status_word = 32'h00000000;
            endcase
        end
    endfunction

    function automatic [31:0] target_param_word(input [1:0] index);
        begin
            target_param_word = 32'h00000000;
            case (target_state)
                4'd1: begin
                    case (index)
                        2'd0: target_param_word = 32'h00000001; // slot 1
                        2'd1: target_param_word = 32'h00000000; // offset
                        2'd2: target_param_word = 32'h30000000; // host writes ROM bytes here
                        2'd3: target_param_word = 32'h00000010; // length
                        default: target_param_word = 32'h00000000;
                    endcase
                end
                4'd2: begin
                    case (index)
                        2'd0: target_param_word = 32'h00000004; // slot 4 save/hi-score
                        2'd1: target_param_word = 32'h00000000; // offset
                        2'd2: target_param_word = 32'h30000100; // host reads save bytes here
                        2'd3: target_param_word = 32'h00000008; // length
                        default: target_param_word = 32'h00000000;
                    endcase
                end
                4'd3: begin
                    if (index == 2'd0) target_param_word = 32'h00000004;
                end
                4'd4: begin
                    case (index)
                        2'd0: target_param_word = 32'h00000001;
                        2'd1: target_param_word = 32'h30000200; // filename struct
                        default: target_param_word = 32'h00000000;
                    endcase
                end
                4'd5: begin
                    if (index == 2'd0) target_param_word = 32'h0C0DE539;
                end
                4'd6: begin
                    case (index)
                        2'd0: target_param_word = 32'h00000001; // upper offset 0, slot 1
                        2'd1: target_param_word = 32'h00000000; // lower offset
                        2'd2: target_param_word = 32'h30000300; // host writes ROM bytes here
                        2'd3: target_param_word = 32'h00000010; // length
                        default: target_param_word = 32'h00000000;
                    endcase
                end
                4'd7: begin
                    case (index)
                        2'd0: target_param_word = 32'h00000004; // upper offset 0, slot 4
                        2'd1: target_param_word = 32'h00000000; // lower offset
                        2'd2: target_param_word = 32'h30000400; // host reads save bytes here
                        2'd3: target_param_word = 32'h00000008; // length
                        default: target_param_word = 32'h00000000;
                    endcase
                end
                4'd8: begin
                    case (index)
                        2'd0: target_param_word = 32'h00000001; // slot 1
                        2'd1: target_param_word = 32'h30000500; // open_dataslot_file_t path
                        default: target_param_word = 32'h00000000;
                    endcase
                end
                default: target_param_word = 32'h00000000;
            endcase
        end
    endfunction
`endif

    function automatic [31:0] decode_read(input [31:0] addr);
        begin
            if (addr == APF_BASE) begin
                decode_read = host_status_word;
            end else if (addr == APF_BASE + 32'h0008) begin
                decode_read = APF_BASE + 32'h0040;
            end else if (addr == APF_BASE + 32'h0040) begin
                decode_read = host_response0;
            end else if (addr == APF_BASE + 32'h0044) begin
                decode_read = host_response1;
            end else if (addr == APF_BASE + 32'h0048) begin
                decode_read = host_response2;
            end else if (addr == TGT_BASE) begin
`ifdef APFSIM_TARGET_COMMAND_SMOKE
                decode_read = target_status_word();
`else
                decode_read = (data_complete && rtc_seen && !ready_ack) ? cmd_word(16'h0140) : 32'h00000000;
`endif
`ifdef APFSIM_TARGET_COMMAND_SMOKE
            end else if (addr == APF_BASE + 32'h1004) begin
                decode_read = APF_BASE + 32'h1020;
            end else if (addr == APF_BASE + 32'h1020) begin
                decode_read = target_param_word(2'd0);
            end else if (addr == APF_BASE + 32'h1024) begin
                decode_read = target_param_word(2'd1);
            end else if (addr == APF_BASE + 32'h1028) begin
                decode_read = target_param_word(2'd2);
            end else if (addr == APF_BASE + 32'h102C) begin
                decode_read = target_param_word(2'd3);
            end else if (addr == 32'h30000100) begin
                decode_read = 32'h11223344;
            end else if (addr == 32'h30000104) begin
                decode_read = 32'h55667788;
            end else if (addr == 32'h30000400) begin
                decode_read = 32'h99AABBCC;
            end else if (addr == 32'h30000404) begin
                decode_read = 32'hDDEEFF00;
            end else if (addr == 32'h30000500) begin
                decode_read = 32'h6D617865; // "exam"
            end else if (addr == 32'h30000504) begin
                decode_read = 32'h73656C70; // "ples"
            end else if (addr == 32'h30000508) begin
                decode_read = 32'h7373612F; // "/ass"
            end else if (addr == 32'h3000050C) begin
                decode_read = 32'h2F737465; // "ets/"
            end else if (addr == 32'h30000510) begin
                decode_read = 32'h6B636F6D; // "mock"
            end else if (addr == 32'h30000514) begin
                decode_read = 32'h6D6F722E; // ".rom"
            end else if (addr == 32'h50000030) begin
                decode_read = target_read_payload_count;
            end else if (addr == 32'h50000034) begin
                decode_read = target_read_word0;
            end else if (addr == 32'h50000038) begin
                decode_read = target_filename_write_count;
`endif
            end else if (addr == 32'h50000010) begin
                decode_read = setting0;
            end else if (addr == 32'h50000020) begin
                decode_read = rom_write_count;
            end else if (addr == 32'h50000024) begin
                decode_read = input_sample_count;
            end else if (addr == 32'h50000040) begin
                decode_read = menu_state_last;
            end else if (addr == 32'h50000044) begin
                decode_read = docked_state_last;
            end else if (addr == 32'h50000048) begin
                decode_read = display_mode_last;
            end else if (addr == 32'h5000004C) begin
                decode_read = data_update_count;
            end else if (addr == 32'h50000050) begin
                decode_read = data_update_slot;
            end else if (addr == 32'h50000054) begin
                decode_read = data_update_size;
            end else if (addr == 32'h50000058) begin
                decode_read = savestate_query_count;
            end else if (addr == 32'h5000005C) begin
                decode_read = savestate_start_count;
            end else if (addr == 32'h50000060) begin
                decode_read = cart_notify_last;
            end else if (addr[31:24] == 8'h10) begin
`ifdef APFSIM_EXTERNAL_SRAM_MODEL
                decode_read = sram_read_word;
`else
                decode_read = rom_mem[addr[10:2]];
`endif
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
        host_response0 = 32'h0;
        host_response1 = 32'h0;
        host_response2 = 32'h0;
        menu_state_last = 32'h0;
        cart_notify_last = 32'h0;
        docked_state_last = 32'h0;
        display_mode_last = 32'h0;
        data_update_count = 32'h0;
        data_update_slot = 32'h0;
        data_update_size = 32'h0;
        savestate_query_count = 32'h0;
        savestate_start_count = 32'h0;
        savestate_busy_count = 4'h0;
        gameplay_latched = 1'b0;
`ifdef APFSIM_TARGET_COMMAND_SMOKE
        target_state = 4'd0;
        target_wait = 8'd0;
        target_read_payload_count = 32'h0;
        target_read_word0 = 32'h0;
        target_filename_write_count = 32'h0;
`endif
        video_de = 1'b0;
        video_skip = 1'b0;
        video_vs = 1'b0;
        video_hs = 1'b0;
        video_rgb = 24'h000000;
        audio_mclk = 1'b0;
        audio_lrck = 1'b0;
        audio_dac = 1'b0;
        for (i = 0; i < 512; i = i + 1) rom_mem[i] = 32'h00000000;
        for (i = 0; i < 16384; i = i + 1) save_mem[i] = 32'h00000000;
        save_mem[32'h0400] = 32'hAABBCCDD;
        save_mem[32'h0401] = 32'h11223344;
        save_mem[32'h0402] = 32'h55667788;
        save_mem[32'h0403] = 32'h99A5A55A;
    end

    wire [15:0] host_cmd = bridge_wr_data[15:0];

    always @(posedge clk_74a) begin
        if (boot_count < 16'd64) begin
            boot_count <= boot_count + 1'b1;
        end else if (status == ST_BOOTING) begin
            status <= ST_SETUP;
            host_status_word <= ok_word(ST_SETUP);
        end

        if (cont1_key[15:0] != 16'h0000) begin
            input_sample_count <= input_sample_count + 1'b1;
            gameplay_latched <= 1'b1;
        end

`ifdef APFSIM_TARGET_COMMAND_SMOKE
        if (status == ST_RUNNING && ready_ack && target_state == 4'd0) begin
            if (target_wait == 8'd32) begin
                target_state <= 4'd1;
            end else begin
                target_wait <= target_wait + 1'b1;
            end
        end
`endif

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
                        CMD_SLOT_UPDATE: begin
                            data_update_count <= data_update_count + 32'd1;
                            data_update_slot <= host_param0;
                            data_update_size <= host_param1;
                            host_status_word <= ok_word(16'h0000);
                        end
                        CMD_ALL_DONE: begin
                            data_complete <= 1'b1;
                            host_status_word <= ok_word(16'h0000);
                        end
                        CMD_RTC: begin
                            rtc_seen <= 1'b1;
                            host_status_word <= ok_word(16'h0000);
                        end
                        CMD_SSTATE: begin
                            host_response0 <= 32'h00000001;
                            host_response1 <= 32'h20001000;
                            if (host_param0[0]) begin
                                savestate_start_count <= savestate_start_count + 32'd1;
                                savestate_busy_count <= 4'd3;
                                host_response2 <= 32'h00000000;
                                host_status_word <= ok_word(16'h0001);
                            end else if (savestate_busy_count != 4'd0) begin
                                savestate_query_count <= savestate_query_count + 32'd1;
                                savestate_busy_count <= savestate_busy_count - 1'b1;
                                host_response2 <= 32'h00000000;
                                host_status_word <= ok_word(16'h0001);
                            end else if (savestate_start_count != 32'h0) begin
                                savestate_query_count <= savestate_query_count + 32'd1;
                                host_response2 <= 32'h00000010;
                                host_status_word <= ok_word(16'h0002);
                            end else begin
                                savestate_query_count <= savestate_query_count + 32'd1;
                                host_response2 <= 32'h00000000;
                                host_status_word <= ok_word(16'h0000);
                            end
                        end
                        CMD_MENU_STATE: begin
                            menu_state_last <= host_param0;
                            host_status_word <= ok_word(16'h0000);
                        end
                        CMD_CART_ADAPT: begin
                            cart_notify_last <= host_param0;
                            host_status_word <= ok_word(16'h0000);
                        end
                        CMD_DOCK_STATE: begin
                            docked_state_last <= host_param0;
                            host_status_word <= ok_word(16'h0000);
                        end
                        CMD_DISPLAY: begin
                            display_mode_last <= host_param0;
                            host_response0 <= 32'h00000000;
                            host_status_word <= ok_word(16'h0000);
                        end
                        default: host_status_word <= ok_word(16'h0000);
                    endcase
                end
            end else if (bridge_addr == TGT_BASE) begin
                if (bridge_wr_data[31:16] == 16'h6F6B || bridge_wr_data[31:16] == 16'h4F4B) ready_ack <= 1'b1;
`ifdef APFSIM_TARGET_COMMAND_SMOKE
                if (bridge_wr_data[31:16] == 16'h6F6B || bridge_wr_data[31:16] == 16'h4F4B) begin
                    case (target_state)
                        4'd1: target_state <= 4'd2;
                        4'd2: target_state <= 4'd3;
                        4'd3: target_state <= 4'd4;
                        4'd4: target_state <= 4'd5;
                        4'd5: target_state <= 4'd6;
                        4'd6: target_state <= 4'd7;
                        4'd7: target_state <= 4'd8;
                        4'd8: target_state <= 4'd9;
                        default: target_state <= target_state;
                    endcase
                end
`endif
`ifdef APFSIM_TARGET_COMMAND_SMOKE
            end else if (bridge_addr >= 32'h30000000 && bridge_addr < 32'h30000010) begin
                target_read_payload_count <= target_read_payload_count + 32'd4;
                if (bridge_addr == 32'h30000000) target_read_word0 <= bridge_wr_data;
            end else if (bridge_addr >= 32'h30000300 && bridge_addr < 32'h30000310) begin
                target_read_payload_count <= target_read_payload_count + 32'd4;
            end else if (bridge_addr >= 32'h30000200 && bridge_addr < 32'h30000300) begin
                target_filename_write_count <= target_filename_write_count + 32'd4;
`endif
            end else if (bridge_addr[31:24] == 8'h10) begin
                rom_write_count <= rom_write_count + 32'd4;
`ifndef APFSIM_EXTERNAL_SRAM_MODEL
                rom_mem[bridge_addr[10:2]] <= bridge_wr_data;
`endif
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
            video_rgb <= {px[7:0] ^ {8{gameplay_latched}}, py[7:0], (px[7:0] ^ py[7:0])};
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
