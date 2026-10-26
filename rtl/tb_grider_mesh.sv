`timescale 1ns/1ps
module tb_grider_mesh;
    localparam integer TILES_X = 2;
    localparam integer TILES_Y = 2;
    localparam integer TILE_W = 16;
    localparam integer TILE_H = 16;
    localparam integer LANES = TILE_W * TILE_H;

    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst_n = 1'b0;
    reg instruction_valid = 1'b0;
    wire instruction_ready;
    wire instruction_done;
    reg [4:0] opcode = '0;
    reg [3:0] dst = '0;
    reg [3:0] src_a = '0;
    reg [3:0] src_b = '0;
    reg [3:0] src_c = '0;
    reg [127:0] immediate = '0;
    reg [3:0] dtype = '0;
    reg [LANES-1:0] lane_mask = '1;
    reg host_write_enable = 1'b0;
    reg host_memory_select = 1'b0;
    reg [7:0] host_tile_x = '0;
    reg [7:0] host_tile_y = '0;
    reg [7:0] host_lane = '0;
    reg [3:0] host_index = '0;
    reg [127:0] host_write_data = '0;
    reg [3:0] host_write_type = '0;
    wire [127:0] host_read_data;
    wire [3:0] host_read_type;

    grider_mesh #(.TILES_X(TILES_X), .TILES_Y(TILES_Y)) dut (.*);

    task automatic host_write(input integer tx, input integer ty,
                              input integer lane, input integer index,
                              input logic [127:0] data, input logic [3:0] tag);
        begin
            @(negedge clk);
            host_write_enable = 1'b1;
            host_tile_x = tx[7:0]; host_tile_y = ty[7:0];
            host_memory_select = 1'b0;
            host_lane = lane[7:0]; host_index = index[3:0];
            host_write_data = data; host_write_type = tag;
            #1;
            if (instruction_ready !== 1'b0)
                $fatal(1, "mesh host write must deassert instruction_ready");
            @(posedge clk); #1;
            if (instruction_done !== 1'b0)
                $fatal(1, "mesh host write without an accepted instruction must leave done low");
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
            #1;
            if (instruction_ready !== 1'b1)
                $fatal(1, "mesh instruction was not ready before the accepting edge");
            @(posedge clk); #1;
            if (instruction_done !== 1'b1)
                $fatal(1, "accepted mesh instruction did not assert done");
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
    integer tx;
    integer ty;
    integer lane;
    integer index;
    integer reg_index;
    integer output_tx;
    integer output_ty;
    reg [7:0] kind;
    reg [127:0] data;
    reg [127:0] imm;
    reg [255:0] mask;
    reg [3:0] tag_hex;
    reg [127:0] saved_reg15_data [0:TILES_X*TILES_Y-1];
    reg [3:0] saved_reg15_type [0:TILES_X*TILES_Y-1];
    string stim_path;

    initial begin
        #1;
        if (instruction_ready !== 1'b0)
            $fatal(1, "mesh instruction_ready must be low during reset");
        repeat (2) @(posedge clk);
        #1;
        if (instruction_done !== 1'b0)
            $fatal(1, "mesh instruction_done must be low during reset");
        if (!$value$plusargs("STIM=%s", stim_path)) $fatal(1, "missing +STIM path");
        @(negedge clk); rst_n = 1'b1;
        #1;
        if (instruction_ready !== 1'b1 || instruction_done !== 1'b0)
            $fatal(1, "mesh reset release must leave the interface ready and idle");
    end

    initial begin
        wait (rst_n);
        fd = $fopen(stim_path, "r");
        if (fd == 0) $fatal(1, "cannot open stimulus file");
        while (!$feof(fd)) begin
            rc = $fscanf(fd, "%s", kind);
            if (rc == 1) begin
                if (kind == "R") begin
                    rc = $fscanf(fd, "%d %d %d %d %h %h\n", tx, ty, lane, index, data, tag_hex);
                    if (rc != 6) $fatal(1, "bad mesh register stimulus");
                    host_write(tx, ty, lane, index, data, tag_hex);
                end else if (kind == "I") begin
                    rc = $fscanf(fd, "%d %d %d %d %d %h %h %h\n",
                                 op, d, a, b, c, imm, tag_hex, mask);
                    if (rc != 8) $fatal(1, "bad mesh instruction stimulus");
                    issue(op, d, a, b, c, imm, tag_hex, mask);
                end else begin
                    $fatal(1, "unknown stimulus record %s", kind);
                end
            end
        end
        $fclose(fd);

        // Save lane 0/register 15 on every tile so the test can prove that a
        // blocked mesh instruction has no partial side effects, then restore it.
        for (output_ty = 0; output_ty < TILES_Y; output_ty = output_ty + 1) begin
            for (output_tx = 0; output_tx < TILES_X; output_tx = output_tx + 1) begin
                host_tile_x = output_tx; host_tile_y = output_ty;
                host_memory_select = 1'b0; host_lane = 0; host_index = 15;
                #0.1;
                saved_reg15_data[output_ty*TILES_X+output_tx] = host_read_data;
                saved_reg15_type[output_ty*TILES_X+output_tx] = host_read_type;
            end
        end

        @(negedge clk);
        host_write_enable = 1'b1; host_tile_x = 0; host_tile_y = 0;
        host_memory_select = 1'b0; host_lane = 0; host_index = 15;
        host_write_data = saved_reg15_data[0]; host_write_type = saved_reg15_type[0];
        opcode = 5'd2; dst = 4'd15; src_a = 0; src_b = 0; src_c = 0;
        immediate = 128'h1234; dtype = 4'h4;
        lane_mask = '0; lane_mask[0] = 1'b1;
        instruction_valid = 1'b1;
        #0.1;
        if (instruction_ready !== 1'b0)
            $fatal(1, "host write must deassert mesh instruction_ready");
        @(posedge clk); #0.1;
        if (instruction_done !== 1'b0)
            $fatal(1, "stalled mesh instruction must not assert done");

        // None of the other tiles may execute the broadcast while the mesh is
        // not ready, even though their individual tile ports are idle.
        for (output_ty = 0; output_ty < TILES_Y; output_ty = output_ty + 1) begin
            for (output_tx = 0; output_tx < TILES_X; output_tx = output_tx + 1) begin
                if ((output_tx != 0) || (output_ty != 0)) begin
                    host_tile_x = output_tx; host_tile_y = output_ty;
                    host_lane = 0; host_index = 15; #0.1;
                    if ((host_read_data !== saved_reg15_data[output_ty*TILES_X+output_tx]) ||
                        (host_read_type !== saved_reg15_type[output_ty*TILES_X+output_tx]))
                        $fatal(1, "blocked mesh instruction partially modified tile %0d,%0d",
                               output_tx, output_ty);
                end
            end
        end

        @(negedge clk);
        host_tile_x = 0; host_tile_y = 0; host_write_enable = 1'b0;
        #0.1;
        if (instruction_ready !== 1'b1)
            $fatal(1, "mesh instruction_ready must return after host write");
        @(posedge clk); #0.1;
        if (instruction_done !== 1'b1)
            $fatal(1, "held mesh instruction must complete after acceptance");

        for (output_ty = 0; output_ty < TILES_Y; output_ty = output_ty + 1) begin
            for (output_tx = 0; output_tx < TILES_X; output_tx = output_tx + 1) begin
                host_tile_x = output_tx; host_tile_y = output_ty;
                host_lane = 0; host_index = 15; #0.1;
                if ((host_read_data !== 128'h1234) || (host_read_type !== 4'h4))
                    $fatal(1, "accepted mesh instruction did not update tile %0d,%0d",
                           output_tx, output_ty);
            end
        end

        @(negedge clk);
        instruction_valid = 1'b0;
        @(posedge clk); #0.1;
        if (instruction_done !== 1'b0)
            $fatal(1, "mesh instruction_done must clear when no instruction is accepted");

        for (output_ty = 0; output_ty < TILES_Y; output_ty = output_ty + 1) begin
            for (output_tx = 0; output_tx < TILES_X; output_tx = output_tx + 1) begin
                host_write(output_tx, output_ty, 0, 15,
                           saved_reg15_data[output_ty*TILES_X+output_tx],
                           saved_reg15_type[output_ty*TILES_X+output_tx]);
            end
        end

        for (output_ty = 0; output_ty < TILES_Y; output_ty = output_ty + 1) begin
            for (output_tx = 0; output_tx < TILES_X; output_tx = output_tx + 1) begin
                host_tile_x = output_tx; host_tile_y = output_ty;
                for (lane = 0; lane < LANES; lane = lane + 1) begin
                    host_lane = lane[7:0];
                    for (reg_index = 0; reg_index <= 8; reg_index = reg_index + 1) begin
                        host_index = reg_index[3:0]; #1;
                        $display("R %0d %0d %0d %0d %032h %01h", output_tx, output_ty,
                                 lane, reg_index, host_read_data, host_read_type);
                    end
                end
            end
        end
        $finish;
    end
endmodule
