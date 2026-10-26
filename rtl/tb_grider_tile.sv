`timescale 1ns/1ps
module tb_grider_tile;
    localparam integer LANES = 256;
    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst_n = 1'b0;
    reg instruction_valid = 1'b0;
    wire instruction_ready;
    wire instruction_done;
    reg host_write_enable = 1'b0;
    reg host_memory_select = 1'b0;
    reg [7:0] host_lane = '0;
    reg [3:0] host_index = '0;
    reg [127:0] host_write_data = '0;
    reg [3:0] host_write_type = '0;
    wire [127:0] host_read_data;
    wire [3:0] host_read_type;
    reg [16*132-1:0] halo_north = '0;
    reg [16*132-1:0] halo_south = '0;
    reg [16*132-1:0] halo_east = '0;
    reg [16*132-1:0] halo_west = '0;
    reg [15:0] halo_north_valid = '0;
    reg [15:0] halo_south_valid = '0;
    reg [15:0] halo_east_valid = '0;
    reg [15:0] halo_west_valid = '0;
    reg [131:0] halo_north_east = '0;
    reg [131:0] halo_south_east = '0;
    reg [131:0] halo_south_west = '0;
    reg [131:0] halo_north_west = '0;
    reg halo_north_east_valid = 1'b0;
    reg halo_south_east_valid = 1'b0;
    reg halo_south_west_valid = 1'b0;
    reg halo_north_west_valid = 1'b0;
    wire [16*132-1:0] edge_north;
    wire [16*132-1:0] edge_south;
    wire [16*132-1:0] edge_east;
    wire [16*132-1:0] edge_west;
    wire [131:0] edge_north_east;
    wire [131:0] edge_south_east;
    wire [131:0] edge_south_west;
    wire [131:0] edge_north_west;
    reg [4:0] opcode = '0;
    reg [3:0] dst = '0;
    reg [3:0] src_a = '0;
    reg [3:0] src_b = '0;
    reg [3:0] src_c = '0;
    reg [127:0] immediate = '0;
    reg [3:0] dtype = '0;
    reg [LANES-1:0] lane_mask = '1;

    grider_tile dut (.*);

    task automatic host_write(input bit is_sram, input integer lane,
                              input integer index, input logic [127:0] data,
                              input logic [3:0] tag);
        begin
            @(negedge clk);
            host_write_enable = 1'b1;
            host_memory_select = is_sram;
            host_lane = lane[7:0];
            host_index = index[3:0];
            host_write_data = data;
            host_write_type = tag;
            @(posedge clk); #1;
            host_write_enable = 1'b0;
        end
    endtask

    task automatic issue(input integer op, input integer d,
                         input integer a, input integer b, input integer c,
                         input logic [127:0] imm, input logic [3:0] tag,
                         input logic [LANES-1:0] mask);
        begin
            @(negedge clk);
            opcode = op[4:0]; dst = d[3:0]; src_a = a[3:0];
            src_b = b[3:0]; src_c = c[3:0]; immediate = imm;
            dtype = tag; lane_mask = mask; instruction_valid = 1'b1;
            @(posedge clk); #1;
            if (!instruction_done) $fatal(1, "instruction did not complete");
            instruction_valid = 1'b0;
        end
    endtask

    integer fd;
    integer rc;
    integer op;
    integer d;
    integer a;
    integer b;
    integer c;
    integer lane;
    integer index;
    reg [7:0] kind;
    reg [127:0] data;
    reg [127:0] imm;
    reg [255:0] mask;
    reg [3:0] tag;
    reg [3:0] tag_hex;
    reg [3:0] op_tag;
    reg [3:0] d4;
    reg [3:0] a4;
    reg [3:0] b4;
    reg [3:0] c4;
    reg [4:0] op5;
    string stim_path;
    integer r;
    integer word_index;

    initial begin
        host_memory_select = 1'b0;
        host_lane = '0;
        host_index = '0;
        repeat (2) @(posedge clk);
        @(negedge clk); rst_n = 1'b1;

        if (!$value$plusargs("STIM=%s", stim_path)) $fatal(1, "missing +STIM path");
        fd = $fopen(stim_path, "r");
        if (fd == 0) $fatal(1, "cannot open stimulus file");
        while (!$feof(fd)) begin
            rc = $fscanf(fd, "%s", kind);
            if (rc == 1) begin
                if (kind == "R" || kind == "S") begin
                    rc = $fscanf(fd, "%d %d %h %h\n", lane, index, data, tag_hex);
                    if (rc != 4) $fatal(1, "bad register/SRAM stimulus");
                    host_write_enable = 1'b0;
                    host_write(kind == "S", lane, index, data, tag_hex);
                end else if (kind == "I") begin
                    rc = $fscanf(fd, "%d %d %d %d %d %h %h %h\n",
                                 op, d, a, b, c, imm, tag_hex, mask);
                    if (rc != 8) $fatal(1, "bad instruction stimulus");
                    issue(op, d, a, b, c, imm, tag_hex, mask);
                end else begin
                    $fatal(1, "unknown stimulus record %s", kind);
                end
            end
        end
        $fclose(fd);

        for (lane = 0; lane < LANES; lane = lane + 1) begin
            for (r = 0; r < 16; r = r + 1) begin
                host_memory_select = 1'b0; host_lane = lane[7:0]; host_index = r[3:0]; #1;
                $display("R %0d %0d %032h %01h", lane, r, host_read_data, host_read_type);
                host_memory_select = 1'b1; #1;
                $display("S %0d %0d %032h %01h", lane, r, host_read_data, host_read_type);
            end
        end
        $finish;
    end
endmodule
