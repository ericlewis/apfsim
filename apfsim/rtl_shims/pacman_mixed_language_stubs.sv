module pacman_statemanager #(
    parameter integer Softmap_SaveState_ADDR = 0
) (
    input  wire        clk,
    input  wire        reset,
    input  wire        save,
    input  wire        load,
    input  wire        vsync,
    output reg         request_savestate,
    output reg         request_loadstate,
    output wire [31:0] request_address,
    input  wire        request_busy
);
    assign request_address = 32'd0;
    always @(posedge clk) begin
        if (reset) begin
            request_savestate <= 1'b0;
            request_loadstate <= 1'b0;
        end else begin
            request_savestate <= save;
            request_loadstate <= load;
        end
    end
endmodule

module pacman_savestates (
    input  wire        clk,
    input  wire        reset_in,
    output reg         reset_out,
    output reg         load_done,
    input  wire        save,
    input  wire        load,
    input  wire [31:0] savestate_address,
    output wire        savestate_busy,
    output wire [63:0] BUS_Din,
    output wire [9:0]  BUS_Adr,
    output wire        BUS_wren,
    output wire        BUS_rst,
    input  wire [63:0] BUS_Dout,
    output reg         loading_savestate,
    output reg         saving_savestate,
    output reg         sleep_savestate,
    input  wire        clock_ena_in,
    output wire [11:0] Save_RAMAddr,
    output wire        Save_RAMWrEn,
    output wire        Save_RAMRdEn,
    output wire [7:0]  Save_RAMWriteData,
    input  wire [7:0]  Save_RAMReadData,
    input  wire [63:0] bus_out_Din,
    output wire [63:0] bus_out_Dout,
    output wire [25:0] bus_out_Adr,
    output wire        bus_out_rnw,
    output wire        bus_out_ena,
    output wire [7:0]  bus_out_be,
    input  wire        bus_out_done
);
    assign savestate_busy = 1'b0;
    assign BUS_Din = 64'd0;
    assign BUS_Adr = 10'd0;
    assign BUS_wren = 1'b0;
    assign BUS_rst = reset_in;
    assign Save_RAMAddr = 12'd0;
    assign Save_RAMWrEn = 1'b0;
    assign Save_RAMRdEn = 1'b0;
    assign Save_RAMWriteData = 8'd0;
    assign bus_out_Dout = 64'd0;
    assign bus_out_Adr = 26'd0;
    assign bus_out_rnw = 1'b1;
    assign bus_out_ena = 1'b0;
    assign bus_out_be = 8'hFF;

    always @(posedge clk) begin
        reset_out <= reset_in;
        load_done <= load;
        loading_savestate <= load;
        saving_savestate <= save;
        sleep_savestate <= save | load;
    end
endmodule

module pacman (
    output reg  [2:0]  O_VIDEO_R,
    output reg  [2:0]  O_VIDEO_G,
    output reg  [1:0]  O_VIDEO_B,
    output reg         O_HSYNC,
    output reg         O_VSYNC,
    output reg         O_HBLANK,
    output reg         O_VBLANK,
    output reg  [9:0]  O_AUDIO,
    input  wire [7:0]  in0,
    input  wire [7:0]  in1,
    input  wire [7:0]  dipsw1,
    input  wire [7:0]  dipsw2,
    input  wire        mod_plus,
    input  wire        mod_jmpst,
    input  wire        mod_bird,
    input  wire        mod_mrtnt,
    input  wire        mod_ms,
    input  wire        mod_woodp,
    input  wire        mod_eeek,
    input  wire        mod_glob,
    input  wire        mod_alib,
    input  wire        mod_ponp,
    input  wire        mod_van,
    input  wire        mod_dshop,
    input  wire        mod_club,
    input  wire        flip_screen,
    input  wire [2:0]  h_offset,
    input  wire [2:0]  v_offset,
    input  wire [15:0] dn_addr,
    input  wire [7:0]  dn_data,
    input  wire        dn_wr,
    input  wire        pause,
    input  wire [11:0] hs_address,
    input  wire [7:0]  hs_data_in,
    output reg  [7:0]  hs_data_out,
    input  wire        hs_write_enable,
    input  wire        hs_access_read,
    input  wire        hs_access_write,
    input  wire [63:0] SaveStateBus_Din,
    input  wire [9:0]  SaveStateBus_Adr,
    input  wire        SaveStateBus_wren,
    input  wire        SaveStateBus_rst,
    output wire [63:0] SaveStateBus_Dout,
    input  wire        reset_ss,
    input  wire        RESET,
    input  wire        CLK,
    input  wire        ENA_6,
    input  wire        ENA_4,
    input  wire        ENA_1M79
);
    localparam integer ACTIVE_W = 288;
    localparam integer ACTIVE_H = 224;
    localparam integer TOTAL_W = 360;
    localparam integer TOTAL_H = 262;
    integer x;
    integer y;
    reg [7:0] hs_ram [0:4095];

    assign SaveStateBus_Dout = 64'd0;

    initial begin
        O_VIDEO_R = 3'd0;
        O_VIDEO_G = 3'd0;
        O_VIDEO_B = 2'd0;
        O_HSYNC = 1'b0;
        O_VSYNC = 1'b0;
        O_HBLANK = 1'b1;
        O_VBLANK = 1'b1;
        O_AUDIO = 10'd0;
        hs_data_out = 8'd0;
        x = 0;
        y = 0;
    end

    always @(posedge CLK) begin
        if (RESET || reset_ss) begin
            x <= 0;
            y <= 0;
            O_HSYNC <= 1'b0;
            O_VSYNC <= 1'b0;
            O_HBLANK <= 1'b1;
            O_VBLANK <= 1'b1;
            O_AUDIO <= 10'd0;
        end else if (ENA_6) begin
            O_HSYNC <= (x < 8);
            O_VSYNC <= (y == 0 && x < 32);
            O_HBLANK <= (x >= ACTIVE_W);
            O_VBLANK <= (y >= ACTIVE_H);
            if (x < ACTIVE_W && y < ACTIVE_H) begin
                O_VIDEO_R <= x[5:3] ^ {2'b00, in0[0]};
                O_VIDEO_G <= y[5:3] ^ {2'b00, in0[5]};
                O_VIDEO_B <= x[4:3] ^ y[4:3];
            end else begin
                O_VIDEO_R <= 3'd0;
                O_VIDEO_G <= 3'd0;
                O_VIDEO_B <= 2'd0;
            end
            O_AUDIO <= O_AUDIO + 10'd3 + {9'd0, ~in1[5]};
            if (x == TOTAL_W - 1) begin
                x <= 0;
                if (y == TOTAL_H - 1) y <= 0;
                else y <= y + 1;
            end else begin
                x <= x + 1;
            end
        end

        if (hs_write_enable || hs_access_write) hs_ram[hs_address] <= hs_data_in;
        if (hs_access_read) hs_data_out <= hs_ram[hs_address];
    end
endmodule
