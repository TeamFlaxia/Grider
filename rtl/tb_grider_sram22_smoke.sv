`timescale 1ns/1ps

module tb_grider_sram22_smoke;
    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst_n = 1'b0;
    reg instruction_valid = 1'b0;
    wire instruction_ready;
    wire instruction_done;
    reg host_write_enable = 1'b0;
    reg host_read_enable = 1'b0;
    wire host_access_ready;
    wire host_read_valid;
    reg host_memory_select = 1'b0;
    reg [7:0] host_lane = 8'd0;
    reg [3:0] host_index = 4'd0;
    reg [127:0] host_write_data = 128'd0;
    reg [3:0] host_write_type = 4'd4;
    wire [127:0] host_read_data;
    wire [3:0] host_read_type;
    reg [4:0] opcode = 5'd0;
    reg [3:0] dst = 4'd0;
    reg [3:0] src_a = 4'd0;
    reg [3:0] src_b = 4'd0;
    reg [3:0] src_c = 4'd0;
    reg [127:0] immediate = 128'd0;
    reg [3:0] dtype = 4'd4;
    reg lane_mask = 1'b1;

    grider_tile #(.TILE_W(1), .TILE_H(1), .LANES(1)) dut (
        .clk(clk), .rst_n(rst_n),
        .instruction_valid(instruction_valid), .instruction_ready(instruction_ready),
        .instruction_done(instruction_done),
        .host_write_enable(host_write_enable), .host_read_enable(host_read_enable),
        .host_access_ready(host_access_ready), .host_read_valid(host_read_valid),
        .host_memory_select(host_memory_select), .host_lane(host_lane),
        .host_index(host_index), .host_write_data(host_write_data),
        .host_write_type(host_write_type), .host_read_data(host_read_data),
        .host_read_type(host_read_type),
        .halo_north(132'b0), .halo_south(132'b0), .halo_east(132'b0), .halo_west(132'b0),
        .halo_north_valid(1'b0), .halo_south_valid(1'b0),
        .halo_east_valid(1'b0), .halo_west_valid(1'b0),
        .halo_north_east(132'b0), .halo_south_east(132'b0),
        .halo_south_west(132'b0), .halo_north_west(132'b0),
        .halo_north_east_valid(1'b0), .halo_south_east_valid(1'b0),
        .halo_south_west_valid(1'b0), .halo_north_west_valid(1'b0),
        .opcode(opcode), .dst(dst), .src_a(src_a), .src_b(src_b), .src_c(src_c),
        .immediate(immediate), .dtype(dtype), .lane_mask(lane_mask)
    );

    task automatic host_write(input bit memory_select, input [3:0] index,
                              input [127:0] data);
        begin
            @(negedge clk);
            host_memory_select = memory_select;
            host_index = index;
            host_write_data = data;
            host_write_type = 4'd4;
            host_read_enable = 1'b0;
            host_write_enable = 1'b1;
            if (host_access_ready !== 1'b1)
                $fatal(1, "host write was not ready");
            @(posedge clk); #1;
            host_write_enable = 1'b0;
        end
    endtask

    task automatic host_read(input bit memory_select, input [3:0] index,
                             input [127:0] expected);
        begin
            @(negedge clk);
            host_memory_select = memory_select;
            host_index = index;
            host_read_enable = 1'b1;
            if (host_access_ready !== 1'b1)
                $fatal(1, "host read was not ready");
            @(posedge clk); #1;
            if (host_read_valid !== 1'b1)
                $fatal(1, "macro host read did not return valid");
            if ((host_read_data !== expected) || (host_read_type !== 4'd4))
                $fatal(1, "macro read mismatch: got %h type %h expected %h",
                       host_read_data, host_read_type, expected);
            host_read_enable = 1'b0;
        end
    endtask

    task automatic run_instruction(input [4:0] op, input [3:0] destination,
                                   input [3:0] source, input [127:0] imm);
        integer timeout_cycles;
        begin
            @(negedge clk);
            opcode = op;
            dst = destination;
            src_a = source;
            immediate = imm;
            dtype = 4'd4;
            instruction_valid = 1'b1;
            if (instruction_ready !== 1'b1)
                $fatal(1, "instruction was not ready");
            @(posedge clk); #1;
            instruction_valid = 1'b0;
            timeout_cycles = 0;
            while (instruction_done !== 1'b1) begin
                @(posedge clk); #1;
                timeout_cycles = timeout_cycles + 1;
                if (timeout_cycles > 8)
                    $fatal(1, "macro instruction did not retire");
            end
        end
    endtask

    initial begin
        repeat (2) @(posedge clk);
        @(negedge clk); rst_n = 1'b1; #1;
        host_read(1'b0, 4'd0, 128'd0);
        host_read(1'b1, 4'd0, 128'd0);
        host_write(1'b0, 4'd0, 128'd5);
        host_read(1'b0, 4'd0, 128'd5);
        run_instruction(5'd2, 4'd1, 4'd0, 128'd9); // MOVI r1, 9
        host_read(1'b0, 4'd1, 128'd9);
        run_instruction(5'd17, 4'd0, 4'd1, 128'd0); // STORE r1 -> SRAM[0]
        host_read(1'b1, 4'd0, 128'd9);
        run_instruction(5'd16, 4'd2, 4'd0, 128'd0); // LOAD r2 <- SRAM[0]
        host_read(1'b0, 4'd2, 128'd9);
        $display("SRAM22 tile smoke test passed");
        $finish;
    end
endmodule
