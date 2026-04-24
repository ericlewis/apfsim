module dcfifo #(
    parameter integer lpm_width = 8,
    parameter integer lpm_numwords = 4,
    parameter integer lpm_widthu = 2,
    parameter string clocks_are_synchronized = "FALSE",
    parameter string intended_device_family = "Cyclone V",
    parameter string lpm_showahead = "OFF",
    parameter string lpm_type = "dcfifo",
    parameter string overflow_checking = "OFF",
    parameter integer rdsync_delaypipe = 5,
    parameter string underflow_checking = "OFF",
    parameter string use_eab = "OFF",
    parameter integer wrsync_delaypipe = 5
) (
    input  wire [lpm_width-1:0] data,
    input  wire rdclk,
    input  wire rdreq,
    input  wire wrclk,
    input  wire wrreq,
    output reg  [lpm_width-1:0] q,
    output wire rdempty,
    output wire wrempty,
    input  wire aclr,
    output wire [1:0] eccstatus,
    output wire rdfull,
    output wire [lpm_widthu-1:0] rdusedw,
    output wire wrfull,
    output wire [lpm_widthu-1:0] wrusedw
);
    localparam integer DEPTH = lpm_numwords < 2 ? 2 : lpm_numwords;
    reg [lpm_width-1:0] mem [0:DEPTH-1];
    integer wr_ptr;
    integer rd_ptr;
    integer count;

    assign rdempty = (count == 0);
    assign wrempty = (count == 0);
    assign rdfull = (count >= DEPTH);
    assign wrfull = (count >= DEPTH);
    assign rdusedw = count[lpm_widthu-1:0];
    assign wrusedw = count[lpm_widthu-1:0];
    assign eccstatus = 2'b00;

    initial begin
        q = '0;
        wr_ptr = 0;
        rd_ptr = 0;
        count = 0;
    end

    always @(posedge wrclk or posedge aclr) begin
        if (aclr) begin
            wr_ptr <= 0;
            count <= 0;
        end else if (wrreq && count < DEPTH) begin
            mem[wr_ptr] <= data;
            wr_ptr <= (wr_ptr + 1) % DEPTH;
            count <= count + 1;
        end
    end

    always @(posedge rdclk or posedge aclr) begin
        if (aclr) begin
            rd_ptr <= 0;
            q <= '0;
        end else if (rdreq && count > 0) begin
            q <= mem[rd_ptr];
            rd_ptr <= (rd_ptr + 1) % DEPTH;
            count <= count - 1;
        end
    end
endmodule

module dcfifo_mixed_widths #(
    parameter integer lpm_width = 32,
    parameter integer lpm_width_r = 64,
    parameter integer lpm_numwords = 4,
    parameter integer lpm_widthu = 2,
    parameter integer lpm_widthu_r = 2,
    parameter string intended_device_family = "Cyclone V",
    parameter string lpm_showahead = "OFF",
    parameter string lpm_type = "dcfifo_mixed_widths",
    parameter string overflow_checking = "OFF",
    parameter integer rdsync_delaypipe = 5,
    parameter string underflow_checking = "OFF",
    parameter string use_eab = "OFF",
    parameter integer wrsync_delaypipe = 5,
    parameter string write_aclr_synch = "OFF"
) (
    input  wire [lpm_width-1:0] data,
    input  wire rdclk,
    input  wire rdreq,
    input  wire wrclk,
    input  wire wrreq,
    output reg  [lpm_width_r-1:0] q,
    output wire rdempty,
    output wire wrempty,
    input  wire aclr,
    output wire [1:0] eccstatus,
    output wire rdfull,
    output wire [lpm_widthu_r-1:0] rdusedw,
    output wire wrfull,
    output wire [lpm_widthu-1:0] wrusedw
);
    localparam integer DEPTH = lpm_numwords < 2 ? 2 : lpm_numwords;
    localparam integer WIDTH_MAX = (lpm_width > lpm_width_r) ? lpm_width : lpm_width_r;
    reg [WIDTH_MAX-1:0] mem [0:DEPTH-1];
    integer wr_ptr;
    integer rd_ptr;
    integer count;

    assign rdempty = (count == 0);
    assign wrempty = (count == 0);
    assign rdfull = (count >= DEPTH);
    assign wrfull = (count >= DEPTH);
    assign rdusedw = count[lpm_widthu_r-1:0];
    assign wrusedw = count[lpm_widthu-1:0];
    assign eccstatus = 2'b00;

    initial begin
        q = '0;
        wr_ptr = 0;
        rd_ptr = 0;
        count = 0;
    end

    always @(posedge wrclk or posedge aclr) begin
        if (aclr) begin
            wr_ptr <= 0;
            count <= 0;
        end else if (wrreq && count < DEPTH) begin
            mem[wr_ptr] <= {{(WIDTH_MAX-lpm_width){1'b0}}, data};
            wr_ptr <= (wr_ptr + 1) % DEPTH;
            count <= count + 1;
        end
    end

    always @(posedge rdclk or posedge aclr) begin
        if (aclr) begin
            rd_ptr <= 0;
            q <= '0;
        end else if (rdreq && count > 0) begin
            q <= mem[rd_ptr][lpm_width_r-1:0];
            rd_ptr <= (rd_ptr + 1) % DEPTH;
            count <= count - 1;
        end
    end
endmodule
