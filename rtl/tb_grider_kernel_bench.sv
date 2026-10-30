# SPDX-License-Identifier: CERN-OHL-W-2.0

`timescale 1ns/1ps

module tb_grider_kernel_bench;
    localparam integer ITERATIONS = 16;

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
    reg [3:0] host_write_type = 4'd2;
    wire [127:0] host_read_data;
    wire [3:0] host_read_type;
    reg [4:0] opcode = 5'd0;
    reg [3:0] dst = 4'd0;
    reg [3:0] src_a = 4'd0;
    reg [3:0] src_b = 4'd0;
    reg [3:0] src_c = 4'd0;
    reg [127:0] immediate = 128'd0;
    reg [3:0] dtype = 4'd2;
    reg lane_mask = 1'b1;

    integer cycles;
    integer add_cycles;
    integer mul_cycles;
    integer mac_cycles;
    integer i;
    real add_mflops_20mhz;
    real mul_mflops_20mhz;
    real mac_mflops_20mhz;
    real add_mflops_at_sta;
    real mul_mflops_at_sta;
    real mac_mflops_at_sta;

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

    task automatic run_bf16(
        input [4:0] op,
        input [3:0] destination,
        input [3:0] source_a,
        input [3:0] source_b,
        input [127:0] imm,
        output integer elapsed_cycles
    );
        begin
            @(negedge clk);
            opcode = op;
            dst = destination;
            src_a = source_a;
            src_b = source_b;
            src_c = 4'd0;
            immediate = imm;
            dtype = 4'd2;
            lane_mask = 1'b1;
            instruction_valid = 1'b1;
            if (instruction_ready !== 1'b1)
                $fatal(1, "BF16 instruction was not ready");
            @(posedge clk); #1;
            instruction_valid = 1'b0;
            elapsed_cycles = 0;
            while (instruction_done !== 1'b1) begin
                @(posedge clk); #1;
                elapsed_cycles = elapsed_cycles + 1;
                if (elapsed_cycles > 8)
                    $fatal(1, "BF16 instruction did not retire");
            end
        end
    endtask

    task automatic check_bf16(input [3:0] index, input [15:0] expected);
        begin
            @(negedge clk);
            host_memory_select = 1'b0;
            host_lane = 8'd0;
            host_index = index;
            host_read_enable = 1'b1;
            if (host_access_ready !== 1'b1)
                $fatal(1, "BF16 host read was not ready");
            @(posedge clk); #1;
            if (host_read_valid !== 1'b1)
                $fatal(1, "BF16 host read did not return valid");
            if ((host_read_data[15:0] !== expected) || (host_read_type !== 4'd2))
                $fatal(1, "BF16 mismatch r%0d: got %h type %h expected %h",
                       index, host_read_data[15:0], host_read_type, expected);
            host_read_enable = 1'b0;
        end
    endtask

    task automatic check_f32(input [3:0] index, input [31:0] expected);
        begin
            @(negedge clk);
            host_memory_select = 1'b0;
            host_lane = 8'd0;
            host_index = index;
            host_read_enable = 1'b1;
            if (host_access_ready !== 1'b1)
                $fatal(1, "F32 host read was not ready");
            @(posedge clk); #1;
            if (host_read_valid !== 1'b1)
                $fatal(1, "F32 host read did not return valid");
            if ((host_read_data[31:0] !== expected) || (host_read_type !== 4'd8))
                $fatal(1, "F32 mismatch r%0d: got %h type %h expected %h",
                       index, host_read_data[31:0], host_read_type, expected);
            host_read_enable = 1'b0;
        end
    endtask

    initial begin
        repeat (2) @(posedge clk);
        @(negedge clk); rst_n = 1'b1; #1;

        // Load operands through real Grider MOVI instructions (BF16 raw bits).
        run_bf16(5'd2, 4'd0, 4'd0, 4'd0, 128'h3f00, cycles); // r0 = 0.5
        if (cycles != 2) $fatal(1, "BF16 MOVI expected 2 cycles, got %0d", cycles);
        run_bf16(5'd2, 4'd1, 4'd0, 4'd0, 128'h3fc0, cycles); // r1 = 1.5
        if (cycles != 2) $fatal(1, "BF16 MOVI expected 2 cycles, got %0d", cycles);
        run_bf16(5'd2, 4'd2, 4'd0, 4'd0, 128'h4000, cycles); // r2 = 2.0
        if (cycles != 2) $fatal(1, "BF16 MOVI expected 2 cycles, got %0d", cycles);

        add_cycles = 0;
        for (i = 0; i < ITERATIONS; i = i + 1) begin
            run_bf16(5'd3, 4'd3, 4'd1, 4'd2, 128'd0, cycles); // ADD
            if (cycles != 4) $fatal(1, "BF16 ADD expected 4 cycles, got %0d", cycles);
            add_cycles = add_cycles + cycles;
        end
        check_bf16(4'd3, 16'h4060); // 3.5

        mul_cycles = 0;
        for (i = 0; i < ITERATIONS; i = i + 1) begin
            run_bf16(5'd5, 4'd4, 4'd1, 4'd2, 128'd0, cycles); // MUL
            if (cycles != 4) $fatal(1, "BF16 MUL expected 4 cycles, got %0d", cycles);
            mul_cycles = mul_cycles + cycles;
        end
        check_bf16(4'd4, 16'h4040); // 3.0

        mac_cycles = 0;
        for (i = 0; i < ITERATIONS; i = i + 1) begin
            run_bf16(5'd6, 4'd0, 4'd1, 4'd2, 128'd0, cycles); // MAC r0 += r1*r2
            if (cycles != 5) $fatal(1, "BF16 MAC expected 5 cycles, got %0d", cycles);
            mac_cycles = mac_cycles + cycles;
        end
        check_f32(4'd0, 32'h42420000); // F32 accumulator = 48.5
        run_bf16(5'd20, 4'd0, 4'd0, 4'd0, 128'd0, cycles); // CONVERT F32 to BF16
        check_bf16(4'd0, 16'h4242); // 48.5 rounded to BF16

        add_mflops_20mhz = 20.0 * ITERATIONS / add_cycles;
        mul_mflops_20mhz = 20.0 * ITERATIONS / mul_cycles;
        mac_mflops_20mhz = 20.0 * (2 * ITERATIONS) / mac_cycles;
        add_mflops_at_sta = 20.982 * ITERATIONS / add_cycles;
        mul_mflops_at_sta = 20.982 * ITERATIONS / mul_cycles;
        mac_mflops_at_sta = 20.982 * (2 * ITERATIONS) / mac_cycles;

        $display("BENCH BF16_ADD lanes=1 instructions=%0d flops=%0d RTL_cycles=%0d cycles_per_instruction=%0d @20MHz=%0.3f_MFLOPS @20.982MHz=%0.3f_MFLOPS",
                 ITERATIONS, ITERATIONS, add_cycles, add_cycles/ITERATIONS,
                 add_mflops_20mhz, add_mflops_at_sta);
        $display("BENCH BF16_MUL lanes=1 instructions=%0d flops=%0d RTL_cycles=%0d cycles_per_instruction=%0d @20MHz=%0.3f_MFLOPS @20.982MHz=%0.3f_MFLOPS",
                 ITERATIONS, ITERATIONS, mul_cycles, mul_cycles/ITERATIONS,
                 mul_mflops_20mhz, mul_mflops_at_sta);
        $display("BENCH BF16_MAC lanes=1 instructions=%0d flops=%0d RTL_cycles=%0d cycles_per_instruction=%0d @20MHz=%0.3f_MFLOPS @20.982MHz=%0.3f_MFLOPS",
                 ITERATIONS, 2*ITERATIONS, mac_cycles, mac_cycles/ITERATIONS,
                 mac_mflops_20mhz, mac_mflops_at_sta);
        $display("BF16 RTL microbenchmark passed; operands and outputs were checked through the host port.");
        $finish;
    end
endmodule
