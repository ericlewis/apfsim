// Optional sim-only PCM-to-I2S source/probe for cores that expose signed 16-bit stereo PCM.
module sound_i2s_probe (
    input  wire        clk,
    input  wire signed [15:0] sample_l,
    input  wire signed [15:0] sample_r,
    output reg         audio_mclk,
    output reg         audio_lrck,
    output reg         audio_dac
);
    reg [5:0] bit_count;
    reg [15:0] shifter;

    initial begin
        audio_mclk = 1'b0;
        audio_lrck = 1'b0;
        audio_dac = 1'b0;
        bit_count = 6'd0;
        shifter = 16'd0;
    end

    always @(posedge clk) begin
        audio_mclk <= ~audio_mclk;
        if (!audio_mclk) begin
            if (bit_count == 0) begin
                shifter <= audio_lrck ? sample_r : sample_l;
            end else begin
                shifter <= {shifter[14:0], 1'b0};
            end
            audio_dac <= shifter[15];
            bit_count <= bit_count + 1'b1;
            if (bit_count == 6'd31) begin
                bit_count <= 6'd0;
                audio_lrck <= ~audio_lrck;
            end
        end
    end
endmodule
