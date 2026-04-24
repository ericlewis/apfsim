module core_top (
    input  wire        clk_74a,
    input  wire        clk_74b,

    output wire [23:0] video_rgb,
    output wire        video_rgb_clock,
    output wire        video_rgb_clock_90,
    output wire        video_de,
    output wire        video_skip,
    output wire        video_vs,
    output wire        video_hs,

    output wire        audio_mclk,
    input  wire        audio_adc,
    output wire        audio_dac,
    output wire        audio_lrck,

    output wire        bridge_endian_little,
    input  wire [31:0] bridge_addr,
    input  wire        bridge_rd,
    output wire [31:0] bridge_rd_data,
    input  wire        bridge_wr,
    input  wire [31:0] bridge_wr_data,

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
    input  wire [31:0] cont4_trig
);
    wire [7:0] cart_tran_bank2;
    wire [7:0] cart_tran_bank3;
    wire [7:0] cart_tran_bank1;
    wire [7:4] cart_tran_bank0;
    wire cart_tran_pin30;
    wire cart_tran_pin31;
    wire port_tran_si;
    wire port_tran_so;
    wire port_tran_sck;
    wire port_tran_sd;
    wire [21:16] cram0_a;
    wire [15:0] cram0_dq;
    wire [21:16] cram1_a;
    wire [15:0] cram1_dq;
    wire [12:0] dram_a;
    wire [1:0] dram_ba;
    wire [15:0] dram_dq;
    wire [1:0] dram_dqm;
    wire [16:0] sram_a;
    wire [15:0] sram_dq;
    wire aux_sda;

    basicassets_core_top_impl impl (
        .clk_74a(clk_74a),
        .clk_74b(clk_74b),
        .shell_reset_n(1'b1),

        .cart_tran_bank2(cart_tran_bank2),
        .cart_tran_bank2_dir(),
        .cart_tran_bank3(cart_tran_bank3),
        .cart_tran_bank3_dir(),
        .cart_tran_bank1(cart_tran_bank1),
        .cart_tran_bank1_dir(),
        .cart_tran_bank0(cart_tran_bank0),
        .cart_tran_bank0_dir(),
        .cart_tran_pin30(cart_tran_pin30),
        .cart_tran_pin30_dir(),
        .cart_pin30_pwroff_reset(),
        .cart_tran_pin31(cart_tran_pin31),
        .cart_tran_pin31_dir(),

        .port_ir_rx(1'b0),
        .port_ir_tx(),
        .port_ir_rx_disable(),
        .port_tran_si(port_tran_si),
        .port_tran_si_dir(),
        .port_tran_so(port_tran_so),
        .port_tran_so_dir(),
        .port_tran_sck(port_tran_sck),
        .port_tran_sck_dir(),
        .port_tran_sd(port_tran_sd),
        .port_tran_sd_dir(),

        .cram0_a(cram0_a),
        .cram0_dq(cram0_dq),
        .cram0_wait(1'b0),
        .cram0_clk(),
        .cram0_adv_n(),
        .cram0_cre(),
        .cram0_ce0_n(),
        .cram0_ce1_n(),
        .cram0_oe_n(),
        .cram0_we_n(),
        .cram0_ub_n(),
        .cram0_lb_n(),
        .cram1_a(cram1_a),
        .cram1_dq(cram1_dq),
        .cram1_wait(1'b0),
        .cram1_clk(),
        .cram1_adv_n(),
        .cram1_cre(),
        .cram1_ce0_n(),
        .cram1_ce1_n(),
        .cram1_oe_n(),
        .cram1_we_n(),
        .cram1_ub_n(),
        .cram1_lb_n(),

        .dram_a(dram_a),
        .dram_ba(dram_ba),
        .dram_dq(dram_dq),
        .dram_dqm(dram_dqm),
        .dram_clk(),
        .dram_cke(),
        .dram_ras_n(),
        .dram_cas_n(),
        .dram_we_n(),

        .sram_a(sram_a),
        .sram_dq(sram_dq),
        .sram_oe_n(),
        .sram_we_n(),
        .sram_ub_n(),
        .sram_lb_n(),
        .vblank(1'b0),
        .dbg_tx(),
        .dbg_rx(1'b1),
        .user1(),
        .user2(1'b0),
        .aux_sda(aux_sda),
        .aux_scl(),
        .vpll_feed(),

        .video_rgb(video_rgb),
        .video_rgb_clock(video_rgb_clock),
        .video_rgb_clock_90(video_rgb_clock_90),
        .video_de(video_de),
        .video_skip(video_skip),
        .video_vs(video_vs),
        .video_hs(video_hs),
        .audio_mclk(audio_mclk),
        .audio_adc(audio_adc),
        .audio_dac(audio_dac),
        .audio_lrck(audio_lrck),

        .bridge_endian_little(bridge_endian_little),
        .bridge_addr(bridge_addr),
        .bridge_rd(bridge_rd),
        .bridge_rd_data(bridge_rd_data),
        .bridge_wr(bridge_wr),
        .bridge_wr_data(bridge_wr_data),

        .cont1_key(cont1_key[15:0]),
        .cont2_key(cont2_key[15:0]),
        .cont3_key(cont3_key[15:0]),
        .cont4_key(cont4_key[15:0]),
        .cont1_joy(cont1_joy),
        .cont2_joy(cont2_joy),
        .cont3_joy(cont3_joy),
        .cont4_joy(cont4_joy),
        .cont1_trig(cont1_trig[15:0]),
        .cont2_trig(cont2_trig[15:0]),
        .cont3_trig(cont3_trig[15:0]),
        .cont4_trig(cont4_trig[15:0])
    );
endmodule
