module apf_video_asserts (
    input wire clk,
    input wire video_hs,
    input wire video_vs,
    input wire video_de,
    input wire [23:0] video_rgb
);
`ifdef VERILATOR
    reg hs_d;
    reg vs_d;
    initial begin
        hs_d = 1'b0;
        vs_d = 1'b0;
    end
    always @(posedge clk) begin
        if (hs_d && video_hs) $error("APF video_hs wider than one pixel clock");
        if (vs_d && video_vs) $error("APF video_vs wider than one pixel clock");
        if (!video_de && video_rgb != 24'h000000) $error("APF video_rgb nonzero while DE is low");
        hs_d <= video_hs;
        vs_d <= video_vs;
    end
`endif
endmodule
