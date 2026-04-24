// Simulation-friendly replacement for common Quartus mf_pllbase-generated PLL wrappers.
// It intentionally models observable behavior only: deterministic derived clocks and lock.
module mf_pllbase #(
    parameter integer DIVIDE_0 = 1,
    parameter integer DIVIDE_1 = 1,
    parameter integer DIVIDE_2 = 8,
    parameter integer DIVIDE_3 = 8,
    parameter integer DIVIDE_4 = 8,
    parameter integer LOCK_AFTER_CYCLES = 1024
) (
    input  wire refclk,
    input  wire rst,
    output reg  outclk_0,
    output reg  outclk_1,
    output reg  outclk_2,
    output reg  outclk_3,
    output reg  outclk_4,
    output reg  locked
);
    integer lock_count;
    integer cnt0;
    integer cnt1;
    integer cnt2;
    integer cnt3;
    integer cnt4;

    initial begin
        outclk_0 = 1'b0;
        outclk_1 = 1'b0;
        outclk_2 = 1'b0;
        outclk_3 = 1'b0;
        outclk_4 = 1'b0;
        locked = 1'b0;
        lock_count = 0;
        cnt0 = 0;
        cnt1 = 0;
        cnt2 = 0;
        cnt3 = 0;
        cnt4 = 0;
    end

    always @(posedge refclk or posedge rst) begin
        if (rst) begin
            outclk_0 <= 1'b0;
            outclk_1 <= 1'b0;
            outclk_2 <= 1'b0;
            outclk_3 <= 1'b0;
            outclk_4 <= 1'b0;
            locked <= 1'b0;
            lock_count <= 0;
            cnt0 <= 0;
            cnt1 <= 0;
            cnt2 <= 0;
            cnt3 <= 0;
            cnt4 <= 0;
        end else begin
            if (lock_count >= LOCK_AFTER_CYCLES) locked <= 1'b1;
            else lock_count <= lock_count + 1;

            cnt0 <= (cnt0 + 1) % (DIVIDE_0 < 1 ? 1 : DIVIDE_0);
            cnt1 <= (cnt1 + 1) % (DIVIDE_1 < 1 ? 1 : DIVIDE_1);
            cnt2 <= (cnt2 + 1) % (DIVIDE_2 < 1 ? 1 : DIVIDE_2);
            cnt3 <= (cnt3 + 1) % (DIVIDE_3 < 1 ? 1 : DIVIDE_3);
            cnt4 <= (cnt4 + 1) % (DIVIDE_4 < 1 ? 1 : DIVIDE_4);
            if (cnt0 == 0) outclk_0 <= ~outclk_0;
            if (cnt1 == 0) outclk_1 <= ~outclk_1;
            if (cnt2 == 0) outclk_2 <= ~outclk_2;
            if (cnt3 == 0) outclk_3 <= ~outclk_3;
            if (cnt4 == 0) outclk_4 <= ~outclk_4;
        end
    end
endmodule
